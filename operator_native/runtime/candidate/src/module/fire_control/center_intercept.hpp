#pragma once

#include "module/fire_control/trajectory_solution.hpp"
#include "module/tracker/trackable.hpp"

namespace rmcs {

struct CenterIntercept {
    TrajectorySolution::Output launch;
    Point3d center;
    Point3d armor;
    Point3d crossing;
    double fly_time = 0.0;
    double lateral_error = 0.0;
    double vertical_error = 0.0;
    std::size_t armor_index = 0;
};

// Trackable exposes centers, not full armor poses. Model each plate as a
// vertical plane with the horizontal outward radial normal. Keep all times
// relative to actual launch; age + shoot_delay is the separate state increment.
// Retain the center-waiting yaw. Only pitch is corrected to this future plate's
// height on its own radial plane, never yaw toward an individual armor and
// never a radius/v time correction.
namespace detail {
inline auto solve_armor_intercept(const Trackable& target, double increment,
    TrajectorySolution::Input input, double yaw_offset, double pitch_offset,
    std::optional<TrajectorySolution::Output> fixed_launch = std::nullopt,
    double lateral_bound = 1.0, double vertical_bound = 1.0)
    -> std::optional<CenterIntercept> {
    const auto finite = [](const auto& p) {
        return std::isfinite(p.x) && std::isfinite(p.y) && std::isfinite(p.z);
    };
    if (!std::isfinite(increment) || !finite(target.get_direction())) return std::nullopt;
    auto trajectory = TrajectorySolution { .input = input };
    trajectory.input.point = target.get_direction();
    auto initial = fixed_launch ? fixed_launch : trajectory.solve();
    if (!initial) return std::nullopt;

    const auto initial_points = target.get_aimpoints();
    auto best = std::optional<CenterIntercept> { };
    auto best_score = std::numeric_limits<double>::infinity();
    for (std::size_t index = 0; index < initial_points.size(); ++index) {
        const auto center0 = target.get_direction();
        const auto radius = std::hypot(initial_points[index].x - center0.x,
            initial_points[index].y - center0.y);
        if (!std::isfinite(radius) || radius <= 1e-6) continue;

        // The near radial plane gives only a seed. Every accepted result below
        // is solved against the individual moving armor plane itself.
        const auto center_distance = std::hypot(center0.x, center0.y);
        if (center_distance <= radius) continue;
        const auto normal0 = Vector3d { center0.x / center_distance,
            center0.y / center_distance, 0.0 };
        const auto shell_point = Point3d { center0.x - radius * normal0.x,
            center0.y - radius * normal0.y, center0.z };
        const auto seed = trajectory.intersect_vertical_plane(*initial, shell_point, normal0);
        if (!seed) continue;
        auto time = seed->fly_time;

        for (int iteration = 0; iteration < 16; ++iteration) {
            auto future = target.clone();
            future->jump_into(increment + time);
            const auto center = future->get_direction();
            const auto points = future->get_aimpoints();
            if (index >= points.size() || !points[index].valid) break;
            const auto armor = points[index];
            if (!finite(center) || !finite(armor)) break;
            const auto r = std::hypot(armor.x - center.x, armor.y - center.y);
            if (!std::isfinite(r) || r <= 1e-6) break;
            const auto normal = Vector3d { (armor.x - center.x) / r,
                (armor.y - center.y) / r, 0.0 };

            trajectory.input.point = center;
            auto launch = fixed_launch ? fixed_launch : trajectory.solve();
            if (!launch) break;
            if (!fixed_launch) {
                launch = trajectory.solve_pitch_for_vertical_plane(
                    launch->yaw, launch->pitch, armor, normal);
                if (!launch) break;
                launch->yaw += yaw_offset;
                launch->pitch += pitch_offset;
            }
            const auto origin = TrajectorySolution::muzzle_origin(input.muzzle_offset,
                launch->yaw, launch->pitch);
            // The gun must view the front, and the projectile must enter it.
            if ((origin.x - armor.x) * normal.x + (origin.y - armor.y) * normal.y <= 0.0
                || normal.x * std::cos(launch->yaw) + normal.y * std::sin(launch->yaw) >= -1e-6) break;
            const auto crossing = trajectory.intersect_vertical_plane(*launch, armor, normal);
            if (!crossing) break;
            const auto delta_time = crossing->fly_time - time;
            if (std::abs(delta_time) < 1e-6) {
                const auto lateral = -(crossing->point.x - armor.x) * normal.y
                    + (crossing->point.y - armor.y) * normal.x;
                const auto vertical = crossing->point.z - armor.z;
                if (!std::isfinite(lateral) || !std::isfinite(vertical)) break;
                auto result = CenterIntercept {
                    .launch = *launch, .center = center, .armor = armor,
                    .crossing = crossing->point, .fly_time = crossing->fly_time,
                    .lateral_error = lateral, .vertical_error = vertical, .armor_index = index,
                };
                // For a measured ray choose a candidate inside BOTH bounds if
                // one exists; the center-command strategy retains its old choice.
                const auto score = fixed_launch
                    ? std::max(std::abs(lateral) / lateral_bound, std::abs(vertical) / vertical_bound)
                    : std::abs(lateral);
                if (score < best_score) { best = result; best_score = score; }
                break;
            }
            time = crossing->fly_time;
        }
    }
    return best;
}

} // namespace detail

inline auto solve_center_intercept(const Trackable& target, double increment,
    TrajectorySolution::Input input, double yaw_offset = 0.0, double pitch_offset = 0.0)
    -> std::optional<CenterIntercept> {
    return detail::solve_armor_intercept(target, increment, input, yaw_offset, pitch_offset);
}

// Fixed physical launch direction from the available measured gimbal pose.
// Never solve toward the center or add command calibration offsets here.
// Age + shoot_delay still advance the TARGET; no future own-pose measurement
// is fabricated. An exposure snapshot is not a real-time muzzle-pose promise.
inline auto solve_measured_intercept(const Trackable& target, double increment,
    TrajectorySolution::Input input, double measured_yaw, double measured_pitch,
    double lateral_bound, double vertical_bound) -> std::optional<CenterIntercept> {
    if (!std::isfinite(measured_yaw) || !std::isfinite(measured_pitch)
        || !std::isfinite(lateral_bound) || lateral_bound <= 0.0
        || !std::isfinite(vertical_bound) || vertical_bound <= 0.0) return std::nullopt;
    return detail::solve_armor_intercept(target, increment, input, 0.0, 0.0,
        TrajectorySolution::Output { .yaw = measured_yaw, .pitch = measured_pitch },
        lateral_bound, vertical_bound);
}

} // namespace rmcs
