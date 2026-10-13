# Final default contour-v3 native control and cleanup check

The final default contour-v3 clean build passed one actual OFFLINE24 execution
after the native cancellation/resource repair was frozen. This is the current
static-chain evidence. Earlier holdout failures and the prior successful
`../pnp_contour_v3_static_chain_20261013` execution remain unchanged.

The run completed 24 rendered raw sensor exposures, 13 native request/result
pairs, 471 actual physics steps and 241 active native gimbal steps. All 13 native
responses contained one accepted pose, original multi-EKF tracking and
`should_control=true`, with target age 0.02 simulation seconds. All 241 active
steps wrote the exact native-derived target into the actuator controls and
changed actual gimbal joints. Request/result frame, image hash, own capture
state and modeled schedule bindings matched. Original confidence/model/PnP
gates were preserved; only the explicitly identified contour-v3 frontend is new.

The original fire controller reported `should_shoot=true` in 7 of 13 responses.
Adapter fire permission was false, and actual physics fire actions were zero.
The actual pinned Qt client admitted a fresh rendered display frame, maintained
healthy transport and acknowledged session closure. Both transport and static
native control qualifications passed; realtime and full-match flags remain false.

Cleanup was measured locally, rather than inferred from a terminal state:

- `shutdown_status.clean=true`, with no unfinished slots or lifecycle errors.
- The shared 1.5-second join budget took 0.01395047 seconds.
- The offline worker thread ended and released its adapter instance.
- The actual native child PID 1216 exited with return code -15 (SIGTERM), and
  stdin/stdout pipes were closed. There was no lingering native child.
- Runtime error was null and the execution recorded no errors.

`EXECUTED_SOURCE.json` recorded ten simulator/driver dependency hashes before
renderer, Qt client and runtime creation. The runner rechecked those hashes
after shutdown; all remained unchanged. `CHAIN_REPORT.json` binds that check,
all native result counts, actual first/last physics samples, preload admission
and raw execution evidence hashes. `NATIVE_RESULTS.json` preserves all 13 native
responses. `SOURCE_BUILD_BINDING.json`, copied `BUILD_MANIFEST.json` and
`PREPARED_INPUTS.json` bind the final clean build to its actual source/model inputs.

The final spec SHA is
`a808f11e8f8088ba89c2cf2a8e94d4bf18c386dc69d3d4114b9b2b40e57a3cdd`.
The ELF SHA is
`4d3570674a7a150da0e86f64bbbd25adcfa8bb9e2731672ac6aeaa296cf92b42`.
The original model SHA remains
`b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255`.
The client used reviewed patch
`91e3653df439289e25d64eb334f9c6f6a73e0c4aa8e3615ce968010e3b1860ee`.
The frozen contour-v3 overlay SHA remains
`0a90e0089a2531a476091d75c3085a6d26a843feba7c0f5cd429ea2928aa812c`.

Native packets use actual MuJoCo-rendered pixels converted to BGR, original
camera K/D and own capture state. Source inspection verifies target truth and
geometric corners are not included. The complete input packet bytes were not
independently archived for every exposure. Source calibration/resolution
association remains an assumption, with no physical optical calibration claim.
The independent holdout's far-3.85 m original-model miss remains a documented
coverage limitation. This fixed-scene software-rendered offline execution does
not establish realtime performance, aim quality, full-match behavior, hardware,
visible desktop or cross-machine qualification. Normal cleanup is demonstrated;
the actual SIGTERM-ignore cancellation case is covered separately by the resource
repair's POSIX lifecycle regression, not injected into this successful camera run.

Actual execution: `artifacts/pnp-native-contour-v3-aftercleanup-offline24-20261013`.
Reproduce with a new output directory in WSL/Linux:

```sh
.venv-linux/bin/python tools/smoke_offline_deployment.py \
  --native-spec artifacts/native-contour-v3-final-default-build/operator_source.local.json \
  --client-root external/polar-rm-client-state-review \
  --client-python /absolute/project/.venv-linux/bin/python \
  --out artifacts/fresh-aftercleanup-static-chain --run
```
