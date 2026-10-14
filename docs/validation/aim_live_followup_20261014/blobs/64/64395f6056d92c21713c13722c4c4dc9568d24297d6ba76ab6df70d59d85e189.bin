"""Regression for source mode selecting its already qualified optical profile."""
import unittest
import numpy as np
import mujoco
from ..match_model import make_match_xml
from .source_runtime import SOURCE_ARMOR_PROFILE

class SourceOpticalProfileTests(unittest.TestCase):
    def test_source_profile_is_role_correct_existing_profile(self):
        self.assertEqual(SOURCE_ARMOR_PROFILE,'role_v23')
        import xml.etree.ElementTree as ET
        root=ET.fromstring(make_match_xml(SOURCE_ARMOR_PROFILE))
        for team in ('red','blue'):
            for side in ('front','back','left','right'):
                body=root.find(f'.//body[@name="{team}_sentry__visual_{side}"]')
                self.assertTrue(any('_original_turret_' in g.get('mesh','') for g in body.findall('geom')))
    def test_profile_preserves_dynamics_colliders_actuation(self):
        base=mujoco.MjModel.from_xml_string(make_match_xml('baseline'))
        fixed=mujoco.MjModel.from_xml_string(make_match_xml(SOURCE_ARMOR_PROFILE))
        self.assertEqual((base.nq,base.nv,base.nu),(fixed.nq,fixed.nv,fixed.nu))
        for key in ('body_mass','body_inertia','body_ipos','body_iquat','jnt_pos','jnt_axis',
                    'actuator_gainprm','actuator_biasprm','actuator_ctrlrange','actuator_forcerange'):
            np.testing.assert_allclose(getattr(base,key),getattr(fixed,key),atol=1e-12,rtol=0)
        for gid in range(base.ngeom):
            if not base.geom_contype[gid] and not base.geom_conaffinity[gid]:continue
            name=mujoco.mj_id2name(base,mujoco.mjtObj.mjOBJ_GEOM,gid);other=fixed.geom(name).id
            for key in ('geom_type','geom_size','geom_pos','geom_quat','geom_friction','geom_contype','geom_conaffinity'):
                np.testing.assert_allclose(getattr(base,key)[gid],getattr(fixed,key)[other],atol=1e-12,rtol=0)
