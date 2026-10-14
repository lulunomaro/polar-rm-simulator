"""Selectable AM02-inspired parametric armor; original mesh and glyph geometry.

Measured shape dimensions refer to official AM02 STEP (SHA256
 dcc2141c6a2928493f9f95ba00eb103ccd15354433f81b03dbba9f58e92e7e49).
No DJI CAD triangles, photos, or official decal artwork are redistributed here.
Optical materials, LED radiance and generic numeral are uncalibrated approximations.
"""
import math
from xml.etree import ElementTree as ET

PROFILE='am02_parametric_v2'


def _chamfered_mesh(asset,name,width,height,depth,chamfer):
    y,z=width/2,height/2;c=chamfer
    polygon=[(-y+c,-z),(y-c,-z),(y,-z+c),(y,z-c),(y-c,z),(-y+c,z),(-y,z-c),(-y,-z+c)]
    vertices=[(x,yy,zz) for x in (-depth/2,depth/2) for yy,zz in polygon]
    faces=[]
    for i in range(1,7):faces.extend([(0,i+1,i),(8,8+i,8+i+1)])
    for i in range(8):
        j=(i+1)%8;faces.extend([(i,j,8+j),(i,8+j,8+i)])
    ET.SubElement(asset,'mesh',name=name,vertex=' '.join(str(v) for p in vertices for v in p),
                  face=' '.join(str(v) for p in faces for v in p))


def add_armor_visual_v2(parent,*,asset,name,team,position=(0,0,0),yaw=0.,
                        collider_name=None,number='3',led_emission=.5):
    """Small AM02 frontplate; outward +X. V1 and its frozen episodes stay unchanged."""
    if team not in ('red','blue'):raise ValueError('red or blue team required')
    if not 0<=led_emission<=1:raise ValueError('MuJoCo emission must be in [0,1]')
    body=ET.SubElement(parent,'body',name=name,pos=' '.join(map(str,position)),euler=f'0 0 {yaw}')
    _chamfered_mesh(asset,name+'_face_mesh',.135,.125,.003,.005)
    _chamfered_mesh(asset,name+'_cover_mesh',.141,.129965,.016,.006)
    ET.SubElement(asset,'material',name=name+'_matte',rgba='.075 .078 .085 1',specular='.18',shininess='.18')
    ET.SubElement(asset,'material',name=name+'_metal',rgba='.025 .027 .03 1',specular='.65',shininess='.6')
    teamrgba='1 .012 .006 1' if team=='red' else '.012 .06 1 1'
    ET.SubElement(asset,'material',name=name+'_led',rgba=teamrgba,emission=str(led_emission),specular='.3',shininess='.3')
    # Single judge collider remains a box; chamfer collision fidelity is explicitly not claimed.
    ET.SubElement(body,'geom',name=collider_name or name+'_armor',type='box',size='.0015 .0675 .0625',
                  rgba='0 0 0 0',mass='.05')
    def geom(**kwargs):
        defaults={'contype':'0','conaffinity':'0','mass':'0'};defaults.update(kwargs)
        return ET.SubElement(body,'geom',**defaults)
    geom(type='mesh',mesh=name+'_cover_mesh',pos='-.0095 0 0',rgba='.035 .037 .04 1')
    geom(type='mesh',mesh=name+'_face_mesh',material=name+'_matte')
    # Measured groove outer82.9x72.9 and flush inner island76.5x66.5 mm.
    # Four thin strokes approximate the groove, rather than claiming the island is recessed.
    for sy in (-1,1):
        geom(type='box',pos=f'.00155 {sy*.04145} 0',size='.00015 .00045 .0355',rgba='.025 .027 .03 1')
    for sz in (-1,1):
        geom(type='box',pos=f'.00155 0 {sz*.03645}',size='.00015 .0405 .00045',rgba='.025 .027 .03 1')
    # Socket screws, measured head diameter7.7mm, centres±47.5/±52.185mm.
    for y in (-.0475,.0475):
        for z in (-.052185,.052185):
            geom(type='cylinder',pos=f'.0017 {y} {z}',size='.00385 .0003',euler='0 1.5707963267948966 0',material=name+'_metal')
            geom(type='cylinder',pos=f'.00205 {y} {z}',size='.00135 .0001',euler='0 1.5707963267948966 0',rgba='.004 .004 .004 1')
    # Optical endpoint span135mm/height56mm is from upstream armor.hpp. Housing
    # shape is an approximation, not a substitution of lens-envelope for PnP span.
    for side in (-1,1):
        geom(type='capsule',fromto=f'.001 {side*.0675} -.0278 .001 {side*.0675} .0278',size='.0032',rgba='.018 .018 .02 1')
        geom(type='capsule',fromto=f'.004 {side*.0675} -.025 .004 {side*.0675} .025',size='.0025',material=name+'_led')
        geom(type='capsule',fromto=f'.006 {side*.0675} -.0245 .006 {side*.0675} .0245',size='.00065',
             rgba='1 .73 .65 1' if team=='red' else '.67 .78 1 1')
    # Original rounded stroke numeral. Not the official RoboMaster decal/font.
    if number=='3':
        strokes=[]
        for centre_z in (.021,-.021):
            points=[]
            for i in range(18):
                angle=math.radians(-100+200*i/17)
                points.append((.0019,.002+.021*math.cos(angle),centre_z+.023*math.sin(angle)))
            strokes.extend(zip(points[:-1],points[1:]))
    else:
        raise ValueError('v2 currently supplies only an explicitly generic numeral3; no fake official sentry glyph')
    for p,q in strokes:
        geom(type='capsule',fromto=' '.join(map(str,p+q)),size='.0022',rgba='.82 .82 .79 1')
    return body
