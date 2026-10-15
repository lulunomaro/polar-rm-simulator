import copy
import unittest
from .contracts import ContractError,validate_action
from .adapters import default_registry,raw_observation
from .test_contracts import sample

class AdapterTests(unittest.TestCase):
    def make(self,aid,o,config=None):
        registry=default_registry();a=registry.create(aid,config or {});a.reset({k:o[k] for k in ('episode','robot_id','binding_epoch')});return a,registry.get(aid).descriptor
    def test_registry_labels_distinguish_algorithms(self):
        d={x['adapter_id']:x for x in default_registry().descriptors()}
        self.assertFalse(d['aim_native_rmcs_v1']['available']);self.assertTrue(d['aim_hold_test_v1']['test_only']);self.assertFalse(d['nav_rule_v1']['trajectory_input'])
    def test_registry_no_import_path_and_native_not_configurable(self):
        r=default_registry()
        with self.assertRaises(ContractError):r.create('os.system',{})
        with self.assertRaises(ContractError):r.create('aim_native_rmcs_v1',{'binary':'other'})
    def test_navigation_existing_rule_and_replace_with_stop(self):
        o=sample();a,d=self.make('nav_rule_v1',o,{'goal_world_m':[2.,0.]});v=validate_action(a.act(o),o,d);self.assertGreater(v['command']['vx_mps'],0);a.close()
        b,e=self.make('nav_stop_test_v1',o);self.assertEqual(validate_action(b.act(o),o,e)['command']['vx_mps'],0)
    def test_pixel_uses_serialized_rgb_only(self):
        o=sample(True);a,d=self.make('aim_pixel_baseline_v1',o);v=validate_action(a.act(o),o,d);self.assertTrue(v['command']['active']);self.assertFalse(v['command']['fire_permission']);self.assertIsNone(v['command']['confidence'])
    def test_pixel_missing_sensor_does_not_fake_detection(self):
        o=sample();a,d=self.make('aim_pixel_baseline_v1',o)
        with self.assertRaisesRegex(ContractError,'camera_unavailable'):a.act(o)
    def test_aim_own_hold_test_is_runnable_without_camera(self):
        o=sample();a,d=self.make('aim_hold_test_v1',o);v=validate_action(a.act(o),o,d);self.assertEqual(v['command']['yaw_rad'],o['own']['qpos'][3]);self.assertFalse(v['command']['fire_permission'])
    def test_hold_does_not_chase_measured_gravity_drift(self):
        o=sample();a,d=self.make("aim_hold_test_v1",o);first=a.act(o);o["own"]["qpos"][4]=-.02
        self.assertEqual(a.act(o)["command"]["pitch_rad"],first["command"]["pitch_rad"])
    def test_stale_pixels_and_rays_fail_closed(self):
        for aid,key in (("aim_pixel_baseline_v1","camera"),("nav_rule_v1","ranges")):
            o=sample(True);o["sensors"][key]["capture_sim_time"]=.1;a,d=self.make(aid,o)
            with self.assertRaisesRegex(ContractError,"stale"):a.act(o)
    def test_binding_context_cannot_cross_robot_or_epoch(self):
        o=sample();a,d=self.make('nav_stop_test_v1',o)
        for k,v in [('robot_id','blue_infantry'),('binding_epoch',2),('episode',2)]:
            n=copy.deepcopy(o);n[k]=v
            with self.assertRaises(ContractError):a.act(n)
    def test_mutable_registry_view_cannot_change_registration(self):
        r=default_registry();s=r.get('nav_stop_test_v1');s.descriptor['available']=False;self.assertTrue(r.get('nav_stop_test_v1').descriptor['available'])
    def test_no_model_in_reconstructed_existing_dto(self):
        r=raw_observation(sample(True));self.assertFalse(hasattr(r,'sim'));self.assertFalse(hasattr(r,'enemy_positions'));self.assertEqual(r.rgb.shape,(12,16,3))
if __name__=='__main__':unittest.main()
