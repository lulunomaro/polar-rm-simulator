import numpy as np
import pytest
from rm_match.camera_profile import SourceCameraProfile,SourceLensWarp,ideal_pixels


def test_source_profile_provenance_and_projection_inverse():
    cv2=pytest.importorskip('cv2');p=SourceCameraProfile()
    assert 'ASSUMED' in p.manifest()['calibration_resolution_association']
    points=np.array([[0,0,3],[.5,.2,3],[-.9,-.5,3]],float)
    distorted,_=cv2.projectPoints(points,np.zeros(3),np.zeros(3),p.K,np.array(p.distortion))
    ideal=ideal_pixels(distorted,p).reshape(-1,2)
    expected=(p.ideal_K@points.T).T;expected=expected[:,:2]/expected[:,2:]
    assert ideal==pytest.approx(expected,abs=1e-6)


def test_warp_uses_matching_rgb_and_explicit_black_coverage():
    pytest.importorskip('cv2');p=SourceCameraProfile(width=144,height=108,fx=172.2231837421459,fy=172.4876404292754,cx=69.68056440882832,cy=56.00821718351237)
    warp=SourceLensWarp(p);image=np.full((108,144,3),127,np.uint8)
    result=warp.apply(image)
    assert result.shape==image.shape and 0<warp.outside_fraction<.2
    assert np.any(result==0)
    with pytest.raises(ValueError):warp.apply(image.astype(float))


@pytest.mark.parametrize('overscan',[0,64])
def test_mujoco_native_render_and_lens_warp_projection(overscan):
    import os
    if os.environ.get('MUJOCO_GL')!='egl':
        pytest.skip('Set MUJOCO_GL=egl for native offscreen projection regression')
    mj=pytest.importorskip('mujoco');cv2=pytest.importorskip('cv2');p=SourceCameraProfile(overscan_pixels=overscan)
    xml=f'<mujoco><visual><global offwidth="{p.render_width}" offheight="{p.render_height}"/><headlight ambient="1 1 1" diffuse="0 0 0" specular="0 0 0"/></visual><worldbody><camera name="test" pos="0 0 0" xyaxes="0 -1 0 0 0 1" fovy="{p.ideal_fovy_degrees}"/><geom type="sphere" pos="3 -.3 .15" size=".01" rgba="1 0 0 1"/></worldbody></mujoco>'
    model=mj.MjModel.from_xml_string(xml);data=mj.MjData(model);mj.mj_forward(model,data)
    renderer=mj.Renderer(model,p.render_height,p.render_width)
    try:
        renderer.update_scene(data,camera='test');rgb=renderer.render().copy()
    finally:renderer.close()
    def centroid(image):
        ys,xs=np.where((image[:,:,0]>100)&(image[:,:,1]<20));return np.array([xs.mean(),ys.mean()])
    point=np.array([[.3,-.15,3.]])
    ideal=(p.ideal_K@point[0]);ideal=ideal[:2]/ideal[2]
    assert centroid(rgb)==pytest.approx(ideal,abs=.3)
    warped=SourceLensWarp(p).apply(rgb)
    projected,_=cv2.projectPoints(point,np.zeros(3),np.zeros(3),p.K,np.array(p.distortion))
    assert centroid(warped)==pytest.approx(projected.reshape(2),abs=.4)


def test_overscan_covers_every_native_output_pixel_without_black_border():
    pytest.importorskip('cv2');p=SourceCameraProfile(overscan_pixels=64);warp=SourceLensWarp(p)
    assert p.render_width==1568 and p.render_height==1208
    assert warp.outside_fraction==0
    rgb=np.full((p.render_height,p.render_width,3),127,np.uint8)
    output=warp.apply(rgb)
    assert output.shape==(1080,1440,3) and np.all(output==127)
    assert p.K==pytest.approx(SourceCameraProfile().K)
    assert p.distortion==SourceCameraProfile().distortion
    assert 'overscan64' in p.manifest()['name']
    with pytest.raises(ValueError,match='insufficient'):SourceLensWarp(SourceCameraProfile(overscan_pixels=1))
