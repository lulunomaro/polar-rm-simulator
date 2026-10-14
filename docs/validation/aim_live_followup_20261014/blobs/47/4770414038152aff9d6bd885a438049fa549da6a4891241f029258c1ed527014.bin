"""Bounded no-render physical driving-direction qualification; SIM only.

Initial own poses are named test conditions, never an operator control path.
Other robots are passive. No source detector, native Qt or full-match claim.
"""
from __future__ import annotations

import sys
if not __debug__ or sys.flags.optimize:
    raise SystemExit("Run without Python optimization: qualification assertions are required")

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path

import mujoco
import numpy as np

from .protocol import ControlGate
from .runtime import OperatorRuntime
from .server import BridgeState


class SimClock:
    def __init__(self):self.now=1000.
    def __call__(self):return self.now


def run_case(name,frame,robot,chassis_yaw,gimbal_yaw,forward,left):
    clock=SimClock();gate=ControlGate(robot,wall=clock,monotonic=clock,session_id='cpu-drive-'+name)
    runtime=OperatorRuntime(BridgeState(gate),render=False)
    try:
        sim=runtime.sim;runtime._control_tick=lambda:None
        # Isolate the selected robot in the unobstructed field centre; rotated
        # spawn poses can collide with their neighbouring passive robots.
        sim.data.qpos[sim.qindices[robot][0]]=-sim.spawns[robot][0]
        sim.data.qpos[sim.qindices[robot][1]]=-sim.spawns[robot][1]
        sim.data.qpos[sim.qindices[robot][2]]=chassis_yaw
        sim.data.qpos[sim.qindices[robot][3]]=gimbal_yaw
        sim.data.qvel[:]=0.
        mujoco.mj_forward(sim.model,sim.data)
        # Explicit initial test conditions only, before any control is accepted.
        start_q=sim.data.qpos[sim.qindices[robot]].copy()
        start_xy=sim.data.xpos[sim.body_ids[robot]][:2].copy()
        seq=0
        mode=dict(spin_enabled=False,spin_direction='auto',spin_speed_dps=420.,chassis_follow=frame)
        def send(*,deadman=True):
            nonlocal seq
            seq+=1
            return gate.accept(dict(session_id=gate.session_id,epoch=gate.epoch,robot_id=robot,
                seq=seq,sent_at_ms=clock()*1000,focus=True,deadman=deadman,fire=False,
                vx_mps=0.,vy_mps=0.,yaw_rate_rps=0.,pitch_rate_rps=0.,mode_request=mode,
                drive_axes=dict(forward_mps=forward if deadman else 0.,left_mps=left if deadman else 0.)))
        assert send(deadman=False)['accepted']
        assert send()['accepted']
        runtime._operator_command(robot)
        target=np.array(runtime.operator_modes['drive']['world_velocity_target_mps'])
        wanted_norm=float(np.linalg.norm(target));assert wanted_norm>0
        unit=target/wanted_norm
        steps=round(.4/float(sim.model.opt.timestep))
        peak_force=0.
        for step in range(steps):
            if step % max(1,round(.05/float(sim.model.opt.timestep))) == 0:assert send()['accepted']
            runtime.step_once();clock.now+=float(sim.model.opt.timestep)
            command=runtime.commands[robot]
            peak_force=max(peak_force,abs(command.force_x),abs(command.force_y))
            assert not command.fire
        end_q=sim.data.qpos[sim.qindices[robot]].copy()
        velocity=sim.data.qvel[sim.vindices[robot]][:2].copy()
        end_xy=sim.data.xpos[sim.body_ids[robot]][:2].copy()
        delta=end_xy-start_xy
        forward_displacement=float(delta@unit);forward_velocity=float(velocity@unit)
        cross_displacement=float(abs(delta[0]*unit[1]-delta[1]*unit[0]))
        cross_velocity=float(abs(velocity[0]*unit[1]-velocity[1]*unit[0]))
        assert forward_displacement>.01,(name,'nonpositive displacement',delta,target)
        assert forward_velocity>.05,(name,'nonpositive velocity',velocity,target)
        assert cross_displacement<max(.005,forward_displacement*.1),(name,'cross displacement',delta,target)
        assert cross_velocity<max(.02,forward_velocity*.1),(name,'cross velocity',velocity,target)
        assert peak_force<=60.
        before_release=asdict(runtime.commands[robot])
        assert send(deadman=False)['accepted'];runtime.step_once()
        after_release=asdict(runtime.commands[robot])
        assert after_release['force_x']==after_release['force_y']==after_release['yaw_torque']==0.
        assert not after_release['fire'];assert not runtime.operator_modes['drive']['active']
        return dict(name=name,frame=frame,robot_id=robot,duration_s=steps*float(sim.model.opt.timestep),
            initial_own_qpos=start_q.tolist(),final_own_qpos=end_q.tolist(),
            initial_world_xy=start_xy.tolist(),final_world_xy=end_xy.tolist(),
            drive_axes=dict(forward_mps=forward,left_mps=left),world_target_velocity_mps=target.tolist(),
            measured_displacement_m=delta.tolist(),measured_world_velocity_mps=velocity.tolist(),
            displacement_along_target_m=forward_displacement,velocity_along_target_mps=forward_velocity,
            cross_displacement_m=cross_displacement,cross_velocity_mps=cross_velocity,peak_force_n=peak_force,
            before_release=before_release,after_release=after_release,passed=True)
    finally:runtime.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    cases=[('free_45_forward','free','red_infantry',math.pi/4,0.,.6,0.),
           ('free_90_left','free','red_infantry',math.pi/2,0.,0.,.6),
           ('free_180_negative','free','red_infantry',math.pi,0.,-.6,0.),
           ('field_red_180','field','red_infantry',math.pi,.4,.6,0.),
           ('field_blue_180','field','blue_infantry',math.pi,.4,.6,0.),
           ('gimbal_45_plus_45','gimbal','red_infantry',math.pi/4,math.pi/4,.6,0.),
           ('gimbal_negative_left','gimbal','red_infantry',0.,math.pi/2,0.,-.6)]
    root=Path(__file__).parent
    source_hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest()
                   for name in ('protocol.py','runtime.py','source_runtime.py','qa_drive_frames.py')}
    results=[run_case(*case) for case in cases]
    report=dict(schema='polar.sim.drive_frames.cpu_physics.v1',simulation_only=True,hardware_transport=False,
        rendered=False,source_detector_executed=False,original_client_executed=False,
        full_match=False,benchmark_claim=False,automatic_chassis_yaw_follow=False,
        world_stabilized_gimbal=False,other_robots='passive_in_named_QA_only',
        mujoco_version=mujoco.__version__,source_sha256=source_hashes,case_count=len(results),
        cases=results,all_passed=all(row['passed'] for row in results))
    (args.out/'results.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(case_count=len(results),all_passed=report['all_passed'],out=str(args.out))))


if __name__=='__main__':main()
