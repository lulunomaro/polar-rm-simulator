// Owned PB integration: ROS simulation stamps, never callback CPU time.
#pragma once
#include <cstdint>
namespace polar_pb {
class SimStampSequence {
 public:
  bool accept(int64_t stamp, double &dt) {
    dt = 0.0;
    if (stamp <= 0 || (initialized_ && stamp <= previous_)) return false;
    if (initialized_) dt = static_cast<double>(stamp - previous_) * 1e-9;
    previous_ = stamp;
    initialized_ = true;
    return true;
  }
  void reset() { initialized_ = false; previous_ = 0; }
 private:
  bool initialized_ = false;
  int64_t previous_ = 0;
};
}  // namespace polar_pb
