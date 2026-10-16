"""Export current static simulated gimbal/muzzle design; no GL, physics steps or NN."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def capture_mounts():
    import mujoco
    from rm_match.platform_v2.backend import MuJoCoBackend
    files=['rm_match/harness.xml','rm_match/match_model.py','rm_match/platform_v2/camera.py']
    before={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in files}
    b=MuJoCoBackend(camera=True)
    def named(kind,name):
     i=mujoco.mj_name2id(b._sim.model,kind,name);assert i>=0;return i
    try:
     m=b._sim.model;rows={}
     for rid in b.robot_ids:
      yaw=named(mujoco.mjtObj.mjOBJ_BODY,rid+'__yaw')
      pitch=named(mujoco.mjtObj.mjOBJ_BODY,rid+'__pitch')
      jy=named(mujoco.mjtObj.mjOBJ_JOINT,rid+'__gimbal_yaw')
      jp=named(mujoco.mjtObj.mjOBJ_JOINT,rid+'__gimbal_pitch')
      site=named(mujoco.mjtObj.mjOBJ_SITE,rid+'__muzzle')
      assert int(m.body_parentid[pitch])==yaw and int(m.jnt_bodyid[jy])==yaw and int(m.jnt_bodyid[jp])==pitch
      assert int(m.site_bodyid[site])==pitch
      assert m.jnt_axis[jy].tolist()==[0.,0.,1.] and m.jnt_axis[jp].tolist()==[0.,-1.,0.]
      assert m.jnt_pos[jy].tolist()==[0.,0.,0.] and m.jnt_pos[jp].tolist()==[0.,0.,0.]
      assert m.body_quat[yaw].tolist()==[1.,0.,0.,0.] and m.body_quat[pitch].tolist()==[1.,0.,0.,0.]
      rows[rid]=dict(parent_frame='gimbal_link',child_frame='shooter_link',
       translation_m=m.site_pos[site].tolist(),rotation_xyzw=m.site_quat[site][[1,2,3,0]].tolist(),
       source_site=rid+'__muzzle',source_body=rid+'__pitch',pitch_positive='up',pitch_joint_axis=m.jnt_axis[jp].tolist(),
       kinematics=dict(origin_frame='gimbal_aim_origin',origin_definition='chassis_fixed_frame_at_zero_yaw_joint_origin',
        yaw_frame='gimbal_yaw',pitch_frame='gimbal_link',
        chassis_to_origin_translation_m=m.body_pos[yaw].tolist(),chassis_to_origin_rotation_xyzw=m.body_quat[yaw][[1,2,3,0]].tolist(),
        origin_to_yaw_translation_m=m.jnt_pos[jy].tolist(),origin_to_yaw_rotation_xyzw=[0.,0.,0.,1.],
        yaw_to_pitch_translation_m=m.body_pos[pitch].tolist(),yaw_to_pitch_rotation_xyzw=m.body_quat[pitch][[1,2,3,0]].tolist(),
        yaw_joint_axis=m.jnt_axis[jy].tolist(),pitch_joint_pivot_m=m.jnt_pos[jp].tolist(),
        source_yaw_body=rid+'__yaw',source_yaw_joint=rid+'__gimbal_yaw',source_pitch_joint=rid+'__gimbal_pitch'))
     result=dict(schema='polar.sim.aim-mount-calibration.v2',origin='static_simulation_model_design_not_hardware_calibration',
      source_sha256=before,robots=rows,physics_steps=0,NN=0,renderer=False)
    finally:b.close()
    assert before=={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in files}
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True,help='Fresh output directory; original mount evidence is never overwritten')
    args=parser.parse_args(argv);out=args.out.absolute()
    out.mkdir(parents=True,exist_ok=False)
    result=capture_mounts()
    raw=(json.dumps(result,indent=2)+'\n').encode()
    (out/'MOUNTS.json').write_bytes(raw)
    (out/'capture.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(path=str(out/'MOUNTS.json'),sha256=hashlib.sha256(raw).hexdigest(),
        robots=len(result['robots']),physics_steps=0,NN=0,renderer=False)))
    return 0


if __name__=='__main__':raise SystemExit(main())
