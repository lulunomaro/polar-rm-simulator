"""Bounded real no-GL loopback qualification of scenario baseline auto-resupply.

No direct HP/ammo/coin/pose modification, renderer, model inference or external bind.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import threading
import time
from .backend import MuJoCoBackend
from .runtime import PlatformRuntime
from .server import PlatformHTTPServer,TransportConfig
from .qa_multiclient import HTTPClient

class ObservedBackend(MuJoCoBackend):
    def display_snapshot(self):
        value=super().display_snapshot()
        # Trusted QA display only, accessed on the same physics authority thread.
        value['qa_projectiles_created']=self._sim.projectile_counter
        return value

def run(out):
    if not __debug__:raise RuntimeError('Qualification refuses Python -O')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    backend=ObservedBackend(virtual_resupply='v1-baseline')
    runtime=PlatformRuntime(backend);server=PlatformHTTPServer(TransportConfig(port=0),runtime)
    http=threading.Thread(target=server.serve_forever,daemon=True);errors=[]
    def authority():
        try:runtime.run(max_wall_seconds=15.)
        except BaseException as exc:errors.append(type(exc).__name__+': '+str(exc))
    physics=threading.Thread(target=authority,daemon=True)
    http.start();physics.start();base=f'http://127.0.0.1:{server.server_address[1]}'
    operator,observer,observer2=[HTTPClient(base) for _ in range(3)]
    result={'passed':False,'scope':'simulation_baseline_auto_resupply_real_MuJoCo_no_GL_loopback',
        'checks':[],'limits':{'official_full_rules_qualified':False,'real_LAN':False,'Windows':False,
        'native_aim':False,'rendering':False,'direct_judge_or_pose_mutation':False}}
    def check(name,ok,evidence=None):
        result['checks'].append(dict(name=name,passed=bool(ok),evidence=evidence))
        if not ok:raise RuntimeError('Failed check: '+name)
    def state():return observer.call('/v2/state')
    def robot(s,rid):return next(r for r in s['robots'] if r['robot_id']==rid)
    def wait(predicate,timeout=8.):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            s=state()
            if predicate(s):return s
            time.sleep(.01)
        raise RuntimeError('Timed out waiting for authoritative state')
    try:
        operator.open('operator');observer.open('spectator');observer2.open('spectator')
        before=wait(lambda s:s.get('telemetry_available',False))
        check('normal_spawn_starts_infantry_at_zero',robot(before,'red_infantry')['ammo']==0 and before['sim_time']<1.,{'sim_time':before['sim_time'],'ammo':robot(before,'red_infantry')['ammo']})
        check('configured_only_at_trusted_startup',before['virtual_resupply']['policy']=='v1-baseline' and before['virtual_resupply']['configured_via']=='trusted_startup_only')
        deny=observer.call('/v2/config',{'virtual_resupply':'disabled'},expect=404)
        check('observer_has_no_configuration_endpoint',deny['error']=='not_found')
        deny=observer.call('/v2/sessions',{'role':'spectator','virtual_resupply':'disabled'},expect=400)
        check('observer_cannot_smuggle_policy_into_session',deny['error']=='invalid_fields')
        deny=observer.call('/v2/claim',{'robot_id':'red_infantry','channels':['fire']},expect=403)
        check('observer_cannot_claim_fire',deny['error']=='read_only_session')
        for c,r in ((observer,'red_infantry'),(observer2,'blue_infantry')):c.call('/v2/watch',{'robot_id':r})
        stocked=wait(lambda s:s.get('virtual_resupply',{}).get('purchases')==4)
        vr=stocked['virtual_resupply'];records=vr['last_results']
        check('natural_coin_tick_and_actual_procurement',stocked['team_coins']=={'red':100,'blue':100},stocked['team_coins'])
        check('infantry_hero_and_sentry_actual_ammo',all(robot(stocked,t+'_infantry')['ammo']==50 and robot(stocked,t+'_hero')['ammo']==5 and robot(stocked,t+'_sentry')['ammo']==750 for t in ('red','blue')))
        check('all_four_purchases_charge_existing_judge',len(records)==4 and all(r['accepted'] and r['coins_before']-r['coins_after']==50 and r['bundles']==5 for r in records.values()),records)
        check('multiple_watchers_do_not_multiply_procurement',vr['attempts']==4 and vr['policy']=='v1-baseline')
        epochs=operator.call('/v2/claim',{'robot_id':'red_infantry','channels':['motion','fire']})['lease_epochs']
        x0=robot(stocked,'red_infantry')['xy'][0]
        for seq in range(5):
            operator.call('/v2/control',dict(robot_id='red_infantry',channel='motion',lease_epoch=epochs['motion'],seq=seq,
                value={'frame':'base_link','vx_mps':.35,'vy_mps':0.,'wz_rps':0.},valid_for_s=.2))
            time.sleep(.05)
        moved=state();dx=robot(moved,'red_infantry')['xy'][0]-x0
        check('ordinary_motor_input_moves_stocked_infantry',dx>.01,{'dx_m':dx})
        operator.call('/v2/control',dict(robot_id='red_infantry',channel='motion',lease_epoch=epochs['motion'],seq=5,
            value={'frame':'base_link','vx_mps':0.,'vy_mps':0.,'wz_rps':0.},valid_for_s=.2))
        operator.call('/v2/renew',dict(robot_id='red_infantry',lease_epochs=epochs))
        shots_before=moved['qa_projectiles_created'];ammo_before=robot(moved,'red_infantry')['ammo']
        operator.call('/v2/control',dict(robot_id='red_infantry',channel='fire',lease_epoch=epochs['fire'],seq=0,value={'fire':True},valid_for_s=.1))
        fired=wait(lambda s:s.get('qa_projectiles_created',0)>shots_before)
        delta=fired['qa_projectiles_created']-shots_before
        check('explicit_fire_creates_physical_projectile_and_spends_ammo',delta>0 and ammo_before-robot(fired,'red_infantry')['ammo']==delta,{'projectiles_created':delta,'ammo_before':ammo_before,'ammo_after':robot(fired,'red_infantry')['ammo']})
        neutral=wait(lambda s:not s['applied_commands']['red_infantry']['fire'] and s['sim_time']>2.)
        check('same_balance_no_extra_automatic_purchase',neutral['virtual_resupply']['attempts']==4 and neutral['team_coins']=={'red':100,'blue':100})
        check('one_authoritative_physics_thread',len({s['authority_thread'] for s in (before,stocked,moved,fired,neutral)})==1)
        check('fire_timeout_neutralizes',not neutral['applied_commands']['red_infantry']['fire'])
        check('scenario_not_official_full_rule_qualification',neutral['virtual_resupply']['official_full_rules_qualified'] is False)
        result['passed']=True;result['final_sim_time']=neutral['sim_time'];result['authority_steps']=neutral['steps']
    except BaseException as exc:
        result['error']=type(exc).__name__+': '+str(exc)
    finally:
        runtime.request_stop();physics.join(5.);server.shutdown();server.server_close();http.join(2.)
        result['authority_errors']=errors;result['threads_stopped']=not physics.is_alive() and not http.is_alive()
        if errors or not result['threads_stopped']:result['passed']=False
        (out/'qualification.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    if not result['passed']:raise RuntimeError(result.get('error','Authority failed'))
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',required=True,type=Path);args=parser.parse_args()
    r=run(args.out);print(json.dumps({'passed':r['passed'],'checks':len(r['checks']),'scope':r['scope']}))
if __name__=='__main__':main()
