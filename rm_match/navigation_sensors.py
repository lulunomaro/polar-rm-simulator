"""Trusted MuJoCo ray/IMU sampling; only detached sensor packets leave this file.

The analytic nonrepeating scan is an explicit provisional MID360-style profile,
not a reconstruction of Livox's optical pattern or calibrated reflectivity.
Every ray is cast at its recorded physics time, without truth-based deskew.
"""
from __future__ import annotations
import base64
import copy
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import time
import xml.etree.ElementTree as ET
import numpy as np
from .platform_v2.navigation_contracts import POINT_ENCODING, POINT_STRUCT

POINT_DTYPE = np.dtype([('x','<f4'),('y','<f4'),('z','<f4'),('offset','<u4'),
    ('reflectivity','u1'),('tag','u1'),('line','u1'),('padding','u1')])


@dataclass(frozen=True)
class NavigationSensorConfig:
    robot_ids: tuple[str, ...] = ('red_sentry',)
    point_rate_hz: int = 200000
    scan_period_ns: int = 100000000
    range_min_m: float = .1
    range_max_m: float = 40.
    mount_translation_m: tuple[float, float, float] = (0., 0., .5)
    mount_rotation_xyzw: tuple[float, float, float, float] = (0., 0., 0., 1.)
    range_noise_std_m: float = .01
    gyro_noise_std_rps: float = .001
    acceleration_noise_std_mps2: float = .01
    seed: int = 20261013

    def __post_init__(self):
        if (type(self.robot_ids) is not tuple or not self.robot_ids or len(set(self.robot_ids)) != len(self.robot_ids)
            or any(type(r) is not str or not r for r in self.robot_ids)
            or type(self.point_rate_hz) is not int or not 1000 <= self.point_rate_hz <= 200000
            or type(self.scan_period_ns) is not int or not 10000000 <= self.scan_period_ns <= 200000000
            or not 0 < self.range_min_m < self.range_max_m <= 100
            or len(self.mount_translation_m) != 3
            or any(not math.isfinite(x) or abs(x)>10 for x in self.mount_translation_m)
            or len(self.mount_rotation_xyzw) != 4
            or any(not math.isfinite(x) for x in self.mount_rotation_xyzw)
            or abs(sum(x*x for x in self.mount_rotation_xyzw)-1)>1e-6
            or any(not math.isfinite(x) or not 0 <= x <= 1 for x in
                (self.range_noise_std_m, self.gyro_noise_std_rps, self.acceleration_noise_std_mps2))
            or type(self.seed) is not int or not 0 <= self.seed <= 2**32-1):
            raise ValueError('Invalid explicit navigation sensor profile')

    def identity(self):
        value = dict(schema='polar.navigation-sensor-profile.v1', **asdict(self),
            pattern='analytic_golden_angle_v1', fov_degrees=[360, -7, 52],
            scan_lines=4,
            reflectivity='constant_100_uncalibrated', orientation_feed=False,
            imu_rate='one_actual_sample_per_physics_step', point_time='physics_step_quantized',
            calibration='provisional_base_mount_not_measured_hardware')
        return value, hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',',':')).encode()).hexdigest()


def navigation_model_xml(xml, config):
    if type(config) is not NavigationSensorConfig: raise ValueError('Explicit navigation sensor config required')
    root = ET.fromstring(xml)
    sensors = root.find('sensor')
    if sensors is None: sensors = ET.SubElement(root, 'sensor')
    for rid in config.robot_ids:
        body = root.find('.//body[@name="'+rid+'__robot"]')
        if body is None: raise ValueError('Navigation robot missing from model: '+rid)
        site = rid+'__navigation_imu'
        if root.find('.//site[@name="'+site+'"]') is not None: raise ValueError('Duplicate navigation sensor mount')
        x,y,z,w=config.mount_rotation_xyzw
        ET.SubElement(body, 'site', name=site, pos=' '.join(map(str, config.mount_translation_m)),
            quat=' '.join(map(str,(w,x,y,z))), size='.001', group='5')
        ET.SubElement(sensors, 'gyro', name=rid+'__navigation_gyro', site=site)
        ET.SubElement(sensors, 'accelerometer', name=rid+'__navigation_accelerometer', site=site)
    return ET.tostring(root, encoding='unicode')


class NavigationSensors:
    def __init__(self, sim, config, *, clock=time.perf_counter):
        import mujoco
        if type(config) is not NavigationSensorConfig: raise ValueError('Explicit navigation sensor config required')
        self.sim, self.config, self.clock = sim, config, clock
        self.quantum = round(float(sim.model.opt.timestep)*1e9)
        if (not 0 < self.quantum <= 10000000 or config.scan_period_ns%self.quantum
            or config.point_rate_hz*self.quantum%1000000000):
            raise ValueError('Navigation rates must be integral actual physics-step multiples')
        self.rays_per_step = config.point_rate_hz*self.quantum//1000000000
        self.profile, self.profile_sha = config.identity()
        self.indices = {}
        for rid in config.robot_ids:
            if rid not in sim.robot_ids: raise ValueError('Unknown navigation sensor robot')
            site = sim.model.site(rid+'__navigation_imu').id
            rows = []
            for name, sensor_type in [('gyro',mujoco.mjtSensor.mjSENS_GYRO),('accelerometer',mujoco.mjtSensor.mjSENS_ACCELEROMETER)]:
                sensor = sim.model.sensor(rid+'__navigation_'+name).id
                if int(sim.model.sensor_type[sensor]) != int(sensor_type) or int(sim.model.sensor_objid[sensor]) != site:
                    raise ValueError('Navigation IMU sensor mapping mismatch')
                rows.append(int(sim.model.sensor_adr[sensor]))
            self.indices[rid] = (site, *rows)
        self.episode = None
        self.states = {}; self.latest = {}; self.proofs = {}

    def _reset(self):
        self.episode = self.sim.episode; self.latest.clear(); self.states.clear(); self.proofs.clear()
        for i,rid in enumerate(self.config.robot_ids):
            self.states[rid] = dict(start=None, last=None, frame=0, ray_index=0, chunks=[], imu=[],
                rng=np.random.default_rng(np.random.SeedSequence([self.config.seed, self.episode, i])))

    def capture(self):
        import mujoco
        if self.episode != self.sim.episode: self._reset()
        stamp = round(float(self.sim.time)*1e9)
        if all(s['last'] == stamp for s in self.states.values()): return
        capture_wall = self.clock()
        # Explicit forward gives site pose, local gyro and specific acceleration
        # at THIS data.time; mj_step sensordata otherwise precedes integration.
        mujoco.mj_forward(self.sim.model, self.sim.data)
        for rid,state in self.states.items():
            if state['last'] is not None and stamp-state['last'] != self.quantum:
                raise ValueError('Navigation sensor skipped or reversed actual physics step')
            if state['start'] is None: state['start'] = stamp
            state['last'] = stamp
            site, gyro, accel = self.indices[rid]; rng = state['rng']
            imu = dict(sample_sim_ns=stamp,
                angular_velocity_rps=(self.sim.data.sensordata[gyro:gyro+3]+rng.normal(0,self.config.gyro_noise_std_rps,3)).tolist(),
                linear_acceleration_mps2=(self.sim.data.sensordata[accel:accel+3]+rng.normal(0,self.config.acceleration_noise_std_mps2,3)).tolist())
            state['imu'].append(imu)
            if stamp-state['start'] == self.config.scan_period_ns:
                self._publish(rid,state,stamp,capture_wall)
                state['start'] = stamp; state['frame'] += 1; state['chunks'] = []; state['imu'] = [imu]
            elif stamp-state['start'] > self.config.scan_period_ns:
                raise ValueError('Navigation scan window skipped')
            count = self.rays_per_step
            indices = np.arange(state['ray_index'], state['ray_index']+count, dtype=np.float64)
            azimuth = np.remainder(indices*math.pi*(3-math.sqrt(5)), 2*math.pi)
            phase = np.remainder(indices*(math.sqrt(2)-1), 1.)
            elevation = np.deg2rad(-7+59*phase)
            directions = np.column_stack((np.cos(elevation)*np.cos(azimuth),np.cos(elevation)*np.sin(azimuth),np.sin(elevation)))
            rotation = self.sim.data.site_xmat[site].reshape(3,3)
            world_directions = np.ascontiguousarray(directions@rotation.T).reshape(-1)
            distances = np.empty(count); geomids = np.empty(count,dtype=np.int32)
            mujoco.mj_multiRay(self.sim.model,self.sim.data,self.sim.data.site_xpos[site],world_directions,
                np.array([1,0,0,0,0,0],dtype=np.uint8),True,self.sim.body_ids[rid],geomids,distances,None,count,self.config.range_max_m)
            valid = (distances >= self.config.range_min_m)&(distances <= self.config.range_max_m)
            # Never export collider IDs, target identity, world origin or rotation.
            measured = np.clip(distances[valid]+rng.normal(0,self.config.range_noise_std_m,np.count_nonzero(valid)),
                self.config.range_min_m,self.config.range_max_m)
            xyz = directions[valid]*measured[:,None]
            packed = np.zeros(len(xyz),dtype=POINT_DTYPE)
            for axis,i in [('x',0),('y',1),('z',2)]: packed[axis] = xyz[:,i]
            packed['offset'] = stamp-state['start']; packed['reflectivity'] = 100; packed['tag'] = 0x10
            packed['line'] = (np.arange(count)[valid]+state['ray_index'])%4
            state['chunks'].append(packed.tobytes()); state['ray_index'] += count

    def _publish(self,rid,state,stamp,capture_wall):
        sim = self.sim; robot = sim.judge.robots[rid]
        ext = dict(parent_frame='base_link',translation_m=list(self.config.mount_translation_m),rotation_xyzw=list(self.config.mount_rotation_xyzw),
            calibration_id='provisional-navigation-base-'+self.profile_sha[:16])
        raw = b''.join(state['chunks'])
        cloud = dict(available=True,reason='available',frame_id=state['frame'],acquisition_start_ns=state['start'],
            acquisition_end_ns=stamp,capture_sim_time=stamp*1e-9,frame='livox_frame',encoding=POINT_ENCODING,
            point_count=len(raw)//POINT_STRUCT.size,data_base64=base64.b64encode(raw).decode('ascii'),
            range_min_m=self.config.range_min_m,range_max_m=self.config.range_max_m,time_quantization_ns=self.quantum,
            provenance='mujoco_ray_cast_nonrepeating_profile_v1',profile_sha256=self.profile_sha,extrinsics=ext)
        imu = dict(available=True,reason='available',frame='livox_frame',capture_sim_time=stamp*1e-9,
            extrinsics=copy.deepcopy(ext),provenance='mujoco_gyro_accelerometer_v1',samples=copy.deepcopy(state['imu']))
        proofs = self.proofs.setdefault(rid,{})
        proofs[state['frame']] = (stamp*1e-9,capture_wall)
        for old in list(proofs):
            if old < state['frame']-2: del proofs[old]
        self.latest[rid] = dict(robot_id=rid,episode=sim.episode,sim_time=stamp*1e-9,capture_wall=capture_wall,
            own=dict(team=sim.teams[rid],role=sim.roles[rid],hp=float(robot.hp),ammo=float(robot.ammo),heat=float(robot.heat),alive=bool(robot.alive)),
            referee=dict(phase='finished' if sim.judge.terminal else ('paused' if sim.paused else sim.phase),
                remaining_seconds=max(0.,sim.judge.duration_s-sim.judge.sim_time),emergency_stop=bool(sim.emergency_stop)),
            sensors=dict(pointcloud=cloud,imu=imu))

    def packet(self,rid):
        if self.episode != self.sim.episode: return None
        return copy.deepcopy(self.latest.get(rid))

    def capture_valid(self,rid,episode,budget,sim_time):
        packet = self.latest.get(rid)
        return bool(packet and episode == self.episode == self.sim.episode and packet['episode'] == episode
            and budget.get('profile_sha256') == self.profile_sha and 0 <= budget['frame_id'] <= packet['sensors']['pointcloud']['frame_id']
            and self.proofs.get(rid,{}).get(budget['frame_id']) == (budget['capture_sim_time'],budget['capture_wall'])
            and budget['capture_sim_time'] <= sim_time <= budget['sim_deadline'])
