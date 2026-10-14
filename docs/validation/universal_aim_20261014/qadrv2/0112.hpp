#pragma once
// Production startup-only thread option. No diagnostic header or frame trace.
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <vector>
#include <opencv2/core.hpp>
#include <openvino/runtime/compiled_model.hpp>
#include <openvino/runtime/core.hpp>
#include <openvino/runtime/properties.hpp>
namespace rmcs::production_inference {
inline constexpr int requested_threads=@INFERENCE_THREADS@;
static_assert(requested_threads>=1 && requested_threads<=32);
inline std::atomic_flag configured=ATOMIC_FLAG_INIT;
inline std::atomic_flag reported=ATOMIC_FLAG_INIT;
inline void configure(ov::Core& core) {
    if(configured.test_and_set())throw std::runtime_error("production_inference_already_configured");
    // Exactly one explicitly hash-bound factor; AUTO selection is retained.
    core.set_property("CPU",ov::inference_num_threads(requested_threads));
}
inline void verify_and_report(const ov::CompiledModel& model) {
    if(reported.test_and_set())throw std::runtime_error("production_inference_already_reported");
    if(!configured.test())throw std::runtime_error("production_inference_not_configured");
    int actual=-1,streams=-1,cv_threads=-1;
    bool cpu=false,latency=false,f32=false,pinning=false,any_core=false;
    const char* error=nullptr;
    try {
        actual=model.get_property(ov::inference_num_threads);
        cpu=model.get_property(ov::execution_devices)==std::vector<std::string>{"CPU"};
        streams=static_cast<std::int32_t>(model.get_property(ov::num_streams));
        latency=model.get_property(ov::hint::performance_mode)==ov::hint::PerformanceMode::LATENCY;
        f32=model.get_property(ov::hint::inference_precision)==ov::element::f32;
        pinning=model.get_property(ov::hint::enable_cpu_pinning);
        any_core=model.get_property(ov::hint::scheduling_core_type)==ov::hint::SchedulingCoreType::ANY_CORE;
        cv_threads=cv::getNumThreads(); // Query only; never configure OpenCV.
        if(!cpu || actual!=requested_threads)error="production_inference_threads_not_effective";
        else if(streams!=1 || !latency || !f32 || !pinning || !any_core || cv_threads<1)
            error="production_inference_execution_property_mismatch";
    } catch(...) {error="production_inference_property_query_failed";}
    const auto stamp=std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
    // Fixed strings and bounded scalars only; one stderr record, no stdout change.
    char line[2048];
    const int size=std::snprintf(line,sizeof(line),
        "[RMCS-PRODUCTION-INFERENCE] {\"schema\":\"rmcs.production-inference-threads.v1\",\"startup\":true,\"native_ticks\":0,\"inference_calls\":0,\"clock_domain\":\"linux_steady_startup_only\",\"linux_steady_ns\":%lld,\"requested_threads\":%d,\"effective_threads\":%d,\"execution_cpu_only\":%s,\"num_streams\":%d,\"latency\":%s,\"f32\":%s,\"enable_cpu_pinning\":%s,\"any_core\":%s,\"cv_num_threads\":%d,\"error\":%s%s%s}\n",
        static_cast<long long>(stamp),requested_threads,actual,cpu?"true":"false",streams,
        latency?"true":"false",f32?"true":"false",pinning?"true":"false",any_core?"true":"false",cv_threads,
        error?"\"":"",error?error:"null",error?"\"":"");
    if(size<=0 || static_cast<std::size_t>(size)>=sizeof(line))throw std::runtime_error("production_inference_report_bound");
    if(std::fwrite(line,1,static_cast<std::size_t>(size),stderr)!=static_cast<std::size_t>(size)
        || std::fflush(stderr)!=0)throw std::runtime_error("production_inference_report_io");
    if(error)throw std::runtime_error(error);
}
}
