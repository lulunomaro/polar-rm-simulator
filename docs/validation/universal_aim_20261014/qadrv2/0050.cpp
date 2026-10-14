#include "module/tracker/model/robot.hpp"
#include "module/tracker/association_transaction.hpp"
#ifdef RMCS_ASSOCIATION_TRANSACTION_TRACE
#include <cstdio>
#endif
#include "module/tracker/observation_consistency.hpp"

#include "utility/clock.hpp"
#include "utility/math/angle.hpp"
#include "utility/math/camera.hpp"
#include "utility/math/conversion.hpp"
#include "utility/math/reprojection.hpp"
#include "utility/math/projection_jacobian.hpp"
#include "utility/math/robot.hpp"
#include "utility/math/solve_pnp/pnp_solution.hpp"
#include "utility/robot/constant.hpp"

#include <eigen3/Eigen/Geometry>
#include <ranges>

using namespace rmcs;

auto RobotModel::State::transition(double seconds) -> void {
    x += vx * seconds;
    y += vy * seconds;
    z += vz * seconds;
    rotation_angle = util::normalize_angle(rotation_angle + rotation_speed * seconds);
}

auto RobotModel::State::get_direction() const -> Point3d { return Point3d { x, y, z }; }

auto RobotModel::State::get_rotation_speed() const -> double { return rotation_speed; }

auto RobotModel::State::get_aimpoints() const -> std::vector<Point3d> {
    auto solution = RobotSolution { };

    solution.input.center = Eigen::Vector3d { x, y, z };
    solution.input.toward =
        Eigen::Quaterniond { Eigen::AngleAxisd { rotation_angle, Eigen::Vector3d::UnitZ() } };
    solution.input.radius_forward = radius_forward;
    solution.input.radius_lateral = radius_lateral;
    solution.input.height_lateral = height_lateral;

    const auto armors = solution.solve_armors();
    auto result       = std::vector<Point3d> { };
    for (int i = 0; i < 4; ++i) {
        result.emplace_back(armors[i].translation);
    }
    return result;
}

struct RobotModel::Impl {
    using StateVector      = Eigen::Matrix<double, 11, 1>;
    using Covariance       = Eigen::Matrix<double, 11, 11>;
    using ProcessNoise     = Eigen::Matrix<double, 11, 11>;
    using ObservationNoise = Eigen::Matrix<double, 4, 4>;
    using KalmanGain       = Eigen::Matrix<double, 11, 4>;

    static constexpr auto kStateX  = 0;
    static constexpr auto kStateY  = 1;
    static constexpr auto kStateZ  = 2;
    static constexpr auto kStateVx = 3;
    static constexpr auto kStateVy = 4;
    static constexpr auto kStateVz = 5;
    static constexpr auto kStateA  = 6; // rotation_angle
    static constexpr auto kStateW  = 7; // rotation_speed
    static constexpr auto kStateRF = 8; // radius_forward
    static constexpr auto kStateRL = 9; // radius_lateral
    static constexpr auto kStateHL = 10; // height_lateral

    struct Context {
        StateVector posteriors_state       = StateVector::Zero();
        Covariance posteriors_covariance   = Covariance::Identity();
        ProcessNoise noise_process         = ProcessNoise::Zero();
        ObservationNoise noise_observation = ObservationNoise::Zero();

        auto reset_covariance() noexcept {
            auto diag = StateVector { };
            diag << 64.0, 64.0, 64.0, // x, y, z
                64.0, 64.0, 64.0, // vx, vy, vz
                0.4, // rotation_angle
                100.0, // rotation_speed
                1e-2, 1e-2, 1e-2; // rf, rl, hl
            posteriors_covariance = diag.asDiagonal();
        }

        auto set_noise(const Config& cfg) noexcept {
            noise_process.diagonal() << cfg.noise_x, cfg.noise_y, cfg.noise_z, //
                cfg.noise_vx, cfg.noise_vy, cfg.noise_vz, //
                cfg.noise_rotation_angle, cfg.noise_rotation_speed, //
                cfg.noise_radius_forward, cfg.noise_radius_lateral, cfg.noise_height_lateral;

            noise_observation.diagonal() << cfg.noise_observation, cfg.noise_observation,
                cfg.noise_observation, cfg.noise_observation;
        }

        auto get_state() const noexcept {
            return State {
                .x = posteriors_state[kStateX],
                .y = posteriors_state[kStateY],
                .z = posteriors_state[kStateZ],

                .vx = posteriors_state[kStateVx],
                .vy = posteriors_state[kStateVy],
                .vz = posteriors_state[kStateVz],

                .rotation_angle = posteriors_state[kStateA],
                .rotation_speed = posteriors_state[kStateW],

                .radius_forward = posteriors_state[kStateRF],
                .radius_lateral = posteriors_state[kStateRL],
                .height_lateral = posteriors_state[kStateHL],
            };
        }
    };

    struct Observable {
        util::CameraFeature feature;

        std::array<Eigen::Vector2d, 8> upper2d;
        std::array<Eigen::Vector2d, 8> lower2d;
        std::array<Eigen::Vector3d, 8> upper3d;
        std::array<Eigen::Vector3d, 8> lower3d;
        std::array<bool, 8> visible;
        std::array<bool, 8> projection_valid;

        double yaw_full_max = 60.0 * std::numbers::pi / 180.0;
        double yaw_part_max = 90.0 * std::numbers::pi / 180.0;

        auto update(const Eigen::Vector3d& center, double theta, double rf, double rl, double hl,
            ArmorGenre genre) {
            const auto q_odom_from_cam = feature.orientation.make<Eigen::Quaterniond>();
            const auto q_cam_from_odom = q_odom_from_cam.conjugate();
            const auto cam_position    = feature.translation.make<Eigen::Vector3d>();

            std::ranges::fill(upper2d, Eigen::Vector2d::Zero());
            std::ranges::fill(lower2d, Eigen::Vector2d::Zero());
            std::ranges::fill(upper3d, Eigen::Vector3d::Zero());
            std::ranges::fill(lower3d, Eigen::Vector3d::Zero());
            std::ranges::fill(visible, false);
            std::ranges::fill(projection_valid, false);

            auto solution = RobotSolution { };

            solution.input.center = center;
            solution.input.toward =
                Eigen::Quaterniond { Eigen::AngleAxisd { theta, Eigen::Vector3d::UnitZ() } };

            solution.input.radius_forward = rf;
            solution.input.radius_lateral = rl;
            solution.input.height_lateral = hl;
            solution.input.genre          = genre;

            const auto lightbars = solution.solve_lightbars();
            const auto armors    = solution.solve_armors();

            for (int i = 0; i < 8; ++i) {
                const auto upper_odom = lightbars[i].upper.make<Eigen::Vector3d>();
                const auto lower_odom = lightbars[i].lower.make<Eigen::Vector3d>();

                const auto upper_camera = q_cam_from_odom * (upper_odom - cam_position);
                const auto lower_camera = q_cam_from_odom * (lower_odom - cam_position);

                upper3d[i] = upper_camera;
                lower3d[i] = lower_camera;

                const auto upper_opt =
                    reproject_point(Point3d { util::ros2opencv_position(upper_camera) }, feature);
                const auto lower_opt =
                    reproject_point(Point3d { util::ros2opencv_position(lower_camera) }, feature);

                if (upper_opt && lower_opt) {
                    projection_valid[i] = util::valid_association_projection(upper_camera, lower_camera, upper_opt->make<Eigen::Vector2d>(), lower_opt->make<Eigen::Vector2d>());
                    upper2d[i] = upper_opt->make<Eigen::Vector2d>();
                    lower2d[i] = lower_opt->make<Eigen::Vector2d>();
                } else {
                    upper2d[i] = Eigen::Vector2d::Zero();
                    lower2d[i] = Eigen::Vector2d::Zero();
                }
            }

            for (int i = 0; i < 4; ++i) {
                const auto orientation = armors[i].orientation.make<Eigen::Quaterniond>();
                const auto position    = armors[i].translation.make<Eigen::Vector3d>();

                const auto armor_to_center = orientation * Eigen::Vector3d::UnitX();
                const auto armor_face      = -armor_to_center;
                const auto armor_to_cam    = (cam_position - position).normalized();
                const auto yaw = std::acos(std::clamp(armor_face.dot(armor_to_cam), -1.0, 1.0));

                if (yaw >= yaw_part_max) continue;

                const auto left_id  = i * 2;
                const auto right_id = i * 2 + 1;

                if (yaw < yaw_full_max) {
                    visible[left_id]  = true;
                    visible[right_id] = true;
                } else {
                    const auto y_axis = Eigen::Vector3d { orientation * Eigen::Vector3d::UnitY() };
                    const auto on_plus_y                    = armor_to_cam.dot(y_axis) > 0.0;
                    visible[on_plus_y ? right_id : left_id] = true;
                }
            }
        }

        auto visible_lightbars() const noexcept {
            auto result = std::vector<int> { };
            for (int i = 0; i < 8; ++i)
                if (visible[i]) result.push_back(i);
            return result;
        }

        auto visible_armors() const noexcept {
            auto result = std::vector<int> { };
            for (int i = 0; i < 4; ++i)
                if (visible[i * 2] && visible[i * 2 + 1]) result.push_back(i);
            return result;
        }
    };

    Config config { };

    util::CameraFeature camera_feature;

    Context context;
    Observable observable;

    Timestamp init_timestamp = Clock::now();
    std::size_t update_count = 0;
    bool correction_consistent = false;
    ArmorGenre genre { DeviceId::UNKNOWN };
    ArmorColor color { ArmorColor::DARK };

    Addition addition { };

private:
    static auto squared_distance(const Eigen::Vector2d& a, const Eigen::Vector2d& b) noexcept {
        const auto dx = a.x() - b.x();
        const auto dy = a.y() - b.y();
        return dx * dx + dy * dy;
    }

    auto make_observation_jacobian(int lightbar_id) const noexcept -> Eigen::Matrix<double, 4, 11> {
        constexpr auto kEpsilon = 1e-4;

        const auto& state = context.posteriors_state;
        if (state.hasNaN()) {
            return Eigen::Matrix<double, 4, 11>::Zero();
        }
        const auto theta = state[kStateA];

        const auto fx = camera_feature.camera_matrix[0][0];
        const auto fy = camera_feature.camera_matrix[1][1];

        const auto r_cam2odom =
            camera_feature.orientation.make<Eigen::Quaterniond>().conjugate().toRotationMatrix();

        auto jacobian = Eigen::Matrix<double, 4, 11> { };
        jacobian.setZero();

        const auto projection_jacobian =
            [this, fx, fy](const Eigen::Vector3d& point) -> std::optional<Eigen::Matrix<double, 2, 3>> {
            const auto jacobian_pixel_camera = util::projection_jacobian(
                util::ros2opencv_position(point), fx, fy, camera_feature.distort_coeff);
            if (!jacobian_pixel_camera) return std::nullopt;
            auto jacobian_camera_ros = Eigen::Matrix3d { };
            jacobian_camera_ros << 0, -1, 0, 0, 0, -1, 1, 0, 0;
            return *jacobian_pixel_camera * jacobian_camera_ros;
        };

        auto theta_jacobian = [&](int id, bool is_upper) {
            auto compute = [&](double angle) -> Eigen::Vector3d {
                auto solution                 = RobotSolution { };
                solution.input.center         = Translation { Eigen::Vector3d {
                    state[kStateX], state[kStateY], state[kStateZ] } };
                solution.input.toward         = Orientation { Eigen::Quaterniond {
                    Eigen::AngleAxisd { angle, Eigen::Vector3d::UnitZ() } } };
                solution.input.radius_forward = state[kStateRF];
                solution.input.radius_lateral = state[kStateRL];
                solution.input.height_lateral = state[kStateHL];
                solution.input.genre          = genre;
                const auto lightbars          = solution.solve_lightbars();
                const auto& point = is_upper ? lightbars[id].upper : lightbars[id].lower;
                return Eigen::Vector3d { point.x, point.y, point.z };
            };
            const auto position_plus  = compute(theta + kEpsilon);
            const auto position_minus = compute(theta - kEpsilon);
            if (position_plus.hasNaN()) return Eigen::Vector3d { };
            return ((position_plus - position_minus) / (2.0 * kEpsilon)).eval();
        };

        for (int endpoint = 0; endpoint < 2; ++endpoint) {
            const auto row      = endpoint * 2;
            const auto is_upper = (endpoint == 0);
            const auto& point_ros =
                is_upper ? observable.upper3d[lightbar_id] : observable.lower3d[lightbar_id];

            const auto jacobian_projection_opt = projection_jacobian(point_ros);
            if (!jacobian_projection_opt) continue;

            auto jacobian_position = Eigen::Matrix<double, 3, 11>::Zero().eval();

            jacobian_position(0, kStateX)             = 1.0;
            jacobian_position(1, kStateY)             = 1.0;
            jacobian_position(2, kStateZ)             = 1.0;
            jacobian_position.block<3, 1>(0, kStateA) = theta_jacobian(lightbar_id, is_upper);

            const auto armor_id = int { lightbar_id / 2 };
            const auto direction_forward =
                Eigen::Vector3d { +std::cos(theta), +std::sin(theta), 0.0 };
            const auto direction_right =
                Eigen::Vector3d { -std::sin(theta), +std::cos(theta), 0.0 };

            auto jacobian_forward = jacobian_position.block<3, 1>(0, kStateRF);
            auto jacobian_lateral = jacobian_position.block<3, 1>(0, kStateRL);

            if (armor_id == 0) jacobian_forward = direction_forward;
            if (armor_id == 2) jacobian_forward = -direction_forward;

            if (armor_id == 1) jacobian_lateral = direction_right;
            if (armor_id == 3) jacobian_lateral = -direction_right;

            if (armor_id == 1 || armor_id == 3) jacobian_position(2, kStateHL) = 1.0;

            jacobian.block<2, 11>(row, 0).noalias() =
                *jacobian_projection_opt * r_cam2odom * jacobian_position;
        }

        return jacobian;
    }

public:
    explicit Impl(const Config& cfg) noexcept {
        config = cfg;

        observable.yaw_full_max = cfg.yaw_full_max;
        observable.yaw_part_max = cfg.yaw_part_max;

        context.set_noise(config);
        context.reset_covariance();
    }

    auto configure_camera(std::array<double, 9> matrix, std::array<double, 5> coeff) noexcept {
        camera_feature.from(matrix);
        camera_feature.from(coeff);
        observable.feature.from(matrix);
        observable.feature.from(coeff);
    }

    auto update_transform(const Transform& t) noexcept -> void {
        camera_feature.translation     = t.translation;
        camera_feature.orientation     = t.orientation;
        observable.feature.translation = t.translation;
        observable.feature.orientation = t.orientation;
    }

    auto init(std::span<const Armor2d> armors2d) noexcept -> bool {
        constexpr auto kPitch = kPredictedOtherArmorPitch;

        correction_consistent = false;
        genre = DeviceId::UNKNOWN;
        color = ArmorColor::DARK;

        if (armors2d.empty()) return false;
        genre = armors2d[0].genre;
        color = armors2d[0].color;

        const Armor2d* best_armor2d = nullptr;
        {
            auto best_width = 0.0;
            for (const auto& armor2d : armors2d) {
                const auto w = std::abs(armor2d.tr.x - armor2d.tl.x);
                if (w <= best_width) continue;
                best_width   = w;
                best_armor2d = &armor2d;
            }
            if (!best_armor2d) return false;
        }

        auto pnp          = util::RobustPnpSolution { };
        pnp.input.feature = camera_feature;
        pnp.input.armor2d = *best_armor2d;
        if (!pnp.solve()) return false;

        const auto best_armor3d = pnp.result.armor3d;

        const auto orientation = best_armor3d.orientation.make<Eigen::Quaterniond>();
        const auto translation = best_armor3d.translation.make<Eigen::Vector3d>();

        const auto armor2center = Eigen::Vector3d {
            Eigen::AngleAxisd { -kPitch, orientation * Eigen::Vector3d::UnitY() }
                * (orientation * Eigen::Vector3d::UnitX()),
        };
        auto yaw    = util::normalize_angle(std::atan2(-armor2center.y(), -armor2center.x()));
        auto center = Eigen::Vector3d { translation + 0.2 * armor2center };

        context.posteriors_state           = StateVector::Zero();
        context.posteriors_state[kStateX]  = center.x();
        context.posteriors_state[kStateY]  = center.y();
        context.posteriors_state[kStateZ]  = center.z();
        context.posteriors_state[kStateRF] = 0.2;
        context.posteriors_state[kStateRL] = 0.2;
        context.posteriors_state[kStateHL] = 0.0;

        // 验证 PnP yaw：选可见装甲板数更多的朝向
        observable.update(center, yaw, 0.2, 0.2, 0.0, genre);
        const auto orig_count = observable.visible_armors().size();

        const auto alt_yaw = util::normalize_angle(yaw + std::numbers::pi);
        observable.update(center, alt_yaw, 0.2, 0.2, 0.0, genre);
        const auto alt_count = observable.visible_armors().size();

        if (alt_count > orig_count) yaw = alt_yaw;

        context.posteriors_state[kStateA] = yaw;
        observable.update(center, yaw, 0.2, 0.2, 0.0, genre);

        // 重新 Init（包括 correct() 里的降级重置）必须是真正的新航迹：
        // 旧的协方差/计数如果保留，下一次观测会把旧状态的错误增益继续放大。
        context.reset_covariance();
        update_count = 0;
        init_timestamp = Clock::now();
        return true;
    }

    auto predict(double dt) noexcept -> void {
        auto next = context.posteriors_state;
        next[kStateX] += next[kStateVx] * dt;
        next[kStateY] += next[kStateVy] * dt;
        next[kStateZ] += next[kStateVz] * dt;
        next[kStateA] = util::normalize_angle(next[kStateA] + next[kStateW] * dt);

        // ⚠️ 2026-09-22 实机第二轮：update() 已经把 z 夹到 ±2，但 predict() 又会
        //    沿 vz 漂出去。一次采样里 z 从 -2.000 变成 -2.050，刚好越过
        //    diverged() 的 |z|>2，仍然删掉有效航迹。位置预测后必须再夹一次。
        next[kStateX] = std::clamp(next[kStateX], -15.0, 15.0);
        next[kStateY] = std::clamp(next[kStateY], -15.0, 15.0);
        next[kStateZ] = std::clamp(next[kStateZ], -2.0, 2.0);
        next[kStateVx] = std::clamp(next[kStateVx], -10.0, 10.0);
        next[kStateVy] = std::clamp(next[kStateVy], -10.0, 10.0);
        next[kStateVz] = std::clamp(next[kStateVz], -1.0, 1.0);
        const auto rotation_speed_limit = std::max(
            std::abs(config.rotation_speed_min), std::abs(config.rotation_speed_max));
        next[kStateW] = std::clamp(next[kStateW], -rotation_speed_limit, rotation_speed_limit);

        auto jacobian               = Covariance { Covariance::Identity() };
        jacobian(kStateX, kStateVx) = dt;
        jacobian(kStateY, kStateVy) = dt;
        jacobian(kStateZ, kStateVz) = dt;
        jacobian(kStateA, kStateW)  = dt;

        context.posteriors_state = next;
        context.posteriors_covariance =
            jacobian * context.posteriors_covariance * jacobian.transpose() + context.noise_process;

        observable.update(
            {
                next[kStateX],
                next[kStateY],
                next[kStateZ],
            },
            next[kStateA], next[kStateRF], next[kStateRL], next[kStateHL], genre);
    }

    auto update(const Eigen::Vector2d& upper, const Eigen::Vector2d& lower, int id) noexcept -> bool {

        const auto prior_state      = context.posteriors_state;
        const auto prior_covariance = context.posteriors_covariance;

        const auto pred_upper = observable.upper2d[id];
        const auto pred_lower = observable.lower2d[id];

        // innovation (4D)
        auto innovation = Eigen::Vector4d { };
        innovation << upper.x() - pred_upper.x(), upper.y() - pred_upper.y(),
            lower.x() - pred_lower.x(), lower.y() - pred_lower.y();

        // 单装甲板时 anchor 偶尔会关联到另一块虚拟装甲板，残差达到数百像素；
        // 这种观测不能交给 EKF（线性化误差会把 x/y 放大到公里级）。
        // 阈值故意放宽到 300px/角点，只挡明显错关联；正确快移观测若被拒，
        // correct() 会用当前检测重新初始化，而不是把旧状态硬拽过去。
        constexpr double kMaxCornerInnovationPx = 300.0;
        if (!innovation.allFinite() || innovation.cwiseAbs().maxCoeff() > kMaxCornerInnovationPx)
            return false;

        // H (4×11): geometry Jacobian
        const auto jacobian = make_observation_jacobian(id);
        if (!jacobian.allFinite()) return false;

        // Kalman gain
        const auto innovation_covariance =
            jacobian * prior_covariance * jacobian.transpose() + context.noise_observation;
        const auto innovation_covariance_inv = innovation_covariance.inverse();
        if (!innovation_covariance_inv.allFinite()) return false;
        const auto kalman_gain =
            prior_covariance * jacobian.transpose() * innovation_covariance_inv;

        // state update
        auto posterior_state = StateVector { prior_state };
        posterior_state.noalias() += kalman_gain * innovation;

        if (posterior_state.hasNaN() || !posterior_state.allFinite()) return false;
        posterior_state[kStateA] = util::normalize_angle(posterior_state[kStateA]);

        posterior_state[kStateRF] = std::clamp(
            posterior_state[kStateRF], config.radius_forward_min, config.radius_forward_max);
        posterior_state[kStateRL] = std::clamp(
            posterior_state[kStateRL], config.radius_lateral_min, config.radius_lateral_max);
        posterior_state[kStateHL] = std::clamp(
            posterior_state[kStateHL], config.height_lateral_min, config.height_lateral_max);

        posterior_state[kStateVx] = std::clamp(posterior_state[kStateVx], -10.0, 10.0);
        posterior_state[kStateVy] = std::clamp(posterior_state[kStateVy], -10.0, 10.0);
        // ⚠️ 2026-09-22 实机：单装甲板时匹配偶尔跳到另一块虚拟装甲板，
        //    rotation_speed / z / vz 会瞬间冲到发散阈值；原代码只 clamp 了
        //    vx/vy，W 和 vz 没有 clamp，于是 TrackerV2 每 0.3~0.6s 删除模型并重新 Init，
        //    表现为“框还在但 tracking 频繁变 false / 追丢”。这里先把所有状态限制在
        //    物理可能范围内，避免单帧误关联把整条航迹打散；真正的关联门控后续再收紧。
        posterior_state[kStateX] = std::clamp(posterior_state[kStateX], -15.0, 15.0);
        posterior_state[kStateY] = std::clamp(posterior_state[kStateY], -15.0, 15.0);
        posterior_state[kStateZ] = std::clamp(posterior_state[kStateZ], -2.0, 2.0);
        posterior_state[kStateVz] = std::clamp(posterior_state[kStateVz], -1.0, 1.0);
        //    配置里的 rotation_speed_min 默认为 0，但车体可以正/反两个方向转；
        //    必须按 max 的对称范围限制，不能把负角速度强行夹成 0。
        const auto rotation_speed_limit = std::max(
            std::abs(config.rotation_speed_min), std::abs(config.rotation_speed_max));
        posterior_state[kStateW] = std::clamp(
            posterior_state[kStateW], -rotation_speed_limit, rotation_speed_limit);

        // covariance update
        const auto complement          = Covariance::Identity() - kalman_gain * jacobian;
        auto posterior_covariance      = Covariance { };
        posterior_covariance.noalias() = complement * prior_covariance * complement.transpose();
        posterior_covariance +=
            (kalman_gain * context.noise_observation * kalman_gain.transpose()).eval();
        posterior_covariance = 0.5 * (posterior_covariance + posterior_covariance.transpose());

        context.posteriors_state      = posterior_state;
        context.posteriors_covariance = posterior_covariance;

        // 刷新 observable，下个灯条用最新状态预测
        observable.update(
            {
                posterior_state[kStateX],
                posterior_state[kStateY],
                posterior_state[kStateZ],
            },
            posterior_state[kStateA], posterior_state[kStateRF], posterior_state[kStateRL],
            posterior_state[kStateHL], genre);
        return true;
    }

    auto full() const {
        auto solution = RobotSolution { };

        const auto state = context.posteriors_state;

        solution.input.center = Eigen::Vector3d { state[kStateX], state[kStateY], state[kStateZ] };
        solution.input.toward =
            Eigen::Quaterniond { Eigen::AngleAxisd { state[kStateA], Eigen::Vector3d::UnitZ() } };
        solution.input.radius_forward = state[kStateRF];
        solution.input.radius_lateral = state[kStateRL];
        solution.input.height_lateral = state[kStateHL];
        solution.input.genre          = genre;
        solution.input.color          = color;

        return solution.solve_armors();
    }

    struct TrialRecord {
        struct ObservedBar {
            int assigned_id;
            Eigen::Vector2d upper;
            Eigen::Vector2d lower;
            bool accepted;
        };
        bool regular_update = false;
        bool valid_fit = true;
        std::vector<ObservedBar> bars;
        int anchor = -1;
        std::vector<bool> accepted_mask;
        double fit = std::numeric_limits<double>::infinity();
    };

    auto correct_trial(std::span<const Armor2d> armors, std::span<const Lightbar2d> lightbars,
        int forced_anchor, std::size_t forced_observation, TrialRecord& record) noexcept -> bool {
        correction_consistent = false;
        const auto& state = context.posteriors_state;
        observable.update(
            {
                state[kStateX],
                state[kStateY],
                state[kStateZ],
            },
            state[kStateA], state[kStateRF], state[kStateRL], state[kStateHL], genre);

        struct SortedEntry {
            int assigned_id;
            Eigen::Vector2d upper;
            Eigen::Vector2d lower;
            bool accepted = false;
        };
        auto sorted = std::vector<SortedEntry> { };

        // Step 1: 交叉匹配，找四角点误差和最小的完整装甲板作为锚
        //
        // ⚠️ 2026-09-22 回退记录：曾经在这里加过"四角点 RMS 误差 <= 0.6*板宽"的
        //    几何门控（仿真 s3 建议，想挡住误检把 EKF 拽走）。**台架实测证明它有害**：
        //    observable.upper2d/lower2d 是 EKF 用上一帧状态预测的灯条位置，靶子一快
        //    速移动，预测位置与正确检测框的偏差就超过门限 -> 正确观测被拒 ->
        //    EKF 永远得不到修正 -> **检测框照常显示但航迹建不起来（锁不上）**。
        //    结论：关联正确性必须由"预测质量/时间窗"来判，不能用一个固定像素门限；
        //    误关联的抑制改由桥侧护栏（重捕确认 + 脏帧保持）兜底，实测甩头从
        //    456 帧降到 8~43 帧。
        Armor2d const* anchor_armor = nullptr;

        auto anchor_armor_id = int { -1 };
        auto best_error_sum  = std::numeric_limits<double>::max();

        for (const auto& armor : armors) {
            for (int armor_id = 0; armor_id < 4; ++armor_id) {
                const auto left_id  = armor_id * 2;
                const auto right_id = armor_id * 2 + 1;
                if (!observable.visible[left_id] || !observable.visible[right_id]) continue;

                const auto error_0 = squared_distance(
                    Eigen::Vector2d { armor.tl.x, armor.tl.y }, observable.upper2d[left_id]);
                const auto error_1 = squared_distance(
                    Eigen::Vector2d { armor.bl.x, armor.bl.y }, observable.lower2d[left_id]);
                const auto error_2 = squared_distance(
                    Eigen::Vector2d { armor.tr.x, armor.tr.y }, observable.upper2d[right_id]);
                const auto error_3 = squared_distance(
                    Eigen::Vector2d { armor.br.x, armor.br.y }, observable.lower2d[right_id]);
                const auto sum = error_0 + error_1 + error_2 + error_3;

                if (sum >= best_error_sum) continue;
                best_error_sum  = sum;
                anchor_armor_id = armor_id;
                anchor_armor    = &armor;
            }
        }

        if (forced_anchor >= 0) {
            if (forced_anchor >= 4 || forced_observation >= armors.size()) return false;
            anchor_armor_id = forced_anchor;
            anchor_armor = &armors[forced_observation];
        }
        record.anchor = anchor_armor_id;

        // 可见性预测与当前完整板都无法关联时，不能继续保留上次航迹并
        // 假装本帧已校正；从当前观测重建，下一帧再进入 EKF。
        if (!anchor_armor) {
            return init(armors);
        }

        // Step 2: 收集全部观测灯条，按 upper.x 排序
        for (const auto& armor : armors) {
            sorted.push_back({ -1, Eigen::Vector2d { armor.tl.x, armor.tl.y },
                Eigen::Vector2d { armor.bl.x, armor.bl.y } });
            sorted.push_back({ -1, Eigen::Vector2d { armor.tr.x, armor.tr.y },
                Eigen::Vector2d { armor.br.x, armor.br.y } });
        }
        for (const auto& lightbar : lightbars) {
            sorted.push_back({
                -1,
                Eigen::Vector2d { lightbar.upper.x, lightbar.upper.y },
                Eigen::Vector2d { lightbar.lower.x, lightbar.lower.y },
            });
        }

        std::ranges::sort(sorted,
            [](const SortedEntry& a, const SortedEntry& b) { return a.upper.x() < b.upper.x(); });

        // Step 3: 锚定位 → 向两侧递推
        {
            auto anchor_left    = std::size_t { 0 };
            auto anchor_right   = std::size_t { 0 };
            auto min_distance_l = std::numeric_limits<double>::max();
            auto min_distance_r = std::numeric_limits<double>::max();
            for (std::size_t i = 0; i < sorted.size(); ++i) {
                const auto distance_l = std::abs(sorted[i].upper.x() - anchor_armor->tl.x);
                const auto distance_r = std::abs(sorted[i].upper.x() - anchor_armor->tr.x);
                if (distance_l < min_distance_l) {
                    min_distance_l = distance_l;
                    anchor_left    = i;
                }
                if (distance_r < min_distance_r) {
                    min_distance_r = distance_r;
                    anchor_right   = i;
                }
            }

            sorted[anchor_left].assigned_id  = anchor_armor_id * 2;
            sorted[anchor_right].assigned_id = anchor_armor_id * 2 + 1;

            for (std::size_t i = anchor_left + 1; i < sorted.size(); ++i)
                sorted[i].assigned_id = (sorted[i - 1].assigned_id + 1) % 8;

            for (std::size_t i = anchor_left; i > 0; --i)
                sorted[i - 1].assigned_id = (sorted[i].assigned_id - 1 + 8) % 8;
        }

        // Step 4: EKF update + 填 tracked
        addition.tracked.clear();
        int accepted_updates = 0;
        for (auto& entry : sorted) {
            entry.accepted = update(entry.upper, entry.lower, entry.assigned_id);
            if (entry.accepted) ++accepted_updates;
            addition.tracked.push_back(
                { entry.assigned_id, Point2d { entry.upper.x(), entry.upper.y() } });
        }

        // 一整帧的预测关联都被拒绝：说明当前 EKF 已经和观测偏离太远。
        // 直接用本帧观测重开航迹，不让 old state 继续污染下一帧。
        if (accepted_updates == 0) {
            return init(armors);
        }

        for (auto&& [index, armor] : std::views::enumerate(addition.armors)) {
            const auto l = static_cast<int>(index) * 2;
            const auto r = l + 1;

            armor.genre = genre;
            armor.color = color;

            const auto& upper = observable.upper2d;
            const auto& lower = observable.lower2d;

            armor.tl = { static_cast<float>(upper[l].x()), static_cast<float>(upper[l].y()) };
            armor.tr = { static_cast<float>(upper[r].x()), static_cast<float>(upper[r].y()) };
            armor.br = { static_cast<float>(lower[r].x()), static_cast<float>(lower[r].y()) };
            armor.bl = { static_cast<float>(lower[l].x()), static_cast<float>(lower[l].y()) };
        }
        // Check the final posterior against every actually accepted lightbar.
        // Earlier lightbars can be moved away again by later sequential updates.
        // Readiness affects output only; state, covariance and update count keep
        // advancing so fast motion can recover through the direct fallback.
        correction_consistent = true;
        for (const auto& entry : sorted) {
            if (!entry.accepted) continue;
            const auto upper = entry.upper - observable.upper2d[entry.assigned_id];
            const auto lower = entry.lower - observable.lower2d[entry.assigned_id];
            if (!util::posterior_observation_consistent(
                    { upper.x(), upper.y(), lower.x(), lower.y() }, config.noise_observation)) {
                correction_consistent = false;
                break;
            }
        }
        record.regular_update = true;
        record.fit = 0.0;
        record.accepted_mask.reserve(sorted.size());
        for (const auto& entry : sorted) {
            record.accepted_mask.push_back(entry.accepted);
            record.bars.push_back({entry.assigned_id,entry.upper,entry.lower,entry.accepted});
            if (!entry.accepted) continue;
            if (!observable.projection_valid[entry.assigned_id]) record.valid_fit = false;
            const Eigen::Vector2d upper = entry.upper - observable.upper2d[entry.assigned_id];
            const Eigen::Vector2d lower = entry.lower - observable.lower2d[entry.assigned_id];
            record.fit += (upper.squaredNorm() + lower.squaredNorm()) / config.noise_observation;
        }
        update_count += 1;
        return true;
    }


    auto correct(std::span<const Armor2d> armors, std::span<const Lightbar2d> lightbars) noexcept -> bool {
        // All speculative correction paths start at the identical predicted prior.
        // None is allowed to mutate the live model before one entire trial is chosen.
        auto prior = *this;
        const auto& state = prior.context.posteriors_state;
        prior.observable.update({ state[kStateX], state[kStateY], state[kStateZ] },
            state[kStateA], state[kStateRF], state[kStateRL], state[kStateHL], prior.genre);
        auto trials = std::vector<Impl> { prior };
        auto records = std::vector<TrialRecord>(1);
        const bool original_result = trials[0].correct_trial(armors, lightbars, -1, 0, records[0]);
        auto scores = std::vector<util::AssociationTrialScore>(1);
        if (original_result && records[0].regular_update
            && util::association_prior_eligible(prior.update_count, prior.correction_consistent)) {
            const auto original_motion = util::association_motion_cost(state,
                trials[0].context.posteriors_state, prior.context.posteriors_covariance);
            if (original_motion && records[0].valid_fit
                && util::valid_association_covariance(trials[0].context.posteriors_covariance))
                scores[0] = { records[0].fit, *original_motion };
            if (util::valid_association_score(scores[0])) {
                for (int board = 0; board < 4; ++board) {
                    const int left = board * 2, right = left + 1;
                    // The original complete-board visibility policy is unchanged.
                    // A current complete observation may support a separate partial-view trial.
                    if (prior.observable.visible[left] == prior.observable.visible[right]) continue;
                    std::optional<std::size_t> best;
                    double best_error = std::numeric_limits<double>::infinity();
                    for (std::size_t i = 0; i < armors.size(); ++i) {
                        const auto& a = armors[i];
                        const double error = squared_distance({a.tl.x,a.tl.y},prior.observable.upper2d[left])
                            + squared_distance({a.bl.x,a.bl.y},prior.observable.lower2d[left])
                            + squared_distance({a.tr.x,a.tr.y},prior.observable.upper2d[right])
                            + squared_distance({a.br.x,a.br.y},prior.observable.lower2d[right]);
                        if (error < best_error) { best_error = error; best = i; }
                    }
                    if (!best) continue;
                    auto trial = prior;
                    auto record = TrialRecord { };
                    const bool result = trial.correct_trial(armors, lightbars, board, *best, record);
                    util::AssociationTrialScore score;
                    if (result && record.regular_update && record.valid_fit
                        && util::valid_association_covariance(trial.context.posteriors_covariance)
                        && record.accepted_mask == records[0].accepted_mask) {
                        const auto motion = util::association_motion_cost(state,
                            trial.context.posteriors_state, prior.context.posteriors_covariance);
                        if (motion) score = { record.fit, *motion };
                    }
                    trials.push_back(std::move(trial));
                    records.push_back(std::move(record));
                    scores.push_back(score);
                }
            }
        }
        [[maybe_unused]] const std::size_t suggested = util::unique_association_dominator(scores).value_or(0);
#ifdef RMCS_ASSOCIATION_TRANSACTION_PRESERVE_ORIGINAL
        const std::size_t chosen = 0;
#else
        const std::size_t chosen = suggested;
#endif
#ifdef RMCS_ASSOCIATION_TRANSACTION_TRACE
        std::fprintf(stderr,"{\"event\":\"transaction_decision\",\"control_ns\":%lld,\"genre\":%d,\"prior_count\":%zu,\"chosen\":%zu,\"prior_state\":[",static_cast<long long>(std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count()),static_cast<int>(genre),prior.update_count,chosen);
        for(int i=0;i<11;++i)std::fprintf(stderr,"%s%.17g",i?",":"",state[i]);
        std::fprintf(stderr,"],\"prior_consistent\":%s,\"suggested\":%zu,\"R\":%.17g,\"prior_covariance\":[",prior.correction_consistent?"true":"false",suggested,config.noise_observation);
        for(int j=0;j<121;++j)std::fprintf(stderr,"%s%.17g",j?",":"",prior.context.posteriors_covariance(j/11,j%11));
        const auto camera_q = camera_feature.orientation.make<Eigen::Quaterniond>();
        const auto camera_p = camera_feature.translation.make<Eigen::Vector3d>();
        std::fprintf(stderr,"],\"camera_q\":[%.17g,%.17g,%.17g,%.17g],\"camera_p\":[%.17g,%.17g,%.17g],\"K\":[",camera_q.w(),camera_q.x(),camera_q.y(),camera_q.z(),camera_p.x(),camera_p.y(),camera_p.z());
        for(int j=0;j<9;++j)std::fprintf(stderr,"%s%.17g",j?",":"",camera_feature.camera_matrix[j/3][j%3]);
        std::fprintf(stderr,"],\"D\":[");
        for(int j=0;j<5;++j)std::fprintf(stderr,"%s%.17g",j?",":"",camera_feature.distort_coeff[j]);
        std::fprintf(stderr,"],\"trials\":[");
        for(std::size_t i=0;i<trials.size();++i){
            std::fprintf(stderr,"%s{\"anchor\":%d,\"regular\":%s,\"count\":%zu,\"ready\":%s,\"fit\":",i?",":"",records[i].anchor,records[i].regular_update?"true":"false",trials[i].update_count,trials[i].converge()?"true":"false");
            if(std::isfinite(scores[i].fit))std::fprintf(stderr,"%.17g",scores[i].fit);else std::fprintf(stderr,"null");
            std::fprintf(stderr,",\"motion\":");
            if(std::isfinite(scores[i].motion))std::fprintf(stderr,"%.17g",scores[i].motion);else std::fprintf(stderr,"null");
            std::fprintf(stderr,",\"accepted_mask\":[");
            for(std::size_t j=0;j<records[i].accepted_mask.size();++j)std::fprintf(stderr,"%s%s",j?",":"",records[i].accepted_mask[j]?"true":"false");
            std::fprintf(stderr,"],\"valid_fit\":%s,\"bars\":[",records[i].valid_fit?"true":"false");
            for(std::size_t j=0;j<records[i].bars.size();++j){const auto& b=records[i].bars[j];std::fprintf(stderr,"%s{\"id\":%d,\"upper\":[%.17g,%.17g],\"lower\":[%.17g,%.17g],\"accepted\":%s}",j?",":"",b.assigned_id,b.upper.x(),b.upper.y(),b.lower.x(),b.lower.y(),b.accepted?"true":"false");}
            std::fprintf(stderr,"],\"covariance\":[");
            for(int j=0;j<121;++j)std::fprintf(stderr,"%s%.17g",j?",":"",trials[i].context.posteriors_covariance(j/11,j%11));
            std::fprintf(stderr,"],\"state\":[");
            for(int j=0;j<11;++j)std::fprintf(stderr,"%s%.17g",j?",":"",trials[i].context.posteriors_state[j]);
            std::fprintf(stderr,"]}");
        }
        std::fprintf(stderr,"]}\n");
#endif
        *this = std::move(trials[chosen]);
        return chosen == 0 ? original_result : true;
    }

    auto converge() const -> bool {
        constexpr auto kMinUpdate = std::size_t { 10 };
        constexpr auto kMaxCovXY  = 1.0;

        if (update_count < kMinUpdate || !correction_consistent) return false;

        const auto& cov = context.posteriors_covariance;
        if (cov(kStateX, kStateX) > kMaxCovXY) return false;
        if (cov(kStateY, kStateY) > kMaxCovXY) return false;

        using namespace std::chrono_literals;
        if (Clock::now() - init_timestamp < 0.1s) return false;

        return true;
    }

    auto diverged() const -> bool {
        const auto& state = context.posteriors_state;
        const auto& cov   = context.posteriors_covariance;
        return std::ranges::any_of(
            std::array {
                cov(kStateX, kStateX) > 150,
                cov(kStateY, kStateY) > 150,

                std::abs(state[kStateX]) > 15.0,
                std::abs(state[kStateY]) > 15.0,
                std::abs(state[kStateZ]) > 02.0,
                std::abs(state[kStateW]) > 10.0 * std::numbers::pi,

                // ⚠️ 2026-09-22 实机：update() 已把 vx/vy 夹到 ±10，但这里却
                //    用 >5 判发散。目标（或手持装甲板）快速横移时 vy 很容易到 5~7，
                //    航迹因此被误删，下一帧重新 Init，表现为“框还在但 tracking 频繁丢”。
                //    阈值必须和 update() 的物理限幅一致，否则限幅值本身就是假阳性源。
                std::abs(state[kStateVx]) > 10.,
                std::abs(state[kStateVy]) > 10.,
                std::abs(state[kStateVz]) > 1.,

                state.hasNaN() == true,
                state.allFinite() == false,
            },
            std::identity { });
    }
};

RobotModel::RobotModel(const Config& cfg) noexcept
    : pimpl { std::make_unique<Impl>(cfg) } { }

RobotModel::~RobotModel() noexcept = default;

auto RobotModel::update_camera(std::array<double, 9> matrix, std::array<double, 5> coeff) noexcept
    -> void {
    pimpl->configure_camera(matrix, coeff);
}

auto RobotModel::init(std::span<const Armor2d> armors) noexcept -> bool {
    return pimpl->init(armors);
}

auto RobotModel::update_transform(const Transform& t) noexcept -> void {
    pimpl->update_transform(t);
}

auto RobotModel::predict(double dt) noexcept -> void { pimpl->predict(dt); }

auto RobotModel::correct(
    std::span<const Armor2d> armors, std::span<const Lightbar2d> lightbars) noexcept -> bool {
    return pimpl->correct(armors, lightbars);
}

auto RobotModel::state() const noexcept -> State { return pimpl->context.get_state(); }

auto RobotModel::full() const -> std::array<Armor3d, 4> { return pimpl->full(); }

auto RobotModel::converge() const -> bool { return pimpl->converge(); }
auto RobotModel::diverged() const -> bool { return pimpl->diverged(); }

auto RobotModel::addition() const -> const Addition& { return pimpl->addition; }
