#pragma once
#include <cstdio>
#define RCLCPP_INFO(logger, ...) do { std::fprintf(stderr, __VA_ARGS__); std::fprintf(stderr,"\n"); } while(0)
#define RCLCPP_WARN(logger, ...) RCLCPP_INFO(logger,__VA_ARGS__)
#define RCLCPP_ERROR(logger, ...) RCLCPP_INFO(logger,__VA_ARGS__)
