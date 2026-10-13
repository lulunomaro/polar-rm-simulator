# Saved-frame PnP diagnosis: executed 2026-10-13

The original failure was reproduced in a newly compiled, unmodified recovered
native pipeline: Detector finds one blue INFANTRY_3 armor, while PoseEstimator
returns zero 3D armors. Both positive-depth, front-facing IPPE candidates are
rejected by the original pitch gate. Gamma and mild blur do not resolve the
failure. Enabling only the disabled corner-optimization body in an independent
namespace also fails and worsens the reprojection residuals. No production fix,
threshold relaxation or training change is justified by these seven inferences.

## Build and identity

The run uses `artifacts/native-build-2`, whose successful full clean build passed
29 syntax checks and compiled 29 translation units. The production ELF SHA-256
is `797e6ba7240aef29cacd8ac624afbba5cae1c751a62a7fa8eb41570451e17250`.
The model SHA-256 remains
`b53470b42a5778aca8f3382ebe3c623482599cbf8ebad2e9a0dcc0c7f42c9255`;
the original 1440x1080 BGR saved-frame SHA-256 remains
`fc961d5a972f25bc7fa691230a36318eede5d4ac7e4330386824910a1dfd106b`.

The unchanged existing saved-frame replay helper ran first. The identity factor
matches that current replay exactly in native corners, confidence, PnP
candidates and estimator output, and matches the original input image bytes.
The source/header, generated input, model, configs, recovery/build manifests,
spec and production ELF remain bound. All 104 input files checked by the factor
tool and all original linked object hashes were unchanged after execution.

This is a current WSL/OpenVINO 2025.4 replay, not historical numerical
equivalence. The historical report used confidence 0.88403928 and corner values
that differ slightly from this run's 0.86365676. The failure mechanism is
reproduced; the cause of the historical/backend numerical difference was not
investigated. Existing individual object hashes are recorded, while independent
proof of their correspondence to the production ELF remains a stated replay
limitation.

## Native measurements

The current raw corners, in pixels, are:

| Corner | x | y |
| --- | ---: | ---: |
| tl | 642.514526 | 853.924683 |
| bl | 639.882019 | 891.892639 |
| br | 769.341309 | 892.950439 |
| tr | 771.709351 | 856.347412 |

The inferred lightbar lengths are 38.059110 and 36.679548 pixels. The native
IPPE solve returns two candidates at depths 1.791170 and 1.791137 meters. Their
front-facing dot products are 0.684625 and 0.684562. Both pass positive depth and
facing checks. The ordinary-armor pitch prior is 15 degrees with the unchanged
40 degree tolerance, permitting -25 through 55 degrees.

| Input factor | Detected armors | Confidence | Left/right length, px | Candidate pitches, deg | IPPE residuals, px | Native 3D armors |
| --- | ---: | ---: | --- | --- | --- | ---: |
| Original / identity | 1 | 0.863657 | 38.059 / 36.680 | -35.224 / 58.272 | 0.527 / 0.605 | 0 |
| Gamma 0.8 | 1 | 0.832200 | 38.105 / 36.832 | -35.123 / 58.206 | 0.523 / 0.595 | 0 |
| Gamma 1.2 | 1 | 0.870713 | 38.438 / 36.911 | -34.723 / 57.757 | 0.532 / 0.615 | 0 |
| Gaussian sigma 0.5 | 1 | 0.830567 | 37.721 / 36.260 | -34.940 / 57.997 | 0.531 / 0.584 | 0 |
| Gaussian sigma 1.0 | 0 | — | — | — | — | 0 |

Each row changes only its stated image factor. All detected candidates in these
cases pass depth and facing and fail pitch. Sigma 1.0 eliminates the detection
in this frame. The native optimizer's two overloads were also called on the
inferred armor in each detected case: all coordinates remained unchanged. The
sigma 1.0 case has no armor to test and is not evidence for optimizer behavior.

## Independent disabled-body experiment

The separate diagnostic copies the original corner implementation into
`rmcs::experimental` and removes exactly the two unconditional early returns.
It leaves the original source, original object, ROI padding, PCA/search constants
and PnP gates untouched. It uses the unchanged original image and one model
inference; the raw model corners and confidence match the current baseline
exactly before refinement.

| Corner | Refined x | Refined y | Displacement, px |
| --- | ---: | ---: | ---: |
| tl | 642.514526 | 853.924683 | 0.000 |
| bl | 635.760864 | 884.353882 | 8.592 |
| br | 767.700989 | 896.976196 | 4.347 |
| tr | 767.748779 | 859.968506 | 5.366 |

The left bar shrinks to 31.169667 pixels and the right bar becomes 37.007721
pixels. Native PoseEstimator still returns zero. Candidate pitches become
62.806943 and -39.825386 degrees, with reprojection residuals 1.254262 and
2.077987 pixels. Positive depth and facing still pass; pitch still rejects both.
This exact candidate does not fix the frame and makes its residuals worse.

Static inspection explains a limitation to investigate separately: the body
chooses its ROI from predicted endpoints plus only 5 pixels of padding. For the
current raw corners, left ROI rows are 848 through 896, and right rows 851
through 897. The preserved original image audit found blue pixels extending
846 through 899 and 846 through 898, respectively. The current ROI excludes
those ends. This observation is a diagnostic hypothesis about incomplete edge
coverage, not a demonstrated repair. ROI expansion would be a separate
algorithmic factor and was not applied in this experiment.

## Evidence and limits

`FACTOR_REPORT.json` preserves all factor measurements and hashes.
`EXPERIMENTAL_CORNER_BODY_REPORT.json` preserves raw/refined corners, gates and
the exact independent source and binary hashes. `BASELINE_REPLAY_BINDING.json`
records the existing replay's verified input bindings and every linked object's
hash. Full logs, raw transformed images and separate diagnostic binaries are in
`artifacts/pnp-factors-20261013` and `artifacts/pnp-corner-body-20261013`.

No geometric truth or substitute corner enters Detector or PnP. The source
frame is a saved synthetic camera image, with no physical-camera calibration or
training-domain evidence. No full tracker, controller, physics rollout or
hardware was qualified. Original failed fixtures and reports remain preserved.

A future image-only refinement candidate needs independent positive and
negative validation: multiple distances (for example 1.5, 2, 3 and 5 meters),
view angles, lighting, color, blur, occlusion and image-edge clipping, plus blank
frames and distractor lights. Any geometry truth must be used only by offline
evaluation. Original gates and failures should remain reported alongside the
candidate, and passing one saved frame cannot qualify deployment.
