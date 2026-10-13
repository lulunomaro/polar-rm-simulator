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

  // Separate DDS readers may invoke raw before request, or request before raw.
  using Raw = std::shared_ptr<const std::string>;
  polar_pb::ScanJoin<Raw> unconfigured;
  assert(rejects([&]{unconfigured.add_raw(0,0,98000000,std::make_shared<const std::string>("raw"));}));
  polar_pb::ScanJoin<Raw> join; join.configure("red_sentry",2,3);
  const auto raw_a=std::make_shared<const std::string>("actual scan A bytes");
  const auto raw_b=std::make_shared<const std::string>("actual scan B bytes");
  Raw raw;std::shared_ptr<const Json> context;
  join.add_raw(100000000,100000000,198000000,raw_a);
  assert(!join.take(raw,context) && join.raw_count()==1);
  join.install(request(1,5,100000000).dump());
  assert(join.take(raw,context) && raw==raw_a && context->at("observed_seq")==1);
  const auto held=context;
  assert(!join.take(raw,context));
  join.install(request(2,6,200000000).dump());
  assert(!join.take(raw,context));
  join.add_raw(200000000,200000000,298000000,raw_b);
  assert(join.take(raw,context) && raw==raw_b && context->at("observed_seq")==2);
  assert(held->at("observed_seq")==1 && held->at("wall_deadline")==99.0);
  assert(held->at("acquisition_start_ns")==100000000);
  assert(rejects([&]{join.add_raw(100000000,100000000,198000000,raw_a);}));
  assert(rejects([&]{join.install(request(1,5,100000000).dump());}));

  // Requests and raw messages can each arrive in the reverse order. Neither
  // side overwrites a prior context, and the earliest known pair gates delivery.
  polar_pb::ScanJoin<Raw> reordered;reordered.configure("red_sentry",2,3);
  reordered.install(request(2,6,200000000).dump());
  reordered.install(request(1,5,100000000).dump());
  reordered.add_raw(200000000,200000000,298000000,raw_b);
  assert(!reordered.take(raw,context));
  reordered.add_raw(100000000,100000000,198000000,raw_a);
  assert(reordered.take(raw,context) && raw==raw_a && context->at("cloud_frame_id")==5);
  assert(reordered.take(raw,context) && raw==raw_b && context->at("cloud_frame_id")==6);

  polar_pb::ScanJoin<Raw> bounded;bounded.configure("red_sentry",2,3);
  for(int64_t i=1;i<=8;++i){
    bounded.install(request(i,i+4,i*100000000).dump());
    bounded.add_raw(i*100000000,i*100000000,i*100000000+98000000,raw_a);
  }
  assert(bounded.request_count()==8 && bounded.raw_count()==8);
  assert(rejects([&]{bounded.install(request(9,13,900000000).dump());}));
  assert(rejects([&]{bounded.add_raw(900000000,900000000,998000000,raw_b);}));
  assert(bounded.request_count()==8 && bounded.raw_count()==8);
  assert(rejects([&]{bounded.add_raw(100000000,100000001,198000000,raw_b);}));
  assert(rejects([&]{bounded.add_raw(100000000,100000000,198000000,raw_b);}));
  auto conflicting=request(2,6,100000000);
  assert(rejects([&]{bounded.install(conflicting.dump());}));
  assert(bounded.take(raw,context) && context->at("observed_seq")==1);
  // Capacity rejection leaves the original head and all remaining bytes intact.
  assert(bounded.take(raw,context) && context->at("observed_seq")==2);
  auto changed=request(10,20,1000000000);changed["binding_epoch"]=4;
  assert(rejects([&]{bounded.install(changed.dump());}));
  assert(bounded.request_count()==0 && bounded.raw_count()==0);
  assert(rejects([&]{bounded.take(raw,context);}));
  assert(rejects([&]{bounded.add_raw(1000000000,1000000000,1098000000,raw_a);}));
  assert(rejects([&]{bounded.install(request(10,20,1000000000).dump());}));

  polar_pb::ScanSource order;order.configure("red_sentry",2,3);
  order.install(request(2,6,200000000).dump());
  assert(rejects([&]{order.install(request(3,5,100000000).dump());}));
  assert(rejects([&]{order.install(request(2,7,100000000).dump());}));
  assert(order.pending_count()==1);

  // Valid short cross-reader reordering: both requests precede raw A/B. The
  // scan A actual last point is 198ms, but its original request window ends at
  // B's 200ms start. Its known exact request must not be discarded as raw-only.
  for(bool reverse : {false,true}) {
    polar_pb::ScanJoin<Raw> short_reorder;short_reorder.configure("red_sentry",2,3);
    short_reorder.install(request(1,5,100000000).dump());
    short_reorder.install(request(2,6,200000000).dump());
    if(reverse) short_reorder.add_raw(200000000,200000000,298000000,raw_b);
    short_reorder.add_raw(100000000,100000000,198000000,raw_a);
    if(!reverse) short_reorder.add_raw(200000000,200000000,298000000,raw_b);
    assert(short_reorder.take(raw,context) && raw==raw_a && context->at("observed_seq")==1);
    assert(context->at("wall_deadline")==99.0 && context->at("acquisition_end_ns")==200000000);
    assert(short_reorder.take(raw,context) && raw==raw_b && context->at("observed_seq")==2);
    auto discarded=short_reorder.take_discards();assert(!discarded.requests && !discarded.raw);
  }

  // Missing raw A: B's matching pair cannot leapfrog A until a genuine later
  // acquisition start exceeds A's original end. No host/Linux clocks are mixed.
  polar_pb::ScanJoin<Raw> missing_raw;missing_raw.configure("red_sentry",2,3);
  missing_raw.install(request(1,5,100000000).dump());
  missing_raw.install(request(2,6,200000000).dump());
  missing_raw.add_raw(200000000,200000000,298000000,raw_b);
  assert(!missing_raw.take(raw,context));
  missing_raw.install(request(3,7,300000000).dump());
  auto discarded=missing_raw.take_discards();
  assert(discarded.requests==1 && discarded.last_request_start==100000000);
  assert(missing_raw.take(raw,context) && raw==raw_b && context->at("observed_seq")==2);
  // Late expired A cannot revive or steal B/C's identity.
  assert(rejects([&]{missing_raw.install(request(1,5,100000000).dump());}));
  assert(rejects([&]{missing_raw.add_raw(100000000,100000000,198000000,raw_a);}));

  polar_pb::ScanJoin<Raw> missing_request;missing_request.configure("red_sentry",2,3);
  missing_request.add_raw(100000000,100000000,198000000,raw_a);
  missing_request.install(request(2,6,200000000).dump());
  discarded=missing_request.take_discards();
  assert(discarded.raw==1 && discarded.last_raw_start==100000000);
  missing_request.add_raw(200000000,200000000,298000000,raw_b);
  assert(missing_request.take(raw,context) && raw==raw_b && context->at("cloud_frame_id")==6);
  assert(context->at("wall_deadline")==99.0);

  // A complete old pair is retained even when C arrives: expiry only removes
  // unpaired input, never rewrites a queued original scan's provenance.
  polar_pb::ScanJoin<Raw> complete;complete.configure("red_sentry",2,3);
  complete.install(request(1,5,100000000).dump());
  complete.add_raw(100000000,100000000,198000000,raw_a);
  complete.install(request(3,7,300000000).dump());
  assert(complete.take(raw,context) && raw==raw_a && context->at("observed_seq")==1);
  discarded=complete.take_discards();assert(!discarded.raw && !discarded.requests);
  assert(rejects([&]{complete.add_raw(400000000,400000000,399999999,raw_b);}));

  polar_pb::ScanJoin<Raw> full_unmatched;full_unmatched.configure("red_sentry",2,3);
  for(int64_t i=1;i<=8;++i) full_unmatched.install(request(i,i+4,100000000+i).dump());
  assert(full_unmatched.request_count()==8);
  // Incoming exact later original acquisition can retire expired entries before
  // capacity admission, rather than being rejected by the obsolete full table.
  full_unmatched.install(request(9,13,300000000).dump());
  assert(full_unmatched.request_count()==1);
  discarded=full_unmatched.take_discards();assert(discarded.requests==8 && !discarded.raw);
  full_unmatched.add_raw(300000000,300000000,398000000,raw_b);
  assert(full_unmatched.take(raw,context) && context->at("observed_seq")==9 && raw==raw_b);
}
