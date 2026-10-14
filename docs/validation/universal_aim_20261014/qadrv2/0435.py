#!/usr/bin/env python3
"""Render a predetermined, bounded PnP holdout with the actual camera pipeline.

Algorithm files contain BGR pixels plus camera calibration and own state only.
Target geometry is saved separately for OFFLINE evaluation, never native input.
No inference, physics integration, source-optics changes or image painting.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

# Frozen before rendering or measuring the candidate. Distances are chassis
# separations, not inferred ranges. Lighting changes are actual scene lighting.
CASES=[
    dict(name="near_2p1",distance=2.1,yaw=0.,light=1.,negative=False),
    dict(name="mid_2p8",distance=2.8,yaw=0.,light=1.,negative=False),
    dict(name="far_3p5",distance=3.5,yaw=0.,light=1.,negative=False),
    dict(name="far_4p5",distance=4.5,yaw=0.,light=1.,negative=False),
    dict(name="yaw_plus20",distance=2.8,yaw=20.,light=1.,negative=False),
    dict(name="yaw_minus20",distance=2.8,yaw=-20.,light=1.,negative=False),
    dict(name="light_dim",distance=2.8,yaw=0.,light=.6,negative=False),
    dict(name="light_bright",distance=2.8,yaw=0.,light=1.3,negative=False),
    dict(name="blank",distance=-3.,yaw=0.,light=1.,negative=True),
    dict(name="full_occlusion",distance=2.8,yaw=0.,light=1.,negative=True),
    dict(name="one_bar_occlusion",distance=2.8,yaw=0.,light=1.,negative=True),
]
INDEPENDENT_CASES=[
    dict(name="near_2p25",distance=2.25,yaw=0.,light=1.,negative=False),
    dict(name="mid_3p05",distance=3.05,yaw=0.,light=1.,negative=False),
    dict(name="far_3p85",distance=3.85,yaw=0.,light=1.,negative=False),
    dict(name="far_4p2",distance=4.2,yaw=0.,light=1.,negative=False),
    dict(name="yaw_plus12",distance=2.65,yaw=12.,light=1.,negative=False),
    dict(name="yaw_minus28",distance=3.1,yaw=-28.,light=1.,negative=False),
    dict(name="light_dim_0p75",distance=3.05,yaw=0.,light=.75,negative=False),
    dict(name="light_bright_1p15",distance=3.05,yaw=0.,light=1.15,negative=False),
    dict(name="blank_2",distance=-2.5,yaw=0.,light=1.,negative=True),
    dict(name="full_occlusion_2",distance=3.05,yaw=0.,light=1.,negative=True),
    dict(name="one_bar_occlusion_2",distance=3.05,yaw=0.,light=1.,negative=True),
]


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--suite",choices=("original","independent2"),default="original")
    args=ap.parse_args();out=args.out.resolve()
    if out.exists():raise ValueError("Choose a fresh output directory")
    out.mkdir(parents=True)
    cases=CASES if args.suite=="original" else INDEPENDENT_CASES
    (out/"PREDECLARED_CASES.json").write_text(json.dumps(cases,indent=2)+"\n")
    import numpy as np,cv2,mujoco
    from rm_match.platform_v2.camera import camera_model_xml,MuJoCoCameraRenderer,Capture
    from rm_match.camera_profile import SourceCameraProfile
    from rm_match.match_engine import MatchSimulation
    from rm_match.match_model import SPAWNS,ROSTER
    profile=SourceCameraProfile(overscan_pixels=64)
    source_xml=camera_model_xml();(out/"BASE_MODEL.xml").write_text(source_xml)
    algorithm_manifest=[];offline_truth=[];renderers=[];fov_checks=[]
    for index,case in enumerate(cases):
        node=ET.fromstring(source_xml)
        for light in node.findall(".//light"):
            values=[float(v) for v in light.get("diffuse",".7 .7 .7").split()]
            light.set("diffuse"," ".join(str(min(1.,v*case["light"])) for v in values))
        if "occlusion" in case["name"]:
            # Actual opaque object between camera and armor, rather than an
            # altered sensor image. Partial occlusion targets one physical bar.
            partial=case["name"].startswith("one_bar_occlusion")
            xpos=-3.5+case["distance"]-.4
            ypos=3.+(.0675 if partial else 0.)
            ET.SubElement(node.find("worldbody"),"geom",name="holdout_physical_occluder",
                type="box",pos=f"{xpos} {ypos} .35",
                size=".02 .023 .085" if partial else ".02 .2 .15",rgba=".25 .25 .25 1",contype="0",conaffinity="0")
        xml=ET.tostring(node,encoding="unicode")
        directory=out/case["name"];directory.mkdir();(directory/"scene.xml").write_text(xml)
        sim=MatchSimulation(render=False,model_xml=xml)
        for rid,team,role in ROSTER:
            ids=sim.qindices[rid]
            if rid=="red_sentry":xy=(-3.5,3.);yaw=0.
            elif rid=="blue_infantry":xy=(-3.5+case["distance"],3.);yaw=math.pi+math.radians(case["yaw"])
            else:xy=(50.,50.);yaw=SPAWNS[rid][2]
            sim.data.qpos[ids[0]]=xy[0]-SPAWNS[rid][0]
            sim.data.qpos[ids[1]]=xy[1]-SPAWNS[rid][1]
            sim.data.qpos[ids[2]]=yaw
        sim.data.qpos[sim.qindices["red_sentry"][3]]=0.
        # The existing MuJoCo joint axis is (0,-1,0): negative pitch looks down.
        sim.data.qpos[sim.qindices["red_sentry"][4]]=-.15
        sim.data.qvel[:]=0.;mujoco.mj_forward(sim.model,sim.data)
        camid=sim.model.camera("red_sentry__aim").id
        rotation=sim.data.cam_xmat[camid].reshape(3,3)@np.diag([1.,-1.,-1.])
        target=sim.model.body("blue_infantry__visual_front").id
        local=np.array([[.004,.0675,.028],[.004,.0675,-.028],[.004,-.0675,-.028],[.004,-.0675,.028]])
        world=local@sim.data.xmat[target].reshape(3,3).T+sim.data.xpos[target]
        optical=(world-sim.data.cam_xpos[camid])@rotation
        pixels,_=cv2.projectPoints(optical,np.zeros(3),np.zeros(3),profile.K,np.array(profile.distortion));pixels=pixels.reshape(-1,2)
        in_fov=bool((optical[:,2]>0).all() and (pixels[:,0]>=0).all() and
                    (pixels[:,0]<profile.width).all() and (pixels[:,1]>=0).all() and (pixels[:,1]<profile.height).all())
        fov_checks.append({"name":case["name"],"negative":case["negative"],"in_fov":in_fov})
        if not case["negative"] and not in_fov:raise ValueError("Positive scene target outside FOV: "+case["name"])
        renderer=MuJoCoCameraRenderer(sim.model,profile)
        try:
            cap=Capture("red_sentry",sim.episode,index+1,0.,time.monotonic(),frozenset(),sim.data,{},())
            rgb=renderer.render(cap)
            renderers.append(renderer.identity)
        finally:renderer.close()
        bgr=np.ascontiguousarray(rgb[:,:,::-1]);frame=directory/"frame.bgr";frame.write_bytes(bgr.tobytes())
        cv2.imwrite(str(directory/"frame.png"),bgr)
        own=sim.data.qpos[list(sim.qindices["red_sentry"])]
        origin=sim.data.xpos[sim.body_ids["red_sentry"]]
        metadata={"K":profile.K.ravel().tolist(),"D":list(profile.distortion),
                  "qpos":own.tolist(),"odom":[float(origin[0]),float(origin[1]),float(own[2])],
                  "frame_sha256":digest(frame)}
        (directory/"metadata.json").write_text(json.dumps(metadata,indent=2)+"\n")
        algorithm_manifest.append({"name":case["name"],"frame":f"{case['name']}/frame.bgr",
            "metadata":f"{case['name']}/metadata.json","frame_sha256":digest(frame),
            "metadata_sha256":digest(directory/"metadata.json")})
        # Isolated evaluation truth. The native runner receives no path or
        # contents from this file and invokes algorithms before reading it.
        left=pixels[np.argsort(pixels[:,0])[:2]];left=left[np.argsort(left[:,1])]
        right=pixels[np.argsort(pixels[:,0])[2:]];right=right[np.argsort(right[:,1])]
        ordered=np.array([left[0],left[1],right[1],right[0]])
        center=np.array([.004,0.,0.])@sim.data.xmat[target].reshape(3,3).T+sim.data.xpos[target]
        native_origin=sim.data.xpos[sim.model.body("red_sentry__pitch").id]
        offline_truth.append({**case,"source_shape_corners_px":ordered.tolist(),
            "native_frame_center_m":(center-native_origin).tolist(),
            "world_target_center_m":center.tolist(),"world_pitchlink_origin_m":native_origin.tolist(),
            "geometry_scope":"Offline PnP-source-shape comparison, source optical 55mm approximates original 56mm object span; no native input"})
        print(case["name"],digest(frame),flush=True)
    (out/"ALGORITHM_INPUTS.json").write_text(json.dumps(algorithm_manifest,indent=2)+"\n")
    (out/"OFFLINE_EVALUATION_TRUTH.json").write_text(json.dumps(offline_truth,indent=2)+"\n")
    (out/"FIXTURE_FOV_CHECKS.json").write_text(json.dumps(fov_checks,indent=2)+"\n")
    (out/"RENDER_BINDING.json").write_text(json.dumps({"schema":"rmcs-pnp-render-holdout-v1",
        "case_count":len(cases),"suite":args.suite,"source_xml_sha256":digest(out/"BASE_MODEL.xml"),
        "predeclared_cases_sha256":digest(out/"PREDECLARED_CASES.json"),
        "algorithm_inputs_sha256":digest(out/"ALGORITHM_INPUTS.json"),"renderer_identities":renderers,
        "profile":profile.manifest(),"physics_steps":0,"real_mujoco_render":True,
        "positive_fov_check_required":True,"own_gimbal_pitch_radians":-.15,
        "image_painting":False,"model_inferences":0,"truth_isolated_from_algorithm_inputs":True},indent=2)+"\n")


if __name__=="__main__":main()
