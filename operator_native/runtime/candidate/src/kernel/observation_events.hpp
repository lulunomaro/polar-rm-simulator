#pragma once

#include "utility/clock.hpp"

#include <memory>
#include <mutex>
#include <utility>

namespace rmcs::kernel {

inline auto observation_timestamp_valid(Timestamp stamp, Timestamp now) noexcept -> bool {
    return stamp > Timestamp { } && stamp <= now
        && now - stamp <= std::chrono::milliseconds { 100 };
}

// Single-owner order gate. Invalid timestamps never advance the high-water mark.
// A source restart requires a new owning pipeline; time regression never resets it.
class ObservationOrder {
public:
    auto accept(Timestamp stamp, Timestamp now) noexcept -> bool {
        if (!observation_timestamp_valid(stamp, now) || stamp <= accepted_) return false;
        accepted_ = stamp;
        return true;
    }

    auto latest_timestamp() const noexcept -> Timestamp { return accepted_; }

private:
    Timestamp accepted_ { };
};

// One synchronized newest-by-exposure slot, shared by callbacks and one worker.
// Admission and replacement are one critical section, not load/compare/store.
// Consumption checks freshness again before callers may update gimbal/Tracker.
template <class Frame>
class OrderedObservationMailbox {
public:
    using Pointer = std::shared_ptr<const Frame>;

    auto submit(Pointer frame, Timestamp now) -> bool {
        if (!frame) return false;
        std::lock_guard lock { mutex_ };
        if (!submitted_.accept(frame->exposure_timestamp, now)) return false;
        pending_ = std::move(frame);
        return true;
    }

    auto take(Timestamp now) -> Pointer {
        std::lock_guard lock { mutex_ };
        auto frame = std::exchange(pending_, nullptr);
        if (!frame || !consumed_.accept(frame->exposure_timestamp, now)) return nullptr;
        return frame;
    }

    auto pending() const -> bool {
        std::lock_guard lock { mutex_ };
        return bool(pending_);
    }

private:
    mutable std::mutex mutex_;
    Pointer pending_;
    ObservationOrder submitted_, consumed_;
};

// Distinguish completed-frame results from silence. Only an accepted, newer
// usable observation can release inhibition; ordinary control ticks cannot.
class ObservationResultGate {
public:
    auto accept(Timestamp stamp, bool observed_now, Timestamp now) noexcept -> bool {
        if (!order_.accept(stamp, now)) return false;
        shoot_allowed_ = observed_now;
        return true;
    }

    auto shoot_allowed() const noexcept -> bool { return shoot_allowed_; }
    auto latest_timestamp() const noexcept -> Timestamp { return order_.latest_timestamp(); }

private:
    ObservationOrder order_;
    bool shoot_allowed_ = false;
};

} // namespace rmcs::kernel
