"""Read-only final audit; observer truth is never returned to the actor."""
import argparse,collections,gzip,hashlib,json,math
from pathlib import Path
from collections import Counter
if not __debug__:raise SystemExit('Audit assertions require ordinary Python; do not run with -O')
p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('--output',type=Path);a=p.parse_args();r=a.run
load=lambda n:json.loads((r/n).read_text())
s=load('summary.json');launch=load('launches.json');resolved=load('uid_resolutions.json');events=load('referee_events.json');contacts=load('projectile_contacts.json')
uid={x['uid']:x for x in launch};resolution={x['uid']:x for x in resolved}
assert len(uid)==len(launch) and len(resolution)==len(resolved)
assert set(uid)==set(resolution)|set(s['uid_audit']['active_censored_at_end'])
assert not set(resolution)&set(s['uid_audit']['active_censored_at_end'])
robot={rid:dict(shots=0,resolved=0,censored=0,geometric_armor_contacts=0,judge_valid_damage=0,hp_removed=0) for rid in {x['owner'] for x in launch}}
for x in launch:robot[x['owner']]['shots']+=1
for x in resolved:
 d=robot[x['owner']];d['resolved']+=1;d['geometric_armor_contacts']+=x['geometric_armor_contact'];d['judge_valid_damage']+=x['judge_valid_damage'];d['hp_removed']+=x['hp_removed']
for x in s['uid_audit']['active_censored_at_end']:robot[uid[x]['owner']]['censored']+=1
rows=[json.loads(l) for l in (r/'rmcs_source/source_io.jsonl').read_text().splitlines()]
controls=[x for x in rows if x['source_response'] is not None];frames=[x for x in rows if x['request_frame'] is not None]
assert all(x['source_response']['clock_time_ns']==round(x['t']*1e9) for x in controls)
assert all(x['request_frame']['exposure_timestamp_ns']%12500000==0 for x in frames)
assert all(0<=round(x['t']*1e9)-x['request_frame']['exposure_timestamp_ns']<12500000 for x in frames)
for x in launch:
 if x['owner']=='red_sentry':
  e=x['transport_event'];assert e and e['level'] is True and e['release_ns']-e['decision_ns']==40000000 and e['release_ns']<=x['launch_ns']
for team in ('red','blue'):
 assert sum(x['hp_removed'] for x in resolved if x['owner'].startswith(team+'_'))==s['uid_audit']['judge_attack_damage'][team]
source_events=load('rmcs_source/source_events.json');source_summary=load('rmcs_source/integration_summary.json')
assert source_summary['source_artifacts_unchanged']
report=dict(status='passed',complete_episode=s['complete_episode'],winner=s['winner'],reason=s['terminal_reason'],vp=s['vp'],physics_seconds=s['physics_seconds'],wall_seconds=s['wall_seconds'],robots=robot,
 source=dict(segments=s['rmcs_source_segments'],control_ticks=len(controls),delivered_frames=len(frames),captures=s['source_captures'],
  detector_executed=sum(bool(x['source_response'].get('detector_executed')) for x in controls),
  detector_positive_calls=sum((x['source_response'].get('pose_estimated3d') or 0)>0 for x in controls),
  tracking_ticks=sum(x['source_response']['tracking'] for x in controls),source_shoot_ticks=sum(x['source_response']['should_shoot'] for x in controls),
  wrapper_fire_ticks=s['rmcs_source_fire_permission_ticks'],negative_completed_observations=sum(x['source_response'].get('completed_result_event') and not x['source_response'].get('completed_result_observed_now') for x in controls),
  segment_close_reasons=dict(collections.Counter(x['reason'] for x in source_events if x['type']=='source_segment_cleared'))),
 checks=dict(unique_uid=True,uid_partition=True,damage_conservation=True,exact_native_clock=True,exposure80_grid=True,selected_frame_age=True,red_launch_transport=True,source_artifacts_unchanged=True),
 video_frames=s['recorded_frames'],video_fps=s['fps'],terminal_hold_s=s['video_terminal_hold_s'],limits=s['scope_limits'])
source_impacts=[x for x in events if x['type']=='impact' and x.get('shooter_id')=='red_sentry']
report['source']['impact_rejection_reasons']=dict(Counter(x.get('reason') or 'valid_damage' for x in source_impacts))
report['source']['physical_contact_targets']=dict(Counter(x.get('target_id') for x in source_impacts))
report['source']['source_active_seconds']=len(controls)/100
report['source']['source_tracking_reported_seconds']=report['source']['tracking_ticks']/100
report['source']['tracking_duration_definition']='Source reported tracking=True; not independently measured target error qualification'
report['source']['active_duration_definition']='Native control response active; excludes pre-start settling wait'
if a.output:a.output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
