"""Descriptive gate accounting from saved logs; does not invent visibility labels."""
import argparse,collections,json
from pathlib import Path
if not __debug__:raise SystemExit('Audit assertions require ordinary Python; do not run with -O')
p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('--output',type=Path);a=p.parse_args();r=a.run
summary=json.loads((r/'summary.json').read_text());end_ns=round(summary['physics_seconds']*1e9)
rows=[json.loads(x) for x in (r/'rmcs_source/source_io.jsonl').read_text().splitlines()]
state_ns=collections.Counter();reason_ns=collections.Counter();layer_ns=collections.Counter();positive_frames=negative_frames=0;source_true_ns=wrapper_true_ns=0
for i,row in enumerate(rows):
 start=round(row['t']*1e9);stop=round(rows[i+1]['t']*1e9) if i+1<len(rows) else end_ns
 if stop<start:raise ValueError('Source log time moved backwards')
 dt=max(0,min(end_ns,stop)-min(end_ns,start));state_ns[row['state']]+=dt;reason_ns[row['fire_gate_reason']]+=dt
 response=row['source_response']
 if response is None:layer='source_disabled_by_stationary_navigation_referee_gate'
 elif not response['tracking']:layer='source_active_tracking_unavailable'
 elif not response['should_shoot']:layer='tracking_available_source_fire_controller_refused'
 elif not row['applied']['fire']:layer='source_fire_true_outer_wrapper_refused'
 else:layer='source_and_outer_wrapper_permitted'
 layer_ns[layer]+=dt
 if response and response['should_shoot']:source_true_ns+=dt
 if row['applied']['fire']:wrapper_true_ns+=dt
 if response and response.get('detector_executed'):
  if (response.get('pose_estimated3d') or 0)>0:positive_frames+=1
  else:negative_frames+=1
transport=json.loads((r/'fire_transport.json').read_text());safety_ns=collections.Counter();safe_ns=applied_ns=queue_wait_ns=0
for i,row in enumerate(transport):
 start=row['time_ns'];stop=transport[i+1]['time_ns'] if i+1<len(transport) else end_ns;dt=max(0,min(end_ns,stop)-min(end_ns,start))
 if row['safe']:safe_ns+=dt
 if row['applied_level']:applied_ns+=dt
 if row['safe'] and row['requested_level'] and not row['delayed_level'] and row['pending_count']>0:queue_wait_ns+=dt
 for reason in row['safety_reasons']:safety_ns[reason]+=dt
if sum(layer_ns.values())!=end_ns:raise ValueError('Control log does not partition full match duration')
seconds=lambda c:{k:v/1e9 for k,v in sorted(c.items())}
result=dict(schema='source-gate-layer-accounting-v1',physics_seconds=end_ns/1e9,
 exclusive_control_layer_seconds=seconds(layer_ns),source_state_seconds=seconds(state_ns),wrapper_gate_reason_seconds=seconds(reason_ns),
 source_requested_fire_seconds=source_true_ns/1e9,wrapper_permitted_fire_seconds=wrapper_true_ns/1e9,
 transport=dict(safety_clear_seconds=safe_ns/1e9,applied_true_seconds=applied_ns/1e9,ordinary_rising_delay_wait_seconds=queue_wait_ns/1e9,
 overlapping_immediate_safety_reason_seconds=seconds(safety_ns)),
 perception=dict(delivered_detection_frames_with_3d=positive_frames,delivered_detection_frames_without_3d=negative_frames,
 visibility_ground_truth='not logged; no detection is not evidence that no target was visible',failure_cause='occlusion, optics, detector rejection and absence are not separable from these logs'),
 missing=dict(feeder_cooldown_rejection_attempts='not logged; feed interval is configured but rejection count not measured',
 ammo_heat_rejection_attempts='no explicit per-attempt reason ledger; do not infer a cause from absent launches',selected_target_identity_switches='native response does not expose persistent selected target identity'),
 interpretation=['Control layer durations are exclusive and partition the match; transport safety reasons overlap and must not be summed.',
 'Control states are held until the next 100Hz log row; transport transitions use exact 2000Hz physics-step timestamps.',
 'Requested fire, wrapper permission, delayed applied level and actual UID launches are separate stages.',
 'Team victory and damage from other robots do not establish the red sentry autoaim contribution.'])
if a.output:a.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
