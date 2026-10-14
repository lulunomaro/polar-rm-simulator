#pragma once
#include <chrono>

// Test-only deterministic clock. Production source files are never rewritten.
// Its time_point stays steady_clock-compatible; only Clock::now() is injected.
namespace rmcs {
struct Clock {
    using duration = std::chrono::steady_clock::duration;
    using rep = duration::rep;
    using period = duration::period;
    using time_point = std::chrono::steady_clock::time_point;
    static constexpr bool is_steady = true;
    inline static time_point injected{};
    static auto now() noexcept -> time_point { return injected; }
};
using TimePoint = Clock::time_point;
using Duration = TimePoint::duration;
using Timestamp = TimePoint;
}
