#pragma once
#include <stdexcept>
namespace rclcpp::exceptions { struct InvalidParameterTypeException:std::runtime_error { using std::runtime_error::runtime_error; }; }
