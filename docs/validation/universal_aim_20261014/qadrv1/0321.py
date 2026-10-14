from pathlib import Path
import xml.etree.ElementTree as ET
import mujoco
import numpy as np
from rm_match.arena import ROOT, apply_arena, arena_metadata


def test_arena_dimensions_collision_and_clearance():
    model = mujoco.MjModel.from_xml_path(str(ROOT / 'arena.xml'))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    for x, y, expected in [(0, 0, 0), (-2.5, 1.5, .2), (2.5, -1.5, .2), (-1.575, .8, .4), (1.575, -.8, .4), (-1.3, .8, 0), (6.15, 0, .42), (0, 4.15, .42)]:
        gid = np.array([-1], dtype=np.int32)
        distance = mujoco.mj_ray(model, data, np.array([x,y,2.]), np.array([0.,0.,-1.]), np.array([1,0,0,0,0,0],dtype=np.uint8), 1, -1, gid)
        assert abs(2-distance-expected)<1e-6
    assert arena_metadata()['cad_imported'] is False
    assert model.nmesh == 0  # no convex hull can seal the traversable corridor


def test_composed_robot_xml_compiles_without_default_changes():
    path = Path(__file__).parents[1] / 'rm_match' / 'harness.xml'
    source = path.read_text()
    assembled = ET.fromstring(apply_arena(source))
    world = assembled.find('worldbody')
    # Explicit fixture placement only: production match integration is separate.
    world.find("body[@name='robot']").set('pos', '-4 -2 .25')
    world.find("body[@name='target']").set('pos', '4 2 .65')
    model = mujoco.MjModel.from_xml_string(ET.tostring(assembled,encoding='unicode'))
    assert model.nq > 0
    assert path.read_text() == source


def test_six_spawns_inside_own_zone_and_disjoint():
    import json
    cfg=json.loads((ROOT/'spawns.json').read_text())
    hx,hy=[v/2 for v in cfg['robot_footprint_xy_m']]
    spawns=cfg['spawns']
    for spawn in spawns:
        x,y,_=spawn['position_m']; xmin,xmax,ymin,ymax=cfg['zones'][spawn['team']+'_supply']
        assert xmin < x-hx and x+hx < xmax
        assert ymin < y-hy and y+hy < ymax
    for i,a in enumerate(spawns):
        for b in spawns[i+1:]:
            x,y,_=a['position_m'];xx,yy,_=b['position_m']
            assert abs(x-xx)>2*hx or abs(y-yy)>2*hy


def test_spawn_fixtures_have_no_initial_penetration():
    import json
    cfg=json.loads((ROOT/'spawns.json').read_text())
    root=ET.parse(ROOT/'arena.xml').getroot()
    world=root.find('worldbody')
    for spawn in cfg['spawns']:
        body=ET.SubElement(world,'body',name=spawn['id'],pos=' '.join(map(str,spawn['position_m'])))
        ET.SubElement(body,'freejoint')
        ET.SubElement(body,'geom',type='box',size='.28 .23 .20',mass='15')
    model=mujoco.MjModel.from_xml_string(ET.tostring(root,encoding='unicode'))
    data=mujoco.MjData(model);mujoco.mj_forward(model,data)
    assert data.ncon == 0
