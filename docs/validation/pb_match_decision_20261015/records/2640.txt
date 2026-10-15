cmake_minimum_required(VERSION 3.16)
project(polar_pb_match_decision LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
find_package(ament_cmake REQUIRED)
# Upstream standalone 4.6.2 exports Config without a ConfigVersion file.
# The owned build pins its library, and runner verifies LibraryVersionString.
find_package(behaviortree_cpp REQUIRED CONFIG)
find_package(rclcpp REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)
find_package(pb_rm_interfaces REQUIRED)
find_package(OpenSSL REQUIRED)
add_executable(polar_pb_match_decision
  runner.cpp
  upstream/pb/plugins/condition/is_game_status.cpp
  upstream/pb/plugins/condition/is_status_ok.cpp
  upstream/pb/plugins/condition/is_rfid_detected.cpp
  upstream/pb/plugins/action/pub_nav2_goal.cpp)
target_include_directories(polar_pb_match_decision PRIVATE upstream/pb/include upstream/ros2/include)
# Deliberately no BT_PLUGIN_EXPORT: upstream registration functions remain
# translation-unit-local (BTCPP_EXPORT=static); original implementations link.
ament_target_dependencies(polar_pb_match_decision rclcpp geometry_msgs tf2_geometry_msgs pb_rm_interfaces)
target_link_libraries(polar_pb_match_decision BT::behaviortree_cpp OpenSSL::Crypto)
target_compile_options(polar_pb_match_decision PRIVATE -Wall -Wextra)
install(TARGETS polar_pb_match_decision RUNTIME DESTINATION bin)
