#pragma once

#include "utility/math/linear.hpp"

#include <optional>

namespace rmcs {

struct TrajectorySolution {
    struct Input {
        double v0 { 0. };
        Point3d point { };
        // Pitch-pivot to muzzle translation, in barrel-local X-forward,
        // Y-left, Z-up metres. Rotation is Rz(yaw) * Ry(command_pitch).
        Point3d muzzle_offset { 0.0, 0.0, 0.0 };
    } input;

    struct Output {
        double fly_time { 0. }; // s
        double yaw { 0. }; // rad
        double pitch { 0. }; // rad
    } result { };

    struct Intersection {
        double fly_time = 0.0;
        Point3d point { };
    };

    auto solve() const -> std::optional<Output>;

    // Keep yaw fixed and solve only pitch to reach this plane's height.
    // Muzzle translation is rotated again for every pitch trial. Calibration
    // remains the caller's final additive step, followed by a fresh crossing.
    auto solve_pitch_for_vertical_plane(double yaw, double initial_pitch,
        const Point3d& plane_point, const Vector3d& plane_normal) const
        -> std::optional<Output>;

    static auto muzzle_origin(const Point3d& offset, double yaw, double pitch) -> Point3d;

    // Follow THIS launch direction, with the same integrator as solve().
    // The plane normal is horizontal; no fresh point-aim solution is taken.
    auto intersect_vertical_plane(const Output& launch, const Point3d& plane_point,
        const Vector3d& plane_normal) const -> std::optional<Intersection>;
};

}
