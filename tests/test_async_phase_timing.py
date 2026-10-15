"""Bounded scalar timing and pure async transport fixtures; no WSL/GL/NN."""
import copy
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import queue
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from rm_match.integrations import phase_timing
from rm_match.integrations import wsl_aim_async as async_module
from rm_match.integrations.phase_timing import NumericPhaseProbe

# Reuse the existing synthetic protocol fixture without making tests a package
# or copying/loosening its source/packet/response builders.
_spec = importlib.util.spec_from_file_location('_async_phase_fixture', Path(__file__).with_name('test_wsl_aim_async.py'))
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)


def test_numeric_snapshot_preserves_typed_original_scalars_and_is_detached():
    source = _fixture.header()[0]['source_context']
    original = copy.deepcopy(source)
    probe = NumericPhaseProbe(capacity=2)
    probe.mark('write_start', source=source, request_id=1, frame_id=7, pixel_sha256='a' * 64,
        original_deadline=source['wall_deadline'], bytes_count=123, queue_depth=0, detail='fixture')
    source['observed_seq'] = 200
    first = probe.snapshot()
    row = first['rows'][0]
    assert tuple(row) == phase_timing.ROW_FIELDS
    assert all(row[k] == value and type(row[k]) is type(value) for k, value in original.items())
    assert row['wall_ns'] > 0 and row['thread_cpu_ns'] > 0 and row['thread_id'] == threading.get_ident()
    assert first['schema'] == phase_timing.SCHEMA and first['complete'] is True
    row['observed_seq'] = -1
    assert probe.snapshot()['rows'][0]['observed_seq'] == 1
    assert all(type(v) in (str, int, float, type(None)) for v in row.values())
    assert len(json.dumps(first)) < 3000


def test_capacity_keeps_first_records_and_reports_all_overflow():
    probe = NumericPhaseProbe(2)
    for step in range(5):
        probe.mark('authority_step_start', detail=step)
    snapshot = probe.snapshot()
    assert snapshot['retained'] == 2 and snapshot['dropped'] == 3 and snapshot['attempted'] == 5
    assert snapshot['complete'] is False
    assert [r['detail'] for r in snapshot['rows']] == [0, 1]
    assert all(r[k] is None for r in snapshot['rows'] for k in phase_timing.SOURCE_FIELDS)


@pytest.mark.parametrize('capacity', [None, True, 0, -1, 1.0, 1048577])
def test_capacity_is_explicit_and_bounded(capacity):
    with pytest.raises(ValueError, match='capacity'):
        NumericPhaseProbe(capacity)


@pytest.mark.parametrize('kwargs', [
    {'detail': b'pixels'}, {'detail': {'payload': 'forbidden'}}, {'detail': 'x' * 97},
    {'detail': True}, {'detail': 1.5}, {'detail': 1 << 64}, {'bytes_count': True},
    {'queue_depth': -1}, {'request_id': 1.0}, {'frame_id': False},
    {'pixel_sha256': 'A' * 64}, {'pixel_sha256': 'a' * 65},
    {'original_deadline': float('nan')}, {'original_deadline': True},
    {'source': {'full_observation': {}}}, {'source': {'image': b'forbidden'}},
])
def test_only_bounded_finite_scalar_metadata_is_retained(kwargs):
    probe = NumericPhaseProbe()
    with pytest.raises(ValueError):
        probe.mark('phase', **kwargs)
    assert probe.snapshot()['attempted'] == 0


@pytest.mark.parametrize('field,value', [
    ('robot_id', ''), ('robot_id', 'x' * 129), ('episode', True), ('binding_epoch', 1.0),
    ('observed_seq', -1), ('sim_time', float('inf')), ('wall_deadline', float('nan')),
    ('wall_deadline', True), ('sim_time', 10 ** 1000),
])
def test_source_six_are_strict_and_never_numeric_aliases(field, value):
    source = _fixture.header()[0]['source_context']
    source[field] = value
    with pytest.raises(ValueError):
        NumericPhaseProbe().mark('phase', source=source)


def test_early_same_thread_sample_is_retained_without_resampling(monkeypatch):
    probe = NumericPhaseProbe()
    stamp = probe.sample()
    def unexpected():
        raise AssertionError('earlier callback sample must not be replaced')
    monkeypatch.setattr(phase_timing.time, 'perf_counter_ns', unexpected)
    monkeypatch.setattr(phase_timing.time, 'thread_time_ns', unexpected)
    probe.mark('reader_entry', sample=stamp)
    row = probe.snapshot()['rows'][0]
    assert (row['wall_ns'], row['thread_cpu_ns'], row['thread_id']) == stamp
    with pytest.raises(ValueError, match='sample_thread'):
        probe.mark('reader_entry', sample=(stamp[0], stamp[1], stamp[2] + 1))


def test_snapshot_and_concurrent_bounded_append_have_coherent_counts():
    probe = NumericPhaseProbe(23)
    barrier = threading.Barrier(3)
    def producer():
        barrier.wait()
        for n in range(20):
            probe.mark('thread_phase', detail=n)
    workers = [threading.Thread(target=producer) for _ in range(2)]
    for thread in workers:
        thread.start()
    barrier.wait()
    intermediate = probe.snapshot()
    assert intermediate['retained'] + intermediate['dropped'] == intermediate['attempted']
    for thread in workers:
        thread.join(1.)
        assert not thread.is_alive()
    final = probe.snapshot()
    assert final['retained'] == 23 and final['dropped'] == 17 and final['attempted'] == 40
    assert len({row['thread_id'] for row in final['rows']}) == 2


def _complete_on_wait(actor, *, advance=None):
    def complete(timeout):
        header = json.loads(actor._outgoing.get_nowait()[0])
        actor._handle_message(_fixture.reply(header, 'native_started'))
        actor._handle_message(_fixture.reply(header))
        if advance:
            advance()
    actor._async_wake.wait = complete


def test_default_none_adds_no_probe_clock_or_metadata_work(tmp_path, monkeypatch):
    actor = _fixture.actor(tmp_path)
    h, raw = _fixture.header()
    def unexpected(*args, **kwargs):
        raise AssertionError('disabled phase timing must do no work')
    monkeypatch.setattr(phase_timing.time, 'perf_counter_ns', unexpected)
    monkeypatch.setattr(phase_timing.time, 'thread_time_ns', unexpected)
    monkeypatch.setattr(actor, '_phase_mark', unexpected)
    _complete_on_wait(actor)
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter', return_value=100.01):
        result = actor.control(_fixture.packet(actor, h, raw), source_context=h['source_context'])
    assert result['should_control'] is True
    assert [e['event'] for e in actor.diagnostics] == ['async_transport_request', 'async_native_started', 'async_native_stdout', 'async_result_accepted80']


def test_enabled_transport_rows_join_original_request_source_frame_and_hash(tmp_path):
    actor = _fixture.actor(tmp_path)
    actor._phase_probe = NumericPhaseProbe()
    h, raw = _fixture.header()
    _complete_on_wait(actor)
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter', return_value=100.01):
        result = actor.control(_fixture.packet(actor, h, raw), source_context=h['source_context'])
    assert result['should_control'] is True and not actor.busy
    rows = actor._phase_probe.snapshot()['rows']
    assert [r['phase'] for r in rows] == ['async_queue_put', 'async_queue_put_end',
        'async_reader_entry', 'async_reader_validated', 'async_reader_entry', 'async_reader_validated', 'async_caller_return']
    for row in rows:
        assert row['request_id'] == 1 and row['frame_id'] == 7
        assert row['pixel_sha256'] == h['packet']['frame']['image']['sha256']
        assert row['original_deadline'] == 100.08
        assert all(type(row[k]) is type(v) and row[k] == v for k, v in h['source_context'].items())
    assert rows[-1]['detail'] == 'accepted'


def test_busy_current_source_does_not_inherit_inflight_frame_or_uuid(tmp_path):
    actor = _fixture.actor(tmp_path)
    actor._phase_probe = NumericPhaseProbe()
    h, raw = _fixture.header()
    _fixture.slot(actor, h)
    current = _fixture.header(8, 2, 2)[0]['source_context']
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter', return_value=100.01):
        result = actor.control(dict(host_deadline=current['wall_deadline']), source_context=current)
    assert result.reason == 'native_compute_inflight'
    row = actor._phase_probe.snapshot()['rows'][0]
    assert row['observed_seq'] == 2 and row['frame_id'] is None and row['request_id'] is None
    assert row['pixel_sha256'] is None


def test_reader_entry_uses_callback_sample_but_invalid_foreign_source_gets_no_row(tmp_path):
    actor = _fixture.actor(tmp_path)
    actor._phase_probe = NumericPhaseProbe()
    h, _ = _fixture.header()
    _fixture.slot(actor, h)
    entry = actor._phase_probe.sample()
    invalid = _fixture.reply(h)
    invalid['source_context']['observed_seq'] = 2
    with pytest.raises(ValueError, match='source_mismatch'):
        actor._handle_message(invalid, _phase_entry=entry)
    assert not actor._phase_probe.snapshot()['rows']
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter', return_value=100.04):
        actor._handle_message(_fixture.reply(h), _phase_entry=entry)
    row = actor._phase_probe.snapshot()['rows'][0]
    assert (row['wall_ns'], row['thread_cpu_ns'], row['thread_id']) == entry


def test_caller_late_after_validated_reply_never_becomes_an_action_or_new_deadline(tmp_path):
    actor = _fixture.actor(tmp_path)
    actor._phase_probe = NumericPhaseProbe()
    h, raw = _fixture.header()
    clock = [100.01]
    _complete_on_wait(actor, advance=lambda: clock.__setitem__(0, 100.081))
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter', side_effect=lambda: clock[0]):
        result = actor.control(_fixture.packet(actor, h, raw), source_context=h['source_context'])
    assert type(result) is async_module.NativeAimPending and result.reason == 'original_deadline_expired'
    rows = actor._phase_probe.snapshot()['rows']
    assert [r['phase'] for r in rows[-2:]] == ['async_caller_late_boundary', 'async_caller_return']
    assert not any(r['detail'] == 'accepted' for r in rows)
    assert all(r['original_deadline'] == 100.08 and r['wall_deadline'] == 100.08 for r in rows)


def test_writer_short_writes_timing_changes_no_original_bytes(tmp_path):
    actor = _fixture.actor(tmp_path)
    actor._phase_probe = NumericPhaseProbe()
    h, raw = _fixture.header()
    _fixture.slot(actor, h, started=False)
    sent = b'{"synthetic_protocol_fixture":true}\n'
    actor._outgoing.put((sent, raw, 100.08, 1))
    collected = bytearray()
    class Stream:
        def write(self, view):
            count = min(1024 * 1024, len(view))
            collected.extend(view[:count])
            if len(collected) == len(sent) + len(raw):
                actor._stop.set()
            return count
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter', return_value=100.01):
        actor._write(SimpleNamespace(stdin=Stream()))
    assert bytes(collected) == sent + raw and not actor._broken.is_set()
    rows = actor._phase_probe.snapshot()['rows']
    assert rows[0]['phase'] == 'async_queue_get'
    assert sum(row['bytes_count'] for row in rows if row['phase'] == 'async_write_end') == len(sent) + len(raw)
    assert [r['phase'] for r in rows[1:]] == ['async_write_start', 'async_write_end'] * 5
    assert all(row['original_deadline'] == 100.08 and row['frame_id'] == 7 and row['request_id'] == 1 for row in rows)


def test_writer_expired_queue_is_recorded_without_sending_one_byte(tmp_path):
    actor = _fixture.actor(tmp_path)
    actor._phase_probe = NumericPhaseProbe()
    h, raw = _fixture.header()
    _fixture.slot(actor, h, started=False, abandoned=True)
    actor._outgoing.put((b'{}\n', raw, 100.08, 1))
    original = actor._outgoing.get
    def once(*args, **kwargs):
        if actor._outgoing.empty():
            actor._stop.set()
            raise queue.Empty
        return original(*args, **kwargs)
    actor._outgoing.get = once
    with patch('rm_match.integrations.wsl_aim_async.time.perf_counter', return_value=100.09):
        actor._write(SimpleNamespace(stdin=SimpleNamespace(write=lambda _: pytest.fail('expired write'))))
    rows = actor._phase_probe.snapshot()['rows']
    assert [r['phase'] for r in rows] == ['async_queue_get', 'async_write_late_boundary']
    assert actor._inflight is None and not actor._broken.is_set()


@pytest.mark.parametrize('enabled', [False, True])
def test_checked_source_pins_add_probe_only_when_enabled(tmp_path, monkeypatch, enabled):
    @dataclass
    class Checked:
        metadata: dict
        _identities: dict
        def verify_unchanged(self):
            pass
    def init(actor, *args, **kwargs):
        actor.repo_root = Path(__file__).resolve().parents[1]
        actor.checked = Checked({'transport_source_sha256': {}}, {})
    digested = []
    monkeypatch.setattr(async_module.WslPipeOperatorProcess, '__init__', init)
    monkeypatch.setattr('rm_match.deployment.profile.digest', lambda p: digested.append(p.name) or 'a' * 64)
    actor = async_module.WslAsyncAimProcess(phase_probe=NumericPhaseProbe() if enabled else None)
    assert ('phase_timing.py' in digested) is enabled
    assert len(digested) == (3 if enabled else 2)
    assert actor._phase_probe is None if not enabled else type(actor._phase_probe) is NumericPhaseProbe
