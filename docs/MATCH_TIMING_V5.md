# Full-match timing v5

This is an offline MuJoCo 3v3 sporting simulation, not a real-robot match. It is a separately named integration demo, not the distance/DR benchmark and not a claim of full official competition conformity.

The red sentry alone runs the frozen repaired RMCS actor from commit `40f7af130d076bcabab98613bd66745f81c7f643`, binary SHA256 `70ad294ff8be702804ebd1e3f98048d0a13b9e74894d8b28615886a83eda0fcb`. Its actual detector, PnP, EKF and fire controller receive camera pixels, calibration and exposure-time own pose. Other five robots keep the existing color-pixel baseline. No opponent weakening or target-truth aiming is added.

Physics uses 2000Hz integer steps. During stationary source segments, capture is 80Hz; the latest captured frame is consumed at rational 36Hz opportunities on 100Hz control ticks. Each delivered native 1440x1080 frame is saved losslessly. Unselected captured frames are not retained. Control time is exact integer nanoseconds and native clock echo must match. Source IMU/gimbal pose is still the exposure pose. Current-muzzle native backports are not included.

Only ordinary fire True/False is delayed 40ms. Safety is evaluated every 0.5ms: motion, drift, lease expiry, missing observations, tracking loss, own death/weakness, emergency stop, pause, terminal, disconnection, saturation and angular misalignment immediately clear the queue. New safe requests wait a fresh 40ms. Gimbal commands are immediate. Feeders remain the old match's provisional 6Hz (17mm) and 1Hz (42mm), rather than the benchmark's 20Hz. Actual launch uses current physical muzzle position, axis and Jacobian velocity.

The source executor uses the frozen benchmark 40ms / 120-degree / preaim-enabled configuration. It does not reproduce the deployed 0ms / 60-degree / preaim-disabled configuration. Chassis movement disables firing and restarts the native tracking process after settling; moving fire is unsupported. Synthetic armor appearance, calibration resolution association, exposure, lighting and robot dynamics are not measured real-world calibration.

The referee implements only its documented 2026 RMUL subset. On match termination, in-flight projectiles are explicitly censored; they are not misses and no post-terminal damage is awarded. All launch UIDs partition into resolved or censored and per-team UID HP removal must equal referee damage.

Recordings contain actual simulation frames. The main broadcast and the separate red-camera observer view show trails connecting recorded projectile centers and enlarged contact markers for readability. Those overlays never enter detector input. The separate camera video's main panel is the ideal unwarped optical view, while its inset is scaled native raw RGB. Video is sampled at 10Hz. A terminal card may be held for 3 seconds and is not extra physics time.

## Run

Use the existing local Python dependencies listed in requirements files and an already built frozen timing-v4 actor. No service API or hardware is used.

```
python tools/prepare_match_v5_spec.py --source-spec EXISTING_V4/headless_rebuild/configs/candidate_spec.json --out config/match_v5_runtime_spec.json
python -m pytest -q
python -m rm_match.opening_runner --mode match --max-seconds 300 --aim rmcs-stop --rmcs-spec config/match_v5_runtime_spec.json --armor-profile role_v23 --resilient-recording --out artifacts/full_match_v5
```

The generated runtime spec contains machine-local paths and must not be committed. The original detector model/binary, official CAD and unrelated assets are not included in this checkpoint. The old match navigation, opponent policies and role_v23 appearance are unchanged except the physics timestep.

## Reproduction boundary

Cloning this navigation patch alone is insufficient to run the native actor. The full actor source/build dependencies and detector model are separate existing inputs. The preparation tool deliberately accepts only the recorded frozen binary SHA256. Recompiling on another machine can produce a different binary hash; that rebuild must receive a new recorded identity and repeat qualification. Do not silently substitute its hash and claim it is this execution freeze.

The historical original-rmcs-stop option is explicitly rejected by this v5 runner before starting a process. Only --aim rmcs-stop with the exact frozen 40f7 identity is qualified. Use the pre-v5 revision for its separately documented historical original protocol; that old protocol is not silently translated or relabeled.
