"""Real model metadata only: no MjData, simulation, integration or renderer."""
import unittest
from types import SimpleNamespace
from .backend import MuJoCoBackend
class ModelMetadata(unittest.TestCase):
 def test_existing_model_yaw_mapping_and_unknown_axis(self):
  import mujoco
  from ..match_model import make_match_xml,ROSTER
  model=mujoco.MjModel.from_xml_string(make_match_xml())
  ids=tuple(r[0] for r in ROSTER);joints=('base_x','base_y','base_yaw','gimbal_yaw','gimbal_pitch');actuators=('drive_x','drive_y','drive_yaw','aim_yaw','aim_pitch')
  sim=SimpleNamespace(model=model,robot_ids=ids,qindices={r:[model.jnt_qposadr[model.joint(r+'__'+n).id]for n in joints]for r in ids},vindices={r:[model.jnt_dofadr[model.joint(r+'__'+n).id]for n in joints]for r in ids},aindices={r:[model.actuator(r+'__'+n).id for n in actuators]for r in ids})
  c=MuJoCoBackend(sim).declared_spin_capabilities();self.assertTrue(all(c[r]['available'] for r in ids));self.assertTrue(all(c[r]['yaw_torque_ctrlrange']==[-20.,20.]for r in ids))
  # Alter only this disposable metadata fixture, never a running model/vehicle.
  model.jnt_axis[model.joint(ids[0]+'__base_yaw').id]=[0.,1.,0.]
  self.assertFalse(MuJoCoBackend(sim).declared_spin_capabilities()[ids[0]]['available'])
if __name__=='__main__':unittest.main()
