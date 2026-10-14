// Adapter-only context carrier for a pinned PB algorithm; no target solver.
#pragma once
#include "pb_request_context.hpp"
#include <limits>
#include <memory>
#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/header.hpp>
#include <std_msgs/msg/string.hpp>

namespace polar_pb_aim {
using Json=polar_pb::Json;
class SourceGate {
  std::string robot_,calibration_,run_,node_;
  int64_t episode_=-1,epoch_=-1,last_seq_=-1,last_stamp_=-1;
  bool configured_=false;
  Json configured_packet_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr configure_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr configured_pub_;
public:
  explicit SourceGate(rclcpp::Node &node) {
    calibration_=node.declare_parameter<std::string>("pb.calibration_id","");
    run_=node.declare_parameter<std::string>("pb.run_uuid","");node_=node.get_name();
    if(run_.size()!=32 || run_.find_first_not_of("0123456789abcdef")!=std::string::npos || calibration_.empty())
      throw std::runtime_error("pb_aim_prepared_run_required");
    configured_pub_=node.create_publisher<std_msgs::msg::String>("polar/pb/aim_configured",rclcpp::QoS(3).reliable());
    configure_=node.create_subscription<std_msgs::msg::String>("polar/pb/aim_configure",rclcpp::QoS(1).reliable(),
      [this](const std_msgs::msg::String::SharedPtr msg) { this->configure(msg->data); });
  }
  void configure(const std::string &raw) {
    if(raw.size()>1024)throw std::runtime_error("pb_aim_configure_bound");
    auto j=polar_pb::parse_strict_json(raw);
    const std::set<std::string> required={"schema","run_uuid","robot_id","episode","binding_epoch","calibration_id"};
    std::set<std::string> actual;
    if(!j.is_object())throw std::runtime_error("pb_aim_configure_object");
    for(auto it=j.begin();it!=j.end();++it)actual.insert(it.key());
    if(actual!=required || j["schema"]!="polar.sim.pb-aim-source-configure.v1" || j["run_uuid"]!=run_
        || !j["robot_id"].is_string() || j["robot_id"].get<std::string>().empty()
        || j["calibration_id"]!=calibration_ || !polar_pb::context_integer(j["episode"])
        || !polar_pb::context_integer(j["binding_epoch"]) || j["episode"].get<int64_t>()<0
        || j["binding_epoch"].get<int64_t>()<1)
      throw std::runtime_error("pb_aim_configure_identity");
    if(configured_ && j!=configured_packet_)throw std::runtime_error("pb_aim_configure_once_per_generation");
    if(!configured_) {
      robot_=j["robot_id"].get<std::string>();episode_=j["episode"];epoch_=j["binding_epoch"];
      configured_packet_=j;configured_=true;
    }
    // Identical reliable retries ACK without clearing last exposure/sequence.
    j["schema"]="polar.sim.pb-aim-source-configured.v1";j["node"]=node_;
    std_msgs::msg::String response;response.data=j.dump();configured_pub_->publish(response);
  }
  Json check(const std::string &raw,const std_msgs::msg::Header &header) {
    if(!configured_)throw std::runtime_error("pb_aim_source_not_configured");
    if(raw.size()>2048)throw std::runtime_error("pb_aim_context_bound");
    auto source=polar_pb::parse_strict_json(raw);
    const std::set<std::string> fields={"schema","robot_id","episode","binding_epoch","observed_seq",
      "sim_time","wall_deadline","frame_id","capture_sim_time","capture_stamp_ns","calibration_id"};
    std::set<std::string> actual;
    if(!source.is_object())throw std::runtime_error("pb_aim_context_object");
    for(auto it=source.begin();it!=source.end();++it)actual.insert(it.key());
    if(actual!=fields || !source["schema"].is_string() || source["schema"]!="polar.sim.aim-source-context.v1"
        || !source["robot_id"].is_string() || source["robot_id"]!=robot_
        || !source["calibration_id"].is_string() || source["calibration_id"]!=calibration_)
      throw std::runtime_error("pb_aim_context_route");
    for(const auto *key:{"episode","binding_epoch","observed_seq","frame_id","capture_stamp_ns"})
      if(!polar_pb::context_integer(source[key]))throw std::runtime_error("pb_aim_context_integer");
    for(const auto *key:{"sim_time","wall_deadline","capture_sim_time"})
      if(!source[key].is_number_float() || !polar_pb::context_number(source[key]))
        throw std::runtime_error("pb_aim_context_clock_type");
    if(source["episode"].get<int64_t>()!=episode_ || source["binding_epoch"].get<int64_t>()!=epoch_)
      throw std::runtime_error("pb_aim_generation_mismatch");
    const int64_t stamp=source["capture_stamp_ns"],seq=source["observed_seq"];
    const int64_t actual_stamp=int64_t(header.stamp.sec)*1000000000LL+header.stamp.nanosec;
    const double age=source["sim_time"].get<double>()-source["capture_sim_time"].get<double>();
    if(header.stamp.sec<0 || header.stamp.nanosec>=1000000000U || stamp!=actual_stamp
        || std::llround(source["capture_sim_time"].get<double>()*1e9)!=stamp || age<0. || age>.080000001)
      throw std::runtime_error("pb_aim_original_exposure_required");
    if(seq<=last_seq_ || stamp<=last_stamp_)throw std::runtime_error("pb_aim_source_not_increasing");
    // The host's QPC wall_deadline stays opaque in ROS. No clock remapping.
    last_seq_=seq;last_stamp_=stamp;return source;
  }
};
inline void check_headers(const std_msgs::msg::Header &outer,const std_msgs::msg::Header &inner) {
  if(outer.frame_id!=inner.frame_id || outer.stamp!=inner.stamp)
    throw std::runtime_error("pb_aim_carrier_header_mismatch");
}
inline void publish_result(const rclcpp::Publisher<std_msgs::msg::String>::SharedPtr &publisher,
    const Json &source,const char *status,double yaw=0.,double pitch=0.) {
  const bool active=std::string(status)=="gimbal_target";
  if(active && (!std::isfinite(yaw) || !std::isfinite(pitch)))throw std::runtime_error("pb_aim_nonfinite_output");
  Json result={{"schema","polar.sim.pb-aim-result.v1"},{"source_context",source},
    {"capture_stamp_ns",source.at("capture_stamp_ns")},{"status",status},
    {"output_frame","chassis_relative_ros_rpy"},{"yaw",active?Json(yaw):Json(nullptr)},
    {"pitch",active?Json(pitch):Json(nullptr)}};
  std_msgs::msg::String msg;msg.data=result.dump();
  if(msg.data.size()>4096)throw std::runtime_error("pb_aim_result_bound");
  publisher->publish(msg);
}
} // namespace polar_pb_aim
