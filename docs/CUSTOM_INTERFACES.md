# Navigation, aim and client interfaces

The simulator owns physics, scene state, collision, referee and authority. Your navigation/aim code receives a serialized own-sensor observation and returns a serialized action. A client uses HTTP for viewing and explicit operator control. Neither role imports a simulator object.

## Local navigation / aim process: JSON Lines

Use the complete runnable standard-library example in [`examples/adapter_jsonl.py`](../examples/adapter_jsonl.py) and registration file [`examples/adapters.json`](../examples/adapters.json). The examples deliberately emit zero velocity or an inactive hold; replace `compute()` with a reviewed algorithm. They are not included in the default profile or used as a fallback.

Add them explicitly:

```sh
python3 tools/deploy.py plan --adapters-json examples/adapters.json
# With dependencies and native build prepared:
python3 tools/deploy.py launch --adapters-json examples/adapters.json \
  --sim-python .venv-sim/bin/python --client-python .venv-client/bin/python --run
```

A local administrator owns this manifest. Its exact top-level keys are `schema` and `adapters`, schema `polar.sim.adapter.jsonl.v1`. Each entry requires:

- `adapter_id`: unique `custom_`-prefixed lowercase identifier. It cannot replace the native or historical IDs.
- `kind`: `navigation` or `aim`
- `label`: human-readable algorithm label
- `command`: argument array; no shell expansion. First item is an existing absolute executable or `{python}` for the selected simulator interpreter.
- `cwd`: working directory, relative to the manifest directory or absolute
- `required_sensors`: any subset of `camera`, `odometry`, `ranges`

Only this local file chooses commands. HTTP binding config cannot alter the command, executable or working directory. A manifest change after server registration fails closed and needs a server restart. This runs trusted local software: process separation is not a malicious-code sandbox and imports, dependencies, filesystem and network access are not isolated. Review programs before registering them. No automatic installation or dependency fetch occurs.

### Lifecycle and wire format

One process is owned by one robot/kind/binding lifecycle. UTF-8 JSON occupies one line per message. Flush stdout after every reply; reserve stdout for protocol. This wrapper discards stderr, so send any needed diagnostic output to your own explicitly local file. It limits input to 12 MiB, response to 64 KiB and one pending transaction. On closure, fault or timeout the process is stopped; an exception needs explicit rebind. There is no hot retry/fallback.

Reset request:

```json
{"schema":"polar.sim.adapter.jsonl.v1","op":"reset","context":{"episode":1,"robot_id":"red_sentry","binding_epoch":1},"config":{}}
```

Reset response:

```json
{"schema":"polar.sim.adapter.jsonl.v1","op":"reset","ok":true}
```

For each `act`, the request is `{"schema":"polar.sim.adapter.jsonl.v1","op":"act","observation":OBSERVATION}`. Return `{"schema":"polar.sim.adapter.jsonl.v1","op":"act","ok":true,"action":ACTION}`. Unknown, duplicate, nonfinite, partial, oversized or out-of-order replies are rejected. Do not emit unsolicited events. Reset has a two-second process-start bound; each action must finish before the smaller of 250 ms and its existing server deadline. Those limits are guards, not promises of available compute time.

### Observation JSON

The complete executable validator is [`rm_match/platform_v2/contracts.py`](../rm_match/platform_v2/contracts.py), schema `polar.sim.observation.v2`. Read it and the [core contract](../rm_match/platform_v2/CONTRACT.md) for every exact nested field. At top level:

- Identity: `robot_id`, `episode`, `binding_epoch`, `observed_seq`, `sim_time`, `wall_deadline`
- `frames`: declared right-handed coordinate conventions
- `own`: team/role, ideal joint `qpos`/`qvel`, own `odom_xyyaw`/`odom_vxyw`, hp/ammo/heat/alive
- `referee`: phase, remaining seconds, emergency-stop status
- `sensors.camera`: either explicit unavailable+reason or actual simulated packed RGB/BGR pixels as base64, dimensions/stride, intrinsics/distortion, extrinsics and exposure-time own pose/velocity
- `sensors.ranges`: either unavailable+reason or anonymous ideal simulated ranges/angles, max range, capture time and base frame

There are no opponent poses, target IDs, segmentation, hidden world roster or simulator/model/judge objects. Range and odometry are explicitly ideal simulation sensors, not a claim of MID360 SLAM. Do not reconstruct an algorithm feed from display truth. Camera capture time and own pose belong to exposure, not delivery. `wall_deadline` uses server monotonic seconds; it is not a UTC stamp and cannot be compared to another computer's clock.

### Action JSON

Use schema `polar.sim.action.v2` and echo all six identity fields exactly from the observation. Add `kind`, `mode`, `command`. Example navigation command:

```json
{"frame":"base_link","vx_mps":0.25,"vy_mps":0.0,"wz_rps":0.0}
```

Navigation uses `kind: navigation`, `mode: velocity_body`. `base_link` means forward/left/up. Each translational component is bounded to ±1 m/s, total speed to 1 m/s, yaw rate to ±2 rad/s. Navigation controls motion only. A destination can live in your binding config, but unsupported trajectory action modes are rejected rather than silently interpreted as velocity.

Example aim command:

```json
{"frame":"base_link","yaw_rad":0.0,"pitch_rad":0.0,"active":false,"confidence":null,"fire_permission":false}
```

Aim uses `kind: aim`, `mode: gimbal_target`. Yaw is chassis-relative, positive pitch up, in radians. Backend joint limits apply. Unknown confidence stays null; do not manufacture it. `fire_permission` is informational only and never creates a shot. Fire remains a separately owned, unexpired explicit manual channel. The authority checks identity, ownership, current motion/referee state and deadlines again immediately before applying a result.

## Bind with the Python SDK

The pinned Qt client recognizes its existing native RMCS, rule and pixel IDs. The default deployment exposes only native RMCS, so there is no default rule/pixel choice. A new `custom_` ID currently requires the SDK or a client that explicitly implements its config UI; the current Qt chooser marks unknown IDs unsupported.

Minimal bounded example for the zero-motion JSONL navigation fixture after starting the server with its manifest:

```python
import time
from rm_match.platform_v2.client import PlatformClient

client = PlatformClient('http://127.0.0.1:8766', control_profile='server_window_v1')
client.open('operator')
try:
    client.claim('red_sentry', ['motion'])
    binding = client.bind('red_sentry', 'navigation', 'custom_navigation_example', {})
    end = time.monotonic() + 1.0
    while time.monotonic() < end:
        client.keepalive()
        client.renew('red_sentry', ['motion'])
        window = client.control_window('red_sentry', ['motion'])
        client.adapter_input('red_sentry', 'navigation', binding['binding_epoch'],
                             window_id=window['window_id'], valid_for_s=0.1)
        time.sleep(0.05)
finally:
    client.close()
```

This intentionally starts an explicit one-second zero-motion adapter binding, not autonomous navigation or fire. Do not implement a blind retry after a lost acknowledgement. An uncertain SDK request blocks control until explicit reconnect; reconnect does not grant old leases or bindings. For a human interface, issue activation only while the intended input/deadman is held, and stop it on focus loss or cancellation.

## Other clients: HTTP/JSON SIM v2

Endpoint: `http://127.0.0.1:8766`. Scheme is plain HTTP only on local loopback; no LAN listener, TLS or remote admission policy is implemented. Run a new client on the same machine. Do not expose this server through a network proxy without a separate approved security design.

- Unauthenticated `GET /v2/health` checks runtime status.
- `POST /v2/sessions` with `{"role":"spectator"}` opens read-only viewing; use `{"role":"operator","control_profile":"server_window_v1"}` for current window-bound operator control.
- The server returns a short-lived bearer capability. Send it only in `Authorization: Bearer …`; keep it in memory and out of logs or URLs. Session creation does not claim any vehicle.
- `GET /v2/robots`, `/v2/capabilities`, `/v2/adapters`, `/v2/state`; `POST /v2/watch` then `GET /v2/frame` provide viewing and negotiation.
- `POST /v2/claim`, `/v2/renew`, `/v2/release` manage per-robot motion/gimbal/fire leases. Do not steal occupied channels.
- `POST /v2/bind`, `/v2/unbind`, `/v2/control_window`, `/v2/adapter_input` bind and activate declared adapters.
- `POST /v2/control` sends explicit channel controls with lease epoch, increasing sequence, current window ID and bounded validity.
- `POST /v2/keepalive` and `/v2/close` maintain/end the session. Reading state does not renew a lease or an input.

The exact request keys and responses are in [`server.py`](../rm_match/platform_v2/server.py), [`client.py`](../rm_match/platform_v2/client.py) and [CONTRACT.md](../rm_match/platform_v2/CONTRACT.md). All successful service replies carry `schema: rm.sim.platform.v2`. The server rejects browser Origin, unexpected Host, redirects, duplicate/unknown body keys and oversized bodies. Build native/desktop clients against the reference SDK rather than a browser page. State/frames are labeled display-only truth and are not the algorithm-sensor API; JSONL adapters receive the approved sensor DTO separately.
