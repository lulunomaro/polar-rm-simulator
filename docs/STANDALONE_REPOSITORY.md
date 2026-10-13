# Standalone repository guide

## Layout and source identity

SIM_ROOT is this repository root. Retained protocol documents describe staged implementations; their historical introduction about a v1-only Qt client predates the current manual SIM v2 client. The current startup commands and scope in this guide take precedence over that old UI status sentence. The extracted rm_match, tools, tests, config, operator_native and upstream_reference retain their relative layout. Run from the checkout root: historical package metadata does not promise that every reference/helper is bundled in a wheel.

CLIENT_ROOT remains the separate Polar Qt client checkout containing main.py and rm_client. Its existing --nav-root argument accepts SIM_ROOT directly. It checks rm_match/platform_v2/__main__.py relative to that directory. No client or algorithm patch is needed for this extraction.

Navigation source commit: 7663ae744d69b27813abaefeaa9ae3e73be46a9f. This is a subtree snapshot, not full Git history. The original repository and branches are unchanged. The public extraction manifest records the exact included source paths and hashes. Historical private evidence and logs are omitted; no prior execution is claimed to have been repeated.

## Manual SIM v2

Use an existing Python environment with requirements-camera.txt and a separate client environment with its requirements-core.txt. Example user-run setup and startup:

```sh
# From SIM_ROOT, if dependencies are not already installed:
/absolute/sim-venv/bin/python -m pip install -r requirements-camera.txt

# From SIM_ROOT:
/absolute/sim-venv/bin/python -m rm_match.platform_v2 --camera --port 8766 --camera-total-fps 2 --max-wall-seconds 300

# From CLIENT_ROOT:
/absolute/client-venv/bin/python main.py --sim-platform-v2 --sim-role operator --sim-endpoint http://127.0.0.1:8766
```

A visible Qt window needs a working desktop display server. Linux headless rendering can explicitly select a supported renderer such as EGL; do not use that Linux prefix on Windows. Fresh pinned installation and Windows wheels were not tested in this extraction. Preserve the invocation path of virtual-environment Python, even when it is a symlink.

The existing client's supervised launcher can plan from CLIENT_ROOT:

```sh
/absolute/client-venv/bin/python tools/launch_sim_platform.py --mode manual --nav-root /absolute/polar-rm-simulator --nav-python /absolute/sim-venv/bin/python --client-python /absolute/client-venv/bin/python --out /absolute/new-manual-output
```

Default is dry-run. Add --run only when intending to start the local simulator and Qt client. Output must be a new directory. The legacy parameter name --nav-root means the standalone simulator root here.

## OFFLINE/native SIL

Use the same client launcher with --mode offline on Linux and explicit --scene-json /absolute/scene.json and --native-spec /absolute/operator_source.local.json. It validates frozen lifecycle source and provided artifact hashes. Native shared-library/rpath/ABI compatibility remains an additional requirement.

This is one stationary, fire-off scene with 24 exposures and modeled delay. The original Qt window is a spectator with watch acknowledgement, not arbitrary manual offline gameplay or a complete match. The older paired 2x24 offscreen QA evidence has a separate scope. See the retained tools/platform_v2/offline_stage6/serve.py entry. Machine-local native inputs are not supplied here.

## Historical timing-v5

Use the exact commands in docs/MATCH_TIMING_V5.md. The frozen repaired timing-v4 actor binary SHA-256 is 70ad294ff8be702804ebd1e3f98048d0a13b9e74894d8b28615886a83eda0fcb. A different rebuild needs a new recorded identity and qualification; do not substitute the operator-FOV identity from OFFLINE experiments.

Only red sentry uses this actor; five robots retain the baseline. Rules and dynamics remain documented approximations. Ordinary fire is delayed 40 ms while safety clears immediately; moving source fire is unsupported. Historical timing-v5 results remain in the source repository and are not included or rerun here.

## Boundaries

- No workflow or CI dispatch is added. Extraction verification starts no physics, renderer, native actor, paid API, or hardware operation.
- The historical detector weight is included at `models/shenzhen-0526.onnx`; point `model_share` to that directory only when preparing an otherwise valid matching runtime spec. See `../models/README.md` for its pinned source, original license notice and interface. This does not supply or validate a runtime spec. Native source/build dependencies, other weights, binaries, private scene initialization and local specs remain separate inputs subject to existing usage rights. No inference or native runtime qualification was performed for this model supplement.
- Keep runtime specs, native outputs, recordings, .env files and secrets local. Review staged changes; ignore patterns are only an additional guard.
- Original owned code is released under MIT. Retain LICENSE, THIRD_PARTY_NOTICES.md, licenses/RMCS_MIT.txt and SOURCE_PROVENANCE.md; third-party dependency and asset terms remain separate.
- Syntax and synthetic checks do not qualify Windows visible UI, LAN, hardware, real-time native execution, a complete match or full official rules.
