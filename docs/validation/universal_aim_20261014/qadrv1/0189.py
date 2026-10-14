"""Six actuated provisional robots in the sourced RMUL fallback world.

Robot shape/mass/drive are illustrative, not official CAD or a wheel-leg model.
Only reset assigns spawn qpos; all subsequent movement is motor-driven.
"""
from pathlib import Path
import copy
import xml.etree.ElementTree as ET
from .arena import arena_worldbody
from .armor_visual import add_armor_visual

ROSTER = [(f'{team}_{role}',team,role) for team in ('red','blue') for role in ('hero','infantry','sentry')]
SPAWNS = {f'{team}_{role}': ((-5.25 if team=='red' else 5.25),
    (1 if team=='red' else -1)*(2.35+i*.65),0. if team=='red' else 3.141592653589793)
    for team in ('red','blue') for i,role in enumerate(('hero','infantry','sentry'))}


def make_match_xml(armor_profile='baseline'):
    if armor_profile not in ('baseline','emissive','infantry_v22','role_v23'):
        raise ValueError('Unknown armor optical profile')
    source=ET.fromstring(Path(__file__).with_name('harness.xml').read_text())
    root=ET.Element('mujoco',{'model':'RMUL fallback Phase B - provisional robot dynamics'})
    for tag in ('compiler','option','visual','default'):
        root.append(copy.deepcopy(source.find(tag)))
    root.find('visual/global').set('offwidth','1280');root.find('visual/global').set('offheight','720')
    world=ET.SubElement(root,'worldbody')
    for element in arena_worldbody():world.append(copy.deepcopy(element))
    ET.SubElement(world,'camera',name='broadcast_overview',pos='0 -10 14',
        xyaxes='1 0 0 0 .813733471 .581238194',fovy='31')
    actuator=ET.SubElement(root,'actuator')
    asset=ET.SubElement(root,'asset')
    if armor_profile=='emissive':
        for team,color,core in [('red','1 .03 .01 1','1 .8 .8 1'),('blue','.02 .12 1 1','.8 .8 1 1')]:
            ET.SubElement(asset,'material',name=team+'_armor_led_emissive',rgba=color,emission='.5',specular='0')
            ET.SubElement(asset,'material',name=team+'_armor_core_emissive',rgba=core,emission='.5',specular='0')
    template=source.find('worldbody/body[@name="robot"]')
    for rid,team,role in ROSTER:
        body=copy.deepcopy(template)
        x,y,yaw=SPAWNS[rid];body.set('pos',f'{x} {y} .25')
        for geom_index,element in enumerate(body.iter()):
            if 'name' in element.attrib:element.set('name',rid+'__'+element.get('name'))
            if element.tag=='geom':
                element.set('rgba','.18 .19 .21 1')
                if 'name' not in element.attrib:element.set('name',f'{rid}__part_{geom_index}')
        # Shared source-dimensioned armor backing/lightbar/number geometry.
        import math
        for label,pos,angle in [('front',(.31,0,.10),0),('back',(-.31,0,.10),math.pi),
                                ('left',(0,.26,.10),math.pi/2),('right',(0,-.26,.10),-math.pi/2)]:
            if armor_profile in ('infantry_v22','role_v23') and (role=='infantry' or (armor_profile=='role_v23' and role=='sentry')):
                from .armor_visual_v22 import add_armor_visual_v22
                if role=='sentry':
                    from .armor_visual_v23 import add_sentry_visual_v23
                    visual=add_sentry_visual_v23
                else:visual=add_armor_visual_v22
                plate=visual(body,asset=asset,name=rid+'__visual_'+label,
                    team=team,position=pos,yaw=angle,collider_name=rid+'__armor_'+label,
                    number='3',led_emission=.5)
                # Optical-only profile: preserve the baseline judge collider,
                # mass, and inertia. No broadening of the hittable target.
                plate.find('geom[@name="'+rid+'__armor_'+label+'"]').set('size','.0015 .07 .0625')
                continue
            plate=add_armor_visual(body,name=rid+'__visual_'+label,team=team,position=pos,yaw=angle,
                large=role=='hero',collider_name=rid+'__armor_'+label,
                number={'hero':'1','infantry':'3','sentry':'7'}[role])
            if armor_profile=='emissive':
                for geom in plate.findall('geom'):
                    material=None
                    if '_light_' in geom.get('name',''):material=team+'_armor_led_emissive'
                    elif geom.get('size')=='.0002 .0007 0.0252':material=team+'_armor_core_emissive'
                    if material:
                        geom.attrib.pop('rgba',None);geom.set('material',material)
        world.append(body)
        for element in source.find('actuator'):
            if element.get('name')=='target_motion':continue
            a=copy.deepcopy(element)
            a.set('name',rid+'__'+a.get('name'));a.set('joint',rid+'__'+a.get('joint'))
            actuator.append(a)
    return ET.tostring(root,encoding='unicode')
