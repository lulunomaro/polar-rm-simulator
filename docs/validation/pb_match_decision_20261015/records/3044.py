"""Independent CPU-only review regressions; no GL or native executable."""
from copy import deepcopy
import json
import unittest
from .contracts import ContractError,validate_observation
from .native_camera_snapshot import NativeCameraSnapshot,is_native_snapshot
from .native_observation import validate_native_observation,raw_native_observation
from .test_native_early_pixels import fixture,C


class IndependentPixelReviewTests(unittest.TestCase):
    def test_complete_unminted_clone_never_admitted(self):
        base,pixels,budget=fixture();clone=object.__new__(NativeCameraSnapshot)
        for key in NativeCameraSnapshot.__slots__:
            if key!='__weakref__':object.__setattr__(clone,key,getattr(pixels,key))
        self.assertFalse(is_native_snapshot(clone))
        with self.assertRaisesRegex(ContractError,'unsealed'):
            validate_native_observation(base,clone,consumer=C,budget=budget,now=1000.01)

    def test_consumer_type_equality_does_not_alias_epoch_or_role(self):
        class Text(str):pass
        base,pixels,budget=fixture()
        variants=[(*C[:4],True),[ *C ],(*C[:4],1.),(Text('adapter'),*C[1:]),(*C[:3],Text(C[3]),C[4])]
        for consumer in variants:
            with self.subTest(consumer=consumer),self.assertRaises(ContractError):
                validate_native_observation(base,pixels,consumer=consumer,budget=budget,now=1000.01)

    def test_typed_capture_cannot_enter_json_contract_and_raw_view_remains_immutable(self):
        base,pixels,budget=fixture();valid=validate_native_observation(base,pixels,consumer=C,budget=budget,now=1000.01)
        for key in ('pixels','native_pixels','native_observation'):
            with self.subTest(key=key),self.assertRaises(ContractError):validate_observation(dict(base,**{key:pixels}))
        with self.assertRaises(TypeError):json.dumps(valid)
        raw=raw_native_observation(valid)
        with self.assertRaises(ValueError):raw.rgb[0,0,0]=0
        metadata=pixels.metadata();metadata['own_qpos_at_capture'][0]=999.
        base['own']['qpos'][0]=999.
        self.assertNotEqual(pixels.own[0][0],999.);self.assertNotEqual(valid.base['own']['qpos'][0],999.)

    def test_operator_cap_sim_budget_and_cross_frame_budget_do_not_refresh_capture(self):
        base,pixels,budget=fixture()
        for update in ({'frame_id':pixels.frame_id+1},{'capture_wall':pixels.capture_wall+.001},
                       {'capture_sim_time':pixels.capture_sim_time+.001},{'sim_deadline':.999},
                       {'wall_deadline':1000.005}):
            with self.subTest(update=update),self.assertRaises(ContractError):
                validate_native_observation(base,pixels,consumer=C,budget={**budget,**update},now=1000.01)
        o=deepcopy(base);o['wall_deadline']=1000.005
        with self.assertRaisesRegex(ContractError,'expired'):validate_native_observation(o,pixels,consumer=C,budget=budget,now=1000.01)


if __name__=='__main__':unittest.main()
