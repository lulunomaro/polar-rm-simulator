# Historical RMCS detector weights

This package restores the exact `shenzhen-0526.onnx` used by the archived RMCS benchmark source seals. The bytes are unmodified.

- Size: 4,359,932 bytes
- SHA-256: `b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255`
- Git blob SHA-1: `c6fc0dcdf37f876f6b1fc2079672139a07c733ab`
- Source: [Alliance-Algorithm/rmcs_auto_aim_v2 at 4f4340956a989b0d3ecd4fbd94b1e72a301293cd](https://github.com/Alliance-Algorithm/rmcs_auto_aim_v2/blob/4f4340956a989b0d3ecd4fbd94b1e72a301293cd/models/shenzhen-0526.onnx)

The same Git blob is present in the user's upper-control repository. Full pinned provenance is recorded in `MODEL_PROVENANCE.json`.

## License and attribution

The upstream repository distributes this file alongside its root MIT license, Copyright (c) 2025 Alliance Algorithm Team. Preserve `LICENSE.upstream.MIT` when redistributing. No separate model-specific license, model card, or exception was found in the pinned tree. The root license does not explicitly discuss weights; this recovery does not independently establish training-data provenance or original weight authorship.

## Compatibility and limits

Static inspection of the raw ONNX graph found:

- Input `images`: **FLOAT16**, shape `[1, 3, 640, 640]`
- Output `output`: **FLOAT32**, shape `[1, 25200, 22]`
- ONNX IR 6, standard-domain opset 11; producer `pytorch` 2.0.1
- 218 nodes and 132 embedded initializers; no external tensor files or custom operator domains found

Direct ONNX consumers must respect the raw graph's FLOAT16 input dtype and shape. A FLOAT32 tensor cannot be fed directly as `images` without conversion or an explicit model transformation.

The pinned OpenVINO wrapper separately declares preprocessing of uint8 NHWC BGR images to float32 RGB divided by 255, with the model layout set to NCHW. That preprocessing declaration must not be mistaken for the raw graph input dtype. Detector results contain four ordered corners, confidence, four color scores, and nine armor genre scores. The original wrapper files are included unchanged under `interfaces/` solely as interface references, not as a standalone build target.

Point the runtime spec's `model_share` to the directory containing this filename. Do not substitute `shenzhen-0708.onnx` or another detector while claiming historical model identity. The model alone does not provide the frozen native binary, executor configuration, autoaim configuration, runtime dependencies, or a valid runtime spec. These must be recovered and verified separately.

Verification in this recovery was limited to byte hashes, source identity, static interface inspection, and static protobuf field inspection. No ONNX checker, model inference, or simulation was run, and no benchmark or runtime-readiness claim is made.
