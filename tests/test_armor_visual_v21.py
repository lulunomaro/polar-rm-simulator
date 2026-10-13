from xml.etree import ElementTree as ET
import numpy as np
from rm_match.armor_visual_v21 import add_armor_visual_v21


def test_v21_flat_original_paint_is_within_measured_label():
    root=ET.Element('mujoco');asset=ET.SubElement(root,'asset');world=ET.SubElement(root,'worldbody')
    body=add_armor_visual_v21(world,asset=asset,name='test',team='red',collider_name='armor')
    assert body.find("geom[@name='armor']").get('size')=='.0015 .0675 .0625'
    paint=asset.find("material[@name='test_paint']")
    assert paint.get('specular')=='0' and paint.get('reflectance')=='0'
    meshes=[m for m in asset.findall('mesh') if '_paint_' in m.get('name')]
    assert len(meshes)==64
    vertices=np.concatenate([np.fromstring(m.get('vertex'),sep=' ').reshape(-1,3) for m in meshes])
    assert np.max(np.abs(vertices[:,1])) < .0765/2
    assert np.max(np.abs(vertices[:,2])) < .0665/2
    assert np.ptp(vertices[:,0]) < .000021
    assert not any(g.get('rgba')=='.82 .82 .79 1' for g in body.findall('geom'))
    assert all(g.get('contype')=='0' for g in body.findall('geom') if g.get('material')=='test_paint')


def test_v22_both_diffuser_layers_are_explicitly_emissive():
    from rm_match.armor_visual_v22 import add_armor_visual_v22
    root=ET.Element('mujoco');asset=ET.SubElement(root,'asset');world=ET.SubElement(root,'worldbody')
    body=add_armor_visual_v22(world,asset=asset,name='new',team='blue',led_emission=.5)
    cores=[g for g in body.findall('geom') if g.get('size')=='.00065']
    assert len(cores)==2 and all(g.get('material')=='new_luminous_core' for g in cores)
    assert asset.find("material[@name='new_luminous_core']").get('emission')=='.5' or float(asset.find("material[@name='new_luminous_core']").get('emission'))==.5
    assert float(asset.find("material[@name='new_led']").get('emission'))==.5
