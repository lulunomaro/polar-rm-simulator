#include "trajectory_solution.hpp"

#include <cmath>
#include <tuple>

using namespace rmcs;

namespace details {

constexpr auto kMaxIterateCount          = int { 10 };
constexpr auto kMaxPitchThreold          = double { 80.0 / 57.3 };
constexpr auto kEstimateDeltaTime        = double { 0.005 };
constexpr auto kHeightErrorThreold       = double { 0.001 };
constexpr auto kEstimateTimeOutThreold   = double { 4.0 };
constexpr auto kMinVelocityX             = double { 0.1 };
constexpr auto kGravity                  = double { 9.81 };
constexpr auto kAirResistanceCoefficient = double { 0.003 };

constexpr auto estimate(double v0, double pitch, double d, double air_resistance,
    bool* reached = nullptr)
    -> std::tuple<double, double> {

    double x = 0, y = 0, t = 0;
    double vx = v0 * std::cos(pitch);
    double vy = v0 * std::sin(pitch);

    double prev_x = 0, prev_y = 0, prev_t = 0;

    while (x < d) {
        prev_x = x;
        prev_y = y;
        prev_t = t;

        const double v = std::sqrt(vx * vx + vy * vy);

        vx -= air_resistance * v * vx * kEstimateDeltaTime;
        vy -= (kGravity + air_resistance * v * vy) * kEstimateDeltaTime;

        x += vx * kEstimateDeltaTime;
        y += vy * kEstimateDeltaTime;
        t += kEstimateDeltaTime;

        if (t > kEstimateTimeOutThreold || vx <= kMinVelocityX) [[unlikely]]
            break;
    }

    if (reached) *reached = x >= d;
    if (x >= d && x > prev_x) {
        double ratio = (d - prev_x) / (x - prev_x);
        return { std::lerp(prev_y, y, ratio), std::lerp(prev_t, t, ratio) };
    }
    return { y, t };
}

}

static auto solve_from_origin(double v0, const Point3d& point)
    -> std::optional<TrajectorySolution::Output> {

    const auto target_d = std::hypot(point.x, point.y);
    const auto target_h = point.z;

    if (v0 <= 0 || target_d <= 0) return std::nullopt;

    const auto yaw = std::atan2(point.y, point.x);

    double pitch = std::atan2(target_h, target_d);
    for (int i = 0; i < details::kMaxIterateCount; ++i) {
        auto [actual_h, t] =
            details::estimate(v0, pitch, target_d, details::kAirResistanceCoefficient);

        auto h_error = target_h - actual_h;
        if (std::abs(h_error) < details::kHeightErrorThreold) {
            auto result     = TrajectorySolution::Output { };
            result.fly_time = t;
            result.yaw      = yaw;
            result.pitch    = -pitch;
            return result;
        }

        pitch += std::atan2(h_error, target_d);

        if (std::abs(pitch) > details::kMaxPitchThreold) break;
    }

    return std::nullopt;
}

auto TrajectorySolution::muzzle_origin(const Point3d& offset, double yaw, double pitch) -> Point3d {
    const auto x = std::cos(pitch) * offset.x + std::sin(pitch) * offset.z;
    return Point3d {
        std::cos(yaw) * x - std::sin(yaw) * offset.y,
        std::sin(yaw) * x + std::cos(yaw) * offset.y,
        -std::sin(pitch) * offset.x + std::cos(pitch) * offset.z,
    };
}

auto TrajectorySolution::solve() const -> std::optional<Output> {
    const auto finite = [](const auto& p) {
        return std::isfinite(p.x) && std::isfinite(p.y) && std::isfinite(p.z);
    };
    if (!std::isfinite(input.v0) || !finite(input.point) || !finite(input.muzzle_offset)) {
        return std::nullopt;
    }
    auto solution = solve_from_origin(input.v0, input.point);
    if (!solution) return std::nullopt;
    // Exactly preserve the legacy point solver when no extrinsic is configured.
    if (input.muzzle_offset.x == 0.0 && input.muzzle_offset.y == 0.0
        && input.muzzle_offset.z == 0.0) return solution;

    for (int i = 0; i < 32; ++i) {
        const auto origin = muzzle_origin(input.muzzle_offset, solution->yaw, solution->pitch);
        const auto relative = Point3d {
            input.point.x - origin.x, input.point.y - origin.y, input.point.z - origin.z,
        };
        auto next = solve_from_origin(input.v0, relative);
        if (!next) return std::nullopt;
        const auto change = std::hypot(std::remainder(next->yaw - solution->yaw,
            2.0 * std::acos(-1.0)), next->pitch - solution->pitch);
        solution = next;
        if (change < 1e-7) return solution;
    }
    // A short muzzle-to-target range can make the rotated-origin fixed point
    // converge too slowly for the bounded iteration count, even for reachable
    // low-arc targets. Preserve every legacy
    // converged result, but resolve that failure with the existing forward-
    // validated fixed-yaw pitch solver. In barrel coordinates the target's
    // lateral component must equal the fixed muzzle Y offset, so yaw is exact.
    const auto horizontal_range = std::hypot(input.point.x, input.point.y);
    if (horizontal_range <= std::abs(input.muzzle_offset.y)) return std::nullopt;
    const auto yaw = std::atan2(input.point.y, input.point.x)
        - std::asin(input.muzzle_offset.y / horizontal_range);
    return solve_pitch_for_vertical_plane(yaw, solution->pitch, input.point,
        Vector3d { std::cos(yaw), std::sin(yaw), 0.0 });
}

auto TrajectorySolution::intersect_vertical_plane(const Output& launch,
    const Point3d& plane_point, const Vector3d& plane_normal) const
    -> std::optional<Intersection> {
    const auto finite = [](const auto& p) {
        return std::isfinite(p.x) && std::isfinite(p.y) && std::isfinite(p.z);
    };
    if (!finite(plane_point) || !finite(plane_normal) || !finite(input.muzzle_offset)
        || !std::isfinite(launch.yaw) || !std::isfinite(launch.pitch)
        || !std::isfinite(launch.fly_time)) return std::nullopt;
    const auto origin = muzzle_origin(input.muzzle_offset, launch.yaw, launch.pitch);
    const auto dx = std::cos(launch.yaw);
    const auto dy = std::sin(launch.yaw);
    const auto denominator = plane_normal.x * dx + plane_normal.y * dy;
    if (!std::isfinite(denominator) || std::abs(denominator) < 1e-9
        || plane_normal.z != 0.0 || !std::isfinite(input.v0) || input.v0 <= 0.0
        || !std::isfinite(launch.pitch)) return std::nullopt;
    const auto distance = ((plane_point.x - origin.x) * plane_normal.x
        + (plane_point.y - origin.y) * plane_normal.y) / denominator;
    if (!std::isfinite(distance) || distance <= 0.0
        || distance > input.v0 * details::kEstimateTimeOutThreold) return std::nullopt;
    auto reached = false;
    const auto [height, time] = details::estimate(input.v0, -launch.pitch, distance,
        details::kAirResistanceCoefficient, &reached);
    if (!reached || !std::isfinite(height) || !std::isfinite(time)
        || time >= details::kEstimateTimeOutThreold) return std::nullopt;
    return Intersection {
        .fly_time = time,
        .point = Point3d { origin.x + distance * dx, origin.y + distance * dy, origin.z + height },
    };
}


auto TrajectorySolution::solve_pitch_for_vertical_plane(double yaw, double initial_pitch,
    const Point3d& plane_point, const Vector3d& plane_normal) const
    -> std::optional<Output> {
    // This is a bounded low-arc correction, not permission to relax the hit
    // window. Acceptance is always checked by the original forward integrator.
    constexpr auto kPitchIterations = 16;
    constexpr auto kPlaneHeightResidual = 1e-5;
    if (!std::isfinite(yaw) || !std::isfinite(initial_pitch)
        || std::abs(initial_pitch) > details::kMaxPitchThreold) return std::nullopt;
    auto launch = Output { .yaw = yaw, .pitch = initial_pitch };
    for (int i = 0; i < kPitchIterations; ++i) {
        const auto crossing = intersect_vertical_plane(launch, plane_point, plane_normal);
        if (!crossing) return std::nullopt;
        const auto residual = crossing->point.z - plane_point.z;
        if (!std::isfinite(residual)) return std::nullopt;
        if (std::abs(residual) <= kPlaneHeightResidual) {
            // Both sides must decrease with downward command pitch. A single
            // forward chord can straddle the peak and falsely accept a tangent
            // or a nearby high-arc root. Keep a conservative symmetric margin.
            constexpr auto kSlopeProbe = 1e-5;
            if (std::abs(launch.pitch) + kSlopeProbe > details::kMaxPitchThreold) {
                return std::nullopt;
            }
            for (const auto step : { -kSlopeProbe, kSlopeProbe }) {
                auto probe = launch;
                probe.pitch += step;
                const auto adjacent = intersect_vertical_plane(probe, plane_point, plane_normal);
                if (!adjacent) return std::nullopt;
                const auto slope = (adjacent->point.z - crossing->point.z) / step;
                if (!std::isfinite(slope) || slope >= -1e-6) return std::nullopt;
            }
            launch.fly_time = crossing->fly_time;
            return launch;
        }
        // Positive command pitch points downward. Scale the correction by
        // cos^2(pitch) to retain convergence for both upward and downward shots.
        // The pivot-relative range includes the rotating muzzle-forward offset;
        // using only muzzle-to-plane range would overcorrect at short range.
        const auto range = crossing->point.x * std::cos(yaw)
            + crossing->point.y * std::sin(yaw);
        if (!std::isfinite(range) || range <= 1e-6) return std::nullopt;
        const auto cosine = std::cos(launch.pitch);
        launch.pitch += std::atan2(residual * cosine * cosine, range);
        if (!std::isfinite(launch.pitch)
            || std::abs(launch.pitch) > details::kMaxPitchThreold) return std::nullopt;
    }
    return std::nullopt;
}
