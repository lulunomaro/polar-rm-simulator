cmake_minimum_required(VERSION 3.20)
project(polar_external_aim_example LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
find_package(OpenCV REQUIRED COMPONENTS core imgproc imgcodecs calib3d dnn highgui)
find_package(Eigen3 REQUIRED)
find_package(OpenVINO REQUIRED COMPONENTS Runtime)
find_package(yaml-cpp REQUIRED)
find_package(fmt REQUIRED)
find_package(spdlog REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(OpenSSL REQUIRED COMPONENTS Crypto)
if(NOT DEFINED POLAR_UPSTREAM_DIR)
  message(FATAL_ERROR "POLAR_UPSTREAM_DIR must name the hash-verified prepared snapshot")
endif()
# Explicit algorithm/tool objects only. No upstream top-level CMake, camera,
# SocketCAN, serial, ROS or hardware acquisition object is compiled or linked.
add_executable(polar_native_aim
  runner.cpp logger_stderr.cpp
  ${POLAR_UPSTREAM_DIR}/tasks/auto_aim/armor.cpp
  ${POLAR_UPSTREAM_DIR}/tasks/auto_aim/classifier.cpp
  ${POLAR_UPSTREAM_DIR}/tasks/auto_aim/detector.cpp
  ${POLAR_UPSTREAM_DIR}/tasks/auto_aim/solver.cpp
  ${POLAR_UPSTREAM_DIR}/tasks/auto_aim/target.cpp
  ${POLAR_UPSTREAM_DIR}/tasks/auto_aim/tracker.cpp
  ${POLAR_UPSTREAM_DIR}/tasks/auto_aim/yolos/yolov5.cpp
  ${POLAR_UPSTREAM_DIR}/tasks/auto_aim/planner/planner.cpp
  ${POLAR_UPSTREAM_DIR}/tasks/auto_aim/planner/tinympc/admm.cpp
  ${POLAR_UPSTREAM_DIR}/tasks/auto_aim/planner/tinympc/tiny_api.cpp
  ${POLAR_UPSTREAM_DIR}/tasks/auto_aim/planner/tinympc/rho_benchmark.cpp
  ${POLAR_UPSTREAM_DIR}/tasks/auto_aim/planner/tinympc/codegen.cpp
  ${POLAR_UPSTREAM_DIR}/tools/extended_kalman_filter.cpp
  ${POLAR_UPSTREAM_DIR}/tools/math_tools.cpp
  ${POLAR_UPSTREAM_DIR}/tools/img_tools.cpp
  ${POLAR_UPSTREAM_DIR}/tools/trajectory.cpp)
target_include_directories(polar_native_aim PRIVATE ${POLAR_UPSTREAM_DIR}
  ${POLAR_UPSTREAM_DIR}/tasks/auto_aim/planner ${OpenCV_INCLUDE_DIRS})
# These two original save() implementations format ArmorName directly. fmt10
# removed its implicit integer mapping. An explicit identical numeric formatter
# keeps original source bytes and filenames, without linking hardware or GUI IO.
set_source_files_properties(
  ${POLAR_UPSTREAM_DIR}/tasks/auto_aim/detector.cpp
  ${POLAR_UPSTREAM_DIR}/tasks/auto_aim/yolos/yolov5.cpp
  PROPERTIES COMPILE_OPTIONS "-include;${CMAKE_CURRENT_SOURCE_DIR}/fmt_armor_name_compat.hpp")
target_link_libraries(polar_native_aim PRIVATE ${OpenCV_LIBS} Eigen3::Eigen
  openvino::runtime yaml-cpp fmt::fmt spdlog::spdlog nlohmann_json::nlohmann_json OpenSSL::Crypto)
