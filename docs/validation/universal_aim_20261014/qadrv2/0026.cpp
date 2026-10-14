#include "tracker.hpp"
#include "module/tracker/observation_guard.hpp"

#include "module/tracker/model/outpost.hpp"
#include "module/tracker/model/robot.hpp"
#include "module/tracker/model/rune.hpp"
#include "utility/logging/printer.hpp"
#include "utility/math/camera.hpp"
#include "utility/serializable.hpp"

#include <algorithm>
#include <fstream>
#include <numbers>
#include <optional>
#include <ranges>
#include <string>
#include <unordered_map>

using namespace rmcs::kernel;
using namespace rmcs::util;

namespace {

enum class RuntimeTrackingMode { Single, MultiEkf };

auto read_tracking_mode(const std::string& path) -> RuntimeTrackingMode {
    std::ifstream stream { path };
    std::string mode;
    stream >> mode;
    return mode == "multi_ekf" ? RuntimeTrackingMode::MultiEkf
                               : RuntimeTrackingMode::Single;
}

// Direct single-armor mode and temporary fallback before a valid robot model
// converges. A single frame cannot determine all robot states, but successive
// one-armor observations must still update the EKF to estimate motion/rotation.
struct DirectArmorState {
    rmcs::Point3d direction;
    double yaw_rate = 0.0;
    double lead_applied = 0.0;
    double lead_elapsed = 0.0;

    auto get_aimpoints() const -> rmcs::AimPoints {
        return rmcs::AimPoints { std::vector<rmcs::Point3d> { direction } };
    }
    auto get_direction() const -> rmcs::Point3d { return direction; }
    auto get_rotation_speed() const -> double { return 0.0; }
    auto transition(double seconds) -> void {
        if (!std::isfinite(seconds) || seconds <= 0.0) return;
        lead_elapsed += seconds;
        const double angle = direct_armor_lead_angle(yaw_rate, lead_elapsed);
        const double step = angle - lead_applied;
        const double x = direction.x, y = direction.y;
        direction.x = std::cos(step) * x - std::sin(step) * y;
        direction.y = std::sin(step) * x + std::cos(step) * y;
        lead_applied = angle;
    }
};

}  // namespace

struct Tracker::Impl {
    struct Config : Serializable {
        std::string fallback_color = "RED";
        double timeout_seconds     = 1.5;
        double image_margin        = 20.0;

        static constexpr std::tuple metas {
            // clang-format off
            &Config::fallback_color, "fallback_color",
            &Config::timeout_seconds, "timeout_seconds",
            &Config::image_margin, "image_margin",
            // clang-format on
        };
    } config;

    struct RobotConfig : RobotModel::Config, Serializable {
        static constexpr std::tuple metas {
            // clang-format off
            &RobotConfig::noise_x, "noise_x",
            &RobotConfig::noise_y, "noise_y",
            &RobotConfig::noise_z, "noise_z",
            &RobotConfig::noise_vx, "noise_vx",
            &RobotConfig::noise_vy, "noise_vy",
            &RobotConfig::noise_vz, "noise_vz",
            &RobotConfig::noise_rotation_angle, "noise_rotation_angle",
            &RobotConfig::noise_rotation_speed, "noise_rotation_speed",
            &RobotConfig::noise_observation, "noise_observation",
            // clang-format on
        };
    } robot_config;

    struct OutpostConfig : OutpostModel::Config, Serializable {
        static constexpr std::tuple metas {
            // clang-format off
            &OutpostConfig::process_noise_xy, "process_noise_xy",
            &OutpostConfig::process_noise_z, "process_noise_z",
            &OutpostConfig::process_noise_speed, "process_noise_speed",
            &OutpostConfig::process_noise_angle, "process_noise_angle",
            &OutpostConfig::observation_noise_xy, "observation_noise_xy",
            &OutpostConfig::observation_noise_z, "observation_noise_z",
            &OutpostConfig::observation_noise_yaw, "observation_noise_yaw",
            &OutpostConfig::plate_switch_yaw_min, "plate_switch_yaw_min",
            // clang-format on
        };
    } outpost_config;

    struct RuneConfig : RuneModel::Config, Serializable {
        static constexpr std::tuple metas {
            // clang-format off
            &RuneConfig::noise_x, "noise_x",
            &RuneConfig::noise_y, "noise_y",
            &RuneConfig::noise_z, "noise_z",
            &RuneConfig::noise_rotation_angle, "noise_rotation_angle",
            &RuneConfig::noise_rotation_speed, "noise_rotation_speed",
            &RuneConfig::noise_face_yaw, "noise_face_yaw",
            &RuneConfig::noise_observation, "noise_observation",
            &RuneConfig::gate_threshold, "gate_threshold",
            &RuneConfig::init_seed_mean_error, "init_seed_mean_error",
            &RuneConfig::init_seed_max_error, "init_seed_max_error",
            &RuneConfig::init_center_gate, "init_center_gate",
            &RuneConfig::init_pitch_bound, "init_pitch_bound",
            &RuneConfig::diverge_face_angle, "diverge_face_angle",
            // clang-format on
        };
    } rune_config;

    struct {
        Armor2ds armor2ds;
        Armor3ds armor3ds;
        Lightbar2ds lightbars;
        std::vector<RuneIcon> icons;
        std::vector<RuneBullseye> bullseyes;
    } stored;

    bool observed_selected_target = false;
    bool aim_intent  = false;
    bool aim_cleanup = false;

    DeviceIds track_devices = DeviceIds::Full();
    DeviceId track_genre    = DeviceId::UNKNOWN;
    ArmorColor track_color  = ArmorColor::DARK;
    CameraFeature camera;
    int image_width = 0, image_height = 0;
    std::vector<bool> accepted_armor2ds;
    std::size_t rejected_color = 0, rejected_genre = 0, rejected_margin = 0, rejected_clipped = 0;
    std::size_t frame_rejected_color = 0, frame_rejected_genre = 0;
    std::size_t frame_rejected_margin = 0, frame_rejected_clipped = 0;
    DeviceId last_rejected_genre = DeviceId::UNKNOWN;
    Timestamp diagnostic_stamp { };
    std::size_t frames_seen = 0, frames_empty = 0, frames_direct = 0;
    std::size_t frames_raw_empty = 0, frames_filtered = 0, frames_pnp_missing = 0;

    // Use 20 ms horizontal smoothing for motion, retaining 50 ms vertical noise rejection.
    std::optional<rmcs::Point3d> direct_armor_direction_;
    Timestamp direct_armor_stamp_ { };
    double direct_yaw_velocity_ = 0.0;
    DeviceId direct_armor_genre_ = DeviceId::UNKNOWN;
    ArmorColor direct_armor_color_ = ArmorColor::DARK;
    RuntimeTrackingMode runtime_mode_ = RuntimeTrackingMode::Single;
    std::string runtime_mode_file_;

    std::unordered_map<DeviceId, Timestamp> robot_stamps;
    std::unordered_map<DeviceId, RobotModel> robot_models;

    Timestamp outpost_stamp, outpost_corrected_stamp;
    std::unique_ptr<OutpostModel> outpost;

    Timestamp rune_stamp, rune_corrected_stamp;
    std::unique_ptr<RuneModel> rune;

    Printer logging { "TrackerV2" };
    Addition addition;

    Impl(const YAML::Node& yaml, std::string runtime_mode_file)
        : runtime_mode_file_ { std::move(runtime_mode_file) } {
        auto compat_yaml = YAML::Clone(yaml);
        if (!compat_yaml["fallback_color"] && compat_yaml["enemy_color"]) {
            compat_yaml["fallback_color"] = compat_yaml["enemy_color"];
        }

        if (auto ret = config.serialize(compat_yaml); !ret) {
            logging.error("TrackerV2 初始化错误: {}", ret.error());
            throw std::runtime_error { "无法构造 TrackerV2" };
        }
        if (auto ret = robot_config.serialize(yaml["robot"]); !ret) {
            logging.error("RobotModel config error: {}", ret.error());
            throw std::runtime_error { "无法构造 RobotModel Config" };
        }
        if (auto ret = outpost_config.serialize(yaml["outpost"]); !ret) {
            logging.error("OutpostModel config error: {}", ret.error());
            throw std::runtime_error { "无法构造 OutpostModel Config" };
        }
        if (const auto rune_node = yaml["rune"]; rune_node && !rune_node.IsNull()) {
            if (auto ret = rune_config.serialize(rune_node); !ret) {
                logging.error("RuneModel config error: {}", ret.error());
                throw std::runtime_error { "无法构造 RuneModel Config" };
            }
        }

        /*^^*/ if (config.fallback_color == "RED") {
            track_color = ArmorColor::RED;
        } else if (config.fallback_color == "BLUE") {
            track_color = ArmorColor::BLUE;
        } else {
            logging.error("invalid color {}", config.fallback_color);
        }
    }

    auto clean() noexcept {
        stored.armor2ds.clear();
        accepted_armor2ds.clear();
        frame_rejected_color = frame_rejected_genre = 0;
        frame_rejected_margin = frame_rejected_clipped = 0;
        stored.armor3ds.clear();
        stored.lightbars.clear();
        stored.icons.clear();
        stored.bullseyes.clear();
    }

    auto store(std::span<const Armor2d> items) {
        // PoseEstimator preserves the original 2D index in Armor3d::id.
        for (const auto& item : items) {
            const auto corners = std::array { item.tl, item.tr, item.br, item.bl };
            const bool color_ok = item.color == track_color;
            const bool genre_ok = track_devices.contains(item.genre);
            const bool bounds_ok = armor_inside_image(corners,
                image_width, image_height, config.image_margin);
            const bool accepted = color_ok && genre_ok && bounds_ok;
            if (!color_ok) { ++rejected_color; ++frame_rejected_color; }
            else if (!genre_ok) {
                ++rejected_genre;
                ++frame_rejected_genre;
                last_rejected_genre = item.genre;
            } else if (!bounds_ok) {
                if (armor_inside_image(corners, image_width, image_height, 0.0)) {
                    ++rejected_margin;
                    ++frame_rejected_margin;
                } else {
                    ++rejected_clipped;
                    ++frame_rejected_clipped;
                }
            }
            accepted_armor2ds.push_back(accepted);
            if (accepted) stored.armor2ds.push_back(item);
        }
    }
    auto store(std::span<const Armor3d> items) {
        for (const auto& item : items) {
            if (item.color == track_color && track_devices.contains(item.genre)
                && accepted_armor_id(item.id, accepted_armor2ds)
                && std::isfinite(item.translation.x) && std::isfinite(item.translation.y)
                && std::isfinite(item.translation.z)) {
                stored.armor3ds.push_back(item);
            }
        }
    }
    auto store(std::span<const Lightbar2d> items) {
        for (const auto& item : items) {
            if (item.color == track_color && track_devices.contains(item.genre)) {
                stored.lightbars.push_back(item);
            }
        }
    }
    auto store(std::span<const RuneIcon> items) {
        if (!track_devices.contains(DeviceId::RUNE)) return;
        std::ranges::copy(items, std::back_inserter(stored.icons));
    }
    auto store(std::span<const RuneBullseye> items) {
        if (!track_devices.contains(DeviceId::RUNE)) return;
        std::ranges::copy(items, std::back_inserter(stored.bullseyes));
    }

    auto execute(Timestamp timestamp) {
        observed_selected_target = false;
        const auto requested_mode = read_tracking_mode(runtime_mode_file_);
        if (requested_mode != runtime_mode_) {
            runtime_mode_ = requested_mode;
            direct_armor_direction_.reset();
            direct_yaw_velocity_ = 0.0;
            robot_models.clear();
            robot_stamps.clear();
            track_genre = DeviceId::UNKNOWN;
            logging.info("tracking mode switched to {}",
                runtime_mode_ == RuntimeTrackingMode::Single ? "single" : "multi_ekf");
        }
        addition.tracked2d.clear();
        addition.tracked3d.clear();
        addition.lightbars.clear();
        addition.rune_features.clear();
        addition.rune_polygon.reset();
        addition.infos.clear();
        ++frames_seen;
        frames_empty += stored.armor2ds.empty();
        frames_raw_empty += accepted_armor2ds.empty();
        frames_filtered += !accepted_armor2ds.empty() && stored.armor2ds.empty();
        frames_pnp_missing += !stored.armor2ds.empty() && stored.armor3ds.empty();
        frames_direct += stored.armor2ds.size() == 1 && stored.armor3ds.size() == 1;
        if (std::chrono::duration<double> { timestamp - diagnostic_stamp }.count() >= 1.0) {
            logging.info("observations frames={} empty2d={} single={} no_detection={} filtered={} pnp_missing={} last_raw2d={} kept2d={} kept3d={}",
                frames_seen, frames_empty, frames_direct, frames_raw_empty, frames_filtered,
                frames_pnp_missing, accepted_armor2ds.size(),
                stored.armor2ds.size(), stored.armor3ds.size());
            logging.info("rejected color={} genre={} margin_band={} clipped={} last_genre={}",
                rejected_color, rejected_genre, rejected_margin, rejected_clipped,
                rmcs::to_string(last_rejected_genre));
            rejected_color = rejected_genre = rejected_margin = rejected_clipped = 0;
            diagnostic_stamp = timestamp;
            frames_seen = frames_empty = frames_direct = 0;
            frames_raw_empty = frames_filtered = frames_pnp_missing = 0;
        }

        // Keep direct tracking available for explicit single mode and for the
        // final fallback. Multi-EKF must process every complete armor observation,
        // including frames with only one visible armor, before choosing output.
        auto outpost_rejected_this_frame = false;
        const auto track_direct = [&]() -> Trackable::Unique {
            if (stored.armor3ds.empty()) return {};
            const auto locked_genre = runtime_mode_ == RuntimeTrackingMode::MultiEkf
                    && aim_intent && track_genre != DeviceId::UNKNOWN
                ? track_genre : DeviceId::UNKNOWN;
            const auto eligible = [&](const auto& armor) {
                return (locked_genre == DeviceId::UNKNOWN || armor.genre == locked_genre)
                    && !(outpost_rejected_this_frame && armor.genre == DeviceId::OUTPOST);
            };
            if (std::ranges::none_of(stored.armor3ds, eligible)) return {};
            const auto score = [&](const auto& armor) {
                if (!eligible(armor)) return std::numeric_limits<double>::max();
                const auto yaw = std::atan2(armor.translation.y, armor.translation.x);
                if (direct_armor_direction_ && armor.genre == direct_armor_genre_) {
                    const auto old_yaw = std::atan2(
                        direct_armor_direction_->y, direct_armor_direction_->x);
                    return std::abs(std::remainder(yaw - old_yaw, 2.0 * std::numbers::pi));
                }
                return std::abs(yaw);
            };
            const auto selected = std::min_element(
                stored.armor3ds.begin(), stored.armor3ds.end(),
                [&](const auto& lhs, const auto& rhs) { return score(lhs) < score(rhs); });
            const auto& armor = *selected;
            const rmcs::Point3d raw_direction {
                armor.translation.x, armor.translation.y, armor.translation.z,
            };

            auto direction = raw_direction;
            if (direct_armor_direction_) {
                const double dt = std::chrono::duration<double> {
                    timestamp - direct_armor_stamp_,
                }.count();
                const auto& previous = *direct_armor_direction_;
                const double angle_change = std::abs(std::remainder(
                    std::atan2(raw_direction.y, raw_direction.x)
                        - std::atan2(previous.y, previous.x), 2.0 * std::numbers::pi));
                const bool same = armor.genre == direct_armor_genre_
                    && armor.color == direct_armor_color_
                    && (runtime_mode_ == RuntimeTrackingMode::Single || angle_change < 0.35);
                const double alpha_xy = direct_armor_alpha(dt, same, 0.02);
                const double alpha_z = direct_armor_alpha(dt, same, 0.05);
                direction.x = previous.x + alpha_xy * (raw_direction.x - previous.x);
                direction.y = previous.y + alpha_xy * (raw_direction.y - previous.y);
                direction.z = previous.z + alpha_z * (raw_direction.z - previous.z);
                direct_yaw_velocity_ = direct_armor_yaw_velocity(direct_yaw_velocity_,
                    std::atan2(previous.y, previous.x), std::atan2(direction.y, direction.x), dt,
                    same && std::hypot(previous.x, previous.y) > 1e-3
                        && std::hypot(direction.x, direction.y) > 1e-3);
            }
            direct_armor_direction_ = direction;
            direct_armor_stamp_     = timestamp;
            direct_armor_genre_     = armor.genre;
            direct_armor_color_     = armor.color;

            observed_selected_target = true;
            track_genre = armor.genre;
            addition.tracked3d.push_back(armor);
            return make_trackable(timestamp,
                DirectArmorState { direction, direct_yaw_velocity_ }, armor.genre);
        };
        if (runtime_mode_ == RuntimeTrackingMode::Single && !stored.armor3ds.empty()) {
            return track_direct();
        }
        // One complete armor still provides an EKF observation. Keep predicting and
        // correcting across one/two-armor visibility changes so rotation can converge.
        // Direct fallback is selected below only if no valid full-model output exists.

        { // 前哨站观测超时：预测/拒绝不能续期成功观测
            const auto dt = std::chrono::duration<double> {
                timestamp - outpost_corrected_stamp,
            };
            if (outpost && dt.count() > config.timeout_seconds) {
                outpost = nullptr;
                outpost_stamp = outpost_corrected_stamp = Timestamp { };

                if (track_genre == DeviceId::OUTPOST && aim_intent && aim_cleanup) {
                    track_genre = DeviceId::UNKNOWN;
                }
            }
        }
        { // 大符超时处理
            if (rune != nullptr) {
                const auto dt = std::chrono::duration<double> {
                    timestamp - rune_corrected_stamp,
                };
                if (dt.count() > config.timeout_seconds) {
                    rune = nullptr;

                    if (track_genre == DeviceId::RUNE && aim_intent && aim_cleanup) {
                        track_genre = DeviceId::UNKNOWN;
                    }
                }
            }
        }
        // 机器人观测超时处理
        std::erase_if(robot_stamps, [&](const auto& item) {
            const auto [id, stamp] = item;

            const auto dt = std::chrono::duration<double> { timestamp - stamp };
            if (dt.count() > config.timeout_seconds) {
                robot_models.erase(id);

                if (track_genre == id && aim_intent && aim_cleanup) {
                    track_genre = DeviceId::UNKNOWN;
                }
                return true;
            }
            return false;
        });

        struct Target final {
            std::vector<Armor2d> armor2ds;
            std::vector<Armor3d> armor3ds;
            std::vector<Lightbar2d> bars;
        };
        auto seen = std::unordered_map<DeviceId, Target> { };

        for (const auto& armor : stored.armor2ds) {
            seen[armor.genre].armor2ds.push_back(armor);
        }
        for (const auto& armor : stored.armor3ds) {
            seen[armor.genre].armor3ds.push_back(armor);
        }
        for (const auto& bar : stored.lightbars) {
            seen[bar.genre].bars.push_back(bar);
        }

        { // 迭代前哨站 Model
            constexpr auto kId = DeviceId::OUTPOST;
            if (seen.contains(kId)) {
                const auto& armors = seen[kId].armor3ds;
                /// @NOTE:
                ///  前哨站为单装甲板输入(120 度，也只能看到一块)，邻侧灯条的信息
                ///  已经在距离优化那个步骤消费掉了，所以这里不需要传入，有时间这
                ///  里也会换成纯 2d 观测，到时候就完全不需要 Armor3d 了
                if (!armors.empty()) {
                    if (outpost == nullptr) {
                        outpost = std::make_unique<OutpostModel>(armors.front());
                        outpost->configure(outpost_config);
                        outpost_stamp = outpost_corrected_stamp = timestamp;
                    } else {
                        const auto dt = std::chrono::duration<double> {
                            timestamp - outpost_stamp,
                        };
                        outpost->predict(dt.count());
                        outpost_stamp = timestamp;
                        const auto corrected = outpost->correct(armors.front());
                        outpost_rejected_this_frame = !corrected;

                        if (outpost->diverged()) {
                            outpost = nullptr;
                            outpost_stamp = outpost_corrected_stamp = Timestamp { };
                            logging.warn("{} is diverged", get_enum_name(kId));
                        } else if (corrected) {
                            outpost_corrected_stamp = timestamp;
                        }
                    }
                }
            }
        }
        { // 迭代大符
            if (!stored.icons.empty() || !stored.bullseyes.empty()) {
                if (rune == nullptr) {
                    auto model = std::make_unique<RuneModel>(rune_config);
                    model->update_camera(std::bit_cast<std::array<double, 9>>(camera.camera_matrix),
                        camera.distort_coeff);
                    model->update_transform({
                        .translation = camera.translation,
                        .orientation = camera.orientation,
                    });
                    if (model->init(stored.icons, stored.bullseyes, timestamp)) {
                        rune                 = std::move(model);
                        rune_stamp           = timestamp;
                        rune_corrected_stamp = timestamp;
                        logging.info("Init OK with {}", get_enum_name(DeviceId::RUNE));
                    }
                } else {
                    const auto dt = std::chrono::duration<double> {
                        timestamp - rune_stamp,
                    };

                    rune->update_transform({
                        .translation = camera.translation,
                        .orientation = camera.orientation,
                    });
                    rune->predict(dt.count(), timestamp);
                    rune_stamp           = timestamp;
                    const auto corrected = rune->correct(stored.icons, stored.bullseyes);

                    if (rune->diverged()) {
                        rune = nullptr;
                        logging.warn("{} is diverged", get_enum_name(DeviceId::RUNE));
                    } else if (corrected) {
                        rune_corrected_stamp = timestamp;
                    }
                }
            }
        }
        // 迭代机器人 Model
        for (const auto& [id, target] : seen) {
            // 仅有灯条而没有完整装甲板时无法校正模型；不能把预测当成新观测
            // 刷新 robot_stamps，否则旧模型可在丢检期间无限续命。
            if (id == DeviceId::OUTPOST || target.armor2ds.empty()) {
                continue;
            }
            if (robot_models.contains(id) == false) {
                auto& model = robot_models.try_emplace(id, robot_config).first->second;
                model.update_camera(
                    std::bit_cast<std::array<double, 9>>(camera.camera_matrix),
                    camera.distort_coeff);
                model.update_transform({
                    .translation = camera.translation,
                    .orientation = camera.orientation,
                });
                if (!model.init(target.armor2ds)) {
                    robot_models.erase(id);
                    robot_stamps.erase(id);
                    continue;
                } else {
                    logging.info("Init OK with {}", get_enum_name(id));
                }
            } else {
                const auto dt = std::chrono::duration<double> {
                    timestamp - robot_stamps[id],
                };

                auto& model = robot_models.at(id);
                model.update_transform({
                    .translation = camera.translation,
                    .orientation = camera.orientation,
                });
                // 超过短丢检窗口后，旧速度和板编号预测已不可靠；从本帧板
                // 重新建航迹。短丢检仍按原 EKF 连续预测处理。
                if (dt.count() > 0.25) {
                    if (!model.init(target.armor2ds)) {
                        robot_models.erase(id);
                        robot_stamps.erase(id);
                        continue;
                    }
                } else {
                    model.predict(dt.count());
                    if (!model.correct(target.armor2ds, target.bars)) {
                        // Prediction already advanced model state. Discard a failed
                        // correction/rebuild instead of stamping it as observed or
                        // retaining it to predict the same elapsed interval twice.
                        // A real current 3D observation may still use direct fallback.
                        robot_models.erase(id);
                        robot_stamps.erase(id);
                        continue;
                    }
                }

                if (model.diverged()) {
                    const auto state = model.state();
                    logging.warn(
                        "{} is diverged: x={:.3f} y={:.3f} z={:.3f} vx={:.3f} vy={:.3f} "
                        "vz={:.3f} w={:.3f}",
                        get_enum_name(id), state.x, state.y, state.z, state.vx, state.vy,
                        state.vz, state.rotation_speed);
                    robot_models.erase(id);
                    robot_stamps.erase(id);
                    continue;
                }
            }
            robot_stamps[id] = timestamp;
        }

        // 选择目标并填充调试信息
        const auto calculate = [&](DeviceId id, const Point3d& p) -> double {
            std::ignore = id;
            /// @NOTE:
            ///  占位符实现，按照目标中心到摄像机视角光轴的
            ///  距离比较优先级，后续可能会引入更复杂的判断
            ///  标准，也可能不会（
            const auto distance_score =
                compute_distance2cam_x({ camera.translation, camera.orientation }, p);
            return distance_score;
        };
        const auto locked = aim_intent && track_genre != DeviceId::UNKNOWN;

        auto result = Trackable::Unique { };
        auto better = std::numeric_limits<double>::max();
        auto device = DeviceId::UNKNOWN;
        {
            if (!locked || DeviceId::OUTPOST == track_genre) {
                if (outpost && outpost->converge()) {
                    const auto state = outpost->state();
                    const auto score = calculate(DeviceId::OUTPOST, state.get_direction());
                    if (better > score) {
                        better = score;
                        result = make_trackable(outpost_stamp, state, DeviceId::OUTPOST);

                        device = DeviceId::OUTPOST;
                    }
                    std::ranges::copy(outpost->full(), std::back_inserter(addition.tracked3d));

                    const auto a = state.rotation_angle;
                    const auto v = state.rotation_speed;
                    addition.infos.push_back({
                        .text  = std::format("a: {:+.1f} | v: {:+2.2f}", a, v),
                        .point = Point3d { state.x, state.y, state.z },
                    });
                }
            }
            if (!locked || DeviceId::RUNE == track_genre) {
                if (rune && rune->converge()) {
                    const auto state = rune->state();
                    const auto score = calculate(DeviceId::RUNE, state.get_direction());
                    if (better > score) {
                        better = score;
                        result = make_trackable(rune_stamp, state, DeviceId::RUNE);

                        device = DeviceId::RUNE;
                    }

                    std::ranges::copy(
                        rune->addition().predicted | std::views::transform([](const auto& item) {
                            return Addition::RuneFeature { item.feature_id, item.point };
                        }),
                        std::back_inserter(addition.rune_features));

                    if (rune->addition().predicted.size() == 6) {
                        auto polygon = Addition::RunePolygon { };
                        auto ok      = true;
                        for (const auto& item : rune->addition().predicted) {
                            if (item.feature_id == 0) {
                                polygon.icon = item.point;
                            } else if (item.feature_id >= 1 && item.feature_id <= 5) {
                                polygon.blades[static_cast<std::size_t>(item.feature_id - 1)] =
                                    item.point;
                            } else {
                                ok = false;
                            }
                        }
                        if (ok) addition.rune_polygon = polygon;
                    }

                    const auto a = state.rotation_angle;
                    const auto v = state.rotation_speed;

                    const auto text_large_rune = [&] {
                        return std::format("spd_{}(t)={:+.2f}{:+.2f}*sin({:+.2f}{:+.2f}t), "
                                           "e={:.3f}",
                            state.update_count, state.sine_v, state.sine_a, state.sine_phase,
                            state.sine_omega, state.prediction_cost);
                    };
                    const auto text_small_rune = [&] {
                        return std::format("spd_{}(t)={:+.2f}, e={:.3f}", state.update_count, v,
                            state.prediction_cost);
                    };
                    const auto text_fallback = [&] { return std::format("theta_ekf={:+.2f}", a); };

                    addition.infos.push_back({
                        .text  = state.sine_valid
                            ? text_large_rune()
                            : (state.use_prediction_speed ? text_small_rune() : text_fallback()),
                        .point = Point3d { state.x, state.y, state.z },
                    });
                }
            }
            for (const auto& [id, model] : robot_models) {
                // 锁定时，不回传其他的目标
                if (locked && id != track_genre) {
                    continue;
                }
                // 不输出无完整板观测的旧航迹；桥侧短丢检补偿负责平滑过渡。
                const auto observed = seen.find(id);
                if (observed == seen.end() || observed->second.armor3ds.empty()) continue;
                if (model.converge()) {
                    const auto state = model.state();
                    // 输出门控只影响指令，不拒绝 EKF 更新。快速运动时仍允许
                    // 当前帧修正模型；如果模型与所有真实 3D 板都相差过大，
                    // 本帧退回直接观测，避免重捕时突然指向错误的虚拟板。
                    bool agrees_with_observation = false;
                    for (const auto& predicted : state.get_aimpoints()) {
                        const double predicted_range = std::hypot(
                            predicted.x, predicted.y, predicted.z);
                        if (!(predicted_range > 1e-3)) continue;
                        for (const auto& actual : observed->second.armor3ds) {
                            const double actual_range = std::hypot(
                                actual.translation.x, actual.translation.y,
                                actual.translation.z);
                            if (!(actual_range > 1e-3)
                                || std::abs(predicted_range - actual_range) > 0.5 * actual_range)
                                continue;
                            const double dot = predicted.x * actual.translation.x
                                + predicted.y * actual.translation.y
                                + predicted.z * actual.translation.z;
                            if (dot > std::cos(0.55) * predicted_range * actual_range) {
                                agrees_with_observation = true;
                                break;
                            }
                        }
                        if (agrees_with_observation) break;
                    }
                    if (!agrees_with_observation) continue;
                    const auto score = calculate(id, state.get_direction());
                    if (better > score) {
                        better = score;
                        result = make_trackable(robot_stamps.at(id), state, id);

                        device = id;
                    }
                    std::ranges::copy( // Armor 2d
                        model.addition().armors, std::back_inserter(addition.tracked2d));
                    std::ranges::copy( // Armor 3d
                        model.full(), std::back_inserter(addition.tracked3d));
                    std::ranges::copy(
                        model.addition().tracked | std::views::transform([](const auto& item) {
                            return Addition::Lightbar { item.lightbar_id, item.point };
                        }),
                        std::back_inserter(addition.lightbars));

                    const auto rv = state.rotation_speed;
                    const auto vx = state.vx;
                    const auto vy = state.vy;
                    addition.infos.push_back({
                        .text  = std::format("rv: {:+2.2f} | v: {:+2.2f}, {:+2.2f}", rv, vx, vy),
                        .point = Point3d { state.x, state.y, state.z },
                    });
                }
            }
        }

        /// @NOTE:
        ///  未锁定时更新目标；一旦自瞄意图按下且已有锁定目标，就保持该目标
        ///  最高优先级，即使目标暂时丢失。开启锁定超时清理时，目标超时后会
        ///  解除锁定并允许重新选择
        if (!locked) {
            track_genre = device;
        }
        if (runtime_mode_ == RuntimeTrackingMode::MultiEkf && !result
            && !stored.armor3ds.empty()) {
            return track_direct();
        }
        direct_armor_direction_.reset();
        direct_yaw_velocity_ = 0.0;
        if (result) {
            // Prediction state time is not proof of a usable current correction.
            observed_selected_target = device == DeviceId::RUNE
                ? rune_corrected_stamp == timestamp
                : device == DeviceId::OUTPOST ? outpost_corrected_stamp == timestamp
                                             : result->get_timestamp() == timestamp;
        }
        return result;
    }
};

Tracker::Tracker(const YAML::Node& yaml)
    : Tracker { yaml, "/tmp/autoaim/tracking_mode" } { }

Tracker::Tracker(const YAML::Node& yaml, std::string runtime_mode_file)
    : pimpl { std::make_unique<Impl>(yaml, std::move(runtime_mode_file)) } { }

Tracker::~Tracker() noexcept = default;

auto Tracker::update_aim_intent(bool intent) -> void { pimpl->aim_intent = intent; }
auto Tracker::update_aim_cleanup(bool on) -> void { pimpl->aim_cleanup = on; }

auto Tracker::update_track_color(CampColor camp) -> void {
    /*^^*/ if (camp == CampColor::RED) {
        pimpl->track_color = ArmorColor::RED;
    } else if (camp == CampColor::BLUE) {
        pimpl->track_color = ArmorColor::BLUE;
    }
    // Do nothing for unknown camp
}
auto Tracker::update_track_genre(DeviceIds ids) -> void { pimpl->track_devices = ids; }

auto Tracker::update_camera(const Transform& t) noexcept -> void {
    pimpl->camera.translation = t.translation;
    pimpl->camera.orientation = t.orientation;
}
auto Tracker::update_camera(const std::array<double, 9>& param) noexcept -> void {
    pimpl->camera.from(param);
}
auto Tracker::update_camera(const std::array<double, 5>& param) noexcept -> void {
    pimpl->camera.from(param);
}

auto Tracker::update_image_size(int width, int height) noexcept -> void {
    pimpl->image_width = width;
    pimpl->image_height = height;
}

auto Tracker::clean() noexcept -> void { pimpl->clean(); }

auto Tracker::store(std::span<const Armor2d> item) -> void { pimpl->store(item); }
auto Tracker::store(std::span<const Armor3d> item) -> void { pimpl->store(item); }
auto Tracker::store(std::span<const Lightbar2d> item) -> void { pimpl->store(item); }
auto Tracker::store(std::span<const RuneIcon> item) -> void { pimpl->store(item); }
auto Tracker::store(std::span<const RuneBullseye> item) -> void { pimpl->store(item); }

auto Tracker::execute(Timestamp stamp) -> Trackable::Unique { return pimpl->execute(stamp); }

auto Tracker::observed_selected_target() const noexcept -> bool {
    return pimpl->observed_selected_target;
}

auto Tracker::addition() const -> const Addition& { return pimpl->addition; }
auto Tracker::frame_stats() const noexcept -> FrameStats {
    return {
        pimpl->accepted_armor2ds.size(),
        pimpl->stored.armor2ds.size(),
        pimpl->stored.armor3ds.size(),
        pimpl->frame_rejected_color,
        pimpl->frame_rejected_genre,
        pimpl->frame_rejected_margin,
        pimpl->frame_rejected_clipped,
    };
}
