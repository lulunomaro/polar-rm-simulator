cmake_minimum_required(VERSION 3.20)
project(rmcs_sim_operator_fov LANGUAGES CXX)
if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux" OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8 OR NOT CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|AMD64|amd64)$")
  message(FATAL_ERROR "This native RMCS target supports Linux x86-64 only; cross-architecture builds are not qualified.")
endif()
set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT DEFINED RMCS_GENERATED_DIR OR NOT EXISTS "${RMCS_GENERATED_DIR}/main.cpp")
  message(FATAL_ERROR "Run build_portable.py prepare/build; generated operator source is required")
endif()
find_package(Eigen3 3.4 REQUIRED NO_MODULE)
find_package(OpenCV 4.10 REQUIRED COMPONENTS core imgproc imgcodecs calib3d features2d flann dnn ximgproc)
find_package(yaml-cpp 0.8 REQUIRED CONFIG)
find_package(OpenVINO 2025.4 REQUIRED COMPONENTS Runtime)
if(NOT DEFINED OpenVINO_GLIBCXX_USE_CXX11_ABI OR NOT "${OpenVINO_GLIBCXX_USE_CXX11_ABI}" STREQUAL "1")
  message(FATAL_ERROR "RMCS requires OpenVINO's official C++ ABI=1 runtime. Python wheels with ABI=0 are incompatible; set --prefix to the official C++ archive's runtime/cmake directory.")
endif()
option(RMCS_USE_CONTOUR_CORNERS "Explicit own image-contour frontend revision" OFF)
set(RMCS_CORNERS_SOURCE candidate/src/utility/math/corners_optimizor.cpp)
if(RMCS_USE_CONTOUR_CORNERS)
  if(NOT EXISTS "${RMCS_GENERATED_DIR}/corners_contour_v1.cpp")
    message(FATAL_ERROR "Contour frontend requires the separately hash-bound generated source")
  endif()
  set(RMCS_CORNERS_SOURCE "${RMCS_GENERATED_DIR}/corners_contour_v1.cpp")
endif()
add_executable(rmcs_sim_operator_fov
  "${RMCS_GENERATED_DIR}/main.cpp"
  candidate/src/kernel/detector.cpp
  candidate/src/kernel/pose_estimator.cpp
  candidate/src/kernel/tracker.cpp
  candidate/src/kernel/fire_control.cpp
  candidate/src/utility/logging/printer.cpp
  candidate/src/utility/panic.cpp
  candidate/src/utility/image/process.cpp
  candidate/src/utility/math/camera.cpp
  ${RMCS_CORNERS_SOURCE}
  candidate/src/utility/math/outpost.cpp
  candidate/src/utility/math/reprojection.cpp
  candidate/src/utility/math/robot.cpp
  candidate/src/utility/math/solve_armors.cpp
  candidate/src/utility/math/solve_pnp/outpost_distance_optimizer.cpp
  candidate/src/utility/math/solve_pnp/pnp_solution.cpp
  candidate/src/utility/math/solve_pnp/yaw_optimizer.cpp
  candidate/src/module/tracker/model/outpost.cpp
  candidate/src/module/tracker/model/robot.cpp
  candidate/src/module/tracker/model/rune.cpp
  candidate/src/module/tracker/model/rune_energy_fitter.cpp
  candidate/src/module/tracker/model/virtual_rune.cpp
  candidate/src/module/detector/adjacency_lightbar.cpp
  candidate/src/module/detector/armor_detection.cpp
  candidate/src/module/detector/green_light.cpp
  candidate/src/module/detector/lightbar.cpp
  candidate/src/module/detector/rune.cpp
  candidate/src/module/fire_control/shoot_evaluator.cpp
  candidate/src/module/fire_control/trajectory_solution.cpp
)
# GCC 15 no longer includes <algorithm> transitively through the original
# headers. Keep all 94 recovered source bytes sealed; supply the required
# standard declaration to this one translation unit at the build boundary.
set_source_files_properties(candidate/src/module/fire_control/shoot_evaluator.cpp
  PROPERTIES COMPILE_OPTIONS "-include;algorithm")
target_include_directories(rmcs_sim_operator_fov PRIVATE
  "${CMAKE_CURRENT_SOURCE_DIR}/shims"
  "${CMAKE_CURRENT_SOURCE_DIR}/candidate/src"
  "${CMAKE_CURRENT_SOURCE_DIR}/candidate/src/kernel")
# The unchanged source uses both <Eigen/...> and <eigen3/Eigen/...>.
get_target_property(EIGEN_INCLUDE_DIRS Eigen3::Eigen INTERFACE_INCLUDE_DIRECTORIES)
foreach(EIGEN_INCLUDE IN LISTS EIGEN_INCLUDE_DIRS)
  if(IS_ABSOLUTE "${EIGEN_INCLUDE}")
    get_filename_component(EIGEN_PARENT "${EIGEN_INCLUDE}" DIRECTORY)
    target_include_directories(rmcs_sim_operator_fov SYSTEM PRIVATE "${EIGEN_PARENT}")
  endif()
endforeach()
target_include_directories(rmcs_sim_operator_fov SYSTEM PRIVATE ${OpenCV_INCLUDE_DIRS})
target_compile_definitions(rmcs_sim_operator_fov PRIVATE REBUILD_CANDIDATE=1 _GLIBCXX_USE_CXX11_ABI=1 NDEBUG)
target_compile_options(rmcs_sim_operator_fov PRIVATE -O2 -Wall -Wextra -Wpedantic -pthread)
target_link_options(rmcs_sim_operator_fov PRIVATE -pthread)
target_link_libraries(rmcs_sim_operator_fov PRIVATE Eigen3::Eigen yaml-cpp::yaml-cpp openvino::runtime ${OpenCV_LIBS})
