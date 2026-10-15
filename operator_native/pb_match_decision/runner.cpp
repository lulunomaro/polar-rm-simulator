// Copyright 2026 Polar simulator contributors. SPDX-License-Identifier: MIT
// Original PB nodes are separate, byte-identical upstream translation units.
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>
#include <cerrno>
#include <csignal>
#include <fcntl.h>
#include <poll.h>
#include <unistd.h>
#include <openssl/sha.h>
#include "behaviortree_cpp/bt_factory.h"
#include "behaviortree_cpp/contrib/json.hpp"
#include "pb2025_sentry_behavior/plugins/condition/is_game_status.hpp"
#include "pb2025_sentry_behavior/plugins/condition/is_status_ok.hpp"
#include "pb2025_sentry_behavior/plugins/condition/is_rfid_detected.hpp"
#include "pb2025_sentry_behavior/plugins/action/pub_nav2_goal.hpp"

using Json = nlohmann::json;
namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;
constexpr const char * WIRE = "polar.sim.adapter.jsonl.v1";
constexpr const char * OBS = "polar.sim.decision-observation.v2";
constexpr const char * INTENT = "polar.sim.decision-intent.v1";
constexpr const char * UPSTREAM_XML = "68e216c145949538444bd8b9f9e97cc1b79b1536ddbc52a37eb00252e20c34f9";
const std::array<std::string,6> SIX = {"robot_id","episode","binding_epoch","observed_seq","sim_time","wall_deadline"};
volatile std::sig_atomic_t stop_requested=0;
void request_stop(int) {stop_requested=1;}

void require(bool condition, const char * code) {if (!condition) throw std::runtime_error(code);}
Json parse_json(const std::string & raw) {
  std::vector<std::set<std::string>> objects;
  return Json::parse(raw,[&objects](int,Json::parse_event_t event,Json & parsed){
    if(event==Json::parse_event_t::object_start)objects.emplace_back();
    else if(event==Json::parse_event_t::key) {
      require(!objects.empty()&&objects.back().insert(parsed.get<std::string>()).second,"native_duplicate_json_key");
    } else if(event==Json::parse_event_t::object_end)objects.pop_back();
    return true;
  });
}
void keys(const Json & value, std::initializer_list<const char *> names) {
  require(value.is_object() && value.size()==names.size(), "native_exact_fields");
  for (const char * name:names) require(value.contains(name), "native_missing_field");
}
bool typed_equal(const Json & a,const Json & b) {
  if(a.type()!=b.type())return false;
  if(a.is_object()) {if(a.size()!=b.size())return false;for(auto it=a.begin();it!=a.end();++it)
    if(!b.contains(it.key()) || !typed_equal(it.value(),b.at(it.key())))return false;return true;}
  if(a.is_array()){if(a.size()!=b.size())return false;for(size_t i=0;i<a.size();++i)
    if(!typed_equal(a[i],b[i]))return false;return true;}
  return a==b;
}
double number(const Json & value,double lo=0.,double hi=9007199254740991.) {
  require(value.is_number() && !value.is_boolean(),"native_number_type");
  double result=value.get<double>();require(std::isfinite(result)&&result>=lo&&result<=hi,"native_number_range");return result;
}
uint64_t integer(const Json & value) {
  require(value.is_number_integer()&&!value.is_boolean(),"native_integer_type");
  number(value);return value.get<uint64_t>();
}
bool hex(const Json & value,size_t length) {
  if(!value.is_string())return false;const auto & s=value.get_ref<const std::string&>();
  return s.size()==length && s.find_first_not_of("0123456789abcdef")==std::string::npos;
}
Json six(const Json & o) {Json value=Json::object();for(const auto & k:SIX)value[k]=o.at(k);return value;}
void identity(const Json & value) {
  require(value.at("robot_id").is_string()&&!value.at("robot_id").get<std::string>().empty(),"native_robot_id");
  for(const char * k:{"episode","binding_epoch","observed_seq"})integer(value.at(k));
  number(value.at("sim_time"));number(value.at("wall_deadline"));
}
void vector(const Json & v,size_t n,double lo,double hi) {
  require(v.is_array()&&v.size()==n,"native_vector");for(const auto & x:v)number(x,lo,hi);
}
std::string bytes(const fs::path & path) {
  std::ifstream f(path,std::ios::binary);require(bool(f),"native_file_missing");
  return std::string(std::istreambuf_iterator<char>(f),{});
}
std::string digest(const std::string & raw) {
  unsigned char output[SHA256_DIGEST_LENGTH];SHA256(reinterpret_cast<const unsigned char*>(raw.data()),raw.size(),output);
  static constexpr char chars[]="0123456789abcdef";std::string text;for(auto x:output){text+=chars[x>>4];text+=chars[x&15];}return text;
}
fs::path plain_path(const Json & value) {
  require(value.is_string(),"native_path_type");fs::path p=value.get<std::string>();
  require(p.is_absolute(),"native_absolute_path");for(const auto & part:p)require(part!="..","native_parent_path");
  auto current=p;while(!current.empty()) {require(!fs::is_symlink(fs::symlink_status(current)),"native_linked_path");
    if(current==current.parent_path())break;current=current.parent_path();}return p;
}
std::string checked_ref(const Json & ref) {
  keys(ref,{"path","sha256"});require(hex(ref.at("sha256"),64),"native_hash");
  auto data=bytes(plain_path(ref.at("path")));require(digest(data)==ref.at("sha256"),"native_reference_changed");return data;
}
FILE * exclusive(const fs::path & path) {
  int fd=::open(path.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);require(fd>=0,"native_owned_evidence_reused");
  FILE * f=fdopen(fd,"wb");if(!f){::close(fd);throw std::runtime_error("native_evidence_open");}return f;
}
void emit(FILE * output,const Json & value) {
  const auto line=value.dump()+"\n";require(fwrite(line.data(),1,line.size(),output)==line.size()&&fflush(output)==0,"native_output_failed");
}
Json capabilities() {return Json{{"schema","polar.sim.decision-plugin.capabilities.v2"},
  {"observation_schema",OBS},{"intent_schema",INTENT},{"sensor_profile","own_referee_navigation_v2"},
  {"output_modes",Json::array({"navigation_intent"})},{"source_association","exact_observation_and_navigation_feedback_v1"},
  {"fire_authority","none"},{"ui_config_contract","empty_v1"}};}

struct Scope {
  bool active=false,estimate=false,rfid_available=false,hold=false;
  Json source=Json::object(),goal_events=Json::array(),node_statuses=Json::array();
  std::optional<geometry_msgs::msg::PoseStamped> goal;
};
Json pose_json(const geometry_msgs::msg::PoseStamped & p) {
  return Json{{"header",{{"frame_id",p.header.frame_id},{"stamp",{{"sec",p.header.stamp.sec},{"nanosec",p.header.stamp.nanosec}}}}},
    {"position_m",{p.pose.position.x,p.pose.position.y,p.pose.position.z}},
    {"rotation_xyzw",{p.pose.orientation.x,p.pose.orientation.y,p.pose.orientation.z,p.pose.orientation.w}}};
}
class ScopedPubNavGoal : public pb2025_sentry_behavior::PubNav2GoalAction {
  Scope * scope_;
public:
  ScopedPubNavGoal(const std::string & name,const BT::NodeConfig & conf,const BT::RosNodeParams & params,Scope * scope)
    : PubNav2GoalAction(name,conf,params),scope_(scope) {}
  bool setMessage(geometry_msgs::msg::PoseStamped & message) override {
    require(scope_->active,"native_goal_outside_tick");
    const bool supply=name()=="supply_goal";
    bool called=false,ok=false;std::string reason="pending_navigation";
    if(scope_->estimate) {
      called=true;ok=pb2025_sentry_behavior::PubNav2GoalAction::setMessage(message);
      reason=ok?"allowed":"upstream_set_message_failed";
      if(supply&&!scope_->rfid_available){ok=false;reason="rfid_unavailable";}
    }
    scope_->goal_events.push_back(Json{{"source",scope_->source},{"node_name",name()},
      {"base_set_message_called",called},{"allowed",ok},{"reason",reason},
      {"message",called?pose_json(message):Json(nullptr)}});
    if(ok) {require(!scope_->goal.has_value(),"native_multiple_goals_one_tick");scope_->goal=message;}
    return ok;
  }
};
class ScopedHold : public BT::SyncActionNode {
  Scope * scope_;
public:
  ScopedHold(const std::string & n,const BT::NodeConfig & c,Scope * s):BT::SyncActionNode(n,c),scope_(s){}
  static BT::PortsList providedPorts(){return {};}
  BT::NodeStatus tick() override {require(scope_->active,"native_hold_outside_tick");scope_->hold=true;return BT::NodeStatus::SUCCESS;}
};

void validate_feedback(const Json & feedback,const Json & o) {
  keys(feedback,{"schema","source","scan","navigation","goal_status"});
  require(feedback.at("schema")=="polar.sim.navigation-feedback.v1"&&typed_equal(feedback.at("source"),six(o)),"native_feedback_identity");
  keys(feedback.at("scan"),{"cloud_frame_id","acquisition_start_ns","acquisition_end_ns","profile_sha256"});
  auto begin=integer(feedback["scan"]["acquisition_start_ns"]),end=integer(feedback["scan"]["acquisition_end_ns"]);
  integer(feedback["scan"]["cloud_frame_id"]);require(end>begin&&end-begin<=200000000&&end<=uint64_t(std::llround(number(o["sim_time"])*1e9)),"native_scan_window");
  require(hex(feedback["scan"]["profile_sha256"],64),"native_scan_profile");
  const auto & n=feedback.at("navigation");require(n.is_object()&&n.at("available").is_boolean(),"native_estimate_available");
  if(n["available"]==true) {
    keys(n,{"available","reason","frame","child_frame","stamp_ns","localization_stamp_ns","position_m","rotation_xyzw","provenance"});
    auto stamp=integer(n["stamp_ns"]);require(n["reason"]=="available"&&n["frame"]=="map"&&n["child_frame"]=="base_link"&&
      stamp==integer(n["localization_stamp_ns"])&&stamp>=begin&&stamp<=end,"native_estimate_source");
    vector(n["position_m"],3,-100000.,100000.);vector(n["rotation_xyzw"],4,-1.,1.);
    double norm=0;for(auto q:n["rotation_xyzw"])norm+=std::pow(q.get<double>(),2);require(std::abs(norm-1.)<=1e-5,"native_estimate_rotation");
    const auto & p=n["provenance"];keys(p,{"method","producer_source_sha256","localization_binary_sha256","mapping_binary_sha256"});
    require(p["method"]=="tf_buffer_exact_localization_stamp_v1","native_estimate_method");
    for(const char * k:{"producer_source_sha256","localization_binary_sha256","mapping_binary_sha256"})require(hex(p[k],64),"native_estimate_hash");
  } else {
    keys(n,{"available","reason"});require(n["reason"].is_string(),"native_estimate_reason");
    const std::set<std::string> reasons={"not_provided","pending_localization","map_transform_unavailable","staged_scan_expired","pending_navigation"};
    require(reasons.count(n["reason"].get<std::string>()),"native_estimate_reason");
  }
  // Goal history is diagnostic input, never a source of new targets here.
  const auto & g=feedback.at("goal_status");require(g.is_object()&&g.at("available").is_boolean(),"native_goal_status");
  if(g["available"]==false){keys(g,{"available","reason"});require(g["reason"]=="not_provided"||g["reason"]=="lifecycle_unavailable","native_goal_unavailable");}
  else {keys(g,{"available","selection","history","operation_count","stop_requested","fault"});
    require(g["history"].is_array()&&g["history"].size()<=8&&g["stop_requested"].is_boolean(),"native_goal_history");
    auto count=integer(g["operation_count"]);require(count<=256&&count>=g["history"].size()&&((count==0)==g["history"].empty()),"native_goal_count");}
}
void validate_observation(const Json & o) {
  keys(o,{"schema","robot_id","episode","binding_epoch","observed_seq","sim_time","wall_deadline","own","referee","navigation","perception"});
  require(o.at("schema")==OBS,"native_observation_schema");identity(o);
  const auto & own=o.at("own");keys(own,{"team","role","hp","ammo","heat","alive"});
  require(own["team"].is_string()&&own["role"].is_string()&&own["alive"].is_boolean(),"native_own_type");
  for(const char * k:{"hp","ammo","heat"})number(own[k],0.,65535.);
  const auto & r=o.at("referee");keys(r,{"phase","remaining_seconds","emergency_stop"});
  require(r["phase"].is_string()&&r["emergency_stop"].is_boolean(),"native_referee_type");number(r["remaining_seconds"],0.,2147483647.);
  const std::set<std::string> phases={"running","paused","idle","finished","countdown"};require(phases.count(r["phase"].get<std::string>()),"native_phase");
  keys(o["perception"],{"available","reason"});require(o["perception"]["available"].is_boolean()&&o["perception"]["available"]==false&&
    o["perception"]["reason"]=="not_provided_in_own_referee_v1","native_perception_unavailable_required");
  validate_feedback(o["navigation"],o);
}

class Runner {
  Json spec_,context_=nullptr,anchor_=nullptr;
  Scope scope_;
  std::shared_ptr<rclcpp::Node> node_;
  BT::BehaviorTreeFactory factory_;
  BT::Blackboard::Ptr global_;
  BT::Tree tree_;
  FILE * ledger_=nullptr;
  uint64_t ticks_=0,last_seq_=0;bool has_seq_=false,prepared_=false;
  double last_sim_=-1.;
  fs::path out_;
public:
  explicit Runner(Json spec):spec_(std::move(spec)) {
    require(typed_equal(spec_.at("capabilities"),capabilities()),"native_capabilities");
    require(hex(spec_["run_uuid"],32)&&spec_["domain_id"].is_number_integer()&&integer(spec_["domain_id"])==84,"native_scope");
    const auto & w=spec_.at("waypoints");keys(w,{"schema","attack_offset_m","supply_offset_m","yaw_offset_rad"});
    require(w["schema"]=="polar.pb.local-waypoints.v1","native_waypoints");vector(w["attack_offset_m"],2,-100000.,100000.);vector(w["supply_offset_m"],2,-100000.,100000.);number(w["yaw_offset_rad"],-M_PI,M_PI);
    auto build=parse_json(checked_ref(spec_["build_ref"]));
    require(build.at("passed")==true&&build.at("source_unchanged")==true&&typed_equal(build["native"],spec_["native_ref"])&&typed_equal(build["xml"],spec_["xml_ref"]),"native_build_binding");
    require(digest(bytes(fs::canonical("/proc/self/exe")))==spec_["native_ref"]["sha256"],"native_executable_changed");
    std::string xml=checked_ref(spec_["xml_ref"]);
    require(std::string(BT::LibraryVersionString())=="4.6.2","native_bt4_version");
    out_=plain_path(spec_["out_linux"]);require(fs::is_directory(out_),"native_owned_output_required");
    ledger_=exclusive(out_/"native_ticks.jsonl");
    rclcpp::NodeOptions options;options.enable_rosout(false);options.start_parameter_services(false);
    node_=std::make_shared<rclcpp::Node>("polar_pb_match_decision",spec_["namespace"].get<std::string>(),options);
    BT::RosNodeParams params(node_);
    factory_.registerNodeType<pb2025_sentry_behavior::IsGameStatusCondition>("IsGameStatus");
    factory_.registerNodeType<pb2025_sentry_behavior::IsStatusOKCondition>("IsStatusOK");
    factory_.registerNodeType<pb2025_sentry_behavior::IsRfidDetectedCondition>("IsRfidDetected");
    factory_.registerNodeType<ScopedPubNavGoal>("PubNav2Goal",params,&scope_);
    factory_.registerNodeType<ScopedHold>("ScopedHold",&scope_);
    global_=BT::Blackboard::create();auto root=BT::Blackboard::create(global_);
    factory_.registerBehaviorTreeFromText(xml);tree_=factory_.createTree("rmul_2025",root);
    for(const auto & subtree:tree_.subtrees)for(const auto & n:subtree->nodes)n->setTickMonitorCallback(
      [this](BT::TreeNode & node,BT::NodeStatus status,std::chrono::microseconds){
        if(scope_.active)scope_.node_statuses.push_back(Json{{"path",node.fullPath()},{"node_id",node.registrationName()},{"status",BT::toStr(status)}});});
    FILE * ready=exclusive(out_/"READY.json");emit(ready,Json{{"schema","polar.pb.match-decision-native-ready.v1"},
      {"run_uuid",spec_["run_uuid"]},{"native_ref",spec_["native_ref"]},{"xml_ref",spec_["xml_ref"]},
      {"build_ref",spec_["build_ref"]},{"btcpp_version",BT::LibraryVersionString()},{"tick_count",0},{"goal_sent",false}});fclose(ready);
  }
  Json request(const Json & req) {
    require(req.is_object()&&req.at("schema")==WIRE&&req.at("op").is_string(),"native_wire");
    auto op=req.at("op").get<std::string>();Json reply={{"schema",WIRE},{"op",op},{"ok",true}};
    if(op=="prepare") {keys(req,{"schema","op","config"});keys(req["config"],{});require(!prepared_&&context_.is_null(),"native_prepare_once");prepared_=true;reply["capabilities"]=capabilities();}
    else if(op=="reset") {
      keys(req,{"schema","op","context","config"});keys(req["config"],{});keys(req["context"],{"robot_id","episode","binding_epoch"});
      require(context_.is_null()&&typed_equal(req["context"],spec_["expected_generation"]),"native_reset_generation");
      Json source=req["context"];source["observed_seq"]=0;source["sim_time"]=0.;source["wall_deadline"]=0.;identity(source);
      context_=req["context"];reply["capabilities"]=capabilities();
    } else if(op=="act") {
      keys(req,{"schema","op","observation"});require(!context_.is_null(),"native_reset_required");
      const auto & o=req.at("observation");validate_observation(o);
      for(auto it=context_.begin();it!=context_.end();++it)require(typed_equal(o.at(it.key()),it.value()),"native_generation");
      auto seq=integer(o["observed_seq"]);double sim=number(o["sim_time"]);
      require((!has_seq_||seq>last_seq_)&&sim>=last_sim_,"native_replayed_observation");
      reply["intent"]=tick(o);last_seq_=seq;last_sim_=sim;has_seq_=true;
    } else throw std::runtime_error("native_operation");
    return reply;
  }
  Json tick(const Json & o) {
    scope_=Scope{};scope_.source=six(o);scope_.estimate=o["navigation"]["navigation"]["available"]==true;
    const auto & nav=o["navigation"]["navigation"];
    if(anchor_.is_null()&&scope_.estimate)anchor_=Json{{"source",six(o)},{"stamp_ns",nav["stamp_ns"]},{"position_m",nav["position_m"]},{"rotation_xyzw",nav["rotation_xyzw"]}};
    if(!anchor_.is_null()) {
      const auto & q=anchor_["rotation_xyzw"];double x=q[0],y=q[1],z=q[2],w=q[3];
      double yaw=std::atan2(2.*(w*z+x*y),1.-2.*(y*y+z*z))+spec_["waypoints"]["yaw_offset_rad"].get<double>();
      for(const auto & item:std::array<std::pair<const char*,const char*>,2>{{{"attack_pose","attack_offset_m"},{"supply_pose","supply_offset_m"}}}) {
        geometry_msgs::msg::PoseStamped p;p.header.frame_id="map";
        p.pose.position.x=anchor_["position_m"][0].get<double>()+spec_["waypoints"][item.second][0].get<double>();
        p.pose.position.y=anchor_["position_m"][1].get<double>()+spec_["waypoints"][item.second][1].get<double>();
        p.pose.orientation.z=std::sin(yaw/2);p.pose.orientation.w=std::cos(yaw/2);
        global_->set(item.first,p);anchor_[item.first]=pose_json(p);
      }
    }
    pb_rm_interfaces::msg::GameStatus game;
    const auto & r=o["referee"];std::string phase=r["phase"];
    game.game_progress=phase=="running"?4:(phase=="countdown"?3:(phase=="finished"?5:0));
    if(r["emergency_stop"]==true||o["own"]["alive"]==false)game.game_progress=0;
    game.stage_remain_time=static_cast<int32_t>(std::floor(number(r["remaining_seconds"])));
    pb_rm_interfaces::msg::RobotStatus own;
    own.current_hp=static_cast<uint16_t>(std::floor(number(o["own"]["hp"])));
    own.projectile_allowance_17mm=static_cast<uint16_t>(std::floor(number(o["own"]["ammo"])));
    own.shooter_17mm_1_barrel_heat=static_cast<uint16_t>(std::ceil(number(o["own"]["heat"])));
    global_->set("referee_gameStatus",game);global_->set("referee_robotStatus",own);
    global_->unset("referee_rfidStatus"); // absent is not NOT_DETECTED
    scope_.active=true;BT::NodeStatus status;
    try {status=tree_.tickExactlyOnce();scope_.active=false;}catch(...){scope_.active=false;throw;}
    Json command={{"behavior","hold"},{"reason","pb_no_current_goal"}};
    if(scope_.hold)command["reason"]="pb_game_or_safety_hold";
    else if(!scope_.estimate)command["reason"]="pb_navigation_unavailable";
    else if(!scope_.goal_events.empty()&&scope_.goal_events.back()["reason"]=="rfid_unavailable")command["reason"]="pb_rfid_unavailable";
    if(scope_.goal.has_value()&&!scope_.hold) {
      auto & p=scope_.goal.value();auto & q=p.pose.orientation;
      command=Json{{"behavior","navigate_to_pose"},{"reason","pb_rmul_2025_current_tick"},
        {"goal",{{"frame","map"},{"position_m",{p.pose.position.x,p.pose.position.y}},
          {"yaw_rad",std::atan2(2.*(q.w*q.z+q.x*q.y),1.-2.*(q.y*q.y+q.z*q.z))}}}};
    }
    Json intent=six(o);intent["schema"]=INTENT;intent["kind"]="decision";intent["mode"]="navigation_intent";intent["command"]=command;
    Json mapped={{"game_progress",game.game_progress},{"stage_remain_time",game.stage_remain_time},
      {"current_hp",own.current_hp},{"projectile_allowance_17mm",own.projectile_allowance_17mm},
      {"shooter_17mm_1_barrel_heat",own.shooter_17mm_1_barrel_heat},{"integer_policy","hp_ammo_time_floor_heat_ceil"},
      {"rfid_available",false},{"perception_available",false}};
    emit(ledger_,Json{{"schema","polar.pb.match-decision-tick.v1"},{"tick_number",++ticks_},
      {"source",six(o)},{"observation",o},{"intent",intent},
      {"tree",{{"tree_id","rmul_2025"},{"xml_sha256",spec_["xml_ref"]["sha256"]},{"upstream_xml_sha256",UPSTREAM_XML},
        {"root_status",BT::toStr(status)},{"tick_steps",1}}},
      {"node_statuses",scope_.node_statuses},{"goal_events",scope_.goal_events},{"anchor",anchor_},{"mapped_referee",mapped}});
    return intent;
  }
  void close(bool normal,bool interrupted) {
    auto started=Clock::now();tree_.haltTree();scope_.active=false;
    tree_=BT::Tree{};global_.reset();node_.reset();rclcpp::shutdown();
    if(ledger_){require(fclose(ledger_)==0,"native_ledger_close");ledger_=nullptr;}
    double elapsed=std::chrono::duration<double>(Clock::now()-started).count();
    FILE * output=exclusive(out_/"CLEANUP.json");emit(output,Json{{"schema","polar.pb.match-decision-native-cleanup.v1"},
      {"clean",normal&&elapsed<1.3},{"tick_count",ticks_},{"tree_halted",true},{"node_destroyed",true},{"context_shutdown",true},
      {"elapsed_s",elapsed},{"actuator_authority","none"},{"protocol_interrupted",interrupted}});fclose(output);
  }
};

int main(int argc,char ** argv) {
  int protocol=-1;std::unique_ptr<Runner> runner;int code=0;
  try {
    require(argc==5&&std::string(argv[1])=="--spec"&&std::string(argv[3])=="--sha256","native_cli");
    std::string raw=bytes(plain_path(argv[2]));require(digest(raw)==argv[4],"native_spec_changed");
    Json spec=parse_json(raw);keys(spec,{"schema","run_uuid","root_linux","out_linux","namespace","domain_id","native_ref","xml_ref","build_ref","environment_ref","source_sha256","expected_generation","waypoints","capabilities"});
    require(spec["schema"]=="polar.pb.match-decision-peer-spec.v1","native_spec_schema");
    fflush(stdout);protocol=dup(STDOUT_FILENO);require(protocol>=0&&dup2(STDERR_FILENO,STDOUT_FILENO)>=0,"native_protocol_fd");
    setenv("ROS_DOMAIN_ID","84",1);setenv("ROS_LOCALHOST_ONLY","1",1);setenv("RCUTILS_LOGGING_USE_STDOUT","0",1);
    int ros_argc=1;char * ros_argv[]={argv[0],nullptr};
    rclcpp::init(ros_argc,ros_argv,rclcpp::InitOptions{},rclcpp::SignalHandlerOptions::None);
    struct sigaction action{};action.sa_handler=request_stop;sigemptyset(&action.sa_mask);action.sa_flags=0;
    require(sigaction(SIGTERM,&action,nullptr)==0&&sigaction(SIGINT,&action,nullptr)==0,"native_stop_handler");
    struct sigaction pipe{};pipe.sa_handler=SIG_IGN;sigemptyset(&pipe.sa_mask);
    require(sigaction(SIGPIPE,&pipe,nullptr)==0,"native_pipe_handler");
    require(fcntl(STDIN_FILENO,F_SETFL,fcntl(STDIN_FILENO,F_GETFL)|O_NONBLOCK)>=0&&
      fcntl(protocol,F_SETFL,fcntl(protocol,F_GETFL)|O_NONBLOCK)>=0,"native_nonblocking_io");
    runner=std::make_unique<Runner>(spec);
    std::string pending;
    while(!stop_requested) {
      auto newline=pending.find('\n');
      if(newline==std::string::npos) {
        require(pending.size()<=12*1024*1024,"native_line_limit");
        struct pollfd input{STDIN_FILENO,POLLIN,0};int ready=poll(&input,1,5);
        if(ready<0){if(errno==EINTR)continue;throw std::runtime_error("native_input_poll");}
        if(ready==0)continue;
        char buffer[4096];ssize_t size=::read(STDIN_FILENO,buffer,sizeof(buffer));
        if(size<0){if(errno==EAGAIN||errno==EINTR)continue;throw std::runtime_error("native_input_read");}
        if(size==0){require(pending.empty()||stop_requested,"native_partial_line");break;}
        pending.append(buffer,size);continue;
      }
      require(newline<=12*1024*1024,"native_line_limit");
      std::string line=pending.substr(0,newline);pending.erase(0,newline+1);
      if(stop_requested)break;
      Json req=parse_json(line);Json response=runner->request(req);auto encoded=response.dump()+"\n";
      require(encoded.size()<=65536,"native_response_limit");
      size_t sent=0;
      while(sent<encoded.size()&&!stop_requested) {
        ssize_t count=::write(protocol,encoded.data()+sent,encoded.size()-sent);
        if(count>0){sent+=size_t(count);continue;}
        if(count<0&&(errno==EAGAIN||errno==EINTR)) {
          struct pollfd output{protocol,POLLOUT,0};int ready=poll(&output,1,5);
          if(ready<0&&errno!=EINTR)throw std::runtime_error("native_output_poll");continue;
        }
        throw std::runtime_error("native_protocol_write");
      }
    }
  } catch(const std::exception & e) {std::cerr<<"pb_match_decision_native_failed:"<<e.what()<<"\n";code=stop_requested?0:2;}
  if(runner){try{runner->close(code==0,stop_requested!=0);}catch(const std::exception & e){std::cerr<<"pb_match_cleanup_failed:"<<e.what()<<"\n";code=2;}}
  else if(rclcpp::ok())rclcpp::shutdown();
  if(protocol>=0)::close(protocol);return code;
}
