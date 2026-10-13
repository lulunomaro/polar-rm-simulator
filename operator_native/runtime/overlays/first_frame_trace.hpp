#pragma once
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <exception>

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
}
