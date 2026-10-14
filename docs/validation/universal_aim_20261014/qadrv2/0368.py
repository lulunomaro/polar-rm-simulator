"""Actual header compiled with explicit fake ROS types; no DDS or algorithms."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
STUB=r'''
#pragma once
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <variant>
#include <vector>
#include <cstdio>
namespace builtin_interfaces {namespace msg {struct Time {int32_t sec=0;uint32_t nanosec=0;};}}
struct Header {builtin_interfaces::msg::Time stamp;std::string frame_id;};
struct Vec {double x=0,y=0,z=0;};
namespace geometry_msgs {namespace msg {struct PoseStamped {Header header;};struct TwistStamped {Header header;struct {Vec linear,angular;} twist;};}}
namespace std_msgs {namespace msg {struct String {using ConstSharedPtr=std::shared_ptr<const String>;std::string data;};}}
namespace rclcpp {
inline std::vector<std::string> logs;
struct Logger{};inline Logger get_logger(const char*){return {};}
template<class...Args> void log(const char* fmt,Args...args){char text[2048];std::snprintf(text,sizeof(text),fmt,args...);logs.emplace_back(text);}
struct Time {int64_t value;int64_t nanoseconds()const{return value;}};
struct Clock {using SharedPtr=std::shared_ptr<Clock>;int64_t value=100000000;Time now()const{return {value};}};
struct KeepLast {explicit KeepLast(int){}};
struct QoS {explicit QoS(KeepLast){}QoS& reliable(){return *this;}QoS& durability_volatile(){return *this;}};
template<class T> struct Subscription {using SharedPtr=std::shared_ptr<Subscription>;};
struct Parameter {
 std::variant<bool,int64_t,std::string> value;
 template<class T>T get_value()const{return std::get<T>(value);}bool as_bool()const{return get_value<bool>();}
};
}
#define RCLCPP_INFO(logger,...) rclcpp::log(__VA_ARGS__)
namespace rclcpp_lifecycle {
template<class T> struct LifecyclePublisher {using SharedPtr=std::shared_ptr<LifecyclePublisher>;std::vector<T> messages;void on_activate(){}void on_deactivate(){}void publish(const T&v){messages.push_back(v);}};
struct LifecycleNode {
 using SharedPtr=std::shared_ptr<LifecycleNode>;std::map<std::string,rclcpp::Parameter> parameters;
 std::map<std::string,std::function<void(std_msgs::msg::String::ConstSharedPtr)>> callbacks;
 rclcpp::Clock::SharedPtr clock=std::make_shared<rclcpp::Clock>();LifecyclePublisher<std_msgs::msg::String>::SharedPtr output;
 bool has_parameter(const std::string&key)const{return parameters.count(key);}
 template<class T>void declare_parameter(const std::string&key,const T&v){parameters[key]={v};}
 rclcpp::Parameter get_parameter(const std::string&key)const{return parameters.at(key);}
 auto get_clock(){return clock;}auto get_logger(){return rclcpp::Logger{};}
 template<class T>auto create_publisher(const std::string&,const rclcpp::QoS&){auto p=std::make_shared<LifecyclePublisher<T>>();output=p;return p;}
 template<class T,class F>auto create_subscription(const std::string&key,const rclcpp::QoS&,F cb){callbacks[key]=cb;return std::make_shared<rclcpp::Subscription<T>>();}
 void receive(const std::string&topic,const std::string&raw){auto p=std::make_shared<std_msgs::msg::String>();p->data=raw;callbacks.at(topic)(p);}
};
}
'''

PROBE=r'''
#include "pb_controller_context.hpp"
#include <cassert>
#include <iostream>
using Json=nlohmann::json;
Json req(int seq=1){return {{"schema","polar.sim.pb-navigation-request.v1"},{"adapter_id","custom_pb_navigation"},{"robot_id","red_sentry"},{"episode",0},{"binding_epoch",1},{"observed_seq",seq},{"sim_time",.1},{"wall_deadline",123.45},{"cloud_frame_id",seq-1},{"acquisition_start_ns",0},{"acquisition_end_ns",100000000}};}
Json loc(Json q,int64_t stamp=98000000){q["schema"]="polar.sim.pb-localization-result.v1";q["localization_stamp_ns"]=stamp;return q;}
auto node(bool diagnostics){auto n=std::make_shared<rclcpp_lifecycle::LifecycleNode>();n->parameters["polar_sourced.enabled"]={true};n->parameters["polar_sourced.diagnostics"]={diagnostics};n->parameters["polar_sourced.robot_id"]={std::string("red_sentry")};n->parameters["polar_sourced.episode"]={int64_t(0)};n->parameters["polar_sourced.binding_epoch"]={int64_t(1)};n->parameters["use_sim_time"]={true};return n;}
Json run(bool diagnostics){
 auto n=node(diagnostics);polar_pb::ControllerContext c;c.configure(n,"base_link");c.activate();
 geometry_msgs::msg::PoseStamped p;p.header.stamp.nanosec=98000000;geometry_msgs::msg::TwistStamped v;v.twist.linear.x=.25;
 assert(c.begin(p).is_null());c.finish(Json(),p,v);
 n->receive("/polar/pb/request",req().dump());assert(c.begin(p).is_null());
 n->receive("/polar/pb/localization",loc(req()).dump());p.header.stamp.nanosec=96000000;assert(c.begin(p).is_null());
 p.header.stamp.nanosec=98000000;auto snapshot=c.begin(p);assert(!snapshot.is_null());
 v.twist.linear.x=1.001;c.finish(snapshot,p,v);assert(n->output->messages.empty());
 v.twist.linear.x=.25;n->clock->value=100000001;c.finish(snapshot,p,v);assert(n->output->messages.empty());
 n->clock->value=97000000;c.finish(snapshot,p,v);assert(n->output->messages.empty());
 n->clock->value=100000000;n->receive("/polar/pb/request",req(2).dump());c.finish(snapshot,p,v);assert(n->output->messages.empty());
 n->receive("/polar/pb/localization",loc(req()).dump());assert(c.begin(p).is_null());
 auto bad=loc(req(2));bad["observed_seq"]=2.;n->receive("/polar/pb/localization",bad.dump());assert(c.begin(p).is_null());
 n->receive("/polar/pb/localization",loc(req(2)).dump());snapshot=c.begin(p);assert(!snapshot.is_null());c.finish(snapshot,p,v);
 assert(n->output->messages.size()==1);auto output=Json::parse(n->output->messages[0].data);assert(output["action"]["observed_seq"]==2);
 assert(c.begin(p).is_null());c.deactivate();assert(c.begin(p).is_null());c.cleanup();return output;
}
int main(){
 auto off=run(false);assert(rclcpp::logs.empty());auto on=run(true);assert(on==off);
 bool clock=false,changed=false,stamp=false,wrongtype=false;
 for(const auto &line:rclcpp::logs){
  if(line.find("finish_clock_outside_window")!=std::string::npos)clock=true;
  if(line.find("finish_pending_changed")!=std::string::npos)changed=true;
  if(line.find("begin_pose_not_localized")!=std::string::npos)stamp=true;
  if(line.find("localization_context_mismatch field=observed_seq")!=std::string::npos)wrongtype=true;
  assert(line.find("wall_deadline")==std::string::npos);assert(line.find("linear_acceleration")==std::string::npos);
 }
 assert(clock&&changed&&stamp&&wrongtype);
 rclcpp::logs.clear();auto n=node(true);polar_pb::ControllerContext bounded;bounded.configure(n,"base_link");bounded.activate();geometry_msgs::msg::PoseStamped p;
 for(int i=0;i<10000;++i)bounded.begin(p);assert(rclcpp::logs.size()==256);
 std::cout<<"DIAGNOSTICS_ON_OFF_IDENTICAL_OUTPUT_AND_REJECTION;256_LOG_BOUND;NO_ROS_DDS\n";
}
'''


def json_include():
    candidates=[Path('/root/polar-humble-ext4-20261014-01/prefix/usr/include'),
        ROOT/'artifacts/pb2025-humble-environment-20261013/prefix/usr/include',Path('/usr/include')]
    return next((p for p in candidates if (p/'nlohmann/json.hpp').is_file()),None)


class ControllerDiagnosticTests(unittest.TestCase):
    def test_default_disabled_and_fixed_metadata_budget(self):
        text=(ROOT/'rm_match/integrations/pb_controller_context.hpp').read_text()
        self.assertIn('"polar_sourced.diagnostics",false',text)
        self.assertIn('diagnostic_count_>=256',text)
        self.assertNotIn('msg->data.c_str()',text)

    @unittest.skipUnless(sys.platform=='linux' and shutil.which('g++'),'actual Linux C++ compiler required; fake ROS only')
    def test_actual_header_diagnostics_preserve_guards_outputs_and_strict_identity(self):
        include=json_include()
        if include is None:self.skipTest('verified nlohmann header unavailable')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'fake_ros.hpp').write_text(STUB)
            for name in ('rclcpp/rclcpp.hpp','rclcpp_lifecycle/lifecycle_node.hpp','std_msgs/msg/string.hpp','geometry_msgs/msg/pose_stamped.hpp','geometry_msgs/msg/twist_stamped.hpp'):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('#include "fake_ros.hpp"\n')
            (root/'probe.cpp').write_text(PROBE)
            proc=subprocess.Popen(['g++','-std=c++17','-I',str(root),'-I',str(ROOT/'rm_match/integrations'),'-I',str(include),str(root/'probe.cpp'),'-o',str(root/'probe')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            try:
                stdout,stderr=proc.communicate(timeout=30)
                self.assertEqual(proc.returncode,0,stderr)
            finally:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                if proc.poll() is None:proc.wait(timeout=1)
                proc.stdout.close();proc.stderr.close()
            result=subprocess.run([str(root/'probe')],capture_output=True,text=True,timeout=3)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('DIAGNOSTICS_ON_OFF_IDENTICAL_OUTPUT_AND_REJECTION;256_LOG_BOUND;NO_ROS_DDS',result.stdout)


if __name__=='__main__':unittest.main()
