"""Original-client OFFLINE smoke driver, never a visible desktop qualification.

Invoke only as part of the parent-owned bounded OFFLINE attempt. This script does
not launch a simulator and does not change any network, camera or action deadlines.
"""
import hashlib
import json
from pathlib import Path
import sys
import time

# Explicit pinned source root supplied by the owning harness.
sys.path.insert(0, str(Path(sys.argv[1]).absolute()))

from PySide6.QtWidgets import QApplication
from rm_client.sim_platform_transport import PlatformTransport
from rm_client.sim_platform_client import PlatformClient
from rm_client.sim_platform_lifecycle import RenewalLifecycle
from transport_probe import TransportProbe


def main():
    url, output = sys.argv[2:]
    out = Path(output)
    app = QApplication(['offline-spectator'])
    # Initialize Qt before OpenCV can alter its plugin search environment.
    # Then load decoder dependencies before time-sensitive transport admission;
    # no decode, sample, timestamp or inference occurs during this preload.
    import cv2
    import numpy
    t = PlatformTransport(url, role='spectator')
    probe = TransportProbe(t)
    client = None
    lifecycle = None
    cleanup = None
    before_cleanup = None
    errors = []
    watched = False
    watch_requested = False
    seen = False
    first_frame = None
    last = None
    t.start()
    try:
        # A queued watch request is not an acknowledged subscription. Do not
        # trigger camera/native work before the real observer has its identity.
        admission_deadline = time.monotonic() + 3.5
        while time.monotonic() < admission_deadline:
            app.processEvents()
            if t.robot_ids and not watch_requested:
                t.watch('red_sentry')
                watch_requested = True
            if probe.watch_ready('red_sentry'):
                watched = True
                break
            if t.client.uncertain:
                raise RuntimeError('Original transport became uncertain during observer admission')
            time.sleep(.01)
        if not watched:
            raise RuntimeError('Original observer did not acknowledge watch/state/catalog before admission')
        client = PlatformClient(url, timeout=.25)
        client.open('operator')
        client.claim('red_sentry', ['gimbal'])
        client.bind('red_sentry', 'aim', 'aim_native_rmcs_offline_v1', {})
        lifecycle = RenewalLifecycle(client, 'red_sentry', ['gimbal'])
        lifecycle.start()
        end = time.monotonic() + 95
        keepalive = time.monotonic()
        while time.monotonic() < end:
            app.processEvents()
            probe.sample()
            with t._lock:
                frame = t.video
                sequence = t.video_sequence
            if frame is not None:
                seen = True
                if first_frame is None:
                    first_frame = dict(sequence=sequence, shape=list(frame.shape),
                        decoded_bgr_sha256=hashlib.sha256(frame.tobytes()).hexdigest())
            last = client.state()
            lifecycle.observe(last)
            if last.get('offline_final_state') in ('COMPLETED', 'HALTED'):
                break
            if time.monotonic() - keepalive > 10:
                client.keepalive()
                keepalive = time.monotonic()
            time.sleep(.05)
    except Exception as exc:
        errors.append(type(exc).__name__ + ': ' + str(exc))
    finally:
        before_cleanup = probe.snapshot()
        if lifecycle is not None:
            cleanup = lifecycle.close()
        elif client is not None:
            try:
                client.close()
            except Exception as exc:
                errors.append('operator_close: ' + str(exc))
        t.stop()
        result = dict(watched=watched, watch_requested=watch_requested,
            frame_decoded=seen, first_decoded_frame=first_frame,
            visible_window=False, qt_event_loop=True, pinned_client_source_unchanged=True,
            decoder_preloaded_before_transport=True, cleanup=cleanup, errors=errors,
            transport_before_cleanup=before_cleanup, last_state=last)
        (out / 'driver.json').write_text(json.dumps(result, indent=2))
        (out / 'driver_events.json').write_text(json.dumps(
            lifecycle.events() if lifecycle is not None else [], indent=2))
    return 0 if not errors else 2


if __name__ == '__main__':
    raise SystemExit(main())
