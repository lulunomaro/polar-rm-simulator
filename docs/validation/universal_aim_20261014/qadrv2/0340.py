import json
from rm_match.diagnostics import analyze

def test_diagnostic_distinguishes_guards_and_session_counters(tmp_path):
    path=tmp_path/'ticks.jsonl'
    row=dict(kind='actual_aim_tick',robot_id='red_sentry',sim_time=.01,status='actual',camera_frame=True,
        command={'fire':False},telemetry=dict(tracking=True,fresh=True,valid_action=True,aim_error_deg=5,
        fire_angle_tol_deg=3,detections=1,policy_session_calls=1,detector_session_calls=1))
    path.write_text(json.dumps(row)+'\n'+json.dumps({**row,'sim_time':.01,'status':'repeated_clock','camera_frame':False,
        'telemetry':dict(tracking=False,fresh=False,valid_action=False,policy_session_calls=1,detector_session_calls=1)})+'\n{')
    d=analyze(path)
    assert d['counts']['actor_ticks']==2 and d['counts']['camera_frames']==1
    assert d['counts']['tracked_fresh_valid_over_angle']==1
    assert d['counts']['incomplete_lines_skipped']==1
    assert d['latest_session_counts']['red_sentry']['policy_session_calls']==1

def test_portable_json_removes_nonfinite_source_diagnostics():
    from rm_match.serialization import dumps
    import numpy as np
    value=json.loads(dumps({'angle':float('inf'),'nan':np.float64('nan'),'ok':np.float64(1)}))
    assert value=={'angle':None,'nan':None,'ok':1.}
