"""Opt-in CAD appearance adapter. Never supplies physical collisions or inertias.

The asset directory is separate and private. Callers must explicitly select it.
The historical infantry profile is not a sentry or a current-season certified robot.
"""
from pathlib import Path
import xml.etree.ElementTree as ET


def add_visual_appearance(scene_xml: str, asset_directory, body_name: str,
                          body_origin_height_m: float, prefix='cad_reference') -> str:
    """Attach a grounded, static CAD visual to an existing chassis body.

    Keeps all existing geometry, joints, collision masks, inertias and actuators.
    The CAD upper assembly does not automatically follow the chassis's gimbal.
    Callers must not use this as proof of camera/armor/collision registration.
    """
    root=ET.fromstring(scene_xml)
    body=root.find(f".//body[@name='{body_name}']")
    if body is None:
        raise ValueError(f'Body not found: {body_name}')
    directory=Path(asset_directory).resolve()
    reference=ET.parse(directory/'appearance.xml').getroot()
    asset=root.find('asset')
    if asset is None: asset=ET.SubElement(root,'asset')
    if any(x.get('name','').startswith(prefix+'_') for x in asset):
        raise ValueError('Choose a unique appearance prefix')
    mesh_names={}
    for src in reference.findall('./asset/mesh'):
        item=ET.fromstring(ET.tostring(src))
        name=prefix+'_'+item.get('name');mesh_names[item.get('name')]=name
        item.set('name',name);item.set('file',str(directory/item.get('file')))
        asset.append(item)
    visual=ET.SubElement(body,'body',name=prefix+'_visual',pos=f'0 0 {-body_origin_height_m:.12g}')
    for src in reference.findall("./worldbody/body[@name='infantry2020_visual']/geom"):
        item=ET.fromstring(ET.tostring(src));item.set('name',prefix+'_'+item.get('name'))
        item.set('mesh',mesh_names[item.get('mesh')]);item.set('contype','0');item.set('conaffinity','0');item.set('mass','0')
        visual.append(item)
    return ET.tostring(root,encoding='unicode')
