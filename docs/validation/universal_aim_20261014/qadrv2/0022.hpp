#pragma once
#include "module/tracker/trackable.hpp"
#include "utility/pimpl.hpp"
#include "utility/serializable.hpp"

#include <optional>

#include <yaml-cpp/yaml.h>

namespace rmcs::kernel {

class FireController {
    RMCS_PIMPL_DEFINITION(FireController)

public:
    struct Config : util::Serializable {
        double bullet_speed;
        double shoot_delay;

        double offset_yaw   = 0.0;
        double offset_pitch = 0.0;

        // Optional known own-gun extrinsic for every ballistic aim branch.
        // Metres in barrel/PitchLink axes, NOT camera-to-muzzle displacement.
        double muzzle_offset_x = 0.0;
        double muzzle_offset_y = 0.0;
        double muzzle_offset_z = 0.0;

        double attack_window = 40.0;

        double degraded_angle_speed = 12.0;

        double window_redundancy = 0.8;
        double window_hysteresis = 0.2;

        double yaw_tolerance   = 0.07;
        double pitch_tolerance = 0.04;

        bool attack_preaim = false;
        double rune_idle_duration;
        double rune_shoot_duration;

        static constexpr std::tuple metas {
            // clang-format off
            &Config::bullet_speed, "bullet_speed",
            &Config::shoot_delay, "shoot_delay",
            &Config::offset_yaw, "offset_yaw",
            &Config::offset_pitch, "offset_pitch",
            &Config::attack_window, "attack_window",
            &Config::degraded_angle_speed, "degraded_angle_speed",
            &Config::window_redundancy, "window_redundancy",
            &Config::window_hysteresis, "window_hysteresis",
            &Config::yaw_tolerance, "yaw_tolerance",
            &Config::pitch_tolerance, "pitch_tolerance",
            &Config::attack_preaim, "attack_preaim",
            &Config::rune_idle_duration, "rune_idle_duration",
            &Config::rune_shoot_duration, "rune_shoot_duration",
            // clang-format on
        };

        // The legacy serializer requires every meta key. Keep the new geometry
        // optional without weakening required-key/type checks for old settings.
        template <typename Source>
        auto serialize(std::string_view prefix, const Source& source) noexcept
            -> std::expected<void, std::string> {
            auto required = make_serializable(metas).serialize(prefix, source, *this);
            if (!required) return required;
            const auto optional = [&](std::string_view key, double& value)
                -> std::expected<void, std::string> {
                const auto name = prefix.empty() ? std::string { key }
                    : std::format("{}.{}", prefix, key);
                try {
                    bool present;
                    if constexpr (requires { source.contains(name); }) {
                        present = source.contains(name);
                    } else if constexpr (requires { source.has_parameter(name); }) {
                        present = source.has_parameter(name);
                    } else if constexpr (std::same_as<std::remove_cvref_t<Source>, YAML::Node>) {
                        present = source[name].IsDefined();
                    } else {
                        static_assert(sizeof(Source) == 0, "Unsupported optional config source");
                    }
                    if (!present) { value = 0.0; return { }; }
                    auto result = util::SerializableSource<std::remove_cvref_t<Source>>::get(
                        source, name, value);
                    if (!result) return result;
                    if (!std::isfinite(value)) {
                        return std::unexpected { std::format("Nonfinite parameter '{}'", name) };
                    }
                    return { };
                } catch (const std::exception& e) {
                    return std::unexpected { std::format("Unable to read parameter '{}': {}", name, e.what()) };
                }
            };
            if (auto r = optional("muzzle_offset_x", muzzle_offset_x); !r) return r;
            if (auto r = optional("muzzle_offset_y", muzzle_offset_y); !r) return r;
            return optional("muzzle_offset_z", muzzle_offset_z);
        }

        template <typename Source>
        auto serialize(const Source& source) noexcept -> std::expected<void, std::string> {
            return serialize("", source);
        }
    };

    struct State {
        Timestamp timestamp = { };

        double yaw   = 0.;
        double pitch = 0.;

        double max_yaw_vel = 10.0;
        double max_yaw_acc = 200.0;
    };

    struct Aimed {
        double aim_yaw = 0;
        double pitch   = 0;

        bool shoot   = false;
        bool pre_aim = false;

        AimPoint target;
        Point3d center;
        Point3d attack;
    };

    explicit FireController(const Config&);

    auto update(State state) -> void;

    auto aim(const Trackable&) -> std::optional<Aimed>;
};

}
