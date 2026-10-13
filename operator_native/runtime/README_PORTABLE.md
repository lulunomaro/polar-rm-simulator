# T2 native runtime source for the RoboMaster simulator

This directory adds a self-contained **source build path** for the simulator's
RMCS operator integration. It uses real RMCS detector, pose-estimation, tracker
and control translation units. The source is `079a7fe29966fe467630f0c4ab8c3ed075edaad9`
plus the two-file T2 tracker change identified in `RECOVERY_MANIFEST.json`.
It is not the older `40f7` full-match baseline or the untouched NJUST upstream.

The existing operator FOV transformation is applied outside this recovered tree.
The resulting protocol remains `rmcs-sim-operator-fov-v1`, compatible with the
existing simulator adapter. A newly built binary gets its own measured SHA-256.
Historical binary hashes are provenance only and are never assigned to new bytes.

## Current verification boundary

- The 94 recovered source/build/license files are hash-pinned and unchanged.
- Setup unit checks cover command construction, source hashes, configuration
  scope, fail-closed input checks, and spec hashing. They do not exercise C++.
- Prepare-only verification produced the exact expected FOV adapter source and
  simulation configuration, with **no native executable and no runtime spec**.
- A successful `build` means a local C++ build succeeded. It does not mean that
  detector inference, MuJoCo feedback control, interactive gameplay, Windows,
  hardware, real-time deadlines, or full matches were verified.
- Native support in this entry is Linux x86-64. There is no Windows-native
  executable, DLL bundle, or Windows-native deployment claim.

See the repository's deployment documentation for current end-to-end verification
and how to register the generated spec. Never fall back silently to a mock or
pixel baseline when the native runtime is missing.

## Layout and dependencies

Install this directory as `operator_native/runtime/`. Keep the existing
`operator_native/prepare_fov_hook.py` next to it. Keep one detector model at
`models/shenzhen-0526.onnx` in the repository root. The model SHA-256 must be
`b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255`.
The entry never downloads models, dependencies, or packages.

The historical build used:

| Dependency | Historical version |
| --- | --- |
| GCC / libstdc++ | Debian 14.2.0-19, C++23 |
| Eigen | 3.4.0-4 |
| OpenCV C++ development libraries | 4.10.0+dfsg-5 |
| yaml-cpp C++ development library | 0.8.0+dfsg-7 |
| OpenVINO C++ runtime | 2025.4.0, C++11 ABI enabled |
| CMake for this portable entry | 3.20 or newer |

OpenCV modules: core, imgproc, imgcodecs, calib3d, features2d, flann, dnn,
ximgproc. `libopencv-contrib-dev` supplies the last module in Debian.
Development headers, CMake package files and runtime shared libraries are
required; Python wheels alone do not satisfy the C++ development dependencies.
OpenVINO's ONNX frontend and CPU plugin must remain available to its runtime.
An accelerator is not required by the default CPU profile.

The historical package/archive hashes are in `RECOVERY_MANIFEST.json`.
The exact OpenVINO archive is Intel's Ubuntu 24 build:
[openvino_toolkit_ubuntu24_2025.4.0.20398.8fdad55727d_x86_64.tgz](https://storage.openvinotoolkit.org/repositories/openvino/packages/2025.4/linux/openvino_toolkit_ubuntu24_2025.4.0.20398.8fdad55727d_x86_64.tgz),
SHA-256 `c57bc759a04bf316d66dc42d644433cf3bd590ad640933630a0616efb380a630`.
The Ubuntu 22 archive and the Python wheel have different identities; the wheel
uses ABI=0 and is rejected explicitly by this CMake entry.
The original [Eigen 3.4.0-4 package](https://deb.debian.org/debian/pool/main/e/eigen3/libeigen3-dev_3.4.0-4_all.deb)
has SHA-256 `1a167bb381acb90c1d8450a8f3e66a09d216dbc64b33ac8a082a0912513ef939`.
The CMake entry accepts compatible versions at or above its declared minimums,
so a successful build on a different toolchain is a new artifact, not a byte-for-
byte reproduction of a previous benchmark. Preserve CMakeCache, compile commands,
logs and BUILD_MANIFEST when reporting a build. A system-compatible C++23 library
with `<expected>`, `<format>` and `<generator>` is necessary.

## Explicit local steps

From the repository root:

```sh
python3 operator_native/runtime/build_portable.py plan
python3 operator_native/runtime/build_portable.py prepare --out /tmp/rmcs-prepare-only
python3 operator_native/runtime/build_portable.py build --out /tmp/rmcs-native-build
```

Each prepare/build needs a fresh output directory. Failed output is preserved for
diagnosis; do not reuse it silently. Choose a new directory after correcting a
dependency problem. `plan` validates source/model inputs and prints commands only.
`prepare` writes transformed source and simulation configs only, never an executable
or admissible runtime spec. Neither action starts the simulator.

If OpenVINO is unpacked in a separate directory, pass its package prefix:

```sh
python3 operator_native/runtime/build_portable.py build \
  --out /tmp/rmcs-native-build-2 \
  --prefix /opt/openvino/runtime/cmake
```

`--prefix` accepts CMake's semicolon-separated package-prefix list. `--model` and
`--operator-hook` accept explicit paths when using this source tree outside the
standard repository layout. `--jobs` bounds native compilation parallelism.

The build configures a fresh CMake build, checks every translation unit with the
compiler's syntax-only mode, and runs clang-tidy first if installed. It then
compiles every unit and links the operator adapter. There is no reuse of old
objects. Configure/build failures stop immediately, with logs retained. The build
does not run the resulting executable.

Only after successful compilation does the entry create:

- `bin/rmcs_sim_operator_fov`
- `configs/simulation_autoaim.yaml` and `configs/simulation_executor.yaml`
- `BUILD_MANIFEST.json`, `BUILD_ATTEMPT.json`, syntax/build logs and CMake records
- `operator_source.local.json`, binding the exact binary/config/model hashes

The generated spec contains absolute paths on the machine that performed the
build. Do not commit or copy it as a portable spec; rebuild on the destination
machine, or regenerate and reverify the complete local input set there.
No configuration or build output should be copied into the source release.

## Simulation-only configuration and authority

`simulation_profile.json` retains only the detector, tracker, pose-estimator,
armor-only toggle, and source control settings used by the headless adapter.
It excludes physical-camera serials, capture/recording pipelines, inherited
camera calibration, network streaming, and private file paths. Camera calibration
and own-platform pose arrive in each validated simulator observation.
Generated YAML is written as JSON syntax, which is also valid YAML.

The runtime uses the simulator's stationary red-sentry contract. Motion gates,
referee gates, fresh-camera checks, FOV admission, and manual-fire authority are
enforced by the existing integration. This package does not authorize hardware
access, change those gates, or enable automatic firing. Changing the source tree,
model, or transformation requires an explicit new reviewed identity manifest.

## License and original tools

Preserve `candidate/LICENSE`, the MIT notice from Alliance Algorithm Team, for the
included RMCS source. Preserve repository licensing and third-party notices for
the surrounding simulator, modifications, model and external dependencies.
External runtime libraries are not bundled here.

The recovered `build.py` remains byte-identical for provenance and old workflows.
Its default `both` also requires an upstream tree that is not included here;
the supported standalone entry in this directory is `build_portable.py`.
The existing parent `build_native.py` and `prepare_operator_spec.py` are unchanged.
