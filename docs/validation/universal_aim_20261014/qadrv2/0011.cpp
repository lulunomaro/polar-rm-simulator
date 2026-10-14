// Platform adaptation only: upstream algorithms must not contaminate JSONL.
#include "tools/logger.hpp"
#include <spdlog/sinks/stdout_color_sinks.h>
namespace tools {
std::shared_ptr<spdlog::logger> logger() {
    static auto value=[] {
        auto sink=std::make_shared<spdlog::sinks::stderr_color_sink_mt>();
        auto logger=std::make_shared<spdlog::logger>("native_aim",sink);
        logger->set_level(spdlog::level::warn);
        return logger;
    }();
    return value;
}
}
