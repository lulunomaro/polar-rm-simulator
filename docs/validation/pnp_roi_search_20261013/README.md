# Bounded ROI factor experiment — 2026-10-13

The independent corner candidate with ROI padding 20 pixels produced one native
3D armor on the saved frame under the unchanged original PnP gates. Padding 12
failed. This is evidence of one-frame gate acceptance by a new candidate; it
does not establish accurate corners, physical pose, optical calibration,
tracker/controller closure or production qualification. The original baseline
and the original padding-5 candidate both remain failed and preserved.

## Controlled change and stopping rule

The reference is the previously executed independent
`rmcs::experimental` copy of the disabled corner body, with its two
unconditional early returns removed. The original implementation, native object,
model, camera/state metadata, source image and PnP gates remain unchanged.

The two new experiments change only `kPad`: 5 to 12, or 5 to 20 pixels. PCA,
brightness normalization, channel subtraction, axis-start 0.3, axis-end 0.7,
and all other code remain identical to that candidate. Both re-inferred raw
model outputs match the current unchanged replay exactly before image-only
refinement. Each variant uses one inference.

The authorized conditional follow-up would change axis-end 0.7 to 0.9 while
fixing padding at 20, only if the padding variants still failed. Padding 20
produced a pose, so that conditional experiment was not executed. This series
stopped after exactly two additional inferences; no parameter sweep occurred.

## Results

The ordinary armor's unchanged pitch prior is 15 degrees with a 40 degree
tolerance, permitting -25 through 55 degrees. All reported candidates pass
positive depth and front-facing checks.

| Candidate | Left/right lengths, px | Length mismatch, px | Candidate pitches, deg | IPPE residuals, px | Original gate accepted candidates | Native 3D count |
| --- | --- | ---: | --- | --- | ---: | ---: |
| Original unmodified baseline | 38.059 / 36.680 | 1.380 | -35.224 / 58.272 | 0.527 / 0.605 | 0 | 0 |
| Independent body, pad 5 | 31.170 / 37.008 | 5.838 | 62.807 / -39.825 | 1.254 / 2.078 | 0 | 0 |
| Independent body, pad 12 | 45.502 / 34.011 | 11.491 | -33.321 / 56.165 | 2.075 / 2.147 | 0 | 0 |
| Independent body, pad 20 | 45.502 / 38.341 | 7.161 | 53.405 / -30.573 | 1.353 / 1.388 | 1 | 1 |

The pad-20 accepted IPPE candidate has depth 1.726954 meters and front-facing
dot product 0.742545. Its pitch of 53.405313 degrees is only 1.594687 degrees
below the original upper boundary; the other candidate still fails pitch.
Native RobustPnpSolution reports success and native PoseEstimator returns one
armor. This is a narrow gate crossing and requires further validation.

| Corner | Raw model x,y | Pad-12 x,y | Pad-20 x,y | Pad-20 displacement from raw, px |
| --- | --- | --- | --- | ---: |
| tl | 642.515,853.925 | 635.218,846.599 | 634.950,846.625 | 10.512 |
| bl | 639.882,891.893 | 635.281,892.102 | 635.010,892.128 | 4.878 |
| br | 769.341,892.950 | 768.362,888.233 | 769.517,890.736 | 2.221 |
| tr | 771.709,856.347 | 768.588,854.223 | 768.825,852.402 | 4.888 |

Displacements, left/right length mismatch and reprojection residuals are only
error proxies; none establishes corner accuracy. The pad-20 candidate has a
larger residual and length mismatch than the failed raw baseline, and its left
bar moves substantially sideways. Passing the gate cannot be equated with a
more accurate pose. No geometric truth was supplied to the algorithm, and no
reference geometry was used to select corners.

## Reproduction and evidence

Run in Linux/WSL after the completed prior factor and body experiments. Every
output directory must be fresh:

```sh
python3 tools/diagnose_pnp_corner_roi.py \
  --build-root artifacts/native-build-2 \
  --factor-root artifacts/pnp-factors-20261013 \
  --reference-root artifacts/pnp-corner-body-20261013 \
  --roi-padding 12 \
  --out artifacts/pnp-corner-pad12-20261013

python3 tools/diagnose_pnp_corner_roi.py \
  --build-root artifacts/native-build-2 \
  --factor-root artifacts/pnp-factors-20261013 \
  --reference-root artifacts/pnp-corner-body-20261013 \
  --roi-padding 20 \
  --out artifacts/pnp-corner-pad20-20261013
```

`PAD12_REPORT.json` and `PAD20_REPORT.json` preserve actual corners, confidence,
candidate gates, residuals, proxy measurements, reference parameters and hashes.
The corresponding `PAD12_RESULT.txt` and `PAD20_RESULT.txt` preserve the raw
native diagnostic output. Full generated source copies, logs and diagnostic
binaries remain in the two artifact output directories. Source/frame/model/ELF
and original object bindings were checked, including after execution.

The unchanged baseline and padding-5 failure are preserved in
`../pnp_factors_20261013/`. The candidate source retains its upstream
CSU-FYT-Vision/FYT2024_vision attribution; the Apache-2.0 license is preserved in
`../pnp_saved_frame_20261013/UPSTREAM_LICENSE`.

## Required follow-up before production consideration

Freeze pad 20 and axis-end 0.7 before testing new held-out images. Test independent
rendered frames at multiple distances, view angles and lighting, with occlusion
and edge clipping, plus blank and distractor-light negative cases. Run the
unmodified baseline and candidate side by side, report unchanged gate rejection,
valid-pose count, corner stability and false positive count. Geometry truth may
be used only by offline evaluation to measure corner/pose error; it must never
enter the candidate. An actual camera dataset and optical calibration would be
needed for claims about physical deployment.

This report does not complete T02 baseline qualification and does not authorize
replacing the production algorithm.
