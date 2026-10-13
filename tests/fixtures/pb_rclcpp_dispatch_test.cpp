// Synthetic, real-rclcpp DDS fixture. No Point-LIO, future samples or SIL.
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/imu.hpp>
#include <array>
#include <chrono>
#include <iostream>
#include <thread>
#include <vector>
#include <algorithm>

int main(int argc, char **argv) {
  if (argc != 2 || (std::string(argv[1]) != "some" && std::string(argv[1]) != "all")) return 2;
  const std::string mode=argv[1];
  rclcpp::init(argc,argv);
  auto publisher_node=std::make_shared<rclcpp::Node>("pb_dispatch_fixture_publisher");
  auto subscriber_node=std::make_shared<rclcpp::Node>("pb_dispatch_fixture_subscriber");
  auto qos=rclcpp::SensorDataQoS().keep_last(1024);
  auto publisher=publisher_node->create_publisher<sensor_msgs::msg::Imu>("pb_fixture/imu",qos);
  std::array<int64_t,51> stamps{};
  std::size_t received=0;bool overflow=false;
  auto subscriber=subscriber_node->create_subscription<sensor_msgs::msg::Imu>("pb_fixture/imu",qos,
    [&](sensor_msgs::msg::Imu::ConstSharedPtr msg) {
      if(received>=stamps.size()){overflow=true;return;}
      stamps[received++]=static_cast<int64_t>(msg->header.stamp.sec)*1000000000LL+msg->header.stamp.nanosec;
    });
  rclcpp::executors::SingleThreadedExecutor executor;executor.add_node(subscriber_node);
  const auto discovery_deadline=std::chrono::steady_clock::now()+std::chrono::seconds(5);
  while(publisher->get_subscription_count()<1 && std::chrono::steady_clock::now()<discovery_deadline)
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  if(publisher->get_subscription_count()<1){rclcpp::shutdown();return 3;}
  const auto start=std::chrono::steady_clock::now();
  for(uint32_t i=0;i<51;++i){
    sensor_msgs::msg::Imu msg;msg.header.frame_id="livox_frame";
    msg.header.stamp.sec=1;msg.header.stamp.nanosec=i*2000000;
    msg.orientation_covariance[0]=-1;msg.linear_acceleration.z=9.81;
    publisher->publish(msg);
  }
  const auto burst_end=std::chrono::steady_clock::now();
  rclcpp::Rate rate(500);
  std::vector<std::size_t> callback_counts;
  std::vector<int64_t> dispatch_ns;
  const auto deadline=start+std::chrono::seconds(2);
  while(rclcpp::ok() && received<51 && std::chrono::steady_clock::now()<deadline && callback_counts.size()<1024){
    const auto before=received;const auto call_start=std::chrono::steady_clock::now();
    if(mode=="some")executor.spin_some();
    else executor.spin_all(std::chrono::milliseconds(1));
    dispatch_ns.push_back(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-call_start).count());
    callback_counts.push_back(received-before);
    if(received<51)rate.sleep();
  }
  const auto finish=std::chrono::steady_clock::now();
  bool original_stamps=received==51 && !overflow;
  for(std::size_t i=0;i<received;++i)original_stamps=original_stamps && stamps[i]==1000000000LL+static_cast<int64_t>(i)*2000000LL;
  const auto max_count=*std::max_element(callback_counts.begin(),callback_counts.end());
  const auto max_duration=*std::max_element(dispatch_ns.begin(),dispatch_ns.end());
  const bool passed=original_stamps && (mode=="some" ? max_count==1 : max_count>1);
  std::cout<<"{\"schema\":\"polar.pb.rclcpp-dispatch-fixture.v1\",\"scope\":\"synthetic DDS fixture, not LIO or SIL\","
    <<"\"clock_domain\":\"linux_steady_diagnostic_only\",\"mode\":\""<<mode<<"\",\"imu_samples\":"<<received
    <<",\"original_stamps_preserved\":"<<(original_stamps?"true":"false")
    <<",\"poll_hz\":500,\"spin_all_budget_ns\":1000000,\"dispatch_calls\":"<<callback_counts.size()
    <<",\"max_callbacks_per_dispatch\":"<<max_count<<",\"max_dispatch_duration_ns\":"<<max_duration
    <<",\"publication_duration_ns\":"<<std::chrono::duration_cast<std::chrono::nanoseconds>(burst_end-start).count()
    <<",\"burst_end_to_complete_ns\":"<<std::chrono::duration_cast<std::chrono::nanoseconds>(finish-burst_end).count()
    <<",\"passed\":"<<(passed?"true":"false")<<",\"callbacks_per_dispatch\":[";
  for(std::size_t i=0;i<callback_counts.size();++i)std::cout<<(i?",":"")<<callback_counts[i];
  std::cout<<"],\"dispatch_duration_ns\":[";
  for(std::size_t i=0;i<dispatch_ns.size();++i)std::cout<<(i?",":"")<<dispatch_ns[i];
  std::cout<<"]}"<<std::endl;
  executor.remove_node(subscriber_node);subscriber.reset();publisher.reset();
  subscriber_node.reset();publisher_node.reset();rclcpp::shutdown();
  return passed?0:4;
}
