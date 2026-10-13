#include <pluginlib/class_loader.hpp>
#include <nav2_costmap_2d/layer.hpp>
#include <nav2_core/controller.hpp>
#include <nav2_core/behavior.hpp>
#include <iostream>
int main() {
  pluginlib::ClassLoader<nav2_costmap_2d::Layer> layers("nav2_costmap_2d", "nav2_costmap_2d::Layer");
  auto layer = layers.createUniqueInstance("pb_nav2_costmap_2d::IntensityVoxelLayer");
  std::cout << "PB_LAYER_CREATED\n";
  pluginlib::ClassLoader<nav2_core::Controller> controllers("nav2_core", "nav2_core::Controller");
  auto controller = controllers.createUniqueInstance("pb_omni_pid_pursuit_controller::OmniPidPursuitController");
  std::cout << "PB_CONTROLLER_CREATED\n";
  pluginlib::ClassLoader<nav2_core::Behavior> behaviors("nav2_core", "nav2_core::Behavior");
  auto behavior = behaviors.createUniqueInstance("pb_nav2_behaviors/BackUpFreeSpace");
  std::cout << "PB_BEHAVIOR_CREATED\n";
}
