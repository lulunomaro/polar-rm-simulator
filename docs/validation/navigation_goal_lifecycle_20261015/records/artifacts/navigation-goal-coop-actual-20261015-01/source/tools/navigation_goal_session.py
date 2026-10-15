"""Owned lifecycle action peer; separate source-pinned executable."""
import queue,subprocess,threading,time
from rm_match.deployment.profile import digest
from rm_match.deployment.wsl_profile import host_to_linux_path
from tools.pb_external_goal_session import ExternalGoalSession,SCHEMA,strict_json
class NavigationGoalSession(ExternalGoalSession):
    def prepare(self):
        end=time.perf_counter()+5.
        if self.child is not None or self.closed or self.stop.is_set():raise RuntimeError('external_owner_single_use')
        if digest(self.spec_path)!=self.spec_sha:raise ValueError('external_spec_changed')
        mapping=lambda p:host_to_linux_path(p,repo_root=self.root,shared_out=self.out)
        command=['C:/Windows/System32/wsl.exe','-d','Ubuntu-22.04','--cd',mapping(self.root),'--',
            '/usr/bin/python3','-u',mapping(self.root/'tools/qa_navigation_goal_supervisor.py'),
            '--spec',mapping(self.spec_path),'--spec-sha256',self.spec_sha]
        self.stderr=(self.out/'supervisor.stderr.log').open('wb')
        self.child=subprocess.Popen(command,cwd=self.root,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=self.stderr,shell=False,bufsize=0,creationflags=subprocess.CREATE_NO_WINDOW)
        reader=threading.Thread(target=self._reader,name='external-ready-reader',daemon=True)
        self.threads.append(reader);reader.start()
        try:value=self.queue.get(timeout=max(0.,end-time.perf_counter()))
        except queue.Empty as error:self.request_stop();raise TimeoutError('external_ready_timeout') from error
        if isinstance(value,BaseException):self.request_stop();raise value
        expected=dict(schema=SCHEMA,event='ready',run_uuid=self.run_uuid,spec_sha256=self.spec_sha)
        if type(value) is not dict or any(type(value.get(k)) is not str or value[k]!=v for k,v in expected.items()):
            self.request_stop();raise ValueError('external_supervisor_ready_identity')
        for key in ('supervisor_pid','start_ticks'):
            if type(value.get(key)) is not int or value[key]<(2 if key=='supervisor_pid' else 0):raise ValueError('external_supervisor_process_identity')
        client=value.get('client')
        if type(client) is not dict or client.get('session_run_uuid')!=self.spec['session_run_uuid'] or client.get('namespace')!=self.spec['namespace']:
            raise ValueError('external_client_namespace')
        if (client.get('schema')!='polar.pb.external-goal-ready.v1' or client.get('run_uuid')!=self.run_uuid
            or client.get('spec_sha256')!=self.spec_sha or type(client.get('domain_id')) is not int or client['domain_id']!=84
            or client.get('state')!='OBSERVING_NO_INPUT_PUBLISHED'):raise ValueError('external_client_ready_fields')
        if any(client.get(k) is not False for k in ('sensor_published','goal_sent','lifecycle_changed')):raise ValueError('external_client_warmed_data')
        if client.get('environment_sha256')!=self.spec['environment_ref']['sha256'] or client.get('source_sha256')!=self.spec['source_sha256']:
            raise ValueError('external_client_source')
        owned=value.get('owned_identity')
        if type(owned) is not dict or type(client.get('pid')) is not int or client['pid']!=owned.get('pid') or owned.get('supervisor_pid')!=value['supervisor_pid']:
            raise ValueError('external_child_ownership')
        if (client.get('start_ticks')!=owned.get('leader_start_ticks') or client.get('boot_id')!=owned.get('boot_id')
            or value.get('boot_id')!=client.get('boot_id')):raise ValueError('external_child_birth_identity')
        if time.perf_counter()>=end:raise TimeoutError('external_ready_deadline')
        self.ready=value;return value

