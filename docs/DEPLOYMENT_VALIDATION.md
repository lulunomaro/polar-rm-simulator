# Deployment verification, 2026-10-13

The deployment source is implemented; full end-to-end live gameplay is **not qualified**. The machine-readable record is [DEPLOYMENT_VALIDATION.json](DEPLOYMENT_VALIDATION.json). Native build and five bounded native software-protocol checks are separate evidence in [NATIVE_BUILD_VALIDATION.json](NATIVE_BUILD_VALIDATION.json).

## Passed

- 28 deployment/JSONL synthetic tests: default own-T2-only catalog, source/build/model tamper rejection, pinned client setup planning, preserved venv invocation, failed doctor blocks launch, profile-ready handshake, custom process deadline/size/duplicate-key/timeout guards, no network config executable substitution.
- 161 existing selected synthetic contract/HTTP/ownership tests; the selection imported no MuJoCo.
- The original 190 extracted source blobs and one exact-function fixture remain unchanged; syntax/JSON/XML checks passed.
- Actual target-interpreter dependency imports, pinned clean external client checkout, actual rebuilt T2 spec and native shared-library lookup passed.
- Original-client Qt event loop, SIM transport, native catalog negotiation and red-sentry watch worked in an offscreen session. This does not establish visible UI or frame display.

The visible-launch doctor correctly reports blocked because this executor has no desktop display. It does not quietly substitute offscreen mode for the user's visible-client request.

## Failed / incomplete live path

Three short, fire-off live smoke attempts retained the same five-wall-second physics budget, camera budget 15 total FPS, 150 ms server input window and 80 ms native camera-age gate. The first two used an in-process test driver; the third used a separate operator process to resemble actual deployment. There were 240, 235 and 313 actual physics steps respectively, zero native requests/results/consumed gimbal commands, zero fire outputs, and clean shutdown. No attempt passed the predefined camera → native → physics criteria.

The timed attempts measured renderer startup at approximately 2.51 and 2.87 seconds. Their first render took approximately 1.27 and 1.56 seconds. On the process-isolated attempt, the frame was 2.62 seconds old at render completion and 2.88 seconds old after encoding, beyond even the 2.5-second display cache lifetime. No renderer exception was reported; that is not proof a timely frame arrived. Camera capture/drop counts and exact timings are in the JSON record.

The operator driver also observed sticky binding expiry/HTTP uncertainty. It did not retry uncertain controls or extend their deadlines. An early suspicion that the first episode reset caused this was disproved by source inspection and is not claimed as a fixed defect. The deployment server now publishes an initial authoritative state before announcing readiness, but this does not cure the measured rendering/timing limitation.

These runs support the negative conclusion that this host/configuration did not deliver a usable live native closed loop. They do not establish that the native algorithm failed, because no eligible image reached it through the live adapter. They also do not establish native aim quality, full-match behavior, Windows, another computer, LAN or hardware support.

## Reproduction

Run safe checks from the repository root:

```sh
python tools/verify_standalone.py
python tools/check_standalone_contracts.py
python -m unittest discover -s tests -p test_deployment.py -v
```

The explicit real smoke tool prints criteria without execution by default:

```sh
python tools/smoke_deployment.py --native-spec /absolute/operator_source.local.json --out /absolute/fresh-smoke
```

`--run` starts actual physics/camera/native software, claims only the red-sentry gimbal channel and never claims fire or motion. Add `--client-python` and `--client-root` together for the pinned client's offscreen spectator transport check. Use the simulator interpreter and native loader environment documented for the target machine, e.g. `MUJOCO_GL=egl`. The output must be new. It writes acceptance criteria before execution and preserves its result, timings and trace. It is a bounded diagnostic, not the default user launcher.

A separate OFFLINE modeled-latency result, if obtained later, must remain separately labeled. It cannot turn these live failures into passes or make the historical 24-exposure diagnostic the default deployment.
