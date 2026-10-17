"""Exposure ownership and original float-remap fidelity, never NN acceptance."""
import hashlib
import os
import time
from types import SimpleNamespace

import numpy as np
import pytest

from rm_match.camera_profile import SourceCameraProfile,SourceLensWarp
from rm_match.platform_v2.camera import MuJoCoCameraRenderer,Capture


@pytest.mark.parametrize('late',[None,False,True,1,2,0.,'0'])
def test_good_physical_frames_do_not_hide_any_late_active_physics_call(late):
    from tests.test_wsl_native_live_classification import smoke,measured
    m=measured();m['late_physical_active_calls']=late
    result=smoke.classify(m)
    assert not result['live_static_chain_qualified'] and not result['checks']['no_late_physical_active_calls']


@pytest.mark.parametrize('layout',['contiguous','rows_reversed','columns_reversed','transposed'])
def test_float_remap_owns_each_exposure_and_cannot_alias_render_or_prior_frames(layout):
    cv2=pytest.importorskip('cv2')
    p=SourceCameraProfile(width=144,height=108,fx=172.,fy=172.,cx=70.,cy=56.)
    warp=SourceLensWarp(p);rng=np.random.default_rng(3017)
    shape=(p.render_width,p.render_height,3) if layout=='transposed' else (p.render_height,p.render_width,3)
    source=rng.integers(0,256,shape,dtype=np.uint8)
    rgb={'contiguous':lambda:source,'rows_reversed':lambda:source[::-1],
        'columns_reversed':lambda:source[:,::-1],'transposed':lambda:source.transpose(1,0,2)}[layout]()
    original=rgb.copy()
    a=warp.apply(rgb)
    reference=cv2.remap(rgb,warp.map_x,warp.map_y,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=(0,0,0)).copy()
    assert np.array_equal(a,reference) and a.flags.owndata and a.flags.c_contiguous
    assert not np.shares_memory(a,rgb)
    b=warp.apply(rgb);assert not np.shares_memory(a,b)
    a[:]=0
    assert np.array_equal(b,reference) and np.array_equal(rgb,original)
    rgb[:]=255
    assert np.array_equal(b,reference)


def test_renderer_preserves_prior_exposure_when_source_and_next_frame_are_reused():
    pytest.importorskip('cv2')
    p=SourceCameraProfile(width=144,height=108,fx=172.,fy=172.,cx=70.,cy=56.)
    ideal=np.full((108,144,3),77,np.uint8)
    class Renderer:
        scene=SimpleNamespace(ngeom=0,maxgeom=0)
        def update_scene(self,*a,**kw):pass
        def render(self):return ideal
    # Only GL is synthetic here: exercise the real renderer method and real
    # float lens warp with a reused readback array, like a renderer buffer.
    r=object.__new__(MuJoCoCameraRenderer);r.renderer=Renderer();r.mujoco=None;r.warp=SourceLensWarp(p)
    cap=SimpleNamespace(buffer=None,robot_id='alpha',projectiles=())
    a=r.render(cap);saved=a.copy();ideal[:]=199;b=r.render(cap)
    assert np.array_equal(a,saved) and not np.shares_memory(a,b)
    b[:]=0;assert np.array_equal(a,saved)


@pytest.mark.skipif(os.environ.get('POLAR_TEST_EXPOSURE_OWNERSHIP')!='1',reason='Explicit actual NVIDIA GL exposure test')
def test_actual_nvidia_exposures_match_same_readback_old_copy_and_remain_detached():
    import json
    import mujoco
    from rm_match.platform_v2.backend import MuJoCoBackend
    backend=MuJoCoBackend(camera=True);sim=backend._sim
    renderer=MuJoCoCameraRenderer(sim.model,SourceCameraProfile(overscan_pixels=64))
    apply=renderer.warp.apply;originals=[];results=[];retained=[];inputs=[]
    def reference(rgb):
        image=apply(rgb);originals.append(image.copy());inputs.append(rgb)
        return image
    renderer.warp.apply=reference
    try:
        assert 'NVIDIA' in str(renderer.identity)
        for index in range(8):
            rid=sim.robot_ids[index%6]
            if index==7:sim.reset()
            else:
                for _ in range(index*3):mujoco.mj_step(sim.model,sim.data)
            mujoco.mj_forward(sim.model,sim.data)
            cap=Capture(rid,int(sim.episode),index+1,float(sim.data.time),time.perf_counter(),frozenset(),sim.data,{},
                ((.03,np.array([-1.,2.,.5])),) if index%2 else ())
            state=[v.copy() for v in (sim.data.qpos,sim.data.qvel,sim.data.ctrl)]
            actual=renderer.render(cap);old=originals[-1];ideal=inputs.pop()
            assert np.array_equal(actual,old) and actual.flags.owndata and actual.flags.c_contiguous
            assert not np.shares_memory(actual,ideal)
            assert all(not np.shares_memory(actual,earlier) for earlier in retained)
            retained.append(actual)
            assert all(np.array_equal(frame,expected) for frame,expected in zip(retained,originals))
            assert all(np.array_equal(a,b) for a,b in zip(state,(sim.data.qpos,sim.data.qvel,sim.data.ctrl)))
            results.append(dict(robot_id=rid,episode=sim.episode,frame=index+1,
                rgb_sha256=hashlib.sha256(actual).hexdigest(),reference_rgb_sha256=hashlib.sha256(old).hexdigest(),
                same_readback_reference=True,prior_exposures_unchanged=True))
        print(json.dumps(dict(identity=renderer.identity,exposures=results,scope='Actual GL, same readback exact old-copy comparison and ownership only, no aim/RTF qualification')))
    finally:renderer.close();backend.close()
