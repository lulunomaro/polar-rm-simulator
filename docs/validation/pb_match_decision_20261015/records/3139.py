"""Read-only analysis of real recorded actor ticks; never changes firing gates."""
import argparse,json
from pathlib import Path
from collections import Counter

def analyze(path):
    counts=Counter();statuses=Counter();errors=[];first=None;last=None;session_counts={}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        try:row=json.loads(line)
        except json.JSONDecodeError:
            counts['incomplete_lines_skipped']+=1;continue
        if row.get('kind')!='actual_aim_tick':continue
        t=row['telemetry'];counts['actor_ticks']+=1
        first=row['sim_time'] if first is None else first;last=row['sim_time']
        statuses[row['status']]+=1
        counts['camera_frames']+=bool(row.get('camera_frame'))
        counts['positive_detector_frames']+=bool(row.get('camera_frame') and t.get('detections',0)>0)
        counts['fire_requested_ticks']+=bool(row['command'].get('fire'))
        counts['not_tracking_ticks']+=not bool(t.get('tracking'))
        counts['not_fresh_ticks']+=not bool(t.get('fresh'))
        counts['invalid_action_ticks']+=not bool(t.get('valid_action'))
        if t.get('tracking') and t.get('fresh') and t.get('valid_action'):
            error=t.get('aim_error_deg');tolerance=t.get('fire_angle_tol_deg')
            if error is not None and tolerance is not None:
                errors.append(error)
                counts['tracked_fresh_valid_over_angle']+=error>tolerance
                counts['tracked_fresh_valid_within_angle']+=error<=tolerance
        session_counts[row['robot_id']]={k:t.get(k) for k in ('detector_session_calls','policy_session_calls')}
    return dict(first_sim_time=first,last_sim_time=last,counts=dict(counts),statuses=dict(statuses),
        latest_session_counts=session_counts,
        tracked_fresh_valid_angle_min_deg=min(errors) if errors else None,
        tracked_fresh_valid_angle_max_deg=max(errors) if errors else None,
        overlapping_conditions=True,
        limits=['Source fire-logit and cooldown cannot be inferred unless separately logged.',
                'Angle gating evidence does not independently validate target pose or physical bore alignment.',
                'A partial log is not a terminal episode or a successful hit benchmark.'])

def main():
    p=argparse.ArgumentParser();p.add_argument('telemetry',type=Path);args=p.parse_args()
    print(json.dumps(analyze(args.telemetry),indent=2))
if __name__=='__main__':main()
