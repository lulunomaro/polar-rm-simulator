"""Owned generation supervisor prototype; preparation is never SIL acceptance.

Linux only for start(), no shell/launch fallback, no synthetic sensor startup.
Call prepare() to inspect configuration; start() configures lifecycle servers.
Activate only after the caller has produced real LIO/SLAM transforms.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import uuid

NODES = {
    'point_lio': ('point_lio', 'pointlio_mapping'),
    'loam_interface': ('loam_interface', 'loam_interface_node'),
    'sensor_scan_generation': ('sensor_scan_generation', 'sensor_scan_generation_node'),
    'terrain_analysis': ('terrain_analysis', 'terrainAnalysis'),
    'terrain_analysis_ext': ('terrain_analysis_ext', 'terrainAnalysisExt'),
    'pointcloud_to_laserscan': ('pointcloud_to_laserscan', 'pointcloud_to_laserscan_node'),
    'slam_toolbox': ('slam_toolbox', 'sync_slam_toolbox_node'),
    'planner_server': ('nav2_planner', 'planner_server'),
    'controller_server': ('nav2_controller', 'controller_server'),
}
GLOBAL_TOPICS = ('/clock', '/tf', '/tf_static', '/polar/pb/request', '/polar/pb/localization', '/polar/pb/result', '/map', '/map_metadata', '/map_updates')
PB_COMMIT = 'cb97fb07ace54fcc617ddb884227ef85fe4b8f85'
DDS_ENVIRONMENT = {'ROS_DOMAIN_ID':'84', 'ROS_LOCALHOST_ONLY':'1', 'RMW_IMPLEMENTATION':'rmw_fastrtps_cpp'}
_DDS_INIT_LOCK = threading.RLock()

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def checked_json(path):
    raw = Path(path).read_bytes()
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('stack_manifest_oversized')
    def pairs(items):
        value = {}
        for k, v in items:
            if k in value: raise ValueError('stack_duplicate_json_key')
            value[k] = v
        return value
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('stack_nonfinite_json')))

def namespace_checked(namespace):
    if type(namespace) is not str or not re.fullmatch(r'/polar_sil_[0-9a-f]{32}/red_sentry', namespace):
        raise ValueError('stack_fresh_namespace_required')
    return namespace

def flatten(value, prefix=''):
    result = {}
    for key, item in value.items():
        name = prefix + key
        if isinstance(item, dict): result.update(flatten(item, name + '.'))
        else: result[name] = item
    return result

def adapt_parameters(reality, simulation, generation, namespace, diagnostics=False):
    """Retain fixed reality algorithm tuning; list every explicit adaptation."""
    namespace_checked(namespace)
    if type(diagnostics) is not bool: raise ValueError('stack_diagnostics_boolean_required')
    params = {key: copy.deepcopy(reality[key]['ros__parameters']) for key in NODES}
    changes = []
    def change(node, key, value, reason):
        flat = flatten(params[node])
        before = flat.get(key, {'missing': True})
        if before == value and type(before) is type(value): return
        # Store flat ROS parameter names, avoiding conflicting nested aliases.
        flat[key] = value
        params[node] = flat
        changes.append(dict(node=node, parameter=key, original=before, adapted=value, reason=reason))
    for node in NODES: change(node, 'use_sim_time', True, 'single owned simulation clock; no wall-time sensor stamps')
    for generated in generation['nodes']:
        node = generated['package']
        for block in generated['parameters']:
            for key, value in block.items(): change(node, key, value, 'reviewed actual Livox/SI/mount/generation overlay')
    for node, keys in {
        'loam_interface': ('base_frame',),
        'sensor_scan_generation': ('base_frame', 'robot_base_frame'),
        'pointcloud_to_laserscan': ('target_frame',),
        'slam_toolbox': ('base_frame',),
    }.items():
        for key in keys: change(node, key, 'base_link', 'actual calibrated simulator rigid base; no fake yaw frame')
    original_acc = flatten(reality['point_lio']['ros__parameters'])['mapping.satu_acc']
    original_norm = flatten(reality['point_lio']['ros__parameters'])['mapping.acc_norm']
    change('point_lio', 'mapping.satu_acc', original_acc * 9.81 / original_norm,
        'same physical acceleration saturation threshold expressed in actual SI input units')
    change('point_lio', 'mapping.gravity', [0.0, 0.0, -9.81], 'simulator gravity SI calibration, no true robot pose')
    change('point_lio', 'mapping.gravity_init', [0.0, 0.0, -9.81], 'sensor rigid mount/units, no localization truth')
    change('point_lio', 'prior_pcd.enable', False, 'online localization only; no prior map')
    change('point_lio', 'pcd_save.pcd_save_en', False, 'owned evidence supplied by caller; no unrelated upstream log writes')
    change('slam_toolbox', 'transform_publish_period', 0.02,
        'enable SLAM-produced map-to-odom; upstream launch used a forbidden static alternative')
    change('slam_toolbox', 'scan_topic', namespace + '/obstacle_scan', 'explicit generation topic isolation')
    change('slam_toolbox', 'map_name', namespace + '/map', 'no cross-generation absolute map topic')
    change('slam_toolbox', 'use_map_saver', False, 'no map saver service or persisted/prior map in first SIL scope')
    change('controller_server', 'odom_topic', namespace + '/odometry', 'actual sensor-scan odometry, never truth')
    change('controller_server', 'progress_checker_plugin', 'progress_checker', 'Humble 1.1.20 singular parameter compatibility')
    for key, value in {'v_linear_min': -1.0, 'v_linear_max': 1.0, 'v_angular_min': -2.0, 'v_angular_max': 2.0}.items():
        change('controller_server', 'FollowPath.' + key, value,
            'platform scalar PID speed norm limit 1 m/s and angular limit 2 rad/s; original gains unchanged')
    for key, value in {'enabled': True, 'robot_id': 'red_sentry', 'episode': 0, 'binding_epoch': 1,
        'request_topic': '/polar/pb/request', 'result_topic': '/polar/pb/result',
        'localization_topic': '/polar/pb/localization'}.items():
        change('controller_server', 'polar_sourced.' + key, value, 'reviewed compute-context hook, fixed generation identity')
    if diagnostics:
        change('point_lio', 'pb.dispatch_diagnostics', True, 'opt-in bounded actual callback metadata; no timing or sensor substitution')
        change('controller_server', 'polar_sourced.diagnostics', True, 'opt-in bounded guard-reason logs; no command or guard changes')
    # Nested costmap ROS nodes use namespace/local_costmap/local_costmap, as upstream.
    maps = {}
    for name in ('local_costmap', 'global_costmap'):
        flat = flatten(copy.deepcopy(reality[name][name]['ros__parameters']))
        for key, value in {'use_sim_time': True, 'robot_base_frame': 'base_link',
            'map_topic': namespace + '/map', 'static_layer.map_topic': namespace + '/map', 'robot_radius':0.38}.items():
            before = flat.get(key, {'missing': True}); flat[key] = value
            if before != value or type(before) is not type(value):
                changes.append(dict(node=name, parameter=key, original=before, adapted=value,
                    reason=('static simplified chassis .28/.23 m halfsize + margin; not real sentry CAD' if key=='robot_radius'
                        else 'owned frame/topic simulation clock; preserve original local odom/global map frames')))
        for key, value in list(flat.items()):
            if isinstance(value, str) and '<robot_namespace>' in value:
                flat[key] = value.replace('<robot_namespace>', namespace)
                changes.append(dict(node=name, parameter=key, original=value, adapted=flat[key], reason='explicit fresh namespace'))
        maps[name] = flat
    if maps['local_costmap']['global_frame'] != 'odom' or maps['global_costmap']['global_frame'] != 'map':
        raise ValueError('stack_costmap_frame_contract_changed')
    if flatten(params['planner_server'])['GridBased.plugin'] != 'nav2_smac_planner/SmacPlannerHybrid':
        raise ValueError('stack_original_planner_required')
    if flatten(params['controller_server'])['FollowPath.plugin'] != 'pb_omni_pid_pursuit_controller::OmniPidPursuitController':
        raise ValueError('stack_original_pid_required')
    for costmap in maps.values():
        if costmap['intensity_voxel_layer.plugin'] != 'pb_nav2_costmap_2d::IntensityVoxelLayer':
            raise ValueError('stack_original_intensity_voxel_required')
    # Original configuration sections outside this finite roster are never launched.
    result = {namespace + '/' + name: {'ros__parameters': flatten(value)} for name, value in params.items()}
    result.update({namespace + '/' + name + '/' + name: {'ros__parameters': value} for name, value in maps.items()})
    return result, changes

class StackFault(RuntimeError):
    def __init__(self, message):
        super().__init__(message)
        self.code=message.split(':',1)[0]

class PBNavigationStack:
    def __init__(self, config, out, namespace=None, domain_id=84, environment=None, diagnostics=False):
        if type(domain_id) is not int or domain_id != 84: raise ValueError('stack_domain_84_required')
        if type(diagnostics) is not bool: raise ValueError('stack_diagnostics_boolean_required')
        self.diagnostics = diagnostics
        self.config = copy.deepcopy(config)
        if environment is not None:self.config['environment']=copy.deepcopy(environment)
        self.out = Path(out).absolute()
        self.namespace = namespace_checked(namespace or '/polar_sil_' + uuid.uuid4().hex + '/red_sentry')
        self.domain_id = domain_id
        self.processes = {}; self.logs = {}; self.node = None; self.context = None; self.executor=None
        self.prepared = False; self.started = False; self.closed = False; self.state = 'NEW'
        self.events = []; self.info = None
        self.cleanup = None; self.health_error = None
        self._stop_lock=threading.Lock(); self._stop_complete=threading.Event()

    @property
    def generation(self):
        return {'robot_id':'red_sentry','episode':0,'binding_epoch':1}

    @property
    def status(self):
        return dict(state=self.state, namespace=self.namespace, domain_id=self.domain_id,
            generation=self.generation, configured=self.started and not self.closed,
            active=self.state=='ACTIVE', health_error=self.health_error, cleanup=self.cleanup)

    def _event(self, event, **fields):
        row = dict(event=event, wall_time=time.perf_counter(), wall_clock='linux_local_perf_counter', **fields)
        self.events.append(row)
        if self.out.exists():
            with (self.out / 'supervisor.jsonl').open('a', encoding='utf8') as handle:
                handle.write(json.dumps(row, allow_nan=False) + '\n')

    def prepare(self):
        if self.prepared: return self.info
        if self.out.exists() or any(p.is_symlink() for p in (self.out, *self.out.parents)):
            raise ValueError('stack_output_must_be_fresh_unlinked')
        cfg = self.config
        required = {'schema','repo_root','source_repo','source_revision','generation_config','environment','install_prefixes','assets','libraries','provenance'}
        if type(cfg) is not dict or set(cfg) != required: raise ValueError('stack_config_fields')
        if cfg['schema']!='polar.pb-stack-config.v1' or cfg['source_revision']!=PB_COMMIT:raise ValueError('stack_config_identity')
        repo = Path(cfg['repo_root']).resolve()
        for ref in [cfg['environment'],cfg['generation_config'],*cfg['provenance'].values()]:
            if type(ref) is not dict or set(ref)!={'path','sha256'} or not Path(ref['path']).is_absolute() or sha(ref['path'])!=ref['sha256']:
                raise ValueError('stack_input_snapshot_changed')
        environment = Path(cfg['environment']['path'])
        environment_value = checked_json(environment)
        env = {k:os.environ[k] for k in ('PATH','HOME','LANG','LC_ALL','TZ','USER','LOGNAME','TMPDIR') if k in os.environ}
        env.update(environment_value['process_environment'])
        env.pop('PYTHONPATH', None)
        if type(cfg['install_prefixes']) is not list or not cfg['install_prefixes'] or any(type(p)is not str or not Path(p).is_absolute() for p in cfg['install_prefixes']):raise ValueError('stack_absolute_install_prefixes')
        installs = [str(Path(p).absolute()) for p in cfg['install_prefixes']]
        for p in installs:
            if not Path(p).is_dir(): raise ValueError('stack_install_missing:' + p)
        for key, suffix in [('AMENT_PREFIX_PATH', ''), ('CMAKE_PREFIX_PATH', ''), ('LD_LIBRARY_PATH', '/lib')]:
            env[key] = ':'.join(p + suffix for p in installs) + ':' + env.get(key, '')
        env.update(DDS_ENVIRONMENT)
        env.update(ROS_DISTRO='humble', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', RCUTILS_COLORIZED_OUTPUT='0')
        if set(cfg['assets']) != set(NODES): raise ValueError('stack_exact_algorithm_roster_required')
        for label, asset in {**cfg['assets'], **cfg['libraries']}.items():
            if type(asset) is not dict or set(asset) != {'path', 'sha256'}: raise ValueError('stack_asset_fields')
            path = Path(asset['path'])
            if not path.is_absolute() or not path.is_file() or sha(path) != asset['sha256']:
                raise ValueError('stack_asset_missing_or_changed:' + label)
            with path.open('rb') as handle:
                if handle.read(4) != b'\x7fELF': raise ValueError('stack_actual_elf_required')
            if label in cfg['assets'] and not os.access(path, os.X_OK): raise ValueError('stack_elf_not_executable')
        if set(cfg['libraries'])!={'pb_intensity_layers','pb_controller'} or Path(cfg['libraries']['pb_intensity_layers']['path']).name != 'libpb_intensity_layers.so':
            raise ValueError('stack_unique_pb_layers_soname_required')
        for p in installs:
            if (Path(p) / 'lib/liblayers.so').exists(): raise ValueError('stack_pb_layers_collision')
        base = Path(cfg['source_repo']).resolve()
        head = subprocess.check_output(['git', '-C', str(base), 'rev-parse', 'HEAD'], text=True).strip()
        if head != PB_COMMIT: raise ValueError('stack_fixed_pb2025_commit_required')
        reality_file = base / 'pb2025_nav_bringup/config/reality/nav2_params.yaml'
        simulation_file = base / 'pb2025_nav_bringup/config/simulation/nav2_params.yaml'
        generation_file = Path(cfg['generation_config']['path'])
        import xml.etree.ElementTree as ET
        vehicle_model=repo/'rm_match/harness.xml'
        chassis=ET.parse(vehicle_model).getroot().find(".//geom[@name='chassis']")
        if chassis is None or chassis.get('type')!='box' or tuple(map(float,chassis.get('size','').split()))!=(.28,.23,.20):
            raise ValueError('stack_static_chassis_profile_changed')
        import yaml
        config_bytes = {}
        for kind in ('reality','simulation'):
            relative='pb2025_nav_bringup/config/'+kind+'/nav2_params.yaml'
            config_bytes[kind]=subprocess.check_output(['git','-C',str(base),'show',PB_COMMIT+':'+relative])
        reality = yaml.safe_load(config_bytes['reality'])
        simulation = yaml.safe_load(config_bytes['simulation'])
        params, adaptations = adapt_parameters(reality, simulation, checked_json(generation_file), self.namespace, self.diagnostics)
        self.out.mkdir(parents=True)
        params_file = self.out / 'owned_parameters.yaml'
        params_file.write_text(yaml.safe_dump(params, sort_keys=False), encoding='utf8')
        commands = {}
        for name, asset in cfg['assets'].items():
            argv = [asset['path'], '--ros-args', '-r', '__ns:=' + self.namespace,
                '-r', '__node:=' + name, '--params-file', str(params_file)]
            for topic in GLOBAL_TOPICS: argv += ['-r', topic + ':=' + self.namespace + topic]
            for topic in ('livox/lidar', 'livox/imu', 'aft_mapped_to_init', 'cloud_registered', 'registered_scan',
                'lidar_odometry', 'sensor_scan', 'odometry', 'terrain_map', 'terrain_map_ext', 'obstacle_scan',
                'cloud_in', 'scan', 'cmd_vel'):
                dest = {'cloud_in': 'terrain_map_ext', 'scan': 'obstacle_scan', 'cmd_vel': 'cmd_vel_nav2_audit'}.get(topic, topic)
                argv += ['-r', topic + ':=' + self.namespace + '/' + dest]
            commands[name] = argv
        python = environment_value['venv_python']
        bridge = [python, '-m', 'rm_match.integrations.pb_navigation_bridge', '--domain-id', '84',
            '--node-name', 'polar_pb_bridge_' + self.namespace.split('/')[1].removeprefix('polar_sil_')[:16]]
        for key, topic in {'cloud_topic': '/livox/lidar', 'pointcloud_topic': '/livox/lidar/pointcloud',
            'imu_topic': '/livox/imu', 'request_topic': '/polar/pb/request', 'result_topic': '/polar/pb/result',
            'odom_topic': '/odometry', 'clock_topic': '/clock', 'tf_static_topic': '/tf_static'}.items():
            bridge += ['--' + key.replace('_', '-'), self.namespace + topic]
        bridge += ['--response-timeout', '0.05', '--expected-robot-id', 'red_sentry', '--expected-episode', '0', '--expected-binding-epoch', '1']
        assert len(bridge) <= 32
        manifest = {'schema': 'polar.sim.pb-navigation-manifest.v1', 'adapters': [{'adapter_id': 'custom_pb_navigation',
            'label': 'PB2025 sourced Smac + PID', 'command': bridge, 'cwd': str(repo)}]}
        manifest_file = self.out / 'bridge_manifest.json'; manifest_file.write_text(json.dumps(manifest, indent=2), encoding='utf8')
        self.info = dict(schema='polar.pb-navigation-stack.v1', namespace=self.namespace, domain_id=84,
            bridge_manifest_path=str(manifest_file), bridge_manifest_sha256=sha(manifest_file), env=env,
            install_prefixes=installs, commands=commands, assets=cfg['assets'], libraries=cfg['libraries'],
            original_configuration={'upstream_commit': head, 'reality_sha256': hashlib.sha256(config_bytes['reality']).hexdigest(), 'simulation_sha256': hashlib.sha256(config_bytes['simulation']).hexdigest(),
                'point_lio_base': 'reality', 'navigation_base': 'reality', 'generation_config_sha256': sha(generation_file)},
            parameters_path=str(params_file), parameters_sha256=sha(params_file), adaptations=adaptations,
            diagnostics=self.diagnostics,
            static_vehicle_calibration={'source':str(repo/'rm_match/harness.xml'),'sha256':sha(repo/'rm_match/harness.xml'),
                'chassis_halfsize_xy_m':[.28,.23],'circumscribed_radius_m':math.hypot(.28,.23),'costmap_radius_m':.38,
                'qualification':'simplified simulator vehicle profile, not real sentry CAD or dynamic world truth'},
            provenance=cfg['provenance'], physics_started=False, sensor_warmup=False, prior_map=False,
            topics={key:self.namespace+value for key,value in {'clock':'/clock','tf':'/tf','tf_static':'/tf_static',
                'request':'/polar/pb/request','localization':'/polar/pb/localization','result':'/polar/pb/result',
                'odom':'/odometry','lio_odom':'/aft_mapped_to_init','map':'/map','cloud':'/livox/lidar',
                'imu':'/livox/imu','scan':'/obstacle_scan'}.items()},
            forbidden_nodes_not_started=['fake_vel_transform', 'velocity_smoother', 'bt_navigator', 'map_server', 'static_map_to_odom'],
            scope='prepared_only_not_algorithm_or_sil_acceptance')
        # Keep only the intended environment entries, not user secrets, in evidence.
        evidence = dict(self.info); evidence['env'] = {k:env[k] for k in (*environment_value['process_environment'],
            'ROS_DISTRO', 'ROS_DOMAIN_ID', 'ROS_LOCALHOST_ONLY', 'RMW_IMPLEMENTATION', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'RCUTILS_COLORIZED_OUTPUT') if k in env}
        (self.out / 'PLAN.json').write_text(json.dumps(evidence, indent=2), encoding='utf8')
        self.prepared = True; self.state = 'PREPARED'; return self.info

    def _recheck_prepared(self):
        refs=[self.config['environment'],self.config['generation_config'],*self.config['provenance'].values()]
        refs += [{'path':self.info['parameters_path'],'sha256':self.info['parameters_sha256']},
            {'path':self.info['bridge_manifest_path'],'sha256':self.info['bridge_manifest_sha256']}]
        if any(sha(ref['path'])!=ref['sha256'] for ref in refs):raise StackFault('stack_prepared_input_changed')

    def _lifecycle(self, name, transition=None, timeout_s=10.0):
        from lifecycle_msgs.srv import ChangeState, GetState
        deadline = time.perf_counter() + timeout_s
        service_type = GetState if transition is None else ChangeState
        client = self.node.create_client(service_type, self.namespace + '/' + name + ('/get_state' if transition is None else '/change_state'))
        try:
            while not client.service_is_ready():
                self.poll_health()
                if time.perf_counter() >= deadline: raise StackFault('stack_lifecycle_service_timeout:' + name)
                self._spin(min(.02, deadline - time.perf_counter()))
            request = service_type.Request()
            if transition is not None: request.transition.id = transition
            future = client.call_async(request)
            while not future.done():
                self.poll_health()
                if time.perf_counter() >= deadline: raise StackFault('stack_lifecycle_reply_timeout:' + name)
                self._spin(min(.02, deadline - time.perf_counter()))
            response = future.result()
            if response is None or transition is not None and not response.success: raise StackFault('stack_lifecycle_rejected:' + name)
            self._event('lifecycle', node=name, transition=transition, state=None if transition is not None else response.current_state.id)
            return None if transition is not None else response.current_state.id
        finally: self.node.destroy_client(client)

    def _spin(self, timeout):
        if self.executor is None:raise StackFault('stack_lifecycle_executor_missing')
        self.executor.spin_once(timeout_sec=max(0.0, timeout))

    def _create_lifecycle_client(self):
        # RMW init consumes process environment, not the env passed to child Popen.
        # Keep the supervisor participant in the exact child DDS scope; restore
        # caller settings even if context/node initialization fails.
        with _DDS_INIT_LOCK:
            previous={key:os.environ.get(key) for key in DDS_ENVIRONMENT}
            initialized=False
            try:
                os.environ.update(DDS_ENVIRONMENT)
                import rclpy
                from rclpy.executors import SingleThreadedExecutor
                self.context=rclpy.context.Context()
                rclpy.init(args=[],context=self.context,domain_id=self.domain_id)
                self.node=rclpy.create_node('polar_stack_supervisor',namespace=self.namespace,context=self.context,
                    use_global_arguments=False)
                self.executor=SingleThreadedExecutor(context=self.context)
                self.executor.add_node(self.node)
                initialized=True
            finally:
                for key,value in previous.items():
                    if value is None:os.environ.pop(key,None)
                    else:os.environ[key]=value
                self._event('supervisor_dds_initialized',settings=dict(DDS_ENVIRONMENT),
                    initialized=initialized,process_environment_restored=all(os.environ.get(k)==v for k,v in previous.items()))

    def start(self):
        if sys.platform != 'linux': raise ValueError('stack_requires_humble_linux')
        if self.started or self.closed: raise StackFault('stack_generation_is_single_use')
        self.prepare()
        try:
            self._recheck_prepared()
            import rclpy
            import importlib.metadata
            if sys.version_info[:2]!=(3,10) or not importlib.metadata.version('rclpy').startswith('3.3.'):
                raise StackFault('stack_requires_humble_rclpy_python310')
            self._create_lifecycle_client()
            for name, command in self.info['commands'].items():
                # Startup asset recheck immediately before exec, no lifecycle/physics data.
                if sha(command[0]) != self.config['assets'][name]['sha256']: raise StackFault('stack_exec_asset_changed')
                log = (self.out / (name + '.log')).open('wb'); self.logs[name] = log
                process = subprocess.Popen(command, cwd=self.out, env=self.info['env'], stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                self.processes[name] = process
                self._event('process_started', node=name, pid=process.pid, pgid=process.pid, command=command)
            for name in ('controller_server', 'planner_server'):
                self._lifecycle(name, 1)  # CONFIGURE, never dummy sensor data.
                if self._lifecycle(name) != 2: raise StackFault('stack_lifecycle_not_inactive:' + name)
            self.poll_health(); self.started = True; self.state = 'CONFIGURED'
            self.info['lifecycle_states']={'controller_server':'inactive','planner_server':'inactive','slam_toolbox':'ordinary_node_not_lifecycle'}
            self._event('configured_ready', sensor_frames=0, physics_steps=0, controller_active=False)
            return self.info
        except BaseException:
            self.health_error=self.health_error or 'lifecycle_setup_failed'
            self.state = 'FAULT'; self.stop(); raise

    def activate_navigation(self, timeout_s=10.0):
        """Caller must have already produced actual LIO odom and SLAM map/TF."""
        if not self.started or self.closed or self.state != 'CONFIGURED': raise StackFault('stack_not_configured')
        try:
            for name in ('controller_server', 'planner_server'):
                self._lifecycle(name, 3, timeout_s=timeout_s)
                if self._lifecycle(name, timeout_s=timeout_s) != 3: raise StackFault('stack_not_active:' + name)
            self.state = 'ACTIVE'; self._event('navigation_active')
        except BaseException:
            self.health_error=self.health_error or 'lifecycle_activation_failed'
            self.state = 'FAULT'; self.stop(); raise

    def activate_controller(self, timeout_s=10.0):
        self.activate_navigation(timeout_s=timeout_s)
        return self.status

    def poll_health(self, generation=None):
        expected=self.generation
        if generation is not None and (type(generation)is not dict or set(generation)!=set(expected) or
            any(type(generation[k])is not type(v) or generation[k]!=v for k,v in expected.items())):
            self.health_error='generation_changed'
            self.state = 'FAULT'; self.stop(); raise StackFault('stack_generation_fault')
        if self.closed: raise StackFault('stack_closed')
        exited = [(name, process.poll()) for name, process in self.processes.items() if process.poll() is not None]
        if exited:
            self.health_error='algorithm_process_exited'
            self._event('process_exit_fault', exits=exited); self.state = 'FAULT'; self.stop()
            raise StackFault('stack_algorithm_process_exited:' + repr(exited))
        return self.state

    @staticmethod
    def _members(pgid):
        members = []
        for item in Path('/proc').iterdir():
            if not item.name.isdigit(): continue
            try:
                fields=(item/'stat').read_text().rsplit(')',1)[1].split()
                if int(fields[2]) == pgid and int(fields[3]) == pgid:
                    members.append({'pid':int(item.name), 'state':fields[0], 'start_ticks':int(fields[19])})
            except (OSError, ValueError, IndexError): pass
        return members

    def stop(self, grace_s=1.5):
        if not self._stop_lock.acquire(blocking=False):
            budget=grace_s+1.0+.15
            end=getattr(self,'_stop_deadline',time.perf_counter()+budget)
            if not self._stop_complete.wait(timeout=max(0.,min(budget,end-time.perf_counter()))):
                return {'schema':'polar.pb-stack-cleanup.v1','clean':False,'errors':['shutdown_in_progress'],'processes':[]}
            return copy.deepcopy(self.cleanup)
        try:
            if self._stop_complete.is_set():return copy.deepcopy(self.cleanup)
            self._stop_deadline=time.perf_counter()+grace_s+1.0+.15
            try:self.cleanup=self._stop_owned(grace_s)
            except BaseException as error:
                self.cleanup={'schema':'polar.pb-stack-cleanup.v1','clean':False,'errors':['shutdown_exception:'+type(error).__name__],
                    'processes':[{'node':n,'pid':p.pid,'returncode':p.poll()} for n,p in self.processes.items()]}
                self.health_error='shutdown_incomplete';self.state='FAULT';self.closed=True
            finally:self._stop_complete.set()
            return copy.deepcopy(self.cleanup)
        finally:self._stop_lock.release()

    def _stop_owned(self, grace_s):
        self.closed = True; started = time.perf_counter(); errors=[]
        for process in self.processes.values():
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            except Exception as error: errors.append(type(error).__name__)
        deadline = started + grace_s
        while time.perf_counter() < deadline and any(self._members(p.pid) for p in self.processes.values()):
            for p in self.processes.values(): p.poll()
            time.sleep(.02)
        for process in self.processes.values():
            if self._members(process.pid):
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                except Exception as error: errors.append(type(error).__name__)
        rows=[]
        reap_deadline=time.perf_counter()+1.0
        for name, process in self.processes.items():
            try: process.wait(timeout=max(0.,reap_deadline-time.perf_counter()))
            except subprocess.TimeoutExpired: errors.append('process_unreaped:' + name)
            rows.append({'node':name,'pid':process.pid,'returncode':process.poll(),'remaining_members':self._members(process.pid)})
        if self.executor is not None:
            try:
                if self.executor.shutdown(timeout_sec=.15) is False:errors.append('executor_shutdown_incomplete')
            except Exception as error:errors.append('executor_close:'+type(error).__name__)
            if self.node is not None:
                try:self.executor.remove_node(self.node)
                except Exception as error:errors.append('executor_remove_node:'+type(error).__name__)
        if self.node is not None:
            try: self.node.destroy_node()
            except Exception as error: errors.append('node_close:' + type(error).__name__)
        if self.context is not None:
            try: self.context.try_shutdown()
            except Exception as error: errors.append('context_close:' + type(error).__name__)
        for log in self.logs.values():
            try:log.close()
            except Exception as error:errors.append('log_close:'+type(error).__name__)
        assets_after={};assets_unchanged=True
        for name,asset in {**self.config.get('assets',{}),**self.config.get('libraries',{})}.items():
            try:
                actual=sha(asset['path']);valid=actual==asset['sha256']
                assets_after[name]={'path':asset['path'],'expected_sha256':asset['sha256'],'actual_sha256':actual,'unchanged':valid}
            except Exception as error:
                valid=False;assets_after[name]={'path':asset.get('path'),'unchanged':False,'error':type(error).__name__}
            assets_unchanged=assets_unchanged and valid
        if not assets_unchanged:errors.append('algorithm_assets_changed')
        clean = not errors and all(r['returncode'] is not None and not r['remaining_members'] for r in rows)
        result = dict(schema='polar.pb-stack-cleanup.v1',clean=clean,errors=errors,processes=rows,
            elapsed_s=time.perf_counter()-started,prior_state=self.state,assets_after=assets_after,assets_unchanged=assets_unchanged)
        self.cleanup=result
        if not clean:self.health_error='shutdown_incomplete'
        if self.out.exists(): (self.out/'CLEANUP.json').write_text(json.dumps(result,indent=2))
        self.state = 'CLOSED' if clean else 'FAULT'
        if self.out.exists(): self._event('stack_closed',clean=clean)
        return result

    def __enter__(self): self.start(); return self
    def __exit__(self, *_): self.stop()
