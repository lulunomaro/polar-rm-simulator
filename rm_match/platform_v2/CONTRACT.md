# Simulation platform v2: bounded interface checkpoint

## Scope and deployment

The v2 service and Python SDK are independent opt-in entry points. The existing operator Qt UI remains on v1. They share the existing simulator core but do not run two physics owners in one match. A single server thread owns physical stepping, collisions, referee state, robot registry and commands. HTTP and adapter workers cannot step physics.

This checkpoint listens only on 127.0.0.1. A proposed private LAN address is configuration metadata, not an enabled listener. Local three-session tests do not qualify cross-device networking. Before LAN activation, separately configure an approved interface, network exposure, server identity/TLS and admission/role policy; do not expose the loopback session-creation policy directly to a LAN. No firewall changes or persistent credentials are included. Session bearer capabilities live in memory and expire; the SDK never returns them from `open()` or prints them in its representation.

The match robot list comes from the loaded backend, not hard-coded network protocol IDs. The bundled backend still uses the current 3v3 scene and verified referee subset. General protocol IDs do not qualify another roster or competition ruleset.

## Session, ownership and arbitration

HTTP schema is `rm.sim.platform.v2`. POST /v2/sessions requires a credential matching a server-owned local `polar.sim.admission.v1` grant. The grant fixes role and operator robot IDs; spectator needs explicit audit authorization. No policy/credential means enrollment fails closed. Bodies cannot choose scopes, audit or trusted-admin privileges. Subsequent requests use the short-lived bearer in the Authorization header. See `server.py` and `docs/ADMISSION.md` for exact fields. Unknown or duplicate keys, unknown endpoints, browser Origin, redirects and oversized requests are rejected. Direct in-process ControlPlane sessions are a trusted administrative/test context unavailable through HTTP.

Robot watch/claim/bind/control/renew/release/window/adapter-input operations check the admitted scope independently of lease ownership. Operator roster/capabilities/catalog/state are scoped. Operator state has no coordinates/odometry, enemy dynamics or other-session commands/config/receipts. Operator frames use `operator_camera_display_v1`: actual JPEG, static K/D/optical-to-gimbal extrinsics, frame identity and original clocks, without capture own pose/odometry. Full spectator audit requires the audit grant. OfflineRuntime inherits both projections; only reviewed scheduler/lifecycle metadata is added. Internal sensor packets retain capture-time own sensors; ideal odometry/ranges remain an unresolved T09 boundary.

Each robot has independently leased `motion`, `gimbal`, and `fire` channels. Claim does not steal ownership. An occupied channel returns a conflict. A client can own one robot while a different client owns another; spectators can read cached state but cannot claim, control, bind, renew or release an operator channel. Read requests never renew leases. Closing/expiring one session affects only its channels.

Commands have a channel lease epoch, strictly increasing sequence and bounded server-receipt validity. Renewal does not restore an expired epoch or renew an old command. A lost response is uncertain: the SDK does not replay it or queue controls, and requires explicit reconnection before further control, renewal or binding. A server restart invalidates old bearer capabilities. Bindings require the corresponding live channel lease; binding navigation excludes manual motion, and binding aim excludes manual gimbal until explicitly unbound. Channel ownership cannot be acquired through an adapter result.

Navigation outputs only motion. Aim outputs only a gimbal target and optional informational fire permission. Fire remains a separate, explicit, current human/test command on the fire channel; the runtime does not convert an algorithm's `fire_permission` to a shot. Exceptions, stale results, invalid states, wrong robot/episode/binding or changed ownership fail closed for the affected channel. No automatic fallback policy secretly takes over.

## Algorithm lifecycle and sensor boundary

Registry IDs select server-registered factories; network config cannot name a Python import, executable or model path. Each robot independently binds one navigation and one aim instance. Lifecycle is `reset({episode, robot_id, binding_epoch})`, `act(observation)`, `close()`. Changing the binding or episode resets instance state. A slot has at most one running job plus one replaceable pending observation. A stuck worker cannot stall physics or allocate an unlimited chain of replacement threads; that slot may require process restart. An adapter exception requires an explicit rebind to recover.

This is a DTO/data-access boundary for reviewed adapters. Same-process Python adapters are not a security sandbox against malicious code. An untrusted third-party plugin needs a separately isolated process/container and explicit resource/access limits before deployment.

`polar.sim.observation.v2` contains only own-state/referee/sensor data. It has robot ID, episode, binding epoch, observation sequence, simulation seconds, and a server-monotonic completion deadline. Client clocks never authorize results. Own ideal joint sensors and own ideal odometry are declared simulation inputs; ranges are anonymous ideal simulated rays. Neither enemy poses, target IDs, segmentation, a world roster, nor simulator/model/data/judge objects are passed into adapters. The separate observer payload is marked `simulator_truth_display_only` and `algorithm_input=false`.

Missing camera or range sensing is an explicit `available=false` with a reason. No image, depth, IMU or LiDAR is fabricated to satisfy a capability. Only the existing own odometry/range sensors and optional calibrated image are implemented; additional sensor types need their own versioned contracts.

Coordinates are right-handed world metres with +Z up, +yaw counter-clockwise viewed from above. `base_link` is forward/left/up. Gimbal yaw is relative to the chassis; positive pitch points up. `camera_optical` is right/down/forward. Image metadata specifies packed rgb8/bgr8, width, height, stride, base64 bytes, focal lengths/principal point, Brown-Conrady five-coefficient distortion and optical-camera-to-gimbal transform (translation metres and xyzw unit quaternion). Its calibration identity and synthetic-camera provenance are explicit. Capture time and own joint pose/velocity plus odometry/velocity at exposure travel together; they are never replaced by delivery-time pose. The camera currently requires at most 8 MiB raw image bytes. No-GL backend camera is unavailable.

## Action semantics and capability levels

`polar.sim.action.v2` must echo the exact robot/episode/binding/observation/time envelope. The server checks deadline, current lease and physical state again immediately before applying it. An acknowledgement is not mechanical arrival.

Navigation's implemented output is `velocity_body`: base-frame vx/vy in m/s, each bounded to 1 with norm <=1, and yaw rate in rad/s bounded to 2. The existing rule adapter can consume an explicit world-point goal in its binding config and computes velocity using own odometry and rays. Goal-input capability is distinct from output capability. Dynamic goal topics, timed trajectories, ROS 2/Nav2 and arbitrary open-source integrations are not implemented merely because the registry exists; unknown action modes are rejected.

Aim's implemented output is `gimbal_target`: base-relative yaw and pitch radians, active flag, confidence (null if the algorithm supplies none), and informational fire permission. Physical joint limits are enforced by the backend. No fake detection confidence, lock box or automatic firing is synthesized. A stationary-only adapter is additionally inhibited by current requested or measured motion at the authority boundary, independently of its previous camera observation.

## Runnable examples

- `nav_rule_v1`: existing own-sensor A* navigation baseline; explicit world-point goal config.
- `nav_stop_test_v1`: zero-motion contract fixture; no navigation-performance claim.
- `aim_pixel_baseline_v1`: existing RGB red-blob baseline, deliberately not equivalent to the native detector/tracker; requires a calibrated image and own odometry.
- `aim_hold_test_v1`: own-angle latch fixture, no detection; available for no-GL arbitration tests.
- `aim_native_rmcs_v1`: opt-in trusted native process wrapper. A local administrator supplies the previously verified source spec and output directory to `default_registry`; HTTP binding only accepts bounded FOV numbers. The wrapper verifies the registered spec plus binary, executor configuration, algorithm configuration, model and runtime-mode hashes at registration/binding/startup, and camera calibration, uses serialized captured own-state and pixels, and never receives a simulator object. It is restricted to stationary red_sentry and has no fire authority. A frozen-image API replay is provided separately; it is not live-camera or multivehicle native qualification.

The two aim algorithms intentionally need not agree on one image. Labels and unavailable states must remain visible in future UI bindings. Replacing an adapter is not proof of equal algorithm quality.

## Reproduce CPU and adapter boundaries

From a checkout with the existing simulation dependencies:

```
python -m unittest rm_match.platform_v2.test_contracts rm_match.platform_v2.test_adapters rm_match.platform_v2.test_native_adapter rm_match.platform_v2.test_client
```

The native image-replay entry is `tools/platform_v2/verify_native_sensor_replay.py`. It requires caller-supplied trusted source spec, recorded original image and matching own-state/calibration frame record, and a new output directory. It reuses the frozen image at declared synthetic timestamps to test the interface. It does not alter the original image or source algorithm. The native process hash, image hash, script and wrapper identities must be retained with private execution evidence. No private images, execution records or host paths belong in a public client checkout.

## Revision 2 safety follow-up

An oversized response, forbidden redirect, malformed session/claim or mismatched command acknowledgement marks the SDK uncertain and blocks control/renewal/binding. Explicit HTTP rejection remains a known result. These guards and source-artifact hash tampering cases are CPU-tested. The earlier actual native frozen-image replay used revision 1; no new native inference or GPU qualification is implied for the added identity guards.

## Revision 3 native environment boundary

A native spec cannot override AUTOAIM_CONFIG, RMCS_HEADLESS_SHARE or ORT_DISABLE_TELEMETRY. Registration rejects these reserved keys and process construction reapplies the verified paths last. Other local environment and dynamically loaded libraries remain trusted administrator/OS inputs; hashing the declared binary/config/model files is not a complete malicious-process sandbox or a hash of every loaded library. The new guards are tested without executing native inference.
