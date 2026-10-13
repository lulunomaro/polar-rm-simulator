// Owned PB integration. Context is captured at the actual CustomMsg ingress.
#pragma once
#include <memory>
#include <map>
#include <cstddef>
#include <utility>
#include "pb_request_context.hpp"
namespace polar_pb {
class GenerationFault : public std::runtime_error {
 public: GenerationFault() : std::runtime_error("pb_source_generation_fault") {}
};
struct WindowDiscards {
  std::size_t requests = 0, raw = 0;
  int64_t last_request_start = -1, last_raw_start = -1;
};
class ScanSource {
 public:
  void configure(std::string robot, int64_t episode, int64_t epoch) {
    if (configured_) throw std::runtime_error("pb_source_configure_once");
    robot_ = std::move(robot); episode_ = episode; epoch_ = epoch; configured_ = true;
  }
  int64_t install(const std::string &raw) {
    return install(raw, [](int64_t) {});
  }
  template<class BeforeInsert> int64_t install(const std::string &raw, BeforeInsert before_insert) {
    if (generation_fault_) throw GenerationFault();
    if (!configured_) throw std::runtime_error("pb_source_not_configured");
    Json j;
    try { j = parse_navigation_request(raw, robot_, episode_, epoch_); }
    catch (const std::exception &e) {
      if (std::string(e.what()) == "pb_context_generation_mismatch") {
        generation_fault_ = true; pending_.clear(); throw GenerationFault();
      }
      throw;
    }
    const int64_t seq = j.at("observed_seq"), frame = j.at("cloud_frame_id");
    const int64_t start = j.at("acquisition_start_ns");
    if (seq <= last_seq_ || frame <= last_frame_ || start <= last_start_)
      throw std::runtime_error("pb_source_nonincreasing");
    if (pending_.count(start)) throw std::runtime_error("pb_source_duplicate_or_conflicting_stamp");
    // Request arrival order is not scan order. Validate relative identities,
    // then commit the replay watermark only when the exact scan is consumed.
    for (const auto &entry : pending_) {
      const auto other_seq = entry.second->at("observed_seq").get<int64_t>();
      const auto other_frame = entry.second->at("cloud_frame_id").get<int64_t>();
      if (seq == other_seq || frame == other_frame ||
          ((start < entry.first) != (seq < other_seq)) ||
          ((start < entry.first) != (frame < other_frame)))
        throw std::runtime_error("pb_source_identity_order_conflict");
    }
    before_insert(start);  // Validated original acquisition, not receipt time.
    if (pending_.size() >= capacity) throw std::runtime_error("pb_request_join_overflow");
    pending_.emplace(start, std::make_shared<const Json>(std::move(j)));
    return start;
  }
  std::shared_ptr<const Json> bind(int64_t header_ns, uint64_t timebase) {
    if (generation_fault_) throw GenerationFault();
    if (header_ns < 0 || static_cast<uint64_t>(header_ns) != timebase ||
        pending_.empty() || pending_.begin()->first != header_ns) return {};
    auto bound = pending_.begin()->second;
    pending_.erase(pending_.begin());
    last_start_ = header_ns; last_seq_ = bound->at("observed_seq");
    last_frame_ = bound->at("cloud_frame_id");
    return bound;
  }
  static constexpr std::size_t capacity = 8;
  std::size_t pending_count() const { return pending_.size(); }
  int64_t first_start() const { return pending_.empty() ? -1 : pending_.begin()->first; }
  int64_t consumed_start() const { return last_start_; }
  bool faulted() const { return generation_fault_; }
  bool configured() const { return configured_; }
  bool has_request(int64_t start) const { return pending_.count(start) != 0; }
  template<class HasRaw> void expire_unmatched(int64_t actual_start, HasRaw has_raw,
                                              WindowDiscards &discarded) {
    for (auto it = pending_.begin(); it != pending_.end();) {
      if (it->second->at("acquisition_end_ns").get<int64_t>() < actual_start &&
          !has_raw(it->first)) {
        ++discarded.requests; discarded.last_request_start = it->first;
        it = pending_.erase(it);
      } else ++it;
    }
  }
 private:
  std::string robot_;
  int64_t episode_ = -1, epoch_ = -1, last_seq_ = -1, last_frame_ = -1, last_start_ = -1;
  bool configured_ = false;
  bool generation_fault_ = false;
  std::map<int64_t, std::shared_ptr<const Json>> pending_;
};
// Raw is the actual ROS shared message pointer in the owned node. No raw copy,
// synthetic frame, latest identity, cross-clock deadline, or new thread is used.
template<class Raw> class ScanJoin {
 public:
  void configure(std::string robot, int64_t episode, int64_t epoch) {
    source_.configure(std::move(robot), episode, epoch);
  }
  void install(const std::string &request) {
    // First prune against an already observed acquisition watermark, so a
    // missing old scan cannot fill the table and reject a fresh request.
    expire_unmatched();
    try { source_.install(request, [this](int64_t start) { advance(start); }); expire_unmatched(); }
    catch (const GenerationFault &) { raw_.clear(); discarded_ = {}; throw; }
  }
  void add_raw(int64_t header_ns, uint64_t timebase, int64_t actual_last_point_ns, Raw raw) {
    if (source_.faulted()) throw GenerationFault();
    if (!source_.configured()) throw std::runtime_error("pb_source_not_configured");
    if (header_ns < 0 || static_cast<uint64_t>(header_ns) != timebase)
      throw std::runtime_error("pb_raw_header_timebase_mismatch");
    if (actual_last_point_ns < header_ns) throw std::runtime_error("pb_raw_end_before_start");
    if (header_ns <= source_.consumed_start()) throw std::runtime_error("pb_raw_replayed_scan");
    advance(header_ns);
    if (actual_last_point_ns < latest_start_ && !source_.has_request(header_ns)) {
      ++discarded_.raw; discarded_.last_raw_start = header_ns;
      return;  // Exact old bytes are discarded, never relabeled as this scan.
    }
    if (raw_.count(header_ns)) throw std::runtime_error("pb_raw_duplicate_scan");
    if (raw_.size() >= ScanSource::capacity) throw std::runtime_error("pb_raw_join_overflow");
    raw_.emplace(header_ns, RawEntry{actual_last_point_ns, std::move(raw)});
    expire_unmatched();
  }
  bool take(Raw &raw, std::shared_ptr<const Json> &context) {
    if (source_.faulted()) throw GenerationFault();
    // The oldest known input on either side must be a complete exact pair.
    // This prevents a later ready scan from jumping over an unmatched input.
    if (raw_.empty() || source_.first_start() != raw_.begin()->first) return false;
    auto bound = source_.bind(raw_.begin()->first, static_cast<uint64_t>(raw_.begin()->first));
    if (!bound) return false;
    raw = std::move(raw_.begin()->second.value); raw_.erase(raw_.begin());
    context = std::move(bound); return true;
  }
  std::size_t request_count() const { return source_.pending_count(); }
  std::size_t raw_count() const { return raw_.size(); }
  WindowDiscards take_discards() { auto result = discarded_; discarded_ = {}; return result; }
 private:
  struct RawEntry { int64_t actual_last_point_ns; Raw value; };
  void advance(int64_t actual_start) {
    if (actual_start > latest_start_) latest_start_ = actual_start;
    expire_unmatched();
  }
  void expire_unmatched() {
    source_.expire_unmatched(latest_start_, [this](int64_t start) { return raw_.count(start) != 0; }, discarded_);
    for (auto it = raw_.begin(); it != raw_.end();) {
      if (it->second.actual_last_point_ns < latest_start_ && !source_.has_request(it->first)) {
        ++discarded_.raw; discarded_.last_raw_start = it->first;
        it = raw_.erase(it);
      } else ++it;
    }
  }
  ScanSource source_;
  std::map<int64_t, RawEntry> raw_;
  int64_t latest_start_ = -1;
  WindowDiscards discarded_;
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
