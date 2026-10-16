"""Snapshot isolation and original control expiration; no NN/GL qualification."""
import copy

import pytest

from rm_match.platform_v2.control import Binding,ControlPlane,_binding_snapshot
from rm_match.platform_v2.test_control import Clock


def test_binding_snapshot_preserves_scalar_types_and_nested_aliases_without_live_aliasing():
    binding=Binding(epoch=3,owner='owner',adapter_id='arbitrary_plugin',
        config={'nested':{'array':[1,False,None,1.25,'text']}},lease_epochs={'gimbal':2},
        activation_required=True,activation_seq=5,activation_expires=1000.15,
        activation_window_id=7,activation_window_deadline=1000.15)
    # Future mutable fields follow the same full-copy path and shared memo.
    binding.extra=binding.config['nested']
    old=copy.deepcopy(vars(binding));new=_binding_snapshot(binding)
    assert new==old
    assert all(type(new[k]) is type(old[k]) for k in old)
    assert new['extra'] is new['config']['nested']
    assert new['extra'] is not binding.extra
    new['config']['nested']['array'][0]=99;new['lease_epochs']['gimbal']=99
    assert binding.config['nested']['array'][0]==1 and binding.lease_epochs['gimbal']==2
    binding.config['nested']['array'][1]=True
    assert new['extra']['array'][1] is False


def test_binding_snapshot_keeps_cycles_detached_from_live_state():
    binding=Binding()
    binding.config['self']=binding.config
    binding.config['binding_fields']=vars(binding)
    result=_binding_snapshot(binding)
    assert result['config'] is not binding.config
    assert result['config']['self'] is result['config']
    assert result['config']['binding_fields'] is result


@pytest.mark.parametrize('single_robot',[False,True])
def test_live_snapshot_cannot_mutate_bindings_and_expiry_is_sticky_at_original_deadline(single_robot):
    clock=Clock();control=ControlPlane(['robot'],clock=clock)
    token=control.open_session('operator',control_profile='server_window_v1')['token']
    lease=control.claim(token,'robot',['gimbal'])['lease_epochs']
    bound=control.bind(token,'robot','aim',lease,'generic_aim',{'nested':{'values':[1,2]}})
    window=control.control_window(token,'robot',lease)
    ack=control.adapter_input(token,'robot','aim',lease,bound['binding_epoch'],0,window['window_id'],.15)
    original_expiry=ack['activation_expires']
    snapshot=lambda:control.snapshot_robot('robot') if single_robot else control.snapshot(token)
    first=snapshot();binding=first['bindings']['robot']['aim']
    binding['config']['nested']['values'].append(3);binding['lease_epochs']['gimbal']=999
    assert control.bindings['robot','aim'].config=={'nested':{'values':[1,2]}}
    assert control.bindings['robot','aim'].lease_epochs['gimbal']==lease['gimbal']
    clock.now=original_expiry-1e-6
    assert snapshot()['bindings']['robot']['aim']['activation_expires']==original_expiry
    clock.now=original_expiry
    expired=snapshot()['bindings']['robot']['aim']
    assert expired['owner'] is None and expired['epoch']>bound['binding_epoch']
    assert control.snapshot()['leases']['robot']['gimbal']['owner'] is not None
    assert snapshot()['bindings']['robot']['aim']['owner'] is None
