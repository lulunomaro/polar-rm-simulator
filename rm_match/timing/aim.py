"""Frozen repaired 40f7 actor with exact clock and 80/36/100Hz acquisition.

Only raw RGB, exposure-own-pose, calibration and current own odometry are used.
The existing conservative stationary wrapper is retained and separately named.
"""
import hashlib,json,os
from pathlib import Path
from PIL import Image
from ..rmcs_stop_aim import RMCSStopAim,sha
from .strict_process import StrictProcess

class TimingMatchAim(RMCSStopAim):
    def __init__(self,sim,spec_path,out):
        spec=json.loads(Path(spec_path).read_text())
        if spec.get('source_commit')!='40f7af130d076bcabab98613bd66745f81c7f643' or spec.get('sha256',{}).get('binary')!='70ad294ff8be702804ebd1e3f98048d0a13b9e74894d8b28615886a83eda0fcb':
            raise ValueError('timing-v5 requires the exact frozen 40f7 actor; legacy or rebuilt identities need separate qualification')
        for key in ('binary','executor_yaml','autoaim_config'):
            if spec['sha256'][key]!=sha(spec[key]):raise ValueError('Frozen artifact hash mismatch: '+key)
        if spec['model_sha256']!=sha(Path(spec['model_share'])/'shenzhen-0526.onnx'):raise ValueError('Frozen model mismatch')
        super().__init__(sim,spec_path,out,client_factory=StrictProcess)
        self.captured_frames=0;self.pending_frame=None;self.selected_id=None;self.last_actuator_saturated=False
        self.source_label='40f7 REPAIRED RMCS'
        self.provenance.update(protocol_id='rmcs-full-match-timing-v5',physics_hz=2000,source_capture_hz=80,
            source_control_hz=100,source_capture_and_inference_hz=None,source_detector_hz=36,
            frame_delivery='80Hz captures only while stationary segment active; newest frame selected at rational 36Hz control opportunities',
            fire_transport_delay_ms=40,feeder_hz=6,source_commit='40f7af130d076bcabab98613bd66745f81c7f643',
            source_input_archive='All delivered selected frames lossless PNG. Unselected 80Hz captures are not archived.',
            no_claim='CPU offline synthetic 3v3, not real hardware, uncalibrated optics and provisional robots; not identical to distance benchmark.')
        (self.out/'provenance.json').write_text(json.dumps(self.provenance,indent=2))
        (self.out/'delivered_frames').mkdir(exist_ok=True)
    def _new_segment(self,o):
        segment=self.out/f'segment_{self.segment+1:03d}';segment.mkdir(exist_ok=True)
        (segment/'tracking_mode').write_text('multi_ekf\n')
        self.pending_frame=None;self.selected_id=None
        super()._new_segment(o)
    def _close_segment(self,o,reason):
        super()._close_segment(o,reason);self.pending_frame=None;self.selected_id=None
    def capture_tick(self,o):
        if self.client and self.gate.active:
            # Base capture writes the actual RGB/BGR and exposure own-state.
            self.pending_frame=super().capture(o);self.delivered_frames-=1;self.captured_frames+=1
    def capture(self,o):
        if self.pending_frame is None or self.pending_frame['frame_id']==self.selected_id:return None
        self.selected_id=self.pending_frame['frame_id'];self.delivered_frames+=1
        Image.fromarray(self.latest_rgb).save(self.out/'delivered_frames'/f'{self.selected_id:07d}.png',compress_level=1)
        return self.pending_frame
    def _act(self,o,mode,desired_velocity=(0.,0.)):
        result=super()._act(o,mode,desired_velocity)
        if self.client:
            mode_path=self.out/f'segment_{self.segment:03d}'/'tracking_mode'
            if mode_path.read_text()!='multi_ekf\n':raise ValueError('Runtime mode mutated')
        return result
