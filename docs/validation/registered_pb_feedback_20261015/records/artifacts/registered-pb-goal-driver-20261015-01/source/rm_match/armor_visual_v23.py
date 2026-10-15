"""V2.3 semantic role revision, built on fixed v2.2 optics.

2026 robot specification Appendix Figure 5 identifies sentries with a turret
symbol, not a numeral 7. This module draws a newly authored simple turret icon;
it does not contain official sticker artwork or a traced/vectorized decal.
Materials, shape and radiometry remain synthetic and uncalibrated. No model
threshold, preprocessing, exposure or brightness parameter is selected here.
"""
import math
from xml.etree import ElementTree as ET
from .armor_visual_v22 import add_armor_visual_v22
PROFILE='am02_parametric_v2.3_original_turret_symbol'


def add_sentry_visual_v23(parent,**kwargs):
    kwargs={**kwargs,'number':'3','led_emission':.5}
    body=add_armor_visual_v22(parent,**kwargs)
    name,asset=kwargs['name'],kwargs['asset']
    for geom in list(body.findall('geom')):
        if geom.get('material')==name+'_paint':body.remove(geom)
    # Newly authored generic turret: outlined upper housing/barrel on a stem,
    # plus a separate trapezoid plinth. Dimensions fit the same central island.
    contours=[
      [(-.025,.018),(-.017,.025),(.003,.025),(.007,.015),(.027,.015),
       (.027,.005),(.006,.005),(.000,-.004),(-.004,-.007),(-.004,-.016),
       (-.018,-.016),(-.018,-.006),(-.025,-.002)],
      [(-.028,-.029),(.022,-.029),(.013,-.021),(-.020,-.021)]]
    width=.003
    for ci,contour in enumerate(contours):
        for j,(a,b) in enumerate(zip(contour,contour[1:]+contour[:1])):
            dy,dz=b[0]-a[0],b[1]-a[1];length=math.hypot(dy,dz)
            ny,nz=-dz/length*width/2,dy/length*width/2
            polygon=[(a[0]+ny,a[1]+nz),(b[0]+ny,b[1]+nz),
                     (b[0]-ny,b[1]-nz),(a[0]-ny,a[1]-nz)]
            vertices=[(x,y,z) for x in (.001505,.001525) for y,z in polygon]
            faces=[(0,2,1),(0,3,2),(4,5,6),(4,6,7)]
            for k in range(4):
                l=(k+1)%4;faces.extend(((k,l,l+4),(k,l+4,k+4)))
            mesh=f'{name}_original_turret_{ci}_{j}'
            ET.SubElement(asset,'mesh',name=mesh,
                vertex=' '.join(str(v) for p in vertices for v in p),
                face=' '.join(str(v) for p in faces for v in p))
            ET.SubElement(body,'geom',type='mesh',mesh=mesh,material=name+'_paint',
                contype='0',conaffinity='0',mass='0')
    return body
