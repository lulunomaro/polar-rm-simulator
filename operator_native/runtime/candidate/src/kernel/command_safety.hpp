#pragma once

#include "kernel/fire_control.hpp"
#include "kernel/observation_events.hpp"

namespace rmcs::kernel {

// Legacy pointer-only helper retained for existing callers/tests. Production
// component adoption uses the stamped observation-result path below.
enum class MissingObservationPolicy { KeepUntilTimeout, Revoke };

inline auto accept_tracking_command(Trackable::Unique& current, const Trackable::Unique& incoming,
    MissingObservationPolicy policy = MissingObservationPolicy::KeepUntilTimeout) -> void {
    if (incoming) {
        current = incoming->clone();
    } else if (policy == MissingObservationPolicy::Revoke) {
        current.reset();
    }
}

inline auto command_timestamp_valid(Timestamp stamp, Timestamp now) -> bool {
    return observation_timestamp_valid(stamp, now);
}

// The event stamp is the exposure of the completed frame, not a prediction's
// state timestamp. A model must be explicitly observed in this exact frame.
inline auto accept_observation_result(ObservationResultGate& gate, Trackable::Unique& current,
    Timestamp exposure, bool observed_now, const Trackable::Unique& incoming, Timestamp now)
    -> bool {
    const auto usable = observed_now && incoming && incoming->get_timestamp() == exposure;
    if (!gate.accept(exposure, usable, now)) return false;
    if (usable) current = incoming->clone();
    // Empty/retained-model results inhibit fire without renewing the coast target.
    return true;
}

struct SafeControlOutput {
    bool should_track = false;
    FireController::Aimed aimed {
        .aim_yaw = kNaN,
        .pitch   = kNaN,
        .target  = AimPoint { Point3d::kNaN(), false },
        .center  = Point3d::kNaN(),
        .attack  = Point3d::kNaN(),
    };
};

inline auto finite_control_solution(const FireController::Aimed& aimed) -> bool {
    const auto finite_vector = [](const auto& value) {
        return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
    };
    return std::isfinite(aimed.aim_yaw) && std::isfinite(aimed.pitch)
        && finite_vector(aimed.target) && finite_vector(aimed.center)
        && finite_vector(aimed.attack) && finite_vector(aimed.target.ff_v)
        && finite_vector(aimed.target.ff_a);
}

// One complete output per control tick. Never inherit track/shoot/feedforward
// from a previous successful solve when this tick has no usable solution.
inline auto safe_control_tick(FireController& fire, Trackable::Unique& target,
    const FireController::State& state, bool shoot_allowed = true) -> SafeControlOutput {
    if (!target) return { };
    if (!command_timestamp_valid(target->get_timestamp(), state.timestamp)) {
        target.reset();
        return { };
    }
    if (!std::isfinite(state.yaw) || !std::isfinite(state.pitch)) return { };

    fire.update(state);
    auto aimed = fire.aim(*target);
    if (!aimed || !finite_control_solution(*aimed)) return { };

    aimed->shoot = aimed->shoot && shoot_allowed;
    return { .should_track = true, .aimed = std::move(*aimed) };
}

} // namespace rmcs::kernel
