"""AM02-inspired v2.1: original flat matte paint glyph, no official artwork.

Keeps frozen v2 geometry intact. Glyph fits the measured 76.5 x 66.5 mm
central island; its shape/material and optical radiance are approximations.
"""
import math
from xml.etree import ElementTree as ET
from .armor_visual_v2 import add_armor_visual_v2
PROFILE = 'am02_parametric_v2.1_flat_paint'


def add_armor_visual_v21(parent, **kwargs):
    body = add_armor_visual_v2(parent, **kwargs)
    asset, name = kwargs['asset'], kwargs['name']
    for geom in list(body.findall('geom')):
        if geom.get('rgba') == '.82 .82 .79 1':
            body.remove(geom)
    material = name + '_paint'
    ET.SubElement(asset, 'material', name=material, rgba='.82 .82 .79 1',
                  specular='0', shininess='0', reflectance='0')
    # Thin flat ribbon segments, 20 micrometre nominal paint relief. Positive Y
    # is screen-right when viewed from the outward +X side. No tubular strokes.
    for arc, centre_z in enumerate((.0145, -.0145)):
        for i in range(32):
            a, b = [math.radians(-100 + 200*j/32) for j in (i, i+1)]
            polygon = []
            for angle, radius in ((a,.0155),(b,.0155),(b,.0205),(a,.0205)):
                polygon.append((.002 + radius*math.cos(angle),
                                centre_z + .8*radius*math.sin(angle)))
            vertices=[(x,y,z) for x in (.001505,.001525) for y,z in polygon]
            faces=[(0,2,1),(0,3,2),(4,5,6),(4,6,7)]
            for j in range(4):
                k=(j+1)%4;faces.extend(((j,k,k+4),(j,k+4,j+4)))
            mesh=f'{name}_paint_{arc}_{i}'
            ET.SubElement(asset,'mesh',name=mesh,
                          vertex=' '.join(str(v) for p in vertices for v in p),
                          face=' '.join(str(v) for p in faces for v in p))
            ET.SubElement(body,'geom',type='mesh',mesh=mesh,material=material,
                          contype='0',conaffinity='0',mass='0')
    return body
