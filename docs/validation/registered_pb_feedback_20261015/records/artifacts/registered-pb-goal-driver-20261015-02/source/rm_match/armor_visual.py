"""Shared visible armor construction; source dimensions, approximate surface appearance.

Dimensions: Alliance-Algorithm/rmcs_auto_aim_v2 @ 4f4340956a989b0d3ecd4fbd94b1e72a301293cd
src/utility/robot/armor.hpp (MIT, Copyright 2025 Alliance Algorithm Team).
No pixel mask or generated target coordinate is exposed to the actor.
"""
from xml.etree import ElementTree as ET

SMALL_PLATE_WIDTH = .140
SMALL_PLATE_HEIGHT = .125
LIGHTBAR_SPAN = .135
LIGHTBAR_HEIGHT = .056
# Thickness and optical appearance are provisional; these are not calibrated CAD.

def add_armor_visual(parent, *, name, team, position=(0,0,0), yaw=0., large=False,
                     collider_name=None, number='3'):
    """Add armor with outward +X normal. Position/yaw in parent's local frame.

    Return the armor body. Caller chooses a unique collider_name for the judge.
    Visual lightbars/number have no contacts; only backing participates in physics.
    """
    if team not in ('red','blue'):
        raise ValueError('team must be red or blue')
    span, width, height = (.230,.235,.127) if large else (.135,.140,.125)
    body=ET.SubElement(parent,'body',name=name,pos=' '.join(map(str,position)),euler=f'0 0 {yaw}')
    ET.SubElement(body,'geom',name=collider_name or name+'_armor',type='box',
                  size=f'.0015 {width/2} {height/2}',rgba='.025 .025 .03 1',mass='.05')
    color = '1 .03 .01 1' if team=='red' else '.02 .12 1 1'
    for side in (-1,1):
        ET.SubElement(body,'geom',name=f'{name}_light_{side}',type='box',
                      pos=f'.003 {side*span/2} 0',size=f'.001 .003 {LIGHTBAR_HEIGHT/2}',
                      rgba=color,contype='0',conaffinity='0',mass='0')
        # White-hot centre approximates an LED core; no post-render labels or masks.
        ET.SubElement(body,'geom',type='box',pos=f'.0041 {side*span/2} 0',
                      size=f'.0002 .0007 {LIGHTBAR_HEIGHT*.45}',rgba='1 .8 .8 1' if team=='red' else '.8 .8 1 1',
                      contype='0',conaffinity='0',mass='0')
    # Original geometric stencil, not an official competition numeral texture.
    segments={'a':(-.015,.025,.015,.025),'b':(.015,.025,.015,0),
              'c':(.015,0,.015,-.025),'d':(-.015,-.025,.015,-.025),
              'e':(-.015,0,-.015,-.025),'f':(-.015,.025,-.015,0),
              'g':(-.015,0,.015,0)}
    digits={'1':'bc','2':'abged','3':'abgcd','4':'fgbc','5':'afgcd','6':'afgecd','7':'abc','8':'abcdefg','9':'abfgcd'}
    if number not in digits:
        raise ValueError('supported stencil numbers are 1 through 9')
    for key in digits[number]:
        y1,z1,y2,z2=segments[key]
        ET.SubElement(body,'geom',type='capsule',fromto=f'.004 {-y1} {z1} .004 {-y2} {z2}',
                      size='.0018',rgba='.92 .92 .92 1',contype='0',conaffinity='0',mass='0')
    return body
