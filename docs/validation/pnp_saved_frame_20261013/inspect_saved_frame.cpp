#define OPENCV_DISABLE_EIGEN_TENSOR_SUPPORT
#include "adapter_clock.hpp"
#include "kernel/detector.hpp"
#include "kernel/pose_estimator.hpp"
#include "utility/math/solve_pnp/pnp_solution.hpp"
#include "utility/math/conversion.hpp"
#include "utility/robot/constant.hpp"
#include <opencv2/calib3d.hpp>
#include <opencv2/core/eigen.hpp>
#include <yaml-cpp/yaml.h>
#include <fstream>
#include <iostream>
#include <iomanip>
using namespace rmcs; using namespace rmcs::kernel; using namespace rmcs::util;
int main(int argc,char** argv) {
 if(argc!=4)return 1;
 auto config=YAML::LoadFile(argv[1]); auto meta=YAML::LoadFile(argv[3]);
 auto K=meta["K"].as<std::array<double,9>>(); auto D=meta["D"].as<std::array<double,5>>();
 auto qp=meta["qpos"].as<std::array<double,5>>();auto odom=meta["odom"].as<std::array<double,3>>();
 Eigen::Quaterniond q=Eigen::AngleAxisd(odom[2]+qp[3],Eigen::Vector3d::UnitZ()) * Eigen::AngleAxisd(-qp[4],Eigen::Vector3d::UnitY());
 Eigen::Vector3d t=q*Eigen::Vector3d(.24,0,.06);
 CameraFeature cf;cf.from(K);cf.from(D);cf.orientation=q;cf.translation=t;
 Detector d;if(auto r=d.initialize(config["detector"]);!r)throw std::runtime_error(r.error());d.update_detect_rune(false);d.update_detect_color(CampColor::BLUE);d.update_camera(K);d.update_camera(D);
 cv::Mat image(1080,1440,CV_8UC3);std::ifstream f(argv[2],std::ios::binary);f.read(reinterpret_cast<char*>(image.data),1440*1080*3);if(f.gcount()!=1440*1080*3)throw std::runtime_error("bad frame bytes");
 const auto result=d.detect(image);
 std::cout<<std::setprecision(17)<<"inference_calls=1\narmors="<<result.armors.size()<<"\nq_odom_camera_wxyz="<<q.w()<<","<<q.x()<<","<<q.y()<<","<<q.z()<<"\nt_odom_camera="<<t.transpose()<<"\n";
 PoseEstimator estimator;if(auto r=estimator.initialize(config["pose_estimator"]);!r)throw std::runtime_error(r.error());estimator.configure_camera(K,D);Transform tf;tf.orientation=q;tf.translation=t;estimator.update_camera_transform(tf);std::cout<<"original_estimator_output_count="<<estimator.estimate_armor(result.armors,image).size()<<"\n";
 for(const auto& a:result.armors) {
  std::cout<<"armor_genre="<<get_enum_name(a.genre)<<"\narmor_color="<<get_enum_name(a.color)<<"\nconfidence="<<a.confidence<<"\n";
  for(auto [name,point]:std::array{std::pair{"tl",a.tl},std::pair{"bl",a.bl},std::pair{"br",a.br},std::pair{"tr",a.tr}})std::cout<<name<<"="<<point.x<<","<<point.y<<"\n";
  const double w=DeviceIds::kLargeArmor().contains(a.genre)?kLargeArmorWidth:kSmallArmorWidth,h=kLightBarHeight;
  std::vector<cv::Point3f> shape{{float(-.5*w),float(-.5*h),0},{float(-.5*w),float(.5*h),0},{float(.5*w),float(.5*h),0},{float(.5*w),float(-.5*h),0}};
  std::vector<cv::Point2f> points{a.tl,a.bl,a.br,a.tr};std::vector<cv::Vec3d> rv,tv;std::vector<double>errors;
  auto success=cv::solvePnPGeneric(shape,points,cf.intrinsic(),cf.distortion(),rv,tv,false,cv::SOLVEPNP_IPPE,cv::noArray(),cv::noArray(),errors);
  std::cout<<"pnp_success="<<success<<"\npnp_candidates="<<rv.size()<<"\n";
  for(size_t i=0;i<rv.size();++i){cv::Mat rm;cv::Rodrigues(rv[i],rm);Eigen::Matrix3d r;cv::cv2eigen(rm,r);Eigen::Vector3d tr;cv::cv2eigen(tv[i],tr);Eigen::Quaterniond qc(opencv2ros_rotation(r));qc.normalize();Eigen::Vector3d tc=opencv2ros_position(tr);Eigen::Quaterniond qo(q*qc);qo.normalize();auto back=Eigen::Vector3d(qc*Eigen::Vector3d::UnitX());double dot=back.dot(tc.normalized());double pitch=eulers(qo,2,1,0)[1];double expected=(a.genre==ArmorGenre::OUTPOST)?kPredictedOutpostArmorPitch:kPredictedOtherArmorPitch;
   std::cout<<"candidate="<<i<<" z="<<tv[i][2]<<" back_dot="<<dot<<" pitch_degrees="<<pitch*180/std::numbers::pi<<" expected_pitch_degrees="<<expected*180/std::numbers::pi<<" pitch_delta_degrees="<<std::abs(pitch-expected)*180/std::numbers::pi<<" reprojection_error="<<errors.at(i)<<" depth_pass="<<(tv[i][2]>0)<<" facing_pass="<<(dot>0)<<" pitch_pass="<<(std::abs(pitch-expected)<=deg2rad(40))<<" rvec="<<rv[i]<<" tvec="<<tv[i]<<" normal_camera_ros="<<back.transpose()<<"\n";
  }
  RobustPnpSolution solver;solver.input.feature=cf;solver.input.armor2d=a;solver.input.fixed_outpost_pitch=config["pose_estimator"]["fixed_outpost_pitch"].as<bool>();solver.input.fixed_normal_pitch=config["pose_estimator"]["fixed_normal_pitch"].as<bool>();std::cout<<"original_robust_pnp_result="<<solver.solve()<<"\n";
 }
}
