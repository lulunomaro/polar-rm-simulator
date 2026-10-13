"""CPU-only real judge -> client consumer/controller -> leased mode integration.

Hits are explicit synthetic referee inputs, not physical projectile evidence.
No renderer, device transport, firing policy or world-groundtruth aiming is used.
"""
from pathlib import Path
import sys,unittest,argparse
from types import SimpleNamespace
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bridge-root',type=Path,required=True)
parser.add_argument('--client-root',type=Path,required=True)
args,remaining=parser.parse_known_args()
sys.path[:0]=[str(args.bridge_root.resolve()),str(args.client_root.resolve())]
from rm_match.operator.protocol import ControlGate
from rm_match.operator.server import BridgeState
from rm_match.operator.runtime import OperatorRuntime
from rm_match.operator.test_protocol import Clock
from rm_client.sim_projectile_damage import ProjectileDamageConsumer
from rm_client.auto_spin import ProjectileHitSpinController
from rm_client.model import build_default_registry

class CrossSideTests(unittest.TestCase):
 def setUp(self):
  self.clock=Clock();self.gate=ControlGate(wall=self.clock,monotonic=self.clock)
  self.bridge=BridgeState(self.gate);self.runtime=OperatorRuntime(self.bridge,render=False)
  self.consumer=ProjectileDamageConsumer();self.controller=ProjectileHitSpinController()
  self.registry=build_default_registry(discover_devices=False);self.feature=self.registry.get('AutoSpinOnHit');self.feature.enabled=True
  self.feature.get_setting('Power Guard').value=False # Unsupported SIM model, explicit test setting.
  self.seq=0;self.send(False);self.publish()
 def tearDown(self):self.runtime.close()
 def send(self,spin,*,focus=True,origin='on_hit'):
  self.seq+=1;g=self.gate
  packet=dict(session_id=g.session_id,epoch=g.epoch,robot_id=g.robot_id,seq=self.seq,sent_at_ms=self.clock()*1000,
   focus=focus,deadman=focus,fire=False,vx_mps=0.,vy_mps=0.,yaw_rate_rps=0.,pitch_rate_rps=0.,
   mode_request=dict(spin_enabled=spin,spin_direction='ccw',spin_speed_dps=120.,chassis_follow='free',spin_origin=origin))
  result=g.accept(packet);self.assertTrue(result['accepted']);return result
 def publish(self):
  r=self.runtime;r.commands[self.gate.robot_id]=r._operator_command(self.gate.robot_id);r._publish();return self.bridge.snapshot()
 def hit(self,*,hp=None):
  j=self.runtime.sim.judge;rid=self.gate.robot_id
  if hp is not None:j.robots[rid].hp=hp
  self.assertTrue(j.fire('blue_sentry','synthetic-hit',0.))
  self.assertTrue(j.apply_hit('synthetic-hit','blue_sentry',rid,'front',20.,0.))
  return self.publish()
 def delta(self,t,live=True):
  return self.consumer.observe(t['own_damage'],self.gate.session(),t['sim_time'],live=live)
 def directive(self,d,*,now=0.,spin=False):
  state=SimpleNamespace(projectile_hit_revision=d.revision,last_projectile_damage_delta=d.damage,
   current_health=self.runtime.sim.judge.robots[self.gate.robot_id].hp,current_stage='MATCH')
  return self.controller.update(state,self.feature,spin_enabled=spin,referee_link=True,now=now)
 def test_actual_credit_triggers_original_controller_and_leased_spin(self):
  self.assertEqual(self.delta(self.publish()).reason,'baseline')
  delta=self.delta(self.hit());self.assertEqual(delta.damage,20.)
  directive=self.directive(delta);self.assertEqual(directive.action,'enable')
  self.send(True);t=self.publish();self.assertTrue(t['operator_modes']['effective']['spin_enabled'])
  self.assertEqual(t['operator_modes']['effective']['spin_origin'],'on_hit')
  self.assertGreater(self.runtime.commands[self.gate.robot_id].yaw_torque,0.)
  self.assertFalse(self.runtime.commands[self.gate.robot_id].fire)
  self.assertEqual(self.delta(t).reason,'duplicate')
  self.clock.advance(.3);t=self.publish();self.assertFalse(t['operator_modes']['effective']['spin_enabled'])
  self.assertIsNone(t['operator_modes']['effective']['spin_origin'])
 def test_reconnect_baseline_cannot_replay_real_hit(self):
  self.delta(self.publish());t=self.hit();self.consumer.reset()
  d=self.delta(t);self.assertEqual(d.reason,'baseline');self.assertEqual(d.damage,0)
  self.assertEqual(self.directive(d).action,'none')
 def test_epoch_switch_cannot_replay_credit(self):
  self.delta(self.publish());self.hit();self.gate.new_epoch();self.send(False)
  d=self.delta(self.publish());self.assertEqual(d.reason,'identity_changed');self.assertEqual(d.damage,0)
 def test_fractional_credit_is_not_rounded_up_or_rejected(self):
  self.delta(self.publish());d=self.delta(self.hit(hp=.5));self.assertEqual(d.damage,.5)
  self.assertEqual(self.directive(d).action,'none')
 def test_default_unsupported_power_guard_blocks_without_fake_buffer(self):
  self.feature.get_setting('Power Guard').value=True
  self.delta(self.publish());d=self.delta(self.hit());self.assertEqual(self.directive(d).action,'none')
  self.assertEqual(self.controller.last_reason,'LOW BUFFER ENERGY')

if __name__=='__main__':unittest.main(argv=[sys.argv[0],*remaining])
