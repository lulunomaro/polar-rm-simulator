# Version 1 cumulative mouse-angle input

Opt in when `/session.capabilities.mouse_angle_input_version == 1`.
`/control` may include `mouse_angle` with exactly `generation` (integer
0..2^53-1), `yaw_total_rad`, and `pitch_total_rad` (finite numbers, absolute
value <= 1e6). Legacy `yaw_rate_rps` and `pitch_rate_rps` must both be zero
when this object is present. Other drive, manual fire, aim, identity, and lease
fields keep their existing meanings.

At each explicit rearm, choose a generation greater than both the local value
and `/session.mouse_angle_last_generation`, then start local cumulative totals
at zero. The first packet can already contain nonzero totals. Never wrap the
generation; exhaustion fails closed. A generation cannot change during an
active angle lease. An active angle lease cannot silently switch to rate input.
Neutral packets should omit `mouse_angle`.

The physics owner consumes the difference from the previously consumed totals
once, without multiplying by wall time or simulation time. Skipped/coalesced
packets retain the latest net angle; repeated totals do not apply again.
Mechanical target limits remain yaw [-3.14, 3.14] and pitch [-0.4, 0.5].
This is net-angle semantics: intermediate paths lost to packet coalescing are
not reconstructed, particularly at mechanical saturation.

Neutral, timeout, rejection, epoch changes, or disable revoke the old generation
and discard pending totals. Unconfirmed input is deliberately not replayed
across a failed lease or reconnect. During source automatic authority mouse
angles are consumed and discarded, not queued for later release. Non-operable
simulation states also discard pending mouse motion.

`control.mouse_angle_ack` reports generation, revoked_generation,
consumed_yaw_total_rad, consumed_pitch_total_rad, consumed_control_seq, and
reason (`no_input`, `revoked`, `consumed`, `discarded_by_authority`). This means
input consumption, not measured mechanical arrival. The native source still
has no automatic fire authority.

CPU regression: 104 tests, including 15 added mouse tests, cover cumulative
and reverse deltas, coalescing, first nonzero packets, duplicate totals,
release/timeout/epoch revocation, invalid numeric fields, generation exhaustion,
source-authority discard, release during inference, and equal target increments
at three physics timesteps, plus ordinary-runtime expiry during and after consumption. No source detector/model/threshold changes are part
of this correction. Real main-window repeatability qualification is separate.
