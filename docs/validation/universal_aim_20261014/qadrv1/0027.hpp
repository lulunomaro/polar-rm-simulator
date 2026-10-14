#pragma once

#include "module/tracker/trackable.hpp"
#include "utility/clock.hpp"
#include "utility/pimpl.hpp"
#include "utility/robot/armor.hpp"
#include "utility/robot/rune.hpp"

#include <optional>
#include <cstddef>
#include <span>
#include <yaml-cpp/yaml.h>

namespace rmcs::kernel {

class Tracker {
    RMCS_PIMPL_DEFINITION(Tracker)

public:
    struct FrameStats {
        std::size_t raw2d = 0;
        std::size_t accepted2d = 0;
        std::size_t accepted3d = 0;
        std::size_t rejected_color = 0;
        std::size_t rejected_genre = 0;
        std::size_t rejected_margin = 0;
        std::size_t rejected_clipped = 0;
    };

    struct Addition {
        Armor2ds tracked2d;
        Armor3ds tracked3d;

        struct Lightbar {
            int id;
            Point2d point;
        };
        std::vector<Lightbar> lightbars;

        struct RuneFeature {
            int id;
            Point2d point;
        };
        std::vector<RuneFeature> rune_features;

        struct RunePolygon {
            Point2d icon;
            std::array<Point2d, 5> blades;
        };
        std::optional<RunePolygon> rune_polygon;

        struct Info {
            std::string text;
            Point3d point;
        };
        std::vector<Info> infos;
    };

    explicit Tracker(const YAML::Node&);
    // Isolate runtime-mode files for tests or separate tracker instances.
    Tracker(const YAML::Node&, std::string runtime_mode_file);

    /// @brief:
    ///  设置自瞄意图，当关闭自瞄时，选取距离相机 X 轴最近的
    ///  机器人锁定，当自瞄开启时，锁定该机器人，即使该机器
    ///  人离开视野
    auto update_aim_intent(bool intent) -> void;

    /// @brief:
    ///  设置锁定超时，开启时，锁定对象将会被模型超时所清理，
    ///  此时会按照正常的优先级选取下一个目标，关闭时，一旦
    ///  锁定，则永远只瞄准该目标，直到自瞄意图被关闭
    auto update_aim_cleanup(bool on) -> void;

    auto update_track_color(CampColor) -> void;
    auto update_track_genre(DeviceIds) -> void;

    auto update_camera(const Transform&) noexcept -> void;
    auto update_camera(const std::array<double, 9>&) noexcept -> void;
    auto update_camera(const std::array<double, 5>&) noexcept -> void;

    auto update_image_size(int width, int height) noexcept -> void;

    auto clean() noexcept -> void;

    auto store(std::span<const Armor2d>) -> void;
    auto store(std::span<const Armor3d>) -> void;
    auto store(std::span<const Lightbar2d>) -> void;
    auto store(std::span<const RuneIcon>) -> void;
    auto store(std::span<const RuneBullseye>) -> void;

    auto execute(Timestamp) -> Trackable::Unique;

    // True only if the selected target was initialized/corrected by this frame.
    // A retained outpost/rune model (including prediction-only rune) is false.
    auto observed_selected_target() const noexcept -> bool;

    auto addition() const -> const Addition&;
    auto frame_stats() const noexcept -> FrameStats;
};

}
