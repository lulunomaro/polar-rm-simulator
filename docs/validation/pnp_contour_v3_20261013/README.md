# Image-only PnP repair candidate v3 — 2026-10-13

The new contour overlay fixes the saved-frame PnP rejection and passes an
independent rendered-frame check: all seven positive frames detected by the
unchanged neural model produce valid native poses, with 0.134–0.405 pixel corner
RMSE and 1.7–28.7 mm position error. Three negative scenes produce zero poses,
including a one-bar occlusion that the original pipeline wrongly accepts. The
eighth positive scene has no original model detection and remains a detection
coverage limitation. Full native tracker/control-chain qualification is still
pending a separately identified complete build.

## Actual repair and preserved algorithm

`operator_native/runtime/overlays/corners_contour_v3.cpp` supplies the original
two `rmcs::util::optimize_corners` signatures, replacing the disabled corner TU
only when explicitly selected in a new native build. Its SHA-256 is
`0a90e0089a2531a476091d75c3085a6d26a843feba7c0f5cd429ea2928aa812c`.
The recovered 94 source/header files remain unchanged. The original neural
model, class and confidence, PnP shapes, pitch gate, tracker and fire controller
are preserved; the repair introduces explicit image postprocessing:

1. A local ROI is derived from the model's measured lightbar endpoints. Saturated
   red/blue pixel support is separated from neutral highlights and background.
2. Complete connected support supplies an unweighted axis and actual support
   endpoints. A one-pixel closing operation joins interpolation holes; endpoint
   positions come from the observed support boundary, not geometric plate size.
3. A colored component touching the lateral search boundary triggers one bounded
   ROI expansion. Sensor/longitudinal clipping still rejects the fit. This
   addresses a measured model-center error without a parameter sweep.
4. Both bars must have complete, consistent support. Missing or inconsistent
   pairs are discarded before PnP; learned corners behind an occluder are not
   accepted as measured physical edges.
5. An original DARK color may be recovered only if the actual image supports one
   unique red or blue complete pair. Neither own team nor target state is an
   input to this optical color decision. Original class and confidence remain
   numerically unchanged for every retained armor.

The original tracker color gate is retained. Color recovery is an explicit new
image measurement, not a relaxed color gate. The original 15-degree pitch prior
and 40-degree tolerance are retained. No corner scaling to expected physical
dimensions, synthetic annotation, target-state substitution or training is used.

## Independent validation

The predetermined independent suite changes chassis separations, view angles
and actual scene lighting. All 11 frames come from real MuJoCo rendering plus
the existing SourceLensWarp at 1440x1080; positive geometry must be in the camera
FOV before rendering. Native processes receive only BGR bytes, calibration and
capture-time own state. The separate evaluator reads source-shape geometry only
after every native process exits, measuring pixel and position error offline.

| Scene | Original pose count | Candidate pose count | Original corner RMSE, px | Candidate corner RMSE, px | Candidate position error, mm |
| --- | ---: | ---: | ---: | ---: | ---: |
| Near, 2.25 m chassis separation | 0 | 1 | 11.940 | 0.134 | 1.7 |
| Mid, 3.05 m | 1 | 1 | 6.211 | 0.239 | 4.0 |
| Far, 3.85 m | 0 | 0 | — | — | — |
| Far, 4.2 m | 1 | 1 | 3.638 | 0.278 | 3.2 |
| Yaw +12 degrees | 1 | 1 | 6.461 | 0.405 | 6.5 |
| Yaw -28 degrees | 1 | 1 | 4.962 | 0.316 | 28.7 |
| Actual light scale 0.75 | 1 | 1 | 6.200 | 0.239 | 4.0 |
| Actual light scale 1.15 | 1 | 1 | 6.206 | 0.239 | 4.0 |
| Blank | 0 | 0 | — | — | — |
| Full occlusion | 0 | 0 | — | — | — |
| One-bar occlusion | 1 | 0 | — | — | — |

The 3.85 m frame has no neural detection in either pipeline. The overlay neither
creates a class nor fabricates corners for an absent neural detection. Its cause
has not been isolated. The blank frame is identical to the earlier blank
regression frame and is not claimed as a new unique image. The eight positive
images and both occlusion images differ from the regression set.

Across the regression set, the candidate produces six poses for six originally
detected positives and rejects all three negatives. Its one-time adaptive ROI
addresses the previously clipped -20-degree left bar. No candidate parameters
changed after the independent suite was inferred.

## Preserved failures and scope

The original saved-frame failure, gamma/blur trials and failed independent
early-return/padding candidates remain in earlier validation directories.
`V1_FAILED_HOLDOUT.json` preserves missing DARK color processing and an accepted
occluded false pose; `V2_REGRESSION.json` preserves the lateral-search clipping
failure. Their source files remain separately preserved as v1 and v2.

The first new holdout fixture mistakenly used +0.15 gimbal pitch, pointing the
camera upwards and placing intended positives outside the FOV. Its all-zero
results remain in `artifacts/pnp-contour-holdout-results-20261013`; they are not
used as a successful negative test or as candidate efficacy evidence. The
corrected fixture uses -0.15 and explicit positive FOV checks, without changing
algorithm parameters or PnP gates.

This is a bounded simulation repair, with no physical-camera calibration,
physical deployment claim, realtime qualification, full match or training-data
generalization claim. It does not yet qualify original T2 tracking/control;
that requires the complete identified build and an actual rendered-camera,
tracker, actuator-consumption and clean-shutdown trace.

## Evidence and reproduction

`INDEPENDENT_COMPARISON.json`, `REGRESSION_COMPARISON.json`, `SUMMARY.json` and
the render/FOV bindings preserve actual measurements and source/model/ELF
hashes. Full native text outputs and separately linked diagnostic ELFs are in
`artifacts/pnp-contour-v3-independent2-results-20261013`. Source/header,
generated input, model/config, production ELF and all original objects were
verified unchanged around inference. Individual object's correspondence to the
original production ELF is not independently proven by the original replay
manifest; exact linked hashes are preserved in the prior baseline binding.

```sh
# Windows .venv-sim renders the independent camera frames.
.venv-sim/Scripts/python.exe tools/diagnose_pnp_render_holdout.py \
  --suite independent2 --out artifacts/fresh-independent-render

# WSL/Linux performs native inference; the two diagnostics are compiled once.
python3 tools/diagnose_pnp_overlay.py \
  --build-root artifacts/native-build-2 \
  --binding artifacts/pnp-factors-20261013/baseline/REPLAY_BINDING.json \
  --frame-root artifacts/fresh-independent-render \
  --overlay operator_native/runtime/overlays/corners_contour_v3.cpp \
  --out artifacts/fresh-independent-results
```

Each output directory must be new. Optional `--reuse-diagnostics` accepts only
prior ELF/source/model/build/binding hashes that match exactly, avoiding
unnecessary repeat compilation.
