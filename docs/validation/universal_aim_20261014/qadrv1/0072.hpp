#pragma once

#include <array>
#include <cmath>
#include <optional>
#include <eigen3/Eigen/Core>

namespace rmcs::util {

// Derivative of OpenCV's five-coefficient distorted projection with respect
// to an OpenCV camera-frame point. The forward EKF observation uses the same
// (k1, k2, p1, p2, k3) model through cv::projectPoints.
inline auto projection_jacobian(const Eigen::Vector3d& point, double fx, double fy,
    const std::array<double, 5>& distortion) -> std::optional<Eigen::Matrix<double, 2, 3>> {
    constexpr double kMinDepth = 0.1;
    if (!point.allFinite() || point.z() < kMinDepth || !std::isfinite(fx)
        || !std::isfinite(fy)) return std::nullopt;

    const double x = point.x() / point.z();
    const double y = point.y() / point.z();
    const double r2 = x * x + y * y;
    const auto [k1, k2, p1, p2, k3] = distortion;
    const double radial = 1.0 + r2 * (k1 + r2 * (k2 + r2 * k3));
    const double radial_slope = k1 + r2 * (2.0 * k2 + 3.0 * r2 * k3);
    const double cross = 2.0 * x * y * radial_slope + 2.0 * p1 * x + 2.0 * p2 * y;

    Eigen::Matrix2d pixel_normalized;
    pixel_normalized << fx * (radial + 2.0 * x * x * radial_slope + 2.0 * p1 * y + 6.0 * p2 * x),
        fx * cross, fy * cross,
        fy * (radial + 2.0 * y * y * radial_slope + 6.0 * p1 * y + 2.0 * p2 * x);
    Eigen::Matrix<double, 2, 3> normalized_camera;
    normalized_camera << 1.0 / point.z(), 0.0, -x / point.z(),
        0.0, 1.0 / point.z(), -y / point.z();
    Eigen::Matrix<double, 2, 3> result = pixel_normalized * normalized_camera;
    if (!result.allFinite()) return std::nullopt;
    return result;
}

} // namespace rmcs::util
