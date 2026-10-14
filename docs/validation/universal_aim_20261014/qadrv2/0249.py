"""Three independent loopback HTTP sessions against real MuJoCo, without GL.

This is not a cross-machine LAN, renderer, native-aim, or 7v7 qualification.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import threading
import time
import secrets
from urllib.error import HTTPError
from urllib.request import Request,build_opener,ProxyHandler
from .backend import MuJoCoBackend
from .runtime import PlatformRuntime
from .server import PlatformHTTPServer,TransportConfig
from .admission import AdmissionPolicy


def local_qa_admission(robot_ids):
    """Trusted QA owner explicitly grants scoped operators and a truth auditor.

    Fresh enrollment credentials remain only in this local process. Neither
    fixture secrets nor session bearer values belong in evidence reports.
    """
    credentials={role:secrets.token_urlsafe(32) for role in ('operator','spectator')}
    policy=AdmissionPolicy([dict(credential_sha256=hashlib.sha256(secret.encode()).hexdigest(),
        role=role,allowed_robots=list(robot_ids) if role=='operator' else [],audit_authorized=role=='spectator')
        for role,secret in credentials.items()])
    return policy,credentials

class HTTPClient:
    def __init__(self,base,admission_credential=None):self.base=base;self.token=None;self._admission_credential=admission_credential;self.opener=build_opener(ProxyHandler({}))
    def call(self,path,body=None,expect=200,headers=None):
        h={} if headers is None else dict(headers)
        if self.token:h['Authorization']='Bearer '+self.token
        if body is not None:h['Content-Type']='application/json'
        req=Request(self.base+path,data=None if body is None else json.dumps(body,allow_nan=False).encode(),headers=h)
        try:
            with self.opener.open(req,timeout=2.) as response:status=response.status;data=response.read()
        except HTTPError as e:status=e.code;data=e.read()
        value=json.loads(data)
        if status!=expect:raise RuntimeError(f'{path}: expected {expect}, got {status}: {value}')
        return value
    def open(self,role):
        body={'role':role}
        if self._admission_credential is not None:body['credential']=self._admission_credential
        result=self.call('/v2/sessions',body);self.token=result['token']
        return {k:v for k,v in result.items() if k!='token'}


def run():
    if not __debug__:raise RuntimeError('Qualification must run without Python -O')
    runtime=PlatformRuntime(MuJoCoBackend())
    admission,credentials=local_qa_admission(runtime.control.robot_ids)
    server=PlatformHTTPServer(TransportConfig(port=0,admission_policy=admission),runtime)
    http=threading.Thread(target=server.serve_forever,name='qa-v2-http',daemon=True)
    errors=[]
    def authority():
        try:runtime.run(max_wall_seconds=30.)
        except Exception as e:errors.append(type(e).__name__+': '+str(e))
    physics=threading.Thread(target=authority,name='qa-v2-physics',daemon=True)
    http.start();physics.start()
    base=f'http://127.0.0.1:{server.server_address[1]}'
    a,b,s=[HTTPClient(base,admission_credential=credentials[role]) for role in ('operator','operator','spectator')];checks=[];samples={}
    def check(name,condition,evidence=None):
        row=dict(name=name,passed=bool(condition),evidence=evidence);checks.append(row)
        if not condition:raise RuntimeError('Failed check: '+name)
    def state():return s.call('/v2/state')
    def wait_for(predicate,timeout=3.):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            value=state()
            if predicate(value):return value
            time.sleep(.02)
        raise RuntimeError('Timed out waiting for authoritative telemetry')
    try:
        sessions=[a.open('operator'),b.open('operator'),s.open('spectator')]
        check('three_independent_session_capabilities',len({v['session_id'] for v in sessions})==3)
        ids=a.call('/v2/robots')['robot_ids'];ra,rb=ids[0],ids[len(ids)//2]
        ae=a.call('/v2/claim',{'robot_id':ra,'channels':['motion','gimbal','fire']})['lease_epochs']
        be=b.call('/v2/claim',{'robot_id':rb,'channels':['motion','gimbal','fire']})['lease_epochs']
        check('two_robot_independent_leases',ra!=rb and bool(ae) and bool(be),{'robots':[ra,rb],'scene_count':len(ids)})
        deny=s.call('/v2/claim',{'robot_id':ra,'channels':['motion']},expect=403)
        check('spectator_claim_forbidden',deny['error']=='read_only_session')
        deny=s.call('/v2/control',dict(robot_id=ra,channel='fire',lease_epoch=ae['fire'],seq=1,value={'fire':True},valid_for_s=.2),expect=403)
        check('spectator_command_forbidden',deny['error']=='read_only_session')
        deny=b.call('/v2/claim',{'robot_id':ra,'channels':['motion']},expect=409)
        check('preemption_rejected',deny['error']=='lease_occupied')
        before=wait_for(lambda x:x.get('telemetry_available',False));samples['before_manual']=before
        seq=0
        for _ in range(12):
            seq+=1
            for client,rid,epochs,speed in [(a,ra,ae,.65),(b,rb,be,.35)]:
                client.call('/v2/renew',dict(robot_id=rid,lease_epochs=epochs))
                client.call('/v2/control',dict(robot_id=rid,channel='motion',lease_epoch=epochs['motion'],seq=seq,
                    value=dict(frame='base_link',vx_mps=speed,vy_mps=0.,wz_rps=0.),valid_for_s=.2))
            time.sleep(.04)
        after=state();samples['manual_active']=after
        commands=after['applied_commands']
        check('both_robots_physical_force_active',commands[ra]['force_x']>0 and commands[rb]['force_x']<0,
              {ra:commands[ra],rb:commands[rb]})
        xy0={r['robot_id']:r['xy'] for r in before['robots']};xy1={r['robot_id']:r['xy'] for r in after['robots']}
        moves={r:math.dist(xy0[r],xy1[r]) for r in (ra,rb)}
        check('both_robots_physically_moved',all(v>.01 for v in moves.values()),moves)
        check('distinct_manual_velocities_preserved',after['applied_targets'][ra]['motion']['vx_mps']==.65 and after['applied_targets'][rb]['motion']['vx_mps']==.35)
        stopped=wait_for(lambda x:all(x.get('applied_targets',{}).get(r,{}).get('motion') is None for r in (ra,rb)))
        samples['command_timeout']=stopped
        check('input_disconnect_neutralizes_forces',all(stopped['applied_commands'][r][k]==0 for r in (ra,rb) for k in ('force_x','force_y','yaw_torque')))
        for client,rid,epochs in [(a,ra,ae),(b,rb,be)]:client.call('/v2/renew',dict(robot_id=rid,lease_epochs=epochs))
        def bind(client,rid,epochs,kind,aid,config=None):
            c='motion' if kind=='navigation' else 'gimbal'
            return client.call('/v2/bind',dict(robot_id=rid,kind=kind,lease_epochs={c:epochs[c]},adapter_id=aid,config=config or {}))
        bind(a,ra,ae,'navigation','nav_rule_v1',{'goal_world_m':[0.,0.]})
        bind(b,rb,be,'navigation','nav_stop_test_v1')
        hold=bind(a,ra,ae,'aim','aim_hold_test_v1')
        pixel=bind(b,rb,be,'aim','aim_pixel_baseline_v1')
        algorithms=wait_for(lambda x:x.get('algorithm_status',{}).get(ra,{}).get('navigation')=='active' and x.get('algorithm_status',{}).get(rb,{}).get('navigation')=='active')
        samples['algorithms']=algorithms
        check('different_navigation_adapters_run',algorithms['control']['bindings'][ra]['navigation']['adapter_id']=='nav_rule_v1'
              and algorithms['control']['bindings'][rb]['navigation']['adapter_id']=='nav_stop_test_v1'
              and algorithms['applied_targets'][rb]['motion']['vx_mps']==0.)
        check('different_aim_bindings_and_sensor_fail_closed',algorithms['control']['bindings'][ra]['aim']['adapter_id']=='aim_hold_test_v1'
              and algorithms['control']['bindings'][rb]['aim']['adapter_id']=='aim_pixel_baseline_v1'
              and algorithms['algorithm_status'][rb]['aim']=='required_sensor_unavailable:camera'
              and algorithms['applied_targets'][rb]['gimbal'] is None)
        nextbind=bind(a,ra,ae,'aim','aim_pixel_baseline_v1')
        changed=wait_for(lambda x:x.get('algorithm_status',{}).get(ra,{}).get('aim')=='required_sensor_unavailable:camera')
        check('aim_binding_epoch_changes_and_old_output_removed',nextbind['binding_epoch']>hold['binding_epoch'] and changed['applied_targets'][ra]['gimbal'] is None)
        bind(a,ra,ae,'navigation','nav_stop_test_v1',{'invalid_test_config':True})
        failure=wait_for(lambda x:x.get('algorithm_status',{}).get(ra,{}).get('navigation','').startswith('adapter_error:'))
        check('adapter_fault_neutral_and_http_responsive',failure['applied_targets'][ra]['motion'] is None and failure['steps']>algorithms['steps'])
        bind(a,ra,ae,'navigation','nav_stop_test_v1')
        recovered=wait_for(lambda x:x.get('algorithm_status',{}).get(ra,{}).get('navigation')=='active')
        check('explicit_rebind_recovers_failed_adapter',recovered['applied_targets'][ra]['motion']['vx_mps']==0.)
        deny=a.call('/v2/bind',dict(robot_id=ra,kind='aim',lease_epochs={'gimbal':ae['gimbal']},adapter_id='aim_native_rmcs_v1',config={}),expect=409)
        check('unconfigured_native_not_claimed_working',deny['error'].startswith('adapter_unavailable:'))
        a.call('/v2/release',dict(robot_id=ra,lease_epochs=ae))
        fresh=b.call('/v2/claim',dict(robot_id=ra,channels=['motion']))['lease_epochs']
        deny=a.call('/v2/control',dict(robot_id=ra,channel='motion',lease_epoch=ae['motion'],seq=1000,
            value=dict(frame='base_link',vx_mps=1.,vy_mps=0.,wz_rps=0.),valid_for_s=.2),expect=409)
        check('old_owner_epoch_cannot_replay_after_explicit_release',fresh['motion']>ae['motion'] and deny['error']=='lease_mismatch')
        final=state();samples['final']=final
        check('one_physics_authority_thread',len({v['authority_thread'] for v in samples.values()})==1,{'authority_thread':final['authority_thread'],'steps':final['steps']})
        check('all_fire_requires_manual_and_remains_off',all(not cmd['fire'] for sample in samples.values() for cmd in sample['applied_commands'].values()))
        check('spectator_truth_explicitly_display_only',final['source']=='simulator_truth_display_only' and final['algorithm_input'] is False)
        check('runtime_workers_bounded',final['worker_limits']['created']<=2*len(ids) and final['worker_limits']['max_pending_per_slot']==1,final['worker_limits'])
        result=dict(qualification='real_MuJoCo_no_GL_three_loopback_HTTP_sessions',passed=all(c['passed'] for c in checks),
            checks=checks,samples=samples,limits=dict(cross_machine_LAN_verified=False,actual_camera_aim_verified=False,
                native_wrapper_integration_verified=False,roster_7v7_verified=False,renderer_used=False),errors=errors)
    finally:
        runtime.request_stop();physics.join(4.);server.shutdown();server.server_close();http.join(2.)
    if errors:raise RuntimeError(str(errors))
    if physics.is_alive():raise RuntimeError('Physics thread did not stop')
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    result=run();args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(passed=result['passed'],checks=len(result['checks']),out=str(args.out))))

if __name__=='__main__':main()
