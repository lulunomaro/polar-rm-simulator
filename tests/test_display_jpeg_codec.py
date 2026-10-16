"""Display JPEG codec contracts; no inference, real-time or match acceptance."""
import base64
import io
import threading
import time
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from rm_match.platform_v2 import camera


@pytest.mark.parametrize('pattern',['black','red','blue','gradient','noise','strided'])
def test_actual_encoders_preserve_rgb_orientation_jpeg85_and_current_pinned_bytes(pattern):
    cv2=pytest.importorskip('cv2')
    rgb=np.zeros((1080,1440,3),dtype=np.uint8)
    if pattern=='red':rgb[:,:,0]=255
    if pattern=='blue':rgb[:,:,2]=255
    if pattern=='gradient':rgb[:]=np.arange(1440,dtype=np.uint16)[None,:,None]%256
    if pattern in ('noise','strided'):rgb=np.random.default_rng(17).integers(0,256,rgb.shape,dtype=np.uint8)
    if pattern=='strided':rgb=rgb[::-1,::-1,:]
    before=rgb.copy();threads=cv2.getNumThreads()
    expected=io.BytesIO();Image.fromarray(rgb).save(expected,format='JPEG',quality=85)
    old=camera.encode_display_jpeg(rgb);new=camera.encode_display_jpeg(rgb,'opencv_jpeg85_v1')
    assert old==expected.getvalue()
    # Pinned local build parity is checked explicitly, not generalized to every
    # possible JPEG library/version. Public contract stays JPEG85 RGB display.
    assert new==old
    decoded=np.asarray(Image.open(io.BytesIO(new)).convert('RGB'))
    assert decoded.shape==rgb.shape and np.array_equal(rgb,before)
    if pattern=='red':assert decoded[:,:,0].mean()>250 and decoded[:,:,2].mean()<3
    if pattern=='blue':assert decoded[:,:,2].mean()>250 and decoded[:,:,0].mean()<3
    assert cv2.getNumThreads()==threads


@pytest.mark.parametrize('codec',[None,False,True,0,1,{},[], 'jpeg','opencv','pillow_jpeg84'])
def test_unknown_codec_rejected_without_loading_encoder(codec):
    with patch.object(Image,'fromarray') as pillow,pytest.raises(ValueError,match='codec'):
        camera.encode_display_jpeg(np.zeros((1,1,3),dtype=np.uint8),codec)
    pillow.assert_not_called()


@pytest.mark.parametrize('codec',camera.DISPLAY_JPEG_CODECS)
def test_original_two_megabyte_limit_applies_to_each_codec(codec,monkeypatch):
    pytest.importorskip('cv2')
    monkeypatch.setattr(camera,'MAX_JPEG_BYTES',1)
    with pytest.raises(ValueError,match='capacity'):
        camera.encode_display_jpeg(np.zeros((32,32,3),dtype=np.uint8),codec)


def test_opencv_failure_does_not_silently_fallback():
    cv2=pytest.importorskip('cv2')
    with patch.object(cv2,'imencode',return_value=(False,None)),patch.object(Image,'fromarray') as fallback:
        with pytest.raises(ValueError,match='encoding failed'):
            camera.encode_display_jpeg(np.zeros((32,32,3),dtype=np.uint8),'opencv_jpeg85_v1')
    fallback.assert_not_called()


def provider(codec='opencv_jpeg85_v1'):
    from rm_match.platform_v2.backend import MuJoCoBackend
    b=MuJoCoBackend(camera=True);p=camera.CameraProvider(b._sim,display_jpeg_codec=codec)
    rid=b.robot_ids[0];p.episode=1;p.desired={rid:frozenset(('test-consumer',))}
    cap=camera.Capture(rid,1,9,.123,time.perf_counter(),frozenset(('test-consumer',)),None,{},())
    return b,p,rid,cap


def test_display_codec_failure_does_not_clear_raw_native_sensor_caches():
    cv2=pytest.importorskip('cv2');b,p,rid,cap=provider()
    raw=object();native=object();p.cache[rid]=raw;p.native_cache[rid]=native
    p.display_pending[rid]=(cap,np.zeros((32,32,3),dtype=np.uint8))
    try:
        with patch.object(cv2,'imencode',return_value=(False,None)):
            p.display_thread=threading.Thread(target=p._display_loop);p.display_thread.start();p.display_thread.join(1.)
        assert not p.display_thread.is_alive() and p.display_error=='ValueError'
        assert p.cache[rid] is raw and p.native_cache[rid] is native
        assert p.display_cache=={} and p.display_pending=={}
    finally:p.stop();assert p.wait_closed();b.close()


def test_stop_during_opencv_encode_never_publishes_old_display_or_restamps_capture():
    cv2=pytest.importorskip('cv2');b,p,rid,cap=provider();entered=threading.Event();release=threading.Event()
    original=cv2.imencode
    def blocked(*args):
        entered.set();assert release.wait(1.);return original(*args)
    p.display_pending[rid]=(cap,np.zeros((32,32,3),dtype=np.uint8))
    try:
        with patch.object(cv2,'imencode',side_effect=blocked):
            p.display_thread=threading.Thread(target=p._display_loop);p.display_thread.start()
            assert entered.wait(1.);p.stop();release.set();p.display_thread.join(1.)
        assert not p.display_thread.is_alive() and p.display_cache=={}
        assert p.rendered==0 and p.display_dropped==1 and p.display_error is None
    finally:release.set();p.stop();assert p.wait_closed();b.close()


def test_dto_keeps_original_capture_identity_and_default_selection():
    pytest.importorskip('cv2');b,p,rid,cap=provider()
    rgb=np.zeros((1080,1440,3),dtype=np.uint8)
    try:
        value=p._encode_display(cap,rgb)
        assert base64.b64decode(value['jpeg'])==camera.encode_display_jpeg(rgb,'pillow_jpeg85')
        saved=value['capture']
        assert saved.wall_time==cap.wall_time and saved.sim_time==cap.sim_time and saved.frame_seq==cap.frame_seq
        assert saved.robot_id==cap.robot_id and saved.episode==cap.episode and saved.consumers==cap.consumers
        assert p.status()['display_codec_identity']['quality']==85
        default=camera.CameraProvider(b._sim)
        assert default.display_jpeg_codec=='pillow_jpeg85' and default.thread is None
        default.stop()
    finally:p.stop();b.close()


def test_explicit_smoke_codec_keeps_old_gates_and_requires_actual_configuration_proof():
    from tools.smoke_wsl_native_live import build_plan,classify
    from tests.test_wsl_native_live_classification import measured
    assert 'display_jpeg_codec' not in build_plan('wsl_async_bgr_v3')['configuration']
    plan=build_plan('wsl_async_bgr_v3',display_jpeg_codec='opencv_jpeg85_v1')
    assert plan['configuration']['camera_native_budget_s']==.08 and plan['configuration']['server_input_window_s']==.15
    assert plan['criteria']['minimum_physics_rtf']==.98
    m=measured();m['configuration']=plan['configuration'];m['original_async_transactions_accounted']=True
    for wrong in (None,False,1,'true'):
        m['display_jpeg_codec_matches_plan']=wrong
        assert 'display_jpeg_codec_matches_plan' in classify(m,plan=plan)['rejected_or_failed_criteria']
    m['display_jpeg_codec_matches_plan']=True
    assert classify(m,plan=plan)['live_static_chain_qualified']
