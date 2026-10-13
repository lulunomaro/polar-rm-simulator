# Native RMCS source build

The source and model are present. Native deployment and end-to-end execution remain separately qualified steps. This guide does not claim a working native executable, detector inference, MuJoCo feedback control, interactive gameplay, Windows support, or real-time deadlines.

## Included identity

- Source: `operator_native/runtime/`, 94 unchanged recovered source/build/license files, plus the reviewed portable build entry and simulation-only profile.
- Algorithm: `079a7fe29966fe467630f0c4ab8c3ed075edaad9 + T2 tracker`, not the older `40f7` full-match baseline and not untouched upstream.
- Adapter: existing operator-FOV transformation, protocol `rmcs-sim-operator-fov-v1`.
- Model: `models/shenzhen-0526.onnx`, SHA-256 `b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255`.
- Native code license: retain `operator_native/runtime/candidate/LICENSE` and repository third-party notices.

## Prepare and build explicitly

Use Linux x86-64 with the documented C++23 compiler, Eigen, OpenCV development modules, yaml-cpp, OpenVINO C++ ABI=1 and CMake prerequisites. The [portable entry guide](../operator_native/runtime/README_PORTABLE.md) gives exact historical versions, package hashes and library limitations. Python wheels alone are not sufficient C++ development dependencies. The OpenVINO Python wheel's ABI=0 is explicitly rejected. No dependency installation or network download is performed by this entry.

From the repository root:

```sh
python3 operator_native/runtime/build_portable.py plan
python3 operator_native/runtime/build_portable.py prepare --out /tmp/rmcs-prepare-only
python3 operator_native/runtime/build_portable.py build --out /tmp/rmcs-native-build --jobs 2
```

Use a fresh output directory for every attempt. If OpenVINO is separately unpacked, supply `--prefix /absolute/openvino/runtime/cmake`. `plan` checks source/model identity and prints commands. `prepare` generates source and simulation configs only; it creates no executable or admissible runtime spec. `build` performs a clean configure, syntax checks, compilation and link, then validates the ELF before recording success and generating `operator_source.local.json`. It does not launch the binary or simulator.

The generated spec binds actual binary/config/model hashes and absolute local paths. Never publish or copy it as a portable spec. A rebuilt binary has a newly measured identity; historical binary hashes are never assigned to new bytes. Follow the client/native integration's explicit registration step and require separate end-to-end qualification before use. No silent mock or pixel-baseline fallback is authorized.

## Publication verification

The source recovery and portable-setup manifests describe static preparation and ten synthetic setup tests. Those tests do not compile C++ or execute native code. The repository's original 190 source blobs and exact deterministic-function fixture remain unchanged. Native compile and runtime results, if established later, must name their exact source, toolchain, dependency and binary hashes. No compiled binary, external library, build log, generated local spec, private calibration, or raw recovery archive is included in this source stage.
