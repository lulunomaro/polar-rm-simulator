#pragma once
// Build boundary only: fmt10 removed unscoped-enum's old implicit int mapping.
// Preserve its numeric formatting, not display names or algorithm semantics.
#include "tasks/auto_aim/armor.hpp"
#include <fmt/format.h>
template <>
struct fmt::formatter<auto_aim::ArmorName> : fmt::formatter<int> {
    template <typename FormatContext>
    auto format(auto_aim::ArmorName value, FormatContext& context) const {
        return fmt::formatter<int>::format(static_cast<int>(value), context);
    }
};
