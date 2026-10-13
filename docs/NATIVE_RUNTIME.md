# Native RMCS source build

The source and model are present. A new clean native build was compiled and linked on Debian 13 Linux x86-64 with GCC 14.2.0 and the pinned historical dependencies. All 29 native translation units passed compiler syntax checks and clean compilation, with zero reported compiler warnings. Five bounded software smoke cases passed, including one blank-frame model inference. The exact hashes, expected failure cases, toolchain and limitations are recorded in [NATIVE_BUILD_VALIDATION.json](NATIVE_BUILD_VALIDATION.json).

This is not a full simulator or deployment qualification: no successful MuJoCo closed-loop qualification, aim-quality/hit-rate evaluation, interactive gameplay, real-time deadline validation, hardware use, or execution on another machine/Windows/macOS/ARM was established. The local ELF includes machine-specific dependency paths and is not distributed. Later deployment attempts and any failed or incomplete verdicts are recorded separately in the deployment guide; the bounded native result is not a live-success claim.

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

The source recovery and portable-setup manifests remain the historical record of static preparation and ten synthetic setup tests. A later [public build-validation report](NATIVE_BUILD_VALIDATION.json) separately records the actual clean compile and five bounded software smoke cases. The build used the immediately preceding build-script snapshot; its only subsequent change moves the existing ELF check before success recording. The final reviewed ELF validator and spec generator were checked against the actual compiled binary; the final script was not separately recompiled. Both script hashes and this distinction are retained in the report.

The repository's original 190 source blobs, exact deterministic-function fixture, 94 recovered native source files, and model bytes remain unchanged. No compiled binary, external library, raw build log, generated local spec, private calibration, or recovery archive is included. Rebuild on the destination machine and independently qualify runtime behavior there.
