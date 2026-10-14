"""Single-robot guard snapshots preserve full-snapshot expiry and isolation."""
import pytest

from .control import ControlPlane, Rejected


class Clock:
    def __init__(self): self.now = 1000.
    def __call__(self): return self.now
    def advance(self, duration): self.now += duration


def setup(*, strict=False, lease_ttl=1., session_ttl=60.):
    clock = Clock()
    control = ControlPlane(['alpha','beta'], clock=clock, lease_ttl=lease_ttl, session_ttl=session_ttl)
    token = control.open_session('operator', 'server_window_v1' if strict else 'legacy_v2')['token']
    epochs = {r:control.claim(token,r,['motion','gimbal','fire'])['lease_epochs'] for r in control.robot_ids}
    return clock, control, token, epochs


def projection(full, rid):
    result = dict(full)
    result['robot_ids'] = [rid]
    result['leases'] = {rid:full['leases'][rid]}
    result['bindings'] = {rid:full['bindings'][rid]}
    return result


@pytest.mark.parametrize('rid', ['alpha','beta'])
def test_robot_snapshot_equals_full_projection_and_does_not_include_other_robot(rid):
    _, control, token, epochs = setup()
    control.control(token,'alpha','fire',epochs['alpha']['fire'],4,{'fire':True},.1)
    control.bind(token,'beta','aim',{'gimbal':epochs['beta']['gimbal']},'test',{'nested':{'label':'beta'}})
    full = control.snapshot()
    single = control.snapshot_robot(rid)
    assert single == projection(full, rid)
    assert list(single['leases']) == [rid]
    assert list(single['bindings']) == [rid]
    assert control.snapshot() == full


def test_robot_snapshot_is_detached_and_preserves_each_robots_ownership():
    _, control, token, epochs = setup()
    control.control(token,'alpha','fire',epochs['alpha']['fire'],3,{'fire':True},.1)
    control.bind(token,'alpha','aim',{'gimbal':epochs['alpha']['gimbal']},'test',{'nested':{'value':[1]}})
    baseline = control.snapshot()
    single = control.snapshot_robot('alpha')
    single['leases']['alpha']['fire']['input']['fire'] = False
    single['bindings']['alpha']['aim']['config']['nested']['value'].append(2)
    single['bindings']['alpha']['aim']['lease_epochs']['gimbal'] += 10
    assert control.snapshot() == baseline
    assert control.snapshot_robot('beta')['leases']['beta'] == baseline['leases']['beta']


@pytest.mark.parametrize('expired_resource', ['lease','session'])
def test_robot_snapshot_expires_global_resources_and_advances_original_epochs(expired_resource):
    clock, control, token, epochs = setup(lease_ttl=.1 if expired_resource == 'lease' else 10.,
                                        session_ttl=.1 if expired_resource == 'session' else 60.)
    for rid in control.robot_ids:
        control.bind(token,rid,'aim',{'gimbal':epochs[rid]['gimbal']},'test',{})
    prior = control.snapshot()
    clock.advance(.1)
    single = control.snapshot_robot('alpha')
    full = control.snapshot()
    assert single == projection(full, 'alpha')
    for rid in control.robot_ids:
        for channel in ('motion','gimbal','fire'):
            lease = full['leases'][rid][channel]
            assert lease['owner'] is None
            assert lease['epoch'] > prior['leases'][rid][channel]['epoch']
        assert full['bindings'][rid]['aim']['owner'] is None
        assert full['bindings'][rid]['aim']['epoch'] > prior['bindings'][rid]['aim']['epoch']
    if expired_resource == 'session': assert not control.sessions
    assert control.snapshot_robot('alpha')['revision'] == full['revision']


def test_expired_manual_input_is_hidden_without_releasing_lease_or_refreshing_ttl():
    clock, control, token, epochs = setup()
    control.control(token,'alpha','fire',epochs['alpha']['fire'],1,{'fire':True},.080)
    before = control.snapshot_robot('alpha')['leases']['alpha']['fire']
    clock.advance(.080)
    after = control.snapshot_robot('alpha')['leases']['alpha']['fire']
    assert after['input'] is None
    assert after['owner'] == before['owner']
    assert after['epoch'] == before['epoch']
    assert after['expires'] == before['expires']
    assert after['input_expires'] == before['input_expires']
    assert after == control.snapshot()['leases']['alpha']['fire']


def test_snapshots_and_same_window_pulse_never_extend_original_activation_window():
    clock, control, token, epochs = setup(strict=True)
    owned = {'gimbal':epochs['alpha']['gimbal']}
    binding = control.bind(token,'alpha','aim',owned,'test',{})
    window = control.control_window(token,'alpha',owned)
    first = control.adapter_input(token,'alpha','aim',owned,binding['binding_epoch'],1,window['window_id'],.080)
    original_deadline = first['activation_expires']
    clock.advance(.030)
    single = control.snapshot_robot('alpha')
    assert single['bindings']['alpha']['aim']['activation_expires'] == original_deadline
    second = control.adapter_input(token,'alpha','aim',owned,binding['binding_epoch'],2,window['window_id'],.150)
    assert second['activation_expires'] == original_deadline
    repeated = control.snapshot_robot('alpha')
    assert repeated['bindings']['alpha']['aim']['activation_window_deadline'] == window['expires_wall']
    assert repeated['leases']['alpha']['gimbal']['expires'] == single['leases']['alpha']['gimbal']['expires']
    clock.now = original_deadline
    expired = control.snapshot_robot('alpha')
    assert expired['bindings']['alpha']['aim']['owner'] is None
    assert expired['bindings']['alpha']['aim']['epoch'] > binding['binding_epoch']
    with pytest.raises(Rejected):
        control.adapter_input(token,'alpha','aim',owned,binding['binding_epoch'],3,window['window_id'],.150)


def test_stop_snapshot_preserves_full_neutralization_and_invalid_robot_is_rejected():
    _, control, _, _ = setup()
    control.stop()
    assert control.snapshot_robot('alpha') == projection(control.snapshot(), 'alpha')
    assert control.snapshot_robot('alpha')['stopped'] is True
    with pytest.raises(Rejected, match='unknown_robot'):
        control.snapshot_robot('not_a_robot')
