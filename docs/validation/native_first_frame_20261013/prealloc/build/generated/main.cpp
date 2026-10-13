#include "first_frame_trace.hpp"
// Rebuilt synchronous offline adapter v2. Not the lost historical headless runner.
// Algorithm translation units are compiled unchanged. This file extracts the
// armor-only AutoAim/component orchestration and replaces ROS scheduling/IO.
#include "adapter_clock.hpp"
#include "kernel/detector.hpp"
#include "kernel/pose_estimator.hpp"
#include "kernel/tracker.hpp"
#include "kernel/fire_control.hpp"
#ifdef REBUILD_CANDIDATE
#include "kernel/command_safety.hpp"
#endif
#include <opencv2/imgcodecs.hpp>
#include <opencv2/calib3d.hpp>
#include <algorithm>
#include <eigen3/Eigen/Geometry>
#include <yaml-cpp/yaml.h>
#include <array>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>

using namespace rmcs;
using namespace rmcs::kernel;
namespace {
auto stamp(std::int64_t ns) -> Timestamp { return headless::timestamp_from_ns(ns); }

auto num(double v) -> std::string {
    if (!std::isfinite(v)) return "null";
    std::ostringstream s; s << std::setprecision(17) << v; return s.str();
}
auto escaped(const std::string& x) -> std::string {
    std::string out="\"";
    for (unsigned char c : x) {
        if (c=='"' || c=='\\') { out+='\\'; out+=static_cast<char>(c); }
        else if (c=='\n') out+="\\n";
        else if (c=='\r') out+="\\r";
        else if (c=='\t') out+="\\t";
        else if (c>=32) out+=static_cast<char>(c);
    }
    return out+'"';
}
auto vec(const Point3d& p) -> std::string {
    return '['+num(p.x)+','+num(p.y)+','+num(p.z)+']';
}
auto required_file(const YAML::Node& n, const char* key) -> std::filesystem::path {
    auto p=std::filesystem::absolute(n[key].as<std::string>());
    if (!std::filesystem::is_regular_file(p)) throw std::runtime_error("Missing input file: "+p.string());
    return p;
}

class Runner {
    Detector detector;
    PoseEstimator estimator;
    std::unique_ptr<Tracker> tracker;
    std::unique_ptr<FireController> fire;
    Trackable::Unique current;
    Eigen::Quaterniond gimbal=Eigen::Quaterniond::Identity();
    Eigen::Vector3d gyro=Eigen::Vector3d::Zero();
    Timestamp gimbal_stamp{}, last_velocity_stamp{};
    double max_yaw_vel=3., max_yaw_acc=100., last_velocity=kNaN;
    std::int64_t last_control_ns=-1;
    bool tracking=false, shooting=false;
    Point3d direction=Point3d::kNaN(), center=Point3d::kNaN();
    std::uint64_t inference_calls=0;
    bool manual_shoot=false;
    bool fov_initialized=false;
    std::array<double,3> operator_fov{};
#ifdef REBUILD_CANDIDATE
    std::string runtime_mode_contents;
    ObservationOrder submitted, consumed, processed;
    ObservationResultGate results;
#endif
public:
    Runner(const std::filesystem::path& executor_path, const std::filesystem::path& config_path) {
        auto cfg=YAML::LoadFile(config_path.string());
        auto exec=YAML::LoadFile(executor_path.string())["auto_aim_component"]["ros__parameters"];
        if (!exec) throw std::runtime_error("Missing auto_aim_component.ros__parameters");
        if (cfg["virtual_rune"] && cfg["virtual_rune"]["enable"].as<bool>())
            throw std::runtime_error("This rebuilt benchmark adapter supports armor only; virtual_rune must be false");
        auto model=std::filesystem::path(cfg["detector"]["model_location"].as<std::string>());
        if (model.is_relative()) model=config_path.parent_path()/model;
        if (!std::filesystem::is_regular_file(model)) throw std::runtime_error("Model file is missing: "+model.string());
        cfg["detector"]["model_location"]=std::filesystem::absolute(model).string();
        if (auto r=detector.initialize(cfg["detector"]); !r) throw std::runtime_error(r.error());
        if (auto r=estimator.initialize(cfg["pose_estimator"]); !r) throw std::runtime_error(r.error());
#ifdef REBUILD_CANDIDATE
        {
            std::ifstream mode("./tracking_mode",std::ios::binary);
            runtime_mode_contents=std::string(std::istreambuf_iterator<char>(mode),{});
            if (runtime_mode_contents!="multi_ekf\n") throw std::runtime_error("Candidate benchmark requires exact tracking_mode contents multi_ekf\\n");
        }
        tracker=std::make_unique<Tracker>(cfg["tracker"], "./tracking_mode");
#else
        tracker=std::make_unique<Tracker>(cfg["tracker"]);
#endif
        FireController::Config fc{};
        if (auto r=fc.serialize(exec["fire_control"]); !r) throw std::runtime_error(r.error());
        fire=std::make_unique<FireController>(fc);
        manual_shoot=exec["manual_shoot"].as<bool>();
        if (manual_shoot) throw std::runtime_error("Benchmark requires manual_shoot=false; no operator intent is simulated");
        detector.update_detect_rune(false);
        tracker->update_aim_intent(true);
        tracker->update_aim_cleanup(true);
        tracker->update_track_genre(DeviceIds::Full());
    }

    auto tick(const YAML::Node& request) -> std::string {
        rmcs::first_frame_trace::FirstTick diagnostic_tick;
        const auto control_ns=request["control_time_ns"].as<std::int64_t>();
        const double t=request["time_s"].as<double>();
        if (control_ns<0 || control_ns<last_control_ns)
            throw std::runtime_error("control_time_ns must be nonnegative and monotonic");
        if (!std::isfinite(t) || std::abs(t-static_cast<double>(control_ns)/1e9)>0.5e-9)
            throw std::runtime_error("Human-readable time_s disagrees with control_time_ns");
        last_control_ns=control_ns; Clock::injected=stamp(control_ns);
#ifdef REBUILD_CANDIDATE
        {
            std::ifstream mode("./tracking_mode",std::ios::binary);
            if (std::string(std::istreambuf_iterator<char>(mode),{})!=runtime_mode_contents)
                throw std::runtime_error("Candidate tracking_mode changed during episode");
        }
#endif
        // Simulation operator fork: FOV changes require a fresh process/track state.
        const auto af=request["operator_fov"];
        if (!af || !af.IsMap() || af.size()!=3) throw std::runtime_error("operator_fov required");
        const std::array<double,3> requested_fov{af["fov_degrees"].as<double>(),af["circle_radius_x_norm"].as<double>(),af["circle_radius_y_norm"].as<double>()};
        for (double v : requested_fov) if (!std::isfinite(v)) throw std::runtime_error("Nonfinite operator FOV");
        if (requested_fov[0]<10. || requested_fov[0]>180. || requested_fov[1]<=0. || requested_fov[1]>2. || requested_fov[2]<=0. || requested_fov[2]>2.)
            throw std::runtime_error("Operator FOV outside contract");
        if (fov_initialized && requested_fov!=operator_fov) throw std::runtime_error("FOV changed: restart source process to clear tracks");
        operator_fov=requested_fov; fov_initialized=true;
        std::size_t fov_admitted2d=0, fov_rejected2d=0;
        bool detector_executed=false, frame_accepted=false, completed=false;
        [[maybe_unused]] bool observed_now=false;
        std::string stats="null";
        std::size_t pose_estimated3d=0;
        [[maybe_unused]] std::size_t raw2d=0;
        double result_exposure=kNaN;
        const auto f=request["frame"];
        if (f && !f.IsNull()) {
            if (f["schema"].as<std::string>()!="rmcs-mujoco-actor-frame-v1") throw std::runtime_error("Unsupported frame schema");
            const auto exposure_ns=f["exposure_timestamp_ns"].as<std::int64_t>();
            diagnostic_tick.start(f["frame_id"].as<std::int64_t>(),exposure_ns,control_ns);
            const auto exposure=Timestamp{std::chrono::duration_cast<Duration>(std::chrono::nanoseconds{exposure_ns})};
            bool admit=true;
#ifdef REBUILD_CANDIDATE
            admit=submitted.accept(exposure,Clock::now()) && consumed.accept(exposure,Clock::now());
#endif
            if (admit) {
                const auto own=f["own"];
                const auto q=own["pitchlink_to_world_quaternion_wxyz"].as<std::array<double,4>>();
                gimbal=Eigen::Quaterniond(q[0],q[1],q[2],q[3]);
                if (!gimbal.coeffs().allFinite() || std::abs(gimbal.norm()-1.)>1e-6) throw std::runtime_error("Exposure quaternion must be unit and finite");
                const auto w=own["pitchlink_angular_velocity_local_rad_s"].as<std::array<double,3>>();
                gyro=Eigen::Vector3d(w[0],w[1],w[2]); gimbal_stamp=exposure;
#ifdef REBUILD_CANDIDATE
                admit=processed.accept(exposure,Clock::now());
#endif
            }
            if (admit) {
                frame_accepted=true;
                const auto im=f["image"];
                if (im["encoding"].as<std::string>()!="bgr8" || im["width"].as<int>()!=1440 || im["height"].as<int>()!=1080
                    || im["stride_bytes"].as<int>()!=4320 || im["bytes"].as<int>()!=4665600)
                    throw std::runtime_error("CameraFrame contract requires bgr8 1440x1080");
                cv::Mat image;
                {
                rmcs::first_frame_trace::Scope phase("actual_bgr_read");
                auto image_path=required_file(im,"path");
                if (image_path.extension()==".bgr" || image_path.extension()==".raw") {
                    image=cv::Mat(1080,1440,CV_8UC3);
                    std::ifstream in(image_path,std::ios::binary);
                    in.read(reinterpret_cast<char*>(image.data),1080*1440*3);
                    if (in.gcount()!=1080*1440*3) throw std::runtime_error("Incomplete raw BGR frame");
                } else image=cv::imread(image_path.string(),cv::IMREAD_COLOR);
                if (image.empty() || image.cols!=1440 || image.rows!=1080) throw std::runtime_error("Invalid decoded frame dimensions");
                }
                const auto c=f["camera"];
                const std::array<double,9> K{c["fx"].as<double>(),0.,c["cx"].as<double>(),0.,c["fy"].as<double>(),c["cy"].as<double>(),0.,0.,1.};
                const auto D=c["distortion"].as<std::array<double,5>>();
                detector.update_camera(K); detector.update_camera(D);
                estimator.configure_camera(K,D); tracker->update_camera(K); tracker->update_camera(D);
                const auto trans=f["own"]["camera_position_pitchlink_m"].as<std::array<double,3>>();
                Transform iso{}; iso.orientation=Orientation{gimbal};
                iso.translation=Translation{gimbal*Eigen::Vector3d(trans[0],trans[1],trans[2])};
                const auto team=f["own_team"].as<std::string>();
                if (team!="red" && team!="blue") throw std::runtime_error("own_team must be red or blue");
                const auto enemy=team=="red" ? CampColor::BLUE : CampColor::RED;
                detector.update_detect_color(enemy); tracker->update_track_color(enemy);
                auto detections=[&] { rmcs::first_frame_trace::Scope phase("detector"); return detector.detect(image); }(); detector_executed=true; ++inference_calls;
                raw2d=detections.armors.size();
                // Gate actual detector output before source PnP/association/selection.
                // This sees camera pixels and calibration only, never enemy truth.
                std::erase_if(detections.armors,[&](const auto& armor) {
                    const auto point=armor.center;
                    if (!std::isfinite(point.x) || !std::isfinite(point.y) || point.x<0 || point.y<0 || point.x>=image.cols || point.y>=image.rows) return true;
                    const double dx=(point.x-image.cols*.5)/(operator_fov[1]*image.cols);
                    const double dy=(point.y-image.rows*.5)/(operator_fov[2]*image.rows);
                    if (dx*dx+dy*dy>1.+1e-12) return true;
                    std::vector<cv::Point2f> pixel{point},normalized;
                    cv::undistortPoints(pixel,normalized,cv::Mat(3,3,CV_64F,const_cast<double*>(K.data())),cv::Mat(1,5,CV_64F,const_cast<double*>(D.data())));
                    if (normalized.size()!=1 || !std::isfinite(normalized[0].x) || !std::isfinite(normalized[0].y)) return true;
                    const double angle=std::atan(std::hypot(normalized[0].x,normalized[0].y))*180./std::acos(-1.);
                    return angle>operator_fov[0]*.5+1e-12;
                });
                fov_admitted2d=detections.armors.size(); fov_rejected2d=raw2d-fov_admitted2d;
                estimator.update_camera_transform(iso);
                auto armors3d=[&] { rmcs::first_frame_trace::Scope phase("pose_estimation"); return estimator.estimate_armor(detections.armors,image); }(); pose_estimated3d=armors3d.size();
                tracker->update_camera(iso);
#ifdef REBUILD_CANDIDATE
                tracker->update_image_size(image.cols,image.rows);
#endif
                Trackable::Unique incoming;
                {
                rmcs::first_frame_trace::Scope phase("tracker");
                tracker->clean(); tracker->store(detections.armors); tracker->store(armors3d);
                tracker->store(detections.lightbars); tracker->store(detections.icons); tracker->store(detections.bullseyes);
                incoming=tracker->execute(exposure);
                }
#ifdef REBUILD_CANDIDATE
                const auto fs=tracker->frame_stats();
                stats="{\"raw2d\":"+std::to_string(fs.raw2d)+",\"accepted2d\":"+std::to_string(fs.accepted2d)+",\"accepted3d\":"+std::to_string(fs.accepted3d)+",\"rejected_color\":"+std::to_string(fs.rejected_color)+",\"rejected_genre\":"+std::to_string(fs.rejected_genre)+",\"rejected_margin\":"+std::to_string(fs.rejected_margin)+",\"rejected_clipped\":"+std::to_string(fs.rejected_clipped)+"}";
                observed_now=tracker->observed_selected_target();
                if (!observed_now) incoming.reset();
                completed=true; result_exposure=static_cast<double>(exposure_ns)/1e9;
                accept_observation_result(results,current,exposure,observed_now,incoming,Clock::now());
#else
                // The upstream AutoAim only publishes nonempty trackables.
                if (incoming) { current=incoming->clone(); completed=true; result_exposure=static_cast<double>(exposure_ns)/1e9; }
                stats="{\"raw2d\":"+std::to_string(raw2d)+",\"accepted2d\":null,\"accepted3d\":null}";
#endif
            }
        }
        if (gimbal_stamp!=Timestamp{} && gimbal_stamp!=last_velocity_stamp) {
            const double velocity=(gimbal*gyro).z();
            if (std::isfinite(velocity)) {
                max_yaw_vel=std::max(max_yaw_vel,std::abs(velocity));
                if (std::isfinite(last_velocity)) {
                    const double dt=std::chrono::duration<double>(gimbal_stamp-last_velocity_stamp).count();
                    if (dt>1e-6) max_yaw_acc=std::max(max_yaw_acc,std::abs((velocity-last_velocity)/dt));
                }
                last_velocity_stamp=gimbal_stamp; last_velocity=velocity;
            }
        }
        const auto dir=gimbal*Eigen::Vector3d::UnitX();
        const FireController::State state{.timestamp=Clock::now(),.yaw=std::atan2(dir.y(),dir.x()),.pitch=std::atan2(-dir.z(),std::hypot(dir.x(),dir.y())),.max_yaw_vel=max_yaw_vel,.max_yaw_acc=max_yaw_acc};
#ifdef REBUILD_CANDIDATE
        auto control=[&] { rmcs::first_frame_trace::Scope phase("control"); return safe_control_tick(*fire,current,state,results.shoot_allowed()); }();
        tracking=control.should_track; shooting=control.aimed.shoot; direction=control.aimed.target; center=control.aimed.center;
#else
        using namespace std::chrono_literals;
        if (current && Clock::now()-current->get_timestamp()>100ms) {
            current.reset(); tracking=false; shooting=false; direction=Point3d::kNaN(); center=Point3d::kNaN();
        }
        if (current) {
            fire->update(state);
            if (auto aim=fire->aim(*current)) { tracking=true; shooting=aim->shoot; direction=aim->target; center=aim->center; }
        }
#endif
        rmcs::first_frame_trace::Scope phase_serialize("stdout_serialize");
        const double age=current ? std::chrono::duration<double>(Clock::now()-current->get_timestamp()).count() : kNaN;
        std::ostringstream out;
        out << "{\"status\":\"ok\",\"runner_identity\":\"rmcs-sim-operator-fov-v1\",\"time_s\":" << num(t) << ",\"clock_time_ns\":" << headless::nanoseconds_from_timestamp(Clock::now())
            << ",\"tracking\":" << (tracking?"true":"false") << ",\"should_shoot\":" << (shooting?"true":"false")
            << ",\"direction\":" << vec(direction) << ",\"direction_frame\":\"world\",\"robot_center\":" << vec(center)
            << ",\"detector_executed\":" << (detector_executed?"true":"false") << ",\"inference_calls\":" << inference_calls
            << ",\"frame_accepted\":" << (frame_accepted?"true":"false") << ",\"frame_stats\":" << stats
            << ",\"fov_raw2d\":" << raw2d << ",\"fov_admitted2d\":" << fov_admitted2d << ",\"fov_rejected2d\":" << fov_rejected2d
            << ",\"pose_estimated3d\":" << pose_estimated3d << ",\"target_age_s\":" << num(age)
            << ",\"completed_result_event\":" << (completed?"true":"false") << ",\"result_exposure_time_s\":" << num(result_exposure);
#ifdef REBUILD_CANDIDATE
        out << ",\"completed_result_observed_now\":" << (observed_now?"true":"false")
            << ",\"observation_shoot_allowed\":" << (results.shoot_allowed()?"true":"false")
            << ",\"runtime_mode_observed_config\":\"multi_ekf\",\"runtime_mode_state_api\":null";
#else
        out << ",\"completed_result_observed_now\":null,\"observation_shoot_allowed\":null";
#endif
        return out.str()+"}";
    }
};
}

int main(int argc,char** argv) {
    try {
        if (argc!=2) throw std::runtime_error("Usage: rmcs_rebuild_<variant> EXECUTOR_YAML (AUTOAIM_CONFIG required)");
        const char* config=std::getenv("AUTOAIM_CONFIG");
        if (!config || !*config) throw std::runtime_error("AUTOAIM_CONFIG is required");
        Runner runner(std::filesystem::absolute(argv[1]),std::filesystem::absolute(config));
        std::string line;
        while (std::getline(std::cin,line)) {
            if (line.empty()) continue;
            try { std::cout << runner.tick(YAML::Load(line)) << std::endl; }
            catch (const std::exception& e) { std::cout << "{\"status\":\"error\",\"error\":" << escaped(e.what()) << "}" << std::endl; return 2; }
        }
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
