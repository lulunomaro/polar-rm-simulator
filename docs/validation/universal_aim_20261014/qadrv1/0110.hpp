#pragma once
#include <string>
namespace rclcpp { struct Logger { std::string name; }; inline Logger get_logger(const std::string& n) { return {n}; } }
