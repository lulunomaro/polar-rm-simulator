import dataclasses
import math
import unittest
from .autoaim import (AutoAimRequest, AutoAimAuthority, ImageCalibration,
                      parse_aim_request, fov_admission)

class AutoAimContractTests(unittest.TestCase):
    def setUp(self):
        self.request=AutoAimRequest(True,True,85,.25,.25)
        self.payload=dataclasses.asdict(self.request)
        self.camera=ImageCalibration(320,240,260,260,160,120)
    def test_legacy_defaults_disabled(self):
        self.assertFalse(parse_aim_request().enabled)
        self.assertFalse(parse_aim_request().hold)
    def test_complete_request_roundtrip(self):
        self.assertEqual(parse_aim_request(self.payload),self.request)
    def test_malformed_rejected(self):
        for payload in [False,[],{},dict(self.payload,truth={}),{'enabled':True}]:
            with self.subTest(payload=payload),self.assertRaises(ValueError):
                parse_aim_request(payload)
    def test_numbers_fail_closed(self):
        for key in ('fov_degrees','circle_radius_x_norm','circle_radius_y_norm'):
            for value in [True,None,'85',math.nan,math.inf,-1,0,10**1000]:
                with self.subTest(key=key,value=repr(value)[:30]),self.assertRaises(ValueError):
                    parse_aim_request(dict(self.payload,**{key:value}))
    def test_bool_is_strict(self):
        for key in ('enabled','hold'):
            with self.assertRaises(ValueError):parse_aim_request(dict(self.payload,**{key:1}))
    def test_bounds(self):
        for value in [9.9,180.1]:
            with self.assertRaises(ValueError):parse_aim_request(dict(self.payload,fov_degrees=value))
        with self.assertRaises(ValueError):parse_aim_request(dict(self.payload,circle_radius_x_norm=2.01))
    def test_circle_ellipse_and_boundary(self):
        self.assertEqual(fov_admission((240,120),self.camera,self.request),(True,'inside_fov'))
        self.assertEqual(fov_admission((241,120),self.camera,self.request),(False,'outside_circle'))
        self.assertEqual(fov_admission((160,181),self.camera,self.request),(False,'outside_circle'))
    def test_angle_intersection(self):
        narrow=dataclasses.replace(self.request,fov_degrees=10)
        self.assertEqual(fov_admission((190,120),self.camera,narrow),(False,'outside_angle'))
        self.assertTrue(fov_admission((160,120),self.camera,narrow)[0])
    def test_resolution_invariance(self):
        big=ImageCalibration(640,480,520,520,320,240)
        for p in [(160,120),(239,120),(241,120),(160,181)]:
            self.assertEqual(fov_admission(p,self.camera,self.request),
                             fov_admission(tuple(2*v for v in p),big,self.request))
    def test_invalid_geometry_never_admitted(self):
        for p in [(math.nan,120),(True,120),(-1,120),(320,120),(1,),None]:
            self.assertFalse(fov_admission(p,self.camera,self.request)[0])
        for c in [None,dataclasses.replace(self.camera,fx=0),dataclasses.replace(self.camera,width=True)]:
            self.assertEqual(fov_admission((160,120),c,self.request),(False,'invalid_calibration'))
    def test_180_angle_valid_without_infinite_tangent(self):
        self.assertTrue(fov_admission((240,120),self.camera,dataclasses.replace(self.request,fov_degrees=180))[0])
    def test_valid_request_does_not_fabricate_authority(self):
        state=AutoAimAuthority().evaluate(self.request,allowed=True,reason='active')
        for key in ('available','active','selected','fov_applied'):self.assertFalse(state[key])
        self.assertEqual(state['reason'],'source_adapter_unavailable')
        self.assertEqual(state['fire_authority'],'manual_only')
        self.assertIsNone(state['source_frame_seq'])
    def test_release_disable_and_gate_reasons(self):
        authority=AutoAimAuthority()
        for request,reason in [(dataclasses.replace(self.request,hold=False),'right_button_released'),
                               (AutoAimRequest(),'module_disabled')]:
            self.assertEqual(authority.evaluate(request,allowed=True)['reason'],reason)
        for reason in ['control_timeout','focus_lost','epoch_changed','dead','paused','camera_error','finished']:
            state=authority.evaluate(self.request,allowed=False,reason=reason,identity=('new',3,'blue_sentry'))
            self.assertEqual(state['reason'],reason);self.assertFalse(state['active'])
    def test_no_sticky_authority_across_identity_or_reengagement(self):
        authority=AutoAimAuthority()
        for i in range(5):
            self.assertFalse(authority.evaluate(self.request,allowed=i%2==0,identity=('session',i,'red_sentry'))['active'])

if __name__=='__main__':unittest.main()
