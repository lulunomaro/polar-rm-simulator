# Bounded native PnP factor diagnosis

This diagnosis replays the saved synthetic camera frame from
`../pnp_saved_frame_20261013/` with the unmodified recovered Detector,
PoseEstimator and RobustPnpSolution. It requires a successful full clean native
Ninja build and runs in Linux/WSL. Results belong to this new diagnosis; the
historical failed qualification remains preserved.

Run from WSL with the library environment of the native build:

```sh
python3 tools/diagnose_pnp_factors.py \
  --build-root artifacts/native-build-2 \
  --out artifacts/pnp-factors-20261013
```

The output directory must be new. The helper first runs the existing unchanged
`reproduce_saved_frame.py`, whose source/header, generated-input, model, config,
spec and ELF bindings must pass. It then compiles only a separate diagnostic main
and links the same hashed native objects. The recovered algorithm files, model,
runtime configuration, original thresholds and production ELF are not edited.

Each run performs exactly one model inference. The bounded experiment has five
cases in addition to the original replay:

| Case | Sole changed factor |
| --- | --- |
| Identity | No image processing; output must exactly match the original replay |
| Gamma 0.8 | LUT: round/saturate `255 * (pixel/255)^0.8` |
| Gamma 1.2 | LUT: round/saturate `255 * (pixel/255)^1.2` |
| Gaussian 0.5 | Gaussian sigma 0.5 pixels, reflected border |
| Gaussian 1.0 | Gaussian sigma 1.0 pixels, reflected border |

Gamma and blur are independent transformations of the same saved BGR image;
neither is combined with another perturbation. No corner scaling, corner
substitution, annotation or geometric truth enters the algorithm. Per-case
reports record real model corners, confidence, IPPE candidates, reprojection
errors, each original gate and the native estimator output count.

Static source inspection identifies unconditional `return` statements at the
start of both `optimize_corners` overloads in the recovered source. The diagnostic
also calls both original overloads on real inferred armors and checks that all
corner coordinates remain unchanged. This establishes current behavior, but
does not establish that enabling the disabled implementation would be correct.

The original 40 degree pitch tolerance is retained. For an ordinary armor the
original expected pitch is 15 degrees, giving a permitted interval of -25 to 55
degrees. Low reprojection error does not override that physical prior.

Limits: one saved synthetic frame, six model inferences, no physical-camera
calibration, dataset qualification, tracker/controller rollout, training or
hardware. Image-processing results are diagnostic experiments and are not a
deployment fix. The original replay records each exact native object's hash;
correspondence between those individual objects and the production ELF is not
independently proven by the original build manifest.

The executed report and conclusions are recorded in `RESULTS.md`. The JSON
reports in this directory preserve the measurements and input bindings.

The additional independent experiment copies the disabled implementation into
`rmcs::experimental`, removes only its two unconditional early returns, and runs
one inference on the original frame. Run it after the factor tool:

```sh
python3 tools/diagnose_pnp_corner_body.py \
  --build-root artifacts/native-build-2 \
  --factor-root artifacts/pnp-factors-20261013 \
  --out artifacts/pnp-corner-body-20261013
```

The copy preserves the original source's attribution to
CSU-FYT-Vision/FYT2024_vision (Apache-2.0); the original license is preserved in
`../pnp_saved_frame_20261013/UPSTREAM_LICENSE`. This experiment retains the
original ROI, brightness/search constants, and PnP gates. It is a new candidate
algorithm experiment and is not the recovered T2 baseline.
