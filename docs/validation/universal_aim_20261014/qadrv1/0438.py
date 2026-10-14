"""Synthetic instrumentation tests only; no rendering/native/live qualification."""
import threading
from types import SimpleNamespace
import unittest
from transport_probe import TransportProbe


class ProbeTests(unittest.TestCase):
    def transport(self):
        client = SimpleNamespace(uncertain=False, _request=lambda *a, **k: {'schema': 'test'})
        return SimpleNamespace(client=client, install_frame=lambda data, **kwargs: data['installed'],
            _lock=threading.RLock(), last_error='', frame_error='', _connected=True,
            watch_robot='red_sentry', watch_epoch=1, video_sequence=-1, video=None,
            raw_state={}, telemetry={}, catalog={'ready': True}, selection_pending=False,
            diagnostics=lambda: {'observed': True})

    def test_original_install_result_and_kwargs_unchanged(self):
        t = self.transport(); received = []
        t.install_frame = lambda data, **kwargs: received.append((data, kwargs)) or True
        p = TransportProbe(t); data = {'available': True, 'frame_seq': 7}
        self.assertTrue(t.install_frame(data, generation=3, request_started=99.))
        self.assertIs(received[0][0], data)
        self.assertEqual(received[0][1], {'generation': 3, 'request_started': 99.})
        self.assertEqual(p.snapshot()['admitted_frame_count'], 1)

    def test_original_exception_is_reraised_and_recorded(self):
        t = self.transport(); error = ValueError('Expired camera sample')
        def fail(*a, **k): raise error
        t.install_frame = fail; p = TransportProbe(t)
        with self.assertRaises(ValueError) as caught: t.install_frame({'available': True}, generation=0)
        self.assertIs(caught.exception, error)
        self.assertEqual(p.snapshot()['frame_calls'][0]['error'], 'Expired camera sample')
        self.assertEqual(p.admitted_frame_count, 0)

    def test_request_cause_kept_without_replaying(self):
        t = self.transport(); calls = []
        def fail(*a, **k):
            calls.append(a)
            try: raise TimeoutError('timed out')
            except TimeoutError as exc: raise RuntimeError('Uncertain request') from exc
        t.client._request = fail; p = TransportProbe(t)
        with self.assertRaises(RuntimeError): t.client._request('/v2/frame')
        self.assertEqual(len(calls), 1)
        self.assertEqual(p.snapshot()['request_errors'][0]['cause_type'], 'TimeoutError')

    def test_queued_watch_is_not_acknowledgement(self):
        t = self.transport(); p = TransportProbe(t)
        for attr, value in [('watch_epoch', None), ('selection_pending', True), ('_connected', False)]:
            old = getattr(t, attr); setattr(t, attr, value)
            self.assertFalse(p.watch_ready('red_sentry')); setattr(t, attr, old)
        self.assertTrue(p.watch_ready('red_sentry'))
        self.assertFalse(p.watch_ready('blue_sentry'))

    def test_snapshot_survives_transport_stop_clear(self):
        t = self.transport(); p = TransportProbe(t); before = p.snapshot()
        t.watch_epoch = None; t._connected = False; t.frame_error = 'Stopped'
        self.assertEqual(before['current']['watch_epoch'], 1)
        self.assertTrue(before['current']['connected'])
        self.assertEqual(before['current']['frame_error'], '')

    def test_history_is_bounded(self):
        t = self.transport(); p = TransportProbe(t, capacity=2)
        for n in range(5):
            t.video_sequence = n; p.sample(); t.install_frame({'installed': False, 'frame_seq': n})
        result = p.snapshot()
        self.assertEqual(len(result['transitions']), 2)
        self.assertEqual(len(result['frame_calls']), 2)


if __name__ == '__main__': unittest.main()
