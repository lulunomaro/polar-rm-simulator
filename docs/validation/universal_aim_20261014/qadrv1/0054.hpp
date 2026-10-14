#pragma once

#include <array>
#include <cmath>

namespace rmcs::util {

// Output-readiness check after the whole EKF correction. This is not an
// innovation gate: a failure must not discard an accepted update or reset the
// track. Use the existing pixel variance to scale the final four-coordinate
// residual. The chi-square(4, .99) magnitude is a conservative consistency
// bound, not a calibrated false-rejection probability for fitted residuals.
inline auto posterior_observation_consistent(
    const std::array<double, 4>& residual, double pixel_variance) -> bool {
    if (!std::isfinite(pixel_variance) || pixel_variance <= 0.0) return false;
    double energy = 0.0;
    for (double value : residual) {
        if (!std::isfinite(value)) return false;
        energy += value * value / pixel_variance;
    }
    constexpr double kMaxResidualEnergy = 13.2767041359876;
    return std::isfinite(energy) && energy <= kMaxResidualEnergy;
}

} // namespace rmcs::util
