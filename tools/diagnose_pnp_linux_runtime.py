#!/usr/bin/env python3
"""Bounded Linux Qt/EGL camera preflight for the actual native OFFLINE24 run."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args();out=args.out.resolve()
    if sys.platform!="linux":raise ValueError("Linux runtime probe")
    if out.exists():raise ValueError("Choose a fresh output directory")
    out.mkdir(parents=True)
    os.environ.setdefault("MUJOCO_GL","egl");os.environ["QT_QPA_PLATFORM"]="offscreen"
    from PySide6 import QtCore,QtWidgets
    app=QtWidgets.QApplication(["offline-native-runtime-probe"]);app.processEvents()
    import cv2,numpy as np,mujoco
    from rm_match.platform_v2.backend import MuJoCoBackend
    from rm_match.platform_v2.camera import Capture,MuJoCoCameraRenderer
    from rm_match.camera_profile import SourceCameraProfile
    sim=MuJoCoBackend(camera=True)._sim;profile=SourceCameraProfile(overscan_pixels=64)
    started=time.monotonic();renderer=MuJoCoCameraRenderer(sim.model,profile)
    initialized=time.monotonic()
    try:
        cap=Capture("red_sentry",sim.episode,1,sim.time,time.monotonic(),frozenset(),sim.data,{},())
        rgb=renderer.render(cap);identity=renderer.identity
    finally:renderer.close()
    ended=time.monotonic();bgr=np.ascontiguousarray(rgb[:,:,::-1]);cv2.imwrite(str(out/"actual_camera.png"),bgr)
    report={"schema":"rmcs-linux-native-runtime-probe-v1","status":"passed",
        "qt_version":QtCore.qVersion(),"mujoco_version":mujoco.__version__,"opencv_version":cv2.__version__,
        "python":sys.version,"python_executable":sys.executable,"MUJOCO_GL":os.environ["MUJOCO_GL"],
        "renderer_identity":identity,"renderer_init_seconds":initialized-started,"render_and_close_seconds":ended-initialized,
        "actual_bgr_shape":list(bgr.shape),"actual_bgr_sha256":hashlib.sha256(bgr.tobytes()).hexdigest(),
        "physics_steps":0,"model_inferences":0,"visible_client":False,
        "scope":"Runtime prerequisite only; actual one camera render, no native control or realtime qualification"}
    (out/"RUNTIME_PROBE.json").write_text(json.dumps(report,indent=2)+"\n");print(json.dumps(report,indent=2))
    app.quit()


if __name__=="__main__":main()
