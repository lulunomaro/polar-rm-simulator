import xml.etree.ElementTree as ET
from rm_match.cad_appearance import add_visual_appearance


def test_private_cad_adapter_keeps_existing_physics(tmp_path):
    (tmp_path/'appearance.xml').write_text('''<mujoco><asset><mesh name="shape" file="shape.obj"/></asset><worldbody><body name="infantry2020_visual"><geom name="shell" type="mesh" mesh="shape"/></body></worldbody></mujoco>''')
    source='<mujoco><worldbody><body name="robot"><joint name="x" type="slide"/><geom name="chassis" type="box" size=".2 .2 .1" mass="15" contype="3" conaffinity="5"/></body></worldbody><actuator><motor joint="x"/></actuator></mujoco>'
    result=ET.fromstring(add_visual_appearance(source,tmp_path,'robot',.25))
    assert result.find('.//geom[@name="chassis"]').attrib == ET.fromstring(source).find('.//geom').attrib
    assert result.find('.//joint').attrib == ET.fromstring(source).find('.//joint').attrib
    cad=result.find('.//geom[@name="cad_reference_shell"]')
    assert [cad.get(x) for x in ['mass','contype','conaffinity']]==['0','0','0']
    assert result.find('.//body[@name="cad_reference_visual"]').get('pos')=='0 0 -0.25'
    assert result.find('./actuator/motor').get('joint')=='x'
