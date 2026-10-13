#pragma once
#include "utility/clock.hpp"
#include <cstdint>
#include <ratio>

// Adapter-only, lossless integer-nanosecond transport. There is no double ->
// timestamp conversion and no tolerance added to production observation gates.
namespace rmcs::headless {
static_assert(std::ratio_equal_v<Duration::period,std::nano>,
    "The portable adapter requires a nanosecond steady_clock duration");
inline auto timestamp_from_ns(std::int64_t ns) noexcept -> Timestamp {
    return Timestamp{std::chrono::duration_cast<Duration>(std::chrono::nanoseconds{ns})};
}
inline auto nanoseconds_from_timestamp(Timestamp t) noexcept -> std::int64_t {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(t.time_since_epoch()).count();
}
}
