#include "pb_scan_source.hpp"
#include <cassert>
using polar_pb::Json;
Json request(int64_t seq, int64_t frame, int64_t start) {
  return Json{{"schema","polar.sim.pb-navigation-request.v1"},{"adapter_id","custom_pb_navigation"},
    {"robot_id","red_sentry"},{"episode",2},{"binding_epoch",3},{"observed_seq",seq},
    {"sim_time",static_cast<double>(start+100000000)*1e-9},{"wall_deadline",99.0},
    {"cloud_frame_id",frame},{"acquisition_start_ns",start},{"acquisition_end_ns",start+100000000}};
}
template<class Fn> bool rejects(Fn fn) { try { fn(); return false; } catch (const std::exception &) { return true; } }
int main() {
  polar_pb::ScanSource source;
  assert(rejects([&]{source.install(request(1,5,100000000).dump());}));
  source.configure("red_sentry",2,3);
  assert(rejects([&]{source.configure("red_sentry",2,3);}));
  polar_pb::ScanSource faulted; faulted.configure("red_sentry",2,3);
  faulted.install(request(1,5,100000000).dump());
  auto wrong=request(1,5,100000000); wrong["episode"]=1;
  assert(rejects([&]{faulted.install(wrong.dump());}));
  assert(rejects([&]{faulted.bind(100000000,100000000);}));
  assert(rejects([&]{faulted.install(request(2,6,200000000).dump());}));
  wrong=request(1,5,100000000); wrong["observed_seq"]=true;
  assert(rejects([&]{source.install(wrong.dump());}));
  source.install(request(1,5,100000000).dump());
  assert(!source.bind(100000001,100000001));
  assert(!source.bind(100000000,100000001));
  auto original=source.bind(100000000,100000000);assert(original);
  assert(!source.bind(100000000,100000000));
  assert(rejects([&]{source.install(request(1,6,200000000).dump());}));
  assert(rejects([&]{source.install(request(2,5,200000000).dump());}));
  source.install(request(2,6,200000000).dump());
  // Replacement pending requests never mutate the context captured in a scan.
  assert(original->at("observed_seq")==1 && original->at("cloud_frame_id")==5);
  auto estimated=polar_pb::localization_event(original,198000000);
  assert(estimated.size()==12);
  assert(estimated.at("schema")=="polar.sim.pb-localization-result.v1");
  assert(estimated.at("localization_stamp_ns")==198000000);
  assert(estimated.at("observed_seq")==1 && estimated.at("acquisition_end_ns")==200000000);
  assert(original->at("schema")=="polar.sim.pb-navigation-request.v1");
  assert(rejects([&]{polar_pb::localization_event(original,200000001);}));
  assert(rejects([&]{polar_pb::localization_event(original,99999999);}));
  assert(rejects([&]{polar_pb::localization_event({},198000000);}));
  auto current=source.bind(200000000,200000000);assert(current->at("observed_seq")==2);
}
