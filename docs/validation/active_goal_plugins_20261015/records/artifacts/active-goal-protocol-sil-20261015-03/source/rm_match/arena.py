"""Rule-dimensioned RMUL arena; never advertised as a complete official CAD export."""
from pathlib import Path
import json
import xml.etree.ElementTree as ET

ROOT = Path(__file__).parent / 'assets' / 'arenas' / 'rmul_2026_rules_v1_2'

def arena_metadata():
    return json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))

def arena_worldbody():
    """Return fresh worldbody with metre coordinates, field centre origin and z-up."""
    return ET.parse(ROOT / 'arena.xml').getroot().find('worldbody')

def apply_arena(xml: str) -> str:
    """Replace only harness scenery, preserving all articulated robots and cameras."""
    root = ET.fromstring(xml)
    world = root.find('worldbody')
    for child in list(world):
        if child.tag == 'geom' and child.get('name') in {'floor','occluder','backwall'}:
            world.remove(child)
    for child in arena_worldbody():
        world.append(child)
    return ET.tostring(root, encoding='unicode')

def main():
    """Open only the sourced arena; this is not the match engine."""
    import time
    import mujoco
    import mujoco.viewer
    model = mujoco.MjModel.from_xml_path(str(ROOT / 'arena.xml'))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    with mujoco.viewer.launch_passive(model, data) as viewer:
        viewer.cam.lookat[:] = (0, 0, 0)
        viewer.cam.distance = 16
        viewer.cam.azimuth = 90
        viewer.cam.elevation = -50
        while viewer.is_running():
            viewer.sync()
            time.sleep(.03)

if __name__ == '__main__':
    main()
