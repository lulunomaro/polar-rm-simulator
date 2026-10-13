// Owned PB integration. Context is captured at the actual CustomMsg ingress.
#pragma once
#include <memory>
#include <utility>
#include "pb_request_context.hpp"
namespace polar_pb {
class GenerationFault : public std::runtime_error {
 public: GenerationFault() : std::runtime_error("pb_source_generation_fault") {}
};
class ScanSource {
 public:
  void configure(std::string robot, int64_t episode, int64_t epoch) {
    if (configured_) throw std::runtime_error("pb_source_configure_once");
    robot_ = std::move(robot); episode_ = episode; epoch_ = epoch; configured_ = true;
  }
  void install(const std::string &raw) {
    if (generation_fault_) throw GenerationFault();
    if (!configured_) throw std::runtime_error("pb_source_not_configured");
    Json j;
    try { j = parse_navigation_request(raw, robot_, episode_, epoch_); }
    catch (const std::exception &e) {
      if (std::string(e.what()) == "pb_context_generation_mismatch") {
        generation_fault_ = true; pending_.reset(); throw GenerationFault();
      }
      throw;
    }
    const int64_t seq = j.at("observed_seq"), frame = j.at("cloud_frame_id");
    if (seq <= last_seq_ || frame <= last_frame_) throw std::runtime_error("pb_source_nonincreasing");
    pending_ = std::make_shared<const Json>(std::move(j));
    last_seq_ = seq; last_frame_ = frame;
  }
  std::shared_ptr<const Json> bind(int64_t header_ns, uint64_t timebase) {
    if (generation_fault_) throw GenerationFault();
    if (!pending_ || header_ns < 0 || static_cast<uint64_t>(header_ns) != timebase ||
        pending_->at("acquisition_start_ns").get<int64_t>() != header_ns) return {};
    auto bound = pending_; pending_.reset(); return bound;
  }
 private:
  std::string robot_;
  int64_t episode_ = -1, epoch_ = -1, last_seq_ = -1, last_frame_ = -1;
  bool configured_ = false;
  bool generation_fault_ = false;
  std::shared_ptr<const Json> pending_;
};
inline Json localization_event(const std::shared_ptr<const Json> &bound, int64_t stamp) {
  if (!bound || stamp < bound->at("acquisition_start_ns").get<int64_t>() ||
      stamp > bound->at("acquisition_end_ns").get<int64_t>())
    throw std::runtime_error("pb_source_localization_window");
  Json result = *bound;
  result["schema"] = "polar.sim.pb-localization-result.v1";
  result["localization_stamp_ns"] = stamp;
  return result;
}
}  // namespace polar_pb
