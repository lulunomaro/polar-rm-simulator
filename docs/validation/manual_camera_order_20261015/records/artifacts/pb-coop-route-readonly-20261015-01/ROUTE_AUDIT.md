# Readonly route audit at simulator development commit83c595b

This is an implementation audit, not a new ROS, build, algorithm or match execution. PROJECT_PLAN.md SHA256 is299b58e785778ae143ff86808f333d2c6ff4e470a00d4dd9138ee1c7380a21fd. Existing running-process inventory contained only the two unrelated Python watchers, with no simulation, test, build or WSL task; they were left untouched.

The environment and production stack configuration referenced by the earlier PB actual3 still exist and have their original bytes:

- artifacts/pb-humble-ext4-runtime-20261014/ENVIRONMENT_COMPAT_FINAL.json: d60183ebf62d520c72eb20b84207fa4344d8f17183bb0df8eee92f97b7f981ee.
- artifacts/pb-navigation-sil-config-20261014-04.json: affba380753b6b8eac9505098fd0bf9d8a4457a4ec2892c09c80fb3da62d5c26.
- rm_match/integrations/pb_wsl_navigation.py: c41aadb017024f6f9b128c05f1db9e556317acdb6934b4f739c2c97b4abd2dd5.
- rm_match/integrations/pb_wsl_navigation_registry.py:1c6c08e6c513d024e092f295d22afec981ab078041c1687cb06e0f3680d7ab9d.

Linux binaries and environment paths were not rechecked by a Linux execution during this audit. The existing trusted preparation path rechecks them before any new actual start. The old real PointLIO/Nav2/PID30-second single-goal qualification remains historical, with its original input/action/consumption and cleanup boundaries.

The current PB registration is single-use, red_sentry only. It consumes original navigation-observation.v1 pointcloud/IMU and echoes original typed six identities, but its goal source is the separately owned ROS external-goal client. It does not implement generic decision_intent_v1 goal/hold/cancel semantics or provide continuous localization feedback to generic composition. It cannot simply be relabelled as an interchangeable generic decision/navigation plugin.

Decision v1 forces navigation/perception unavailable and invokes decision before navigation in the same original request deadline. The PB Odometry callback currently keeps only its maximum timestamp for status tagging. PointLIO's actual publish_odometry code simultaneously holds Measures.pb_context, odomAftMapped.pose and the original algorithm timestamp, but localization_event publishes only context+stamp. A future versioned producer event could preserve an actual LIO-native-frame pose with those original identities, calibration/profile and frozen producer/build/config provenance. It must be implemented and actually checked before being exposed as feedback.

Current map→odom/goal readiness TF queries use latest transforms; the SLAM map edge has no source scanning context. Do not interpolate/latest-match this edge and attach a current scan identity or rename a LIO-native estimate as a proven map pose. A full map-frame feedback chain requires actual source context from the SLAM callback and each real transform. Goal UUID/intent linkage is separate from localization source association.

Potential future generic feedback contract: retain current observation identity and include prior completed estimate's unchanged source identity, producer and original stamp; bounded same-robot/episode/binding cache, original host request known and150ms still valid, clear on release/rebind/fault/episode. No deadline refresh, simulator truth, fabricated quality/progress or automatic-fire permission. Keep old v1 unavailable until an explicitly negotiated v2 exists. No such code or new team-algorithm pass is claimed here.

Practical next validation is a genuine ordinary Qt keyboard/mouse operator on red_infantry alongside the existing separately sourced PB red_sentry navigation, after the manual-client stream-order defect is fixed. It will still be a partial two-robot scenario, not the PB match behavior tree or full3v3. Full traditional match decisions, map alignment, own-referee messages, moving aim, auto-fire, remaining four robots and complete-match evidence remain required.
