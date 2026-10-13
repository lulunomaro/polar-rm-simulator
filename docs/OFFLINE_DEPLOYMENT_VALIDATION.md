# Bounded OFFLINE camera/client diagnostic, 2026-10-13

The second 24-exposure test displayed actual MuJoCo camera frames through the unchanged pinned Polar client's original Qt transport. Own T2 performed 13 model inferences after its original warmup. Both attempts produced zero accepted 3D poses and zero consumed native gimbal commands. This is useful transport evidence; native closed-loop aim quality remains failed in this scene.

See [the sanitized numeric record](OFFLINE_DEPLOYMENT_VALIDATION.json). The three failed five-second **live** attempts remain in [DEPLOYMENT_VALIDATION.md](DEPLOYMENT_VALIDATION.md); this OFFLINE result does not replace them or change the default profile.

## Exact scope and results

Both attempts used the same public analytic scene: red sentry at (-3.5, 3.0) m, blue infantry at (-1.2, 3.0) m, zero initial velocities, and the remaining original 3v3 scene unchanged. Chassis position is simulation setup only; target truth never enters the algorithm observation. The new clean-built T2 binary and pinned model/configuration were unchanged.

- OFFLINE001: 24 real captures, 471 physics steps, 13 native request/result pairs, zero accepted 3D poses, zero gimbal/fire consumption; no Qt frame decoded. The initial test driver did not retain the first transport failure cause.
- OFFLINE002: 24 real captures, 471 physics steps, 13 native pairs, 24 original-client frame admissions/decoded sequence transitions, no request errors, and clean lifecycle/resource shutdown. Still zero accepted 3D poses and zero gimbal/fire consumption. Runtime took about 22.1 wall seconds for 0.942 simulated seconds.
- The second harness initialized decoder dependencies before transport admission and waited for acknowledged watch, state and catalog before binding the operator. It also recorded bounded transport diagnostics. Neither the original client nor simulator/native algorithm source was patched, and the first failure's precise cause remains unproven.

The second run retained detailed frame admission rows for IDs 3–24 at server-reported ages 0.228–0.512 seconds. Its counter and sequence transitions establish all 24 admissions, but the 128-call ring overwrote the first two detailed rows. Only the first decoded BGR hash was recorded. These are not independently recomputed pixels or a claim of 24 retained per-frame hashes.

The camera's 2.5-second display lifetime, five-second camera/native barrier watchdog, 90-second whole-attempt limit, and original modeled timing were unchanged: capture period 40 ms, sensor delay 10 ms, compute delay 10 ms, maximum native simulated age 80 ms. Renderer initialization completed before admission, bounded at 10 seconds, without capture, physics or inference. No timestamp was refreshed to disguise an old frame. OFFLINE simulation barriers differ from live wall-clock deadlines.

## Why aim is still blocked

A separate saved-frame diagnostic invoked the same model once and detected BLUE INFANTRY_3 at confidence 0.884. The unchanged saved synthetic frame, original failure record, gate/projection evidence and bounded replay helpers are in [the saved-frame diagnostic packet](validation/pnp_saved_frame_20261013/README.md). Both IPPE candidates had positive depth and passed facing checks. Their pitches were -36.015 and +59.060 degrees, outside the original allowed interval [-25, 55], so the unmodified estimator correctly returned zero 3D poses.

The detected light-bar corners span about 37 pixels vertically. The source's 135 × 56 mm object points project to about 54.51 pixels, matching the approximately 54-pixel rendered bars. Corner ordering, image scaling, ROI, camera association and clipping checks did not reveal a conversion bug. The 55 mm diffuser versus 56 mm source approximation is too small to explain this difference. Learned corner localization on the uncalibrated synthetic optics is the observed failure location; no model, scene, threshold or gate was tuned to hide it.

## Reproduce on another Linux machine

First follow [DEPLOYMENT.md](DEPLOYMENT.md) to obtain the pinned external client, install the simulator and client dependencies, and build the own-T2 native runtime locally. Use the resulting consumer-local spec. Native shared libraries must be discoverable through the installed runtime or its documented loader environment. A visible desktop is unnecessary for this explicitly offscreen diagnostic. Linux EGL rendering must work; Windows and another computer have not been qualified by these results.

From the simulator repository root, inspect the side-effect-free plan:

```sh
python tools/smoke_offline_deployment.py
```

Run exactly one explicitly bounded diagnostic with paths adjusted to your local environment:

```sh
.venv-sim/bin/python tools/smoke_offline_deployment.py --run \
  --native-spec operator_native/runtime/local_build/operator_source.local.json \
  --client-root external/polar-rm-client \
  --client-python .venv-client/bin/python \
  --out runs/offline24-001
```

The output directory must not already exist. The helper refuses a wrong native source/model/build identity or changed pinned client tracked source. It does not install packages, change algorithm gates, grant firing/motion authority, or repeat a failed control request. It starts the original client Qt event loop offscreen, waits for watch admission, and records the scene, native/physics ledger, client diagnostics, timings and cleanup.

Exit 0 means the bounded diagnostic's camera/display/native-request transport criteria passed. Inspect `qualified_static_offline_chain` separately: it remains false when no active native target reaches physics, including the recorded scene here. Neither exit status qualifies live gameplay, aim accuracy or a full match.

The published portable wrapper is a parameterization of the executed local harness. It was syntax/CLI-checked and covered by synthetic report/probe tests after OFFLINE002, without another physics run. The original tested driver/probe bytes are retained. Reproduction logs may contain local paths and ephemeral session identifiers; review/sanitize them before sharing publicly.

Synthetic checks:

```sh
python -m unittest discover -s tests -p test_offline_deployment_smoke.py -v
python -m unittest discover -s tools/offline_smoke -p test_transport_probe.py -v
```
