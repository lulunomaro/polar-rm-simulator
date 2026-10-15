// Server-owned goal/source association overlay, Apache-2.0.
// The original PB PID algorithm is loaded unchanged; no fallback velocity is emitted.
#pragma once
#include <array>
#include <cmath>
#include <iomanip>
#include <sstream>
#include <cstddef>
#include <deque>
#include <mutex>
#include <set>
#include <string>
#include <vector>
#include <nlohmann/json.hpp>
#include "pb_request_context.hpp"
#include <rclcpp/rclcpp.hpp>
#include <rclcpp_lifecycle/lifecycle_node.hpp>
#include <std_msgs/msg/string.hpp>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include <geometry_msgs/msg/twist_stamped.hpp>

namespace polar_pb {
class GoalControllerContext {
  using Json = nlohmann::json;
  std::mutex mutex_;
  Json pending_;
  std::deque<int64_t> odom_;
  bool active_{false};
  bool configured_{false};
  bool generation_fault_{false};
  bool diagnostics_{false};
  size_t diagnostic_count_{0};
  rclcpp::Logger logger_{rclcpp::get_logger("polar_pb_sourced")};
  std::string robot_;
  int64_t episode_{-1}, epoch_{-1}, last_seq_{-1}, last_frame_{-1};
  rclcpp::Clock::SharedPtr clock_;
  rclcpp_lifecycle::LifecyclePublisher<std_msgs::msg::String>::SharedPtr output_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr input_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr localization_input_;

  static int64_t ns(const builtin_interfaces::msg::Time &s) {
    return static_cast<int64_t>(s.sec)*1000000000LL+s.nanosec;
  }
  static bool number(const Json &j) {
    return j.is_number() && std::isfinite(j.get<double>()) && j.get<double>()>=0 && j.get<double>()<=1e12;
  }
  static bool integer(const Json &j) {
    return j.is_number_integer() && j.get<double>()>=0 && j.get<double>()<=9007199254740991.0;
  }
  static Json parse_strict(const std::string &raw) {
    return polar_pb::parse_strict_json(raw);
  }
  void diagnostic_locked(const char *reason,int64_t pose=-1,int64_t computed=-1,
                         double norm=0.,double wz=0.,const Json *source=nullptr,
                         const char *field="none") {
    if(!diagnostics_ || diagnostic_count_>=256)return;
    ++diagnostic_count_;
    const auto seq=pending_.is_null()?-1LL:pending_["observed_seq"].get<int64_t>();
    const auto frame=pending_.is_null()?-1LL:pending_["cloud_frame_id"].get<int64_t>();
    const auto window=pending_.is_null()?-1.:pending_["sim_time"].get<double>();
    int64_t source_seq=-1;double source_window=-1.;
    if(source && source->is_object()) {
      if(source->contains("observed_seq") && integer((*source)["observed_seq"]))source_seq=(*source)["observed_seq"].get<int64_t>();
      if(source->contains("sim_time") && number((*source)["sim_time"]))source_window=(*source)["sim_time"].get<double>();
    }
    bool contains=false;for(const auto stamp:odom_)if(stamp==pose)contains=true;
    RCLCPP_INFO(logger_,"polar_goal_sourced_diag reason=%s field=%s active=%d configured=%d generation_fault=%d pending=%d seq=%lld frame=%lld source_seq=%lld pose_ns=%lld computed_ns=%lld sim_window_s=%.17g source_window_s=%.17g loc_count=%zu loc_first_ns=%lld loc_last_ns=%lld loc_contains=%d norm=%.17g wz=%.17g",
      reason,field,int(active_),int(configured_),int(generation_fault_),int(!pending_.is_null()),static_cast<long long>(seq),static_cast<long long>(frame),static_cast<long long>(source_seq),
      static_cast<long long>(pose),static_cast<long long>(computed),window,source_window,odom_.size(),
      static_cast<long long>(odom_.empty()?-1:odom_.front()),static_cast<long long>(odom_.empty()?-1:odom_.back()),int(contains),norm,wz);
  }
  void diagnostic(const char *reason,int64_t pose=-1,int64_t computed=-1,double norm=0.,double wz=0.,const Json *source=nullptr) {
    if(!diagnostics_)return;
    std::lock_guard<std::mutex> lock(mutex_);diagnostic_locked(reason,pose,computed,norm,wz,source);
  }
  template<class T> T param(const rclcpp_lifecycle::LifecycleNode::SharedPtr &node,
                          const std::string &name,const T &value) {
    if (!node->has_parameter(name)) node->declare_parameter<T>(name,value);
    return node->get_parameter(name).get_value<T>();
  }
public:
  void configure(const rclcpp_lifecycle::LifecycleNode::SharedPtr &node,const std::string &base) {
    // Disabled on unchanged upstream launches. A trusted local supervisor must
    // start fresh LIO/controller processes and set one explicit generation.
    if (!param<bool>(node,"polar_goal_sourced.enabled",false)) return;
    if (param<bool>(node,"polar_sourced.enabled",false))
      throw std::runtime_error("legacy plugin publisher must be disabled for goal-sourced server");
    diagnostics_=param<bool>(node,"polar_goal_sourced.diagnostics",false);logger_=node->get_logger();
    robot_=param<std::string>(node,"polar_goal_sourced.robot_id","");
    episode_=param<int64_t>(node,"polar_goal_sourced.episode",-1);
    epoch_=param<int64_t>(node,"polar_goal_sourced.binding_epoch",-1);
    if (robot_.empty() || robot_.size()>256 || episode_<0 || epoch_<0 || base!="base_link" ||
        !node->has_parameter("use_sim_time") || !node->get_parameter("use_sim_time").as_bool())
      throw std::runtime_error("polar sourced controller requires fixed generation, base_link and simulation clock");
    const auto request=param<std::string>(node,"polar_goal_sourced.request_topic","/polar/pb/request");
    const auto result=param<std::string>(node,"polar_goal_sourced.result_topic","/polar/pb/result");
    const auto localization=param<std::string>(node,"polar_goal_sourced.localization_topic","/polar/pb/localization");
    clock_=node->get_clock();
    auto qos=rclcpp::QoS(rclcpp::KeepLast(1)).reliable().durability_volatile();
    output_=node->create_publisher<std_msgs::msg::String>(result,qos);
    input_=node->create_subscription<std_msgs::msg::String>(request,qos,
      [this](std_msgs::msg::String::ConstSharedPtr msg) {
        try {
          Json j=parse_strict(msg->data);
          const std::set<std::string> required={"schema","adapter_id","robot_id","episode","binding_epoch",
            "observed_seq","sim_time","wall_deadline","cloud_frame_id","acquisition_start_ns","acquisition_end_ns"};
          std::set<std::string> actual;
          if(!j.is_object())return;
          for(auto it=j.begin();it!=j.end();++it)actual.insert(it.key());
          if(actual!=required || j["schema"]!="polar.sim.pb-navigation-request.v1" ||
             j["adapter_id"]!="custom_pb_navigation" || j["robot_id"]!=robot_)return;
          for(const auto *k:{"episode","binding_epoch","observed_seq","cloud_frame_id","acquisition_start_ns","acquisition_end_ns"})
            if(!integer(j[k]))return;
          if(!number(j["sim_time"]) || !number(j["wall_deadline"]))return;
          if(j["episode"].get<int64_t>()!=episode_ || j["binding_epoch"].get<int64_t>()!=epoch_) {
            std::lock_guard<std::mutex> lock(mutex_);
            generation_fault_=true;active_=false;pending_=Json();odom_.clear();return;
          }
          const int64_t start=j["acquisition_start_ns"],end=j["acquisition_end_ns"];
          if(start>=end || end-start>200000000LL || end*1e-9-j["sim_time"].get<double>()>.5e-9 ||
             j["sim_time"].get<double>()-end*1e-9>.2)return;
          std::lock_guard<std::mutex> lock(mutex_);
          if(!active_ || j["observed_seq"].get<int64_t>()<=last_seq_ || j["cloud_frame_id"].get<int64_t>()<=last_frame_)return;
          last_seq_=j["observed_seq"];last_frame_=j["cloud_frame_id"];pending_=std::move(j);odom_.clear();
          diagnostic_locked("request_installed");
        } catch(const std::exception &) { /* fail closed, no payload logging */ }
      });
    localization_input_=node->create_subscription<std_msgs::msg::String>(localization,qos,
      [this](std_msgs::msg::String::ConstSharedPtr msg) {
        try {
          Json j=parse_strict(msg->data);
          const std::set<std::string> required={"schema","adapter_id","robot_id","episode","binding_epoch",
            "observed_seq","sim_time","wall_deadline","cloud_frame_id","acquisition_start_ns","acquisition_end_ns","localization_stamp_ns"};
          if(!j.is_object())return;
          std::set<std::string> actual;for(auto it=j.begin();it!=j.end();++it)actual.insert(it.key());
          if(actual!=required || j["schema"]!="polar.sim.pb-localization-result.v1" || !integer(j["localization_stamp_ns"]))return;
          const int64_t stamp=j["localization_stamp_ns"];
          std::lock_guard<std::mutex> lock(mutex_);
          if(!active_ || pending_.is_null()){diagnostic_locked("localization_no_pending",stamp);return;}
          for(const auto *k:{"adapter_id","robot_id","episode","binding_epoch","observed_seq","sim_time","wall_deadline",
              "cloud_frame_id","acquisition_start_ns","acquisition_end_ns"})
            if(j[k].type()!=pending_[k].type() || j[k]!=pending_[k]){diagnostic_locked("localization_context_mismatch",stamp,-1,0.,0.,&j,k);return;}
          if(stamp<pending_["acquisition_start_ns"].get<int64_t>() || stamp>pending_["acquisition_end_ns"].get<int64_t>()){diagnostic_locked("localization_outside_window",stamp);return;}
          odom_.push_back(stamp);if(odom_.size()>64)odom_.pop_front();
          diagnostic_locked("localization_accepted",stamp);
        } catch(const std::exception &) { /* only reviewed LIO provenance is usable */ }
      });
    configured_=true;
  }
  void activate() {
    std::lock_guard<std::mutex> lock(mutex_);
    if(configured_ && !generation_fault_){output_->on_activate();active_=true;}
  }
  void deactivate() {
    std::lock_guard<std::mutex> lock(mutex_);
    active_=false;pending_=Json();odom_.clear();if(output_)output_->on_deactivate();
  }
  void cleanup() {deactivate();input_.reset();localization_input_.reset();output_.reset();configured_=false;}
  Json begin(const geometry_msgs::msg::PoseStamped &pose) {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto stamp=ns(pose.header.stamp);
    if(!active_ || pending_.is_null()){diagnostic_locked("begin_no_pending",stamp);return Json();}
    bool found=false;for(const auto v:odom_)if(v==stamp)found=true;
    if(!found){diagnostic_locked("begin_pose_not_localized",stamp);return Json();}
    diagnostic_locked("begin_accepted",stamp);
    return pending_;
  }
  void finish(const Json &request,const geometry_msgs::msg::PoseStamped &pose,
              const geometry_msgs::msg::TwistStamped &cmd,const std::array<uint8_t,16> &goal_uuid) {
    if(request.is_null()){diagnostic("finish_no_request",ns(pose.header.stamp));return;}
    // Called under the owned ActionServer current-goal lock. UUID is from
    // before this exact successful plugin compute, never a latest-goal cache.
    std::ostringstream uuid_text;uuid_text<<std::hex<<std::setfill('0');
    for(const auto byte:goal_uuid)uuid_text<<std::setw(2)<<static_cast<unsigned>(byte);
    const auto &v=cmd.twist;
    if(!std::isfinite(v.linear.x)||!std::isfinite(v.linear.y)||!std::isfinite(v.angular.z)||
       std::hypot(v.linear.x,v.linear.y)>1.0 || std::abs(v.angular.z)>2.0){diagnostic("finish_velocity_rejected",ns(pose.header.stamp),-1,std::hypot(v.linear.x,v.linear.y),v.angular.z,&request);return;}
    const auto stamp=ns(pose.header.stamp),computed=clock_->now().nanoseconds();
    if(computed<stamp || computed>static_cast<int64_t>(std::llround(request["sim_time"].get<double>()*1e9))){diagnostic("finish_clock_outside_window",stamp,computed,std::hypot(v.linear.x,v.linear.y),v.angular.z,&request);return;}
    std::lock_guard<std::mutex> lock(mutex_);
    if(!active_ || pending_.is_null() || pending_!=request){diagnostic_locked("finish_pending_changed",stamp,computed,0.,0.,&request);return;}
    Json action={{"schema","polar.sim.action.v2"},{"kind","navigation"},{"mode","velocity_body"},
      {"command",{{"frame","base_link"},{"vx_mps",v.linear.x},{"vy_mps",v.linear.y},{"wz_rps",v.angular.z}}}};
    for(const auto *k:{"robot_id","episode","binding_epoch","observed_seq","sim_time","wall_deadline"})action[k]=request[k];
    Json result={{"schema","polar.sim.pb-navigation-result.v2"},{"adapter_id",request["adapter_id"]},{"action",action},
      {"source",{{"cloud_frame_id",request["cloud_frame_id"]},{"localization_stamp_ns",stamp},
        {"controller_stamp_ns",computed},{"controller_id","nav2_server_pb_pid_goal_v1"},{"goal_uuid",uuid_text.str()}}}};
    std_msgs::msg::String message;message.data=result.dump();output_->publish(message);
    diagnostic_locked("finish_published",stamp,computed,std::hypot(v.linear.x,v.linear.y),v.angular.z);
    pending_=Json();odom_.clear();
  }
};
}  // namespace polar_pb
