"""Non-rendering adapter safety tests; all injected doubles are test-only."""
import dataclasses
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ..contracts import Command
from ..rmcs_stop_aim import RMCSStopAim
from .autoaim import AutoAimRequest
from .source_aim import OperatorSourceAim,IDENTITY

class SourceAimBoundaryTests(unittest.TestCase):
    def test_cached_command_rechecked_at_each_physics_tick(self):
        aim=object.__new__(OperatorSourceAim)
        request=AutoAimRequest(True,True,85,.25,.25)
        aim.error=None;aim.identity=('test',0,'red_sentry',1)
        aim.fov={k:v for k,v in dataclasses.asdict(request).items() if k not in ('enabled','hold')}
        aim.gate=SimpleNamespace(update=lambda *args:True)
        aim.client=object();aim.capture_bucket=80;aim.control_bucket=100
        aim.latest_command=Command(gimbal_yaw=.4,gimbal_pitch=.1)
        aim.last_accepted_s=.921;aim.last_detector_summary={};aim.selected_id=7
        aim.latest_response={'target_age_s':.079,'result_exposure_time_s':.921}
        o=SimpleNamespace(robot_id='red_sentry',sim_time=1.0095)
        c=aim.act_operator(o,request,identity=aim.identity,allowed=True)
        self.assertIsNone(c);self.assertFalse(aim.feedback['active'])
        self.assertEqual(aim.feedback['reason'],'source_observation_stale')
    def test_fov_applied_when_real_detector_candidates_all_rejected(self):
        aim=object.__new__(OperatorSourceAim)
        aim.latest_response={};aim.last_accepted_s=None;aim.client=object()
        aim.fov=aim.requested_fov={'fov_degrees':10,'circle_radius_x_norm':.02,'circle_radius_y_norm':.02}
        aim.requested=True;aim.held=True;aim.selected_id=8
        aim.last_detector_summary=dict(sim_time=.5,frame_seq=8,fov_raw2d=1,fov_admitted2d=0,fov_rejected2d=1)
        aim._feedback(None,'no_admitted_source_target')
        self.assertTrue(aim.feedback['fov_applied']);self.assertFalse(aim.feedback['active'])
        self.assertEqual(aim.feedback['fov_rejected2d'],1)
    def test_sticky_source_error_never_restarts_process(self):
        aim=object.__new__(OperatorSourceAim);aim.error='Injected failure';reasons=[]
        aim.disengage=lambda o,reason:reasons.append(reason)
        aim.act_operator(object(),AutoAimRequest(True,True),identity=('test',),allowed=True)
        self.assertEqual(reasons,['source_error'])
    def test_provenance_matches_native_cadence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);binary=root/'dummy-never-executed';binary.write_bytes(b'fixture')
            spec=root/'spec.json';spec.write_text(json.dumps(dict(operator_identity=IDENTITY,binary=str(binary),frozen_build={'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()})))
            sim=SimpleNamespace(model=SimpleNamespace(opt=SimpleNamespace(timestep=.0005)))
            def fake_init(self,sim,spec,out,**kwargs):
                self.out=Path(out);self.out.mkdir();self.provenance={'physics_hz':500};self.error=None
            with patch.object(RMCSStopAim,'__init__',fake_init):
                aim=OperatorSourceAim(sim,spec,root/'out')
            record=json.loads((root/'out/provenance.json').read_text())
            self.assertEqual((record['physics_hz'],record['source_capture_hz'],record['source_detector_hz'],record['source_control_hz']),(2000,80,36,100))
            self.assertIn('never applied',record['source_fire_authority'])

if __name__=='__main__':unittest.main()
