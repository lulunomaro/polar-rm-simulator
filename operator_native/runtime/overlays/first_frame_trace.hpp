#pragma once
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <exception>
#include <atomic>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <openvino/runtime/compiled_model.hpp>
#include <openvino/runtime/properties.hpp>
#include <opencv2/core.hpp>

// Only this explicitly generated profile emits diagnostics. Never source time.
namespace rmcs::first_frame_trace {
inline constexpr const char* profile = "@PROFILE@";
inline constexpr unsigned max_records = 96;
struct Context { bool active=false; std::int64_t frame=-1, exposure=-1, control=-1; };
inline thread_local Context context;
inline thread_local bool first_tick_claimed=false;
inline thread_local unsigned emitted=0;
inline auto now_ns() noexcept -> long long {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}
inline void emit(const char* phase,const char* event,bool startup,long long stamp,long long elapsed=0,bool unwinding=false) noexcept {
    if(emitted>=max_records) return;
    ++emitted;
    char line[768];
    const auto frame=startup?-1:context.frame;
    const auto exposure=startup?-1:context.exposure;
    const auto control=startup?-1:context.control;
    int size;
    if(event[0]=='b')
        size=std::snprintf(line,sizeof(line),
            "[RMCS-FIRST-FRAME] {\"schema\":\"rmcs.first-frame-trace.v1\",\"profile\":\"%s\",\"phase\":\"%s\",\"event\":\"begin\",\"frame_id\":%lld,\"exposure_timestamp_ns\":%lld,\"control_time_ns\":%lld,\"linux_steady_ns\":%lld,\"clock_domain\":\"linux_steady_diagnostic_only\",\"startup\":%s}\n",
            profile,phase,static_cast<long long>(frame),static_cast<long long>(exposure),static_cast<long long>(control),stamp,startup?"true":"false");
    else
        size=std::snprintf(line,sizeof(line),
            "[RMCS-FIRST-FRAME] {\"schema\":\"rmcs.first-frame-trace.v1\",\"profile\":\"%s\",\"phase\":\"%s\",\"event\":\"end\",\"frame_id\":%lld,\"exposure_timestamp_ns\":%lld,\"control_time_ns\":%lld,\"linux_steady_ns\":%lld,\"clock_domain\":\"linux_steady_diagnostic_only\",\"startup\":%s,\"elapsed_ns\":%lld,\"exception_unwinding\":%s}\n",
            profile,phase,static_cast<long long>(frame),static_cast<long long>(exposure),static_cast<long long>(control),stamp,startup?"true":"false",elapsed,unwinding?"true":"false");
    if(size>0 && static_cast<unsigned>(size)<sizeof(line)) {
        std::fwrite(line,1,static_cast<std::size_t>(size),stderr);
        std::fflush(stderr); // Preserve begin even when the owned process times out.
    }
}
struct Scope {
    const char* phase; bool startup, enabled; long long began; int exceptions;
    explicit Scope(const char* name,bool initializing=false) noexcept
        : phase(name),startup(initializing),enabled(initializing||context.active),
          began(enabled?now_ns():0),exceptions(std::uncaught_exceptions()) {
        if(enabled)emit(phase,"begin",startup,began);
    }
    ~Scope() noexcept {
        if(enabled){const auto ended=now_ns();emit(phase,"end",startup,ended,ended-began,std::uncaught_exceptions()>exceptions);}
    }
    Scope(const Scope&)=delete; Scope& operator=(const Scope&)=delete;
};
struct FirstTick {
    bool enabled=false; long long began=0; int exceptions=0;
    void start(std::int64_t frame,std::int64_t exposure,std::int64_t control) noexcept {
        if(first_tick_claimed)return;
        first_tick_claimed=true; enabled=true; context={true,frame,exposure,control};
        began=now_ns();exceptions=std::uncaught_exceptions();emit("first_tick","begin",false,began);
    }
    ~FirstTick() noexcept {
        if(enabled){const auto ended=now_ns();emit("first_tick","end",false,ended,ended-began,std::uncaught_exceptions()>exceptions);context.active=false;}
    }
};

// Independent startup-only protocol. Never change compilation or issue a tick.
// Process-wide once, even if a caller accidentally repeats model initialization.
inline std::atomic_flag compiled_model_reported = ATOMIC_FLAG_INIT;
namespace compiled_properties {
inline auto quote(const std::string& value) -> std::string {
    if(value.size()>64)throw std::runtime_error("property_value_out_of_bounds");
    std::string result="\"";
    for(unsigned char c:value) {
        if(c<32 || c>126)throw std::runtime_error("property_value_out_of_bounds");
        if(c=='\"' || c=='\\')result+='\\';
        result+=static_cast<char>(c);
    }
    return result+'\"';
}
inline auto value_json(bool value) -> std::string { return value?"true":"false"; }
inline auto value_json(std::int32_t value) -> std::string {
    if(value < -1 || value>65536)throw std::runtime_error("property_value_out_of_bounds");
    return std::to_string(value);
}
inline auto value_json(ov::streams::Num value) -> std::string {
    return value_json(static_cast<std::int32_t>(value));
}
inline auto value_json(const std::vector<std::string>& values) -> std::string {
    if(values.empty() || values.size()>8)throw std::runtime_error("property_value_out_of_bounds");
    std::string result="[";
    for(const auto& value:values){if(result.size()>1)result+=',';result+=quote(value);}
    return result+']';
}
template<class T> inline auto value_json(const T& value) -> std::string {
    std::ostringstream stream;stream<<value;return quote(stream.str());
}
inline auto unknown(const char* reason) -> std::string {
    return std::string("{\"status\":\"unknown\",\"value\":null,\"reason\":\"")+reason+"\"}";
}
template<class Property> inline auto property_json(const ov::CompiledModel& model,
    const std::vector<ov::PropertyName>& supported,bool support_known,const Property& key) -> std::string {
    if(!support_known)return unknown("supported_properties_query_failed");
    bool found=false;for(const auto& name:supported)if(name==key.name()){found=true;break;}
    if(!found)return unknown("unsupported_property");
    try {
        return std::string("{\"status\":\"known\",\"value\":")+value_json(model.get_property(key))+",\"reason\":null}";
    } catch(...) { return unknown("property_query_or_value_failed"); }
}
}
inline void report_compiled_model(const ov::CompiledModel& model) noexcept {
    if(compiled_model_reported.test_and_set())return;
    static constexpr const char* prefix="[RMCS-COMPILED-MODEL] ";
    if(first_tick_claimed || context.active) {
        std::fprintf(stderr,"%s{\"schema\":\"rmcs.compiled-model-properties.v1\",\"profile\":\"%s\",\"startup\":false,\"native_ticks\":null,\"inference_calls\":null,\"clock_domain\":\"linux_steady_diagnostic_only\",\"linux_steady_ns\":%lld,\"properties\":null,\"cv_num_threads\":null,\"report_error\":\"report_not_startup\"}\n",prefix,profile,now_ns());
        std::fflush(stderr);return;
    }
    try {
        std::vector<ov::PropertyName> supported;bool support_known=false;
        try {supported=model.get_property(ov::supported_properties);support_known=true;}catch(...){}
        using compiled_properties::property_json;
        std::string properties="{";
        const auto add=[&](const char* name,const auto& key) {
            if(properties.size()>1)properties+=',';
            properties+=compiled_properties::quote(name)+':'+property_json(model,supported,support_known,key);
        };
        add("execution_devices",ov::execution_devices);
        add("inference_num_threads",ov::inference_num_threads);
        add("num_streams",ov::num_streams);
        add("performance_mode",ov::hint::performance_mode);
        add("inference_precision",ov::hint::inference_precision);
        add("enable_cpu_pinning",ov::hint::enable_cpu_pinning);
        add("scheduling_core_type",ov::hint::scheduling_core_type);
        properties+='}';
        std::string cv_threads;
        try {cv_threads=std::string("{\"status\":\"known\",\"value\":")+
            compiled_properties::value_json(static_cast<std::int32_t>(cv::getNumThreads()))+",\"reason\":null}";}
        catch(...) {cv_threads=compiled_properties::unknown("opencv_threads_query_failed");}
        std::string line=std::string(prefix)+"{\"schema\":\"rmcs.compiled-model-properties.v1\",\"profile\":"+
            compiled_properties::quote(profile)+",\"startup\":true,\"native_ticks\":0,\"inference_calls\":0,"+
            "\"clock_domain\":\"linux_steady_diagnostic_only\",\"linux_steady_ns\":"+std::to_string(now_ns())+
            ",\"properties\":"+properties+",\"cv_num_threads\":"+cv_threads+",\"report_error\":null}\n";
        if(line.size()>4096)throw std::runtime_error("compiled_report_size_limit");
        std::fwrite(line.data(),1,line.size(),stderr);std::fflush(stderr);
    } catch(...) {
        // Missing/failed properties never become an apparently known setting.
        std::fprintf(stderr,"%s{\"schema\":\"rmcs.compiled-model-properties.v1\",\"profile\":\"%s\",\"startup\":true,\"native_ticks\":0,\"inference_calls\":0,\"clock_domain\":\"linux_steady_diagnostic_only\",\"linux_steady_ns\":%lld,\"properties\":null,\"cv_num_threads\":null,\"report_error\":\"report_construction_failed\"}\n",prefix,profile,now_ns());
        std::fflush(stderr);
    }
}
}
