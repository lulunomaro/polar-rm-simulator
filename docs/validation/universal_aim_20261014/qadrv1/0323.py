"""Optical role correction is independent of dynamics and detector score."""
import numpy as np
import mujoco
from rm_match.match_model import make_match_xml


def test_role_v23_keeps_every_collision_and_dynamic_parameter():
    base=mujoco.MjModel.from_xml_string(make_match_xml('baseline'))
    corrected=mujoco.MjModel.from_xml_string(make_match_xml('role_v23'))
    assert base.nq==corrected.nq and base.nv==corrected.nv
    for key in ('body_mass','body_inertia','body_ipos','body_iquat','jnt_pos','jnt_axis','actuator_gainprm'):
        np.testing.assert_allclose(getattr(base,key),getattr(corrected,key),atol=1e-12,rtol=0)
    for gid in range(base.ngeom):
        if not base.geom_contype[gid] and not base.geom_conaffinity[gid]:continue
        name=mujoco.mj_id2name(base,mujoco.mjtObj.mjOBJ_GEOM,gid)
        other=corrected.geom(name).id
        for key in ('geom_type','geom_size','geom_pos','geom_quat','geom_friction','geom_contype','geom_conaffinity'):
            np.testing.assert_allclose(getattr(base,key)[gid],getattr(corrected,key)[other],atol=1e-12,rtol=0)


def test_both_sentries_use_turret_not_number_three_or_seven_with_fixed_optics():
    import xml.etree.ElementTree as ET
    root=ET.fromstring(make_match_xml('role_v23'))
    for team in ('red','blue'):
        for side in ('front','back','left','right'):
            name=f'{team}_sentry__visual_{side}'
            body=root.find(f'.//body[@name="{name}"]')
            meshes=[g.get('mesh','') for g in body.findall('geom')]
            assert any('_original_turret_' in m for m in meshes)
            assert not any('_paint_' in m for m in meshes)
            for suffix in ('_led','_luminous_core'):
                assert root.find(f'asset/material[@name="{name+suffix}"]').get('emission')=='.5' or float(root.find(f'asset/material[@name="{name+suffix}"]').get('emission'))==.5
