"""V2.2 declared optical revision: luminous core and outer diffuser.

Fixes the v2/v2.1 inconsistency where only the colored outer lens emitted light.
No measured photometric calibration, exposure response, bloom or official glyph.
"""
from xml.etree import ElementTree as ET
from .armor_visual_v21 import add_armor_visual_v21 as _base_visual
PROFILE='am02_parametric_v2.2_emissive_core'


def add_armor_visual_v22(parent, **kwargs):
    body=_base_visual(parent,**kwargs)
    name,asset,team=kwargs['name'],kwargs['asset'],kwargs['team']
    emission=kwargs.get('led_emission',.5)
    material=name+'_luminous_core'
    ET.SubElement(asset,'material',name=material,
                  rgba='1 .73 .65 1' if team=='red' else '.67 .78 1 1',
                  emission=str(emission),specular='0',shininess='0')
    for geom in body.findall('geom'):
        if geom.get('type')=='capsule' and geom.get('size')=='.00065':
            geom.attrib.pop('rgba',None)
            geom.set('material',material)
    return body

# Same fixture factory API; explicitly distinct PROFILE in manifests.
add_armor_visual_v21=add_armor_visual_v22
