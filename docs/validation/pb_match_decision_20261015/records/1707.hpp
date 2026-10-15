// Shared reviewed context parser for owned PB LIO/controller overlays.
#pragma once
#include <cmath>
#include <cstdint>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
#include <nlohmann/json.hpp>

namespace polar_pb {
using Json=nlohmann::json;
inline Json parse_strict_json(const std::string &raw) {
  if(raw.size()>65536)throw std::runtime_error("pb_context_oversized");
  std::vector<std::set<std::string>> keys;
  auto callback=[&keys](int,Json::parse_event_t event,Json &parsed) {
    if(event==Json::parse_event_t::object_start)keys.emplace_back();
    else if(event==Json::parse_event_t::key && !keys.back().insert(parsed.get<std::string>()).second)
      throw std::runtime_error("pb_context_duplicate_key");
    else if(event==Json::parse_event_t::object_end)keys.pop_back();
    return true;
  };
  return Json::parse(raw,callback);
}
inline bool context_integer(const Json &j) {
  return j.is_number_integer() && j.get<double>()>=0 && j.get<double>()<=9007199254740991.0;
}
inline bool context_number(const Json &j) {
  return j.is_number() && std::isfinite(j.get<double>()) && j.get<double>()>=0 && j.get<double>()<=1e12;
}
inline Json parse_navigation_request(const std::string &raw,const std::string &robot,int64_t episode,int64_t epoch) {
  Json j=parse_strict_json(raw);
  const std::set<std::string> required={"schema","adapter_id","robot_id","episode","binding_epoch","observed_seq",
    "sim_time","wall_deadline","cloud_frame_id","acquisition_start_ns","acquisition_end_ns"};
  std::set<std::string> actual;
  if(!j.is_object())throw std::runtime_error("pb_context_not_object");
  for(auto it=j.begin();it!=j.end();++it)actual.insert(it.key());
  if(actual!=required || !j["schema"].is_string() || j["schema"]!="polar.sim.pb-navigation-request.v1" ||
      !j["adapter_id"].is_string() || j["adapter_id"]!="custom_pb_navigation" ||
      !j["robot_id"].is_string() || j["robot_id"]!=robot)throw std::runtime_error("pb_context_fields_or_route");
  for(const auto *k:{"episode","binding_epoch","observed_seq","cloud_frame_id","acquisition_start_ns","acquisition_end_ns"})
    if(!context_integer(j[k]))throw std::runtime_error("pb_context_integer");
  if(!context_number(j["sim_time"]) || !context_number(j["wall_deadline"]))throw std::runtime_error("pb_context_clock");
  if(episode<0 || epoch<0 || j["episode"].get<int64_t>()!=episode || j["binding_epoch"].get<int64_t>()!=epoch)
    throw std::runtime_error("pb_context_generation_mismatch");
  const int64_t start=j["acquisition_start_ns"],end=j["acquisition_end_ns"];
  if(start>=end || end-start>200000000LL || end*1e-9-j["sim_time"].get<double>()>.5e-9 ||
      j["sim_time"].get<double>()-end*1e-9>.2)throw std::runtime_error("pb_context_scan_window");
  return j;
}
} // namespace polar_pb
