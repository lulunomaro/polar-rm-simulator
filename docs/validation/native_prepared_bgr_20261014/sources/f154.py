"""Typed spin CPU contract only. No MuJoCo construction or stepping."""
import copy,math,unittest
from .spin import capability,parse_spin,requested_yaw,validate_mapping
from .control import ControlPlane,Rejected

def cap():
 return capability(dict.fromkeys(('joint_transmission','hinge_joint','own_qpos','own_dof','axis_positive_z','unit_gear','fixed_unit_gain','no_bias','no_dynamics','control_limited','no_force_limit'),True)|dict(ctrl_min=-20.,ctrl_max=20.))
def spin(direction='auto',speed=420):return dict(mode='spin_v1',frame='base_link',vx_mps=0.,vy_mps=0.,direction=direction,speed_dps=speed)
def manual(yaw=1):return dict(frame='base_link',vx_mps=0.,vy_mps=0.,wz_rps=yaw)
class Typed(unittest.TestCase):
 def setUp(self):
  self.now=100.;self.p=ControlPlane(['r'],clock=lambda:self.now,spin_capabilities={'r':cap()});self.s=self.p.open_session('operator','server_window_v1');self.token=self.s['token'];self.e=self.p.claim(self.token,'r',['motion'])['lease_epochs'];self.win=self.p.control_window(self.token,'r',self.e)
 def send(self,value,seq=0,**kw):return self.p.control(self.token,'r','motion',kw.get('epoch',self.e['motion']),seq,value,.15,kw.get('window_id',self.win['window_id']))
 def test_default_conversion(self):self.assertAlmostEqual(requested_yaw(parse_spin(spin(),cap())),420*math.pi/180)
 def test_directions(self):
  for d,k in [('auto',1),('ccw',1),('cw',-1)]:self.assertAlmostEqual(requested_yaw(parse_spin(spin(d,720),cap())),k*4*math.pi)
 def test_strict_schema(self):
  for v in [dict(spin(),wz_rps=0),dict(spin(),direction=True),dict(spin(),frame='world'),dict(spin(),speed_dps=True),dict(spin(),speed_dps=float('nan')),dict(spin(),speed_dps=10**999),dict(spin(),speed_dps=721),dict(spin(),speed_dps=119)]:
   with self.subTest(value=str(v)[:80]),self.assertRaises(Rejected):self.send(v)
  self.assertEqual(self.p.leases['r','motion'].seq,-1)
 def test_translation_normalized(self):
  v=parse_spin(dict(spin(),vx_mps=1,vy_mps=1),cap());self.assertAlmostEqual(math.hypot(v['vx_mps'],v['vy_mps']),1)
 def test_missing_cap_rejects(self):
  self.p._spin_capabilities={}
  with self.assertRaises(Rejected):self.send(spin())
 def test_legacy_rejects_spin(self):
  self.p.sessions[self.s['session_id']].control_profile='legacy_v2'
  with self.assertRaises(Rejected):self.send(spin())
 def test_manual_limits_unchanged(self):
  self.send(manual(4))
  with self.assertRaises(Rejected):self.send(manual(4.01),1)
 def test_manual_changes_not_mode_change(self):self.send(manual(4));self.send(manual(-4),1);self.assertFalse(self.p.leases['r','motion'].mode_fault)
 def test_mode_change_fault_only_after_valid_admission(self):
  self.send(spin())
  with self.assertRaises(Rejected):self.send(spin('cw'),900,window_id=99)
  self.assertFalse(self.p.leases['r','motion'].mode_fault);self.assertEqual(self.p.leases['r','motion'].seq,0)
  with self.assertRaises(Rejected):self.send(spin('cw'),1)
  self.assertTrue(self.p.leases['r','motion'].mode_fault);self.assertIsNone(self.p.leases['r','motion'].input);self.assertEqual(self.p.leases['r','motion'].seq,0)
 def test_mode_fault_survives_renew_window_unbind(self):
  self.send(spin())
  with self.assertRaises(Rejected):self.send(spin('ccw'),1)
  self.p.renew(self.token,'r',self.e);self.p.unbind(self.token,'r','navigation',self.e);self.win=self.p.control_window(self.token,'r',self.e)
  with self.assertRaises(Rejected):self.send(spin(),2)
  with self.assertRaises(Rejected):self.p.bind(self.token,'r','navigation',self.e,'nav_test',{})
 def test_release_restores_mode(self):
  self.send(spin());self.p.release(self.token,'r',self.e);self.e=self.p.claim(self.token,'r',['motion'])['lease_epochs'];self.win=self.p.control_window(self.token,'r',self.e);self.send(manual());self.assertFalse(self.p.leases['r','motion'].mode_fault)
 def test_exact_expiry_no_mode_fault(self):
  self.send(spin());self.now=self.win['expires_wall']
  with self.assertRaises(Rejected):self.send(spin('cw'),1)
  self.assertFalse(self.p.leases['r','motion'].mode_fault)
 def test_old_input_deadline_unchanged_by_new_window(self):
  self.send(spin());deadline=self.p.leases['r','motion'].input_expires;self.now+=.05;self.p.control_window(self.token,'r',self.e);self.assertEqual(deadline,self.p.leases['r','motion'].input_expires)
 def test_navigation_excludes_spin(self):
  self.p.bind(self.token,'r','navigation',self.e,'nav_rule_v1',{});self.win=self.p.control_window(self.token,'r',self.e)
  with self.assertRaises(Rejected):self.send(spin())
 def test_invalid_model_mapping_no_capability(self):
  self.assertFalse(capability({})['available']);self.assertFalse(validate_mapping({'ctrl_min':-20,'ctrl_max':20}))
if __name__=='__main__':unittest.main()
