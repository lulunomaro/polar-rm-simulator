# Own client + own RMCS deployment

The default profile is `own-rmcs-t2-v1`. It uses this independent repository, the owner's separate Polar Qt client and the owner's `079a7fe + T2 tracker` RMCS source. It is an explicit, fail-closed deployment path. It is not yet a validated complete game: live native wall-clock qualification, moving native aim, multiple native robots and automatic fire remain outside its scope.

## 1. Platform and repositories

Use a Linux x86-64 desktop. The server and client run on the same computer over loopback; deploying both on another computer is supported by these setup steps. This is not a remote-LAN client/server configuration. Windows native and WSL-to-Windows desktop integration are not qualified; the doctor refuses a non-Linux native host. Old `.bat` files are historical/manual entries.

Clone this public simulator repository normally. No historical navigation checkout or private recovery archive is needed for the deployment sources. From its root:

```sh
python3 tools/deploy.py setup-client
python3 tools/deploy.py setup-client --run
```

The first command only prints the Git commands. The second fetches exactly `0cedf99b70b1beec99865b9980af6789e6c53d99` from `https://github.com/lulunomaro/polar-rm-client.git` into `external/polar-rm-client` and checks out that commit detached. It does not initialize submodules, install software, start the client or change the user's other checkout. The destination must not exist. Use `--client-root /absolute/existing-client` to reuse a clean checkout at the same pin. The doctor verifies the commit, required files and absence of tracked-source modifications. It does not upload anything.

`external/` is ignored by this simulator's Git rules. Preserve the client's own licenses. A downloaded external component is not relicensed by the simulator.

## 2. Separate Python environments

The following are commands for the person installing the project. The deployment helper does not install dependencies automatically:

```sh
python3 -m venv .venv-sim
python3 -m venv .venv-client
.venv-sim/bin/python -m pip install -r requirements-camera.txt
.venv-client/bin/python -m pip install -r external/polar-rm-client/requirements-core.txt
```

Python 3.10+ is required. Choose interpreters compatible with the pinned package wheels on the target machine. Keep the two environments separate because camera-server and Qt-client OpenCV builds serve different uses. Preserve the venv executable path even if it is a symlink. Do not replace it with its resolved base Python.

The doctor actually imports NumPy, MuJoCo, Pillow and OpenCV in the selected simulator interpreter, and PySide6 QtCore/QtWidgets, OpenCV, NumPy, MQTT and serial modules in the selected client interpreter. Importing a module is not creating a physics world, opening a hardware port or showing a window. These probes do not prove that the target GL driver or Qt display works.

## 3. Build the owner's RMCS locally

See [native build requirements](NATIVE_RUNTIME.md) and `operator_native/runtime/README_PORTABLE.md`. The native target needs CMake, a C++23 compiler, Eigen 3.4, OpenCV 4.10 development libraries including ximgproc, yaml-cpp 0.8 and OpenVINO 2025.4's C++ ABI=1 runtime. Python wheels alone are insufficient; the OpenVINO Python wheel's ABI=0 is incompatible and rejected. Follow the portable guide's version/toolchain constraints rather than substituting arbitrary system packages.

```sh
python3 operator_native/runtime/build_portable.py plan
python3 operator_native/runtime/build_portable.py build \
  --out operator_native/runtime/local_build \
  --prefix /absolute/openvino/runtime/cmake --jobs 2
```

Omit `--prefix` only when the correct OpenVINO CMake package is already discoverable. Every attempt uses a fresh output directory; never overwrite a failed attempt. On success, the build entry produces `operator_source.local.json`, `BUILD_MANIFEST.json`, native binary and generated simulation-only configs. The default deployment expects the spec under `operator_native/runtime/local_build/`; override `--native-spec` for another output location.

Rebuild on the target machine. Generated specs contain consumer-local absolute paths and actual byte hashes; copying an old machine's spec is not portable. The default profile checks:

- Source base `079a7fe29966fe467630f0c4ab8c3ed075edaad9`
- T2 patch SHA-256 `ea1235cfd11018bde08b40a43f3aba072a0870a8906f40ff35255cfdd16e4c7d`
- Model SHA-256 `b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255`
- A matching clean-build manifest plus binary, executor, autoaim config and tracking-mode hashes
- Linux ELF64 x86-64 binary identity

The operator protocol remains `rmcs-sim-operator-fov-v1`; it does not identify the underlying algorithm revision on its own. The T2 source/build checks distinguish the owner's RMCS from a legacy binary that speaks that same protocol. Hashes provide reproducibility checks, not a sandbox against a malicious local compiler, binary or dependency.

## 4. Doctor and explicit launch

```sh
python3 tools/deploy.py doctor \
  --sim-python .venv-sim/bin/python --client-python .venv-client/bin/python
python3 tools/deploy.py launch \
  --sim-python .venv-sim/bin/python --client-python .venv-client/bin/python
# Review the plan, then explicitly launch:
python3 tools/deploy.py launch \
  --sim-python .venv-sim/bin/python --client-python .venv-client/bin/python --run
```

`plan` and `launch` without `--run` start nothing. The doctor checks target interpreters, client pin, native lineage/bytes, `ldd` lookup of the trusted local binary, visible-display environment and a fresh output path. It reports every blocker it can find. `ready_to_attempt: true` means prerequisites passed, not that native inference, camera timing or visible UI is working. There is no automatic download, build, package installation, credentials setup, hardware access or paid service call.

Launch reruns the doctor, verifies the server ready message against profile and spec hash, then starts the original Qt SIM v2 entry. It never starts a hardware backend. Defaults are port 8766, up to 300 wall seconds, camera budget 15 total FPS, real-time factor at most 1, EGL server rendering and no virtual resupply. `--gl glfw` selects an alternative existing renderer; `--gl osmesa` needs its system libraries. Changing rendering options does not qualify timing. The 80 ms native camera gate and 150 ms server input-window mechanism are unchanged.

Runtime evidence stays under fresh `artifacts/deployment/`; choose `--out` for another attempt. The launch records its plan, doctor report, verified ready message, process logs and exit reason. It gives the client separate `POLAR_USER_DATA_ROOT` storage under that output, avoiding edits to the external source checkout. Closing either side, Ctrl-C, or the bounded duration cleans up owned processes. `launch_result.json` is launch evidence, not a full-match pass.

In the client:

1. Select/watch `red_sentry`.
2. Select `aim_native_rmcs_v1` under `V2 Aim`. This is the only default registered algorithm; the catalog labels its T2 provenance.
3. F2 claims the selected channels; a subsequent explicit F2 arms once current state/frame eligibility allows it. Observe runtime feedback before treating an output as applied.
4. Remain stationary for native aim. Motion inhibits it. Fire is a separately controlled manual channel; native output never grants fire authority.
5. F12 releases. Focus loss, lease/window expiry, stale image/result or an adapter error clears affected controls. There is no automatic baseline takeover.

The present pinned Qt UI begins in Manual and requires explicit selection/arming. “Default own-RMCS profile” describes the deployed source and catalog, not permission to auto-claim or auto-fire. Native workers start only after a valid native binding and eligible sensor input. A successful server launch alone does not prove the native worker executed.

## 5. Extension and qualification gaps

[Custom interfaces](CUSTOM_INTERFACES.md) documents the JSONL navigation/aim adapter boundary and alternative HTTP clients. Extensions are optional local registrations and are never fallback policies.

Before claiming the user's complete requested game works, separately validate a fresh native build and inference, camera calibration/timing, deadline-safe operator/native closed loop, intended roster and motion/fire behavior, visible client interaction, sustained match and cleanup on the actual target machine. Do not substitute the 24-exposure OFFLINE diagnostic or old timing-v5/40f7 run for these tests. No such full-match result is claimed by this deployment addition.
