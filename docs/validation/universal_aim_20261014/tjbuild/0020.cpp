// Neutral native compute protocol, not a team-specific platform admission path.
#include <Eigen/Geometry>
#include <nlohmann/json.hpp>
#include <openssl/sha.h>
#include <opencv2/core.hpp>
#include <yaml-cpp/yaml.h>
#include <chrono>
#include <cstdint>
#include <climits>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <set>
#include <sstream>
#include "tasks/auto_aim/yolos/yolov5.hpp"
#include "tasks/auto_aim/solver.hpp"
#include "tasks/auto_aim/tracker.hpp"
#include "tasks/auto_aim/planner/planner.hpp"
using J=nlohmann::json;
namespace fs=std::filesystem;
constexpr const char* SCHEMA="polar.native.aim-compute.v1";
constexpr std::size_t IMAGE_BYTES=1440u*1080u*3u;

J parse(const std::string& line) {
    std::vector<std::set<std::string>> keys;
    return J::parse(line,[&](int,J::parse_event_t event,J& value) {
        if(event==J::parse_event_t::object_start)keys.emplace_back();
        else if(event==J::parse_event_t::object_end)keys.pop_back();
        else if(event==J::parse_event_t::key && !keys.back().insert(value.get<std::string>()).second)
            throw std::runtime_error("duplicate_json_key");
        return true;
    });
}
void fields(const J& value,std::initializer_list<const char*> names) {
    if(!value.is_object() || value.size()!=names.size())throw std::runtime_error("packet_fields");
    for(auto name:names)if(!value.contains(name))throw std::runtime_error("packet_fields");
}
std::int64_t integer(const J& value) {
    if(!value.is_number_integer() || value.is_boolean())throw std::runtime_error("integer_type");
    if(value.is_number_unsigned() && value.get<std::uint64_t>()>static_cast<std::uint64_t>(INT64_MAX))
        throw std::runtime_error("integer_overflow");
    const auto result=value.get<std::int64_t>();if(result<0)throw std::runtime_error("negative_identity");return result;
}
double finite(const J& value) {
    if(!value.is_number() || value.is_boolean())throw std::runtime_error("number_type");
    const auto result=value.get<double>();if(!std::isfinite(result))throw std::runtime_error("nonfinite");return result;
}
bool read_line(std::string& line) {
    line.clear();char c;
    while(std::cin.get(c)) {
        if(c=='\n')return true;
        if(line.size()>=65535)throw std::runtime_error("native_line_bound");
        line+=c;
    }
    if(!line.empty())throw std::runtime_error("partial_native_eof");return false;
}
std::string digest(const std::vector<unsigned char>& content) {
    unsigned char hash[SHA256_DIGEST_LENGTH];SHA256(content.data(),content.size(),hash);
    std::ostringstream stream;stream<<std::hex<<std::setfill('0');
    for(auto byte:hash)stream<<std::setw(2)<<static_cast<unsigned>(byte);return stream.str();
}
std::vector<unsigned char> image_bytes(const J& image,const fs::path& root) {
    fields(image,{"path","sha256","width","height","stride_bytes","bytes"});
    if(integer(image["width"])!=1440 || integer(image["height"])!=1080
        || integer(image["stride_bytes"])!=4320 || integer(image["bytes"])!=IMAGE_BYTES)
        throw std::runtime_error("unsupported_image_geometry");
    const auto supplied=fs::path(image["path"].get<std::string>());
    if(!supplied.is_absolute() || supplied.lexically_normal()!=supplied)throw std::runtime_error("image_alias");
    for(auto cursor=supplied;!cursor.empty();) {
        if(fs::is_symlink(fs::symlink_status(cursor)))throw std::runtime_error("image_symlink");
        auto parent=cursor.parent_path();if(parent==cursor)break;cursor=parent;
    }
    if(supplied.parent_path()!=root || !fs::is_regular_file(supplied)
        || fs::file_size(supplied)!=IMAGE_BYTES)throw std::runtime_error("image_outside_owned_root");
    const auto before=fs::last_write_time(supplied);
    std::ifstream stream(supplied,std::ios::binary);std::vector<unsigned char> bytes(IMAGE_BYTES);
    stream.read(reinterpret_cast<char*>(bytes.data()),bytes.size());
    if(stream.gcount()!=static_cast<std::streamsize>(bytes.size()) || stream.peek()!=std::char_traits<char>::eof()
        || fs::last_write_time(supplied)!=before)throw std::runtime_error("image_changed_or_truncated");
    if(digest(bytes)!=image["sha256"].get<std::string>())throw std::runtime_error("image_sha_mismatch");return bytes;
}
void reply(const J& value) {
    const auto text=value.dump()+"\n";
    if(text.size()>65536 || std::fwrite(text.data(),1,text.size(),stdout)!=text.size() || std::fflush(stdout)!=0)
        throw std::runtime_error("native_stdout_failure");
}

class Runner {
    std::string config_path_;
    auto_aim::YOLOV5 yolo_;
    auto_aim::Solver solver_;
    std::unique_ptr<auto_aim::Tracker> tracker_;
    auto_aim::Planner planner_;
    double speed_threshold_,fast_delay_,slow_delay_;
    std::int64_t last_capture_=-1;
public:
    explicit Runner(const std::string& config):config_path_(config),yolo_(config,false),solver_(config),planner_(config) {
        const auto yaml=YAML::LoadFile(config);
        speed_threshold_=yaml["decision_speed"].as<double>();
        fast_delay_=yaml["high_speed_delay_time"].as<double>();slow_delay_=yaml["low_speed_delay_time"].as<double>();
        tracker_=std::make_unique<auto_aim::Tracker>(config,solver_);
    }
    J compute(const J& packet,const fs::path& image_root) {
        fields(packet,{"schema","op","frame_id","capture_ns","control_ns","image","gimbal_quaternion_wxyz","bullet_speed"});
        if(packet["schema"]!=SCHEMA || packet["op"]!="compute")throw std::runtime_error("native_schema_or_op");
        const auto frame=integer(packet["frame_id"]),capture=integer(packet["capture_ns"]),control=integer(packet["control_ns"]);
        if(control<capture || control-capture>80000000)throw std::runtime_error("original_capture_control_budget");
        if(capture<=last_capture_)throw std::runtime_error("duplicate_or_older_exposure");
        const auto& quaternion=packet["gimbal_quaternion_wxyz"];
        if(!quaternion.is_array() || quaternion.size()!=4)throw std::runtime_error("quaternion_shape");
        Eigen::Quaterniond q(finite(quaternion[0]),finite(quaternion[1]),finite(quaternion[2]),finite(quaternion[3]));
        if(std::abs(q.squaredNorm()-1.)>1e-6)throw std::runtime_error("quaternion_not_unit");
        const auto speed=finite(packet["bullet_speed"]);if(speed<10. || speed>25.)throw std::runtime_error("unsupported_bullet_speed");
        auto bytes=image_bytes(packet["image"],image_root);
        cv::Mat bgr(1080,1440,CV_8UC3,bytes.data());solver_.set_R_gimbal2world(q);
        auto armors=yolo_.detect(bgr,static_cast<int>(frame%INT32_MAX));
        const auto detected=armors.size();
        // Public source nanoseconds are represented by a time_point solely so
        // original Tracker/Target APIs can take their DIFFERENCES. Never feed
        // Linux now() to prediction or overwrite the original ns in outputs.
        const auto exposure=std::chrono::steady_clock::time_point(std::chrono::nanoseconds(capture));
        auto targets=tracker_->track(armors,exposure);
        auto_aim::Plan plan={false};
        if(!targets.empty()) {
            auto target=targets.front();
            const auto delay=std::abs(target.ekf_x()[7])>speed_threshold_?fast_delay_:slow_delay_;
            if(!std::isfinite(delay) || delay<0. || delay>1.)throw std::runtime_error("configured_delay_bound");
            target.predict(static_cast<double>(control-capture)/1e9+delay);
            // Original Target overload; optional<Target> overload uses OS now.
            plan=planner_.plan(target,speed);
        }
        last_capture_=capture;
        J result={{"schema",SCHEMA},{"op","compute"},{"ok",true},{"frame_id",frame},
            {"capture_ns",capture},{"control_ns",control},{"input_bgr_sha256",packet["image"]["sha256"]},
            {"detector_executed",true},{"detections",detected},{"targets",targets.size()},
            {"tracker_state",tracker_->state()},{"control",plan.control},{"would_fire",plan.control&&plan.fire},
            {"yaw_rad",nullptr},{"pitch_rad",nullptr},{"clock_policy","original_source_ns_differences"},
            {"reference_frame","stationary_capture_origin_inertial"}};
        if(plan.control) {
            if(!std::isfinite(plan.yaw) || !std::isfinite(plan.pitch))throw std::runtime_error("nonfinite_original_plan");
            result["yaw_rad"]=plan.yaw;result["pitch_rad"]=plan.pitch;
        }
        return result;
    }
};
int main(int argc,char** argv) {
    try {
        if(argc!=3)throw std::runtime_error("Usage: polar_native_aim CONFIG_YAML OWNED_IMAGE_ROOT");
        const auto image_root=fs::canonical(argv[2]);
        // Upstream TinyMPC error/debug cout becomes stderr; protocol uses C stdout.
        std::cout.rdbuf(std::cerr.rdbuf());
        Runner runner(fs::canonical(argv[1]).string());
        reply({{"schema",SCHEMA},{"op","ready"},{"ok",true},{"inference_calls",0}});
        std::string line;
        while(read_line(line)) {
            if(line.empty())throw std::runtime_error("empty_native_request");
            try {reply(runner.compute(parse(line),image_root));}
            catch(const std::exception& error) {std::cerr<<error.what()<<'\n';reply({{"schema",SCHEMA},{"op","compute"},{"ok",false},{"error","native_compute_failed"}});return 2;}
        }
    } catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}
}
