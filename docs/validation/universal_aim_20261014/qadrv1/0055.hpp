#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>

namespace rmcs::util {

// Intrinsic principal points are not image dimensions (off-centre calibration
// is normal). Check every corner, including NaNs, against the captured frame.
template <class Corners>
auto armor_inside_image(const Corners& corners, int width, int height, double margin) -> bool {
    if (width <= 0 || height <= 0 || !std::isfinite(margin) || margin < 0.0) return false;
    for (const auto& p : corners) {
        if (!std::isfinite(p.x) || !std::isfinite(p.y)
            || p.x < margin || p.x > width - 1.0 - margin
            || p.y < margin || p.y > height - 1.0 - margin) return false;
    }
    return true;
}

// Armor3d::id is the index in the unfiltered PnP input. Preserve that mapping
// when the corresponding 2D armor is rejected by color, genre or image bounds.
template <class Mask>
auto accepted_armor_id(int id, const Mask& accepted) -> bool {
    return id >= 0 && static_cast<std::size_t>(id) < accepted.size() && accepted[id];
}

// A discontinuity must start from the new measurement, never retain the old
// point while giving it a fresh timestamp. The caller selects the axis's lag.
inline auto direct_armor_alpha(double dt, bool same_target, double tau = 0.05) -> double {
    if (!same_target || !std::isfinite(dt) || dt <= 0.0 || dt >= 0.2
        || !std::isfinite(tau) || tau <= 0.0) return 1.0;
    return dt / (tau + dt);
}

// Estimate world-frame bearing velocity from actual consecutive observations.
// Reject discontinuities instead of converting a changed target into a fast lead.
inline auto direct_armor_yaw_velocity(double previous_rate, double previous_yaw,
    double yaw, double dt, bool same_target) -> double {
    if (!same_target || !std::isfinite(dt) || dt <= 0.0 || dt >= 0.2
        || !std::isfinite(previous_rate) || !std::isfinite(previous_yaw)
        || !std::isfinite(yaw)) return 0.0;
    const double delta = std::atan2(std::sin(yaw - previous_yaw), std::cos(yaw - previous_yaw));
    const double rate = delta / dt;
    if (std::abs(rate) > 8.0) return 0.0;
    const double alpha = dt / (0.03 + dt);
    return std::clamp(previous_rate + alpha * (rate - previous_rate), -4.0, 4.0);
}

// Cap both time (80 ms) and angle (0.15 rad). This does not extend track lifetime.
inline auto direct_armor_lead_angle(double yaw_rate, double seconds) -> double {
    if (!std::isfinite(yaw_rate) || !std::isfinite(seconds) || seconds <= 0.0) return 0.0;
    return std::clamp(yaw_rate * std::min(seconds, 0.08), -0.15, 0.15);
}

} // namespace rmcs::util
