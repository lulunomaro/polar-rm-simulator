# Licensing and third-party notices

The original owned implementation and documentation in this repository are released under the root MIT License. Third-party code, dependencies and separately supplied assets retain their own terms; the root license does not grant rights to materials not owned by this project.

- The deterministic rule_decide function originated in lulunomaro/llm-RM-navigation at 6ff95524df1a6aadce7697e366ab32ac5e9bbafc, source sentry-brain/deploy/sentry_decide_server.py, Git blob 967e396947ab608b4e6a4aa609c79f95a6dc4c7a. rm_match/upstream_rule.py retains the exact function body with an explicit RMUL configuration. upstream_reference/sentry_decide_server.py is a function-only source-text test fixture; it is not the original full HTTP/LLM server. The owner authorized MIT publication of owned simulator code, including this deterministic function.
- The separately built original native RMCS algorithm is Alliance-Algorithm/rmcs_auto_aim_v2 at 4f4340956a989b0d3ecd4fbd94b1e72a301293cd. Its MIT notice is retained verbatim in licenses/RMCS_MIT.txt. A recovered native source build tree is included under `operator_native/runtime/`, preserving the original notice at `operator_native/runtime/candidate/LICENSE`. Its exact identity is `079a7fe + T2 tracker`, recorded in `RECOVERY_MANIFEST.json`; it is not the unchanged upstream revision or historical `40f7` baseline. External dependency libraries and the compiled executable are not bundled. The historical `models/shenzhen-0526.onnx` detector weight is bundled unchanged with pinned provenance and another verbatim copy of the upstream notice at `models/LICENSE.upstream.MIT`. Its upstream wrapper headers are retained unchanged under `models/interfaces/` as interface references, not a complete build. No separate model-specific license or restriction was found at the pinned revision; the root license does not explicitly discuss weights, and this publication does not establish training-data provenance or original weight authorship. See `models/MODEL_PROVENANCE.json`. The narrow operator_native FOV integration delta does not relicense any external build inputs.
- Arena and armor are newly authored analytic approximations of cited dimensions/rule references. Official CAD meshes, sticker artwork and product photographs are not included. Official documents remain their owners' copyrighted works and are not relicensed. Arena source references and approximation boundaries are retained in its manifest and docs/ARENA_ASSETS.md.
- Python dependencies remain external packages with their respective licenses. No claim is made that the root MIT License licenses external model weights, native libraries, private vehicle CAD, or any third-party dataset.
- The explicitly selected `camera-fast` extra uses external `pybase64==1.5.1` under BSD-2-Clause, with its bundled native base64 library retaining upstream notices. See https://github.com/mayeut/pybase64/tree/v1.5.1 and the installed wheel's license files. It serializes the same actual camera bytes; it does not replace vision inference. The wheel and compiled extension are not bundled in this repository.

## Source-pinned PB behavior-tree integration

The owned `operator_native/pb_match_decision/runner.cpp`, CMake integration and
Python preparation/peer glue use the root MIT License for the newly authored
code only. They do not relicense the original PB conditions/actions, XML,
BehaviorTree.ROS2 fork, BehaviorTree.CPP or protocol messages. The preparation
tool copies pinned inputs into an owned build directory and records their raw
SHA256 values. The original XML is preserved separately from the explicitly
changed spin/stop/local-waypoint I/O overlay; the original PB C++ node
implementations and their notices remain intact.

The following notices were copied byte for byte from the local fixed source
checkouts. Source URLs below come from those checkouts' Git `origin` metadata;
the fixed revision identifies the license and source, rather than the moving
repository default branch.

| Component and fixed revision | Upstream source | Unchanged license text |
| --- | --- | --- |
| PB `pb2025_sentry_behavior`, `d111b635d326775c6c19aa12500a0bbd6a27a588` | [SMBU-PolarBear-Robotics-Team/pb2025_sentry_behavior](https://github.com/SMBU-PolarBear-Robotics-Team/pb2025_sentry_behavior/tree/d111b635d326775c6c19aa12500a0bbd6a27a588) | Apache-2.0: [PB_SENTRY_BEHAVIOR_APACHE2.txt](licenses/PB_SENTRY_BEHAVIOR_APACHE2.txt) |
| PB `BehaviorTree.ROS2` fork, `7d177dcfbd7dbb7f5e5cd79c4e5e3e744e389c56` | [SMBU-PolarBear-Robotics-Team/BehaviorTree.ROS2](https://github.com/SMBU-PolarBear-Robotics-Team/BehaviorTree.ROS2/tree/7d177dcfbd7dbb7f5e5cd79c4e5e3e744e389c56) | Apache-2.0: [PB_BEHAVIORTREE_ROS2_APACHE2.txt](licenses/PB_BEHAVIORTREE_ROS2_APACHE2.txt) |
| `BehaviorTree.CPP` 4.6.2, `2a8a226fbbd99f524f0796e0d8a3145773c61c06` | [BehaviorTree/BehaviorTree.CPP](https://github.com/BehaviorTree/BehaviorTree.CPP/tree/2a8a226fbbd99f524f0796e0d8a3145773c61c06) | MIT: [BEHAVIORTREE_CPP_4_6_2_MIT.txt](licenses/BEHAVIORTREE_CPP_4_6_2_MIT.txt) |
| `pb_rm_interfaces` protocol-v1.7.0, `8912fa565a7ac57ef070df218957379123d238ee` | [SMBU-PolarBear-Robotics-Team/pb_rm_interfaces](https://github.com/SMBU-PolarBear-Robotics-Team/pb_rm_interfaces/tree/8912fa565a7ac57ef070df218957379123d238ee) | MIT: [PB_RM_INTERFACES_1_7_0_MIT.txt](licenses/PB_RM_INTERFACES_1_7_0_MIT.txt) |

The native runner ELF, BT shared library, generated protocol typesupport and
other ROS/system shared libraries remain external build outputs and are not
published as part of this repository. Their runtime paths and hashes are build
evidence, not a grant of rights to redistribute every dependency. Original
third-party copyright, license and any applicable notice obligations remain;
the root MIT notice is not a substitute for them. Build or tick evidence alone
does not establish a complete licensed release, field-map rights, full-match
qualification or hardware acceptance.
