"""Create a distinct, v2-only actual causal goal/velocity probe."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
raw=(ROOT/'tools/qa_navigation_goal_coop_sil.py').read_text(encoding='utf8')
raw=raw.replace('Opt-in original Qt infantry and real Nav2 source-bound goal cancellation SIL.',
 'Opt-in real server goal UUID to sourced PB velocity and original Qt SIL.')
raw=raw.replace('qa_navigation_goal_coop_sil.py','qa_goal_velocity_coop_sil.py')
raw=raw.replace("'rm_match/platform_v2/runtime.py','rm_match/platform_v2/backend.py'", "'tools/audit_navigation_goals.py','tools/prepare_nav2_goal_controller_overlay.py','rm_match/integrations/pb_goal_controller_context.hpp',\n 'rm_match/platform_v2/runtime.py','rm_match/platform_v2/backend.py'")
raw=raw.replace('navigation=audit_navigation_consumption(rows,ros);', "navigation=audit_navigation_consumption(rows,ros,result_profile='follow_path_uuid_v2');")
anchor="    write(out/'PB_RESULT.json',dict(goal=goal,external=external,gate=gate))"
assert raw.count(anchor)==1
raw=raw.replace(anchor,anchor+"\n    from tools.audit_navigation_goals import audit_goal_navigation_consumption\n    goal_motion=audit_goal_navigation_consumption(rows,ros,goal.get('lifecycle',{}));write(out/'GOAL_MOTION_AUDIT.json',goal_motion)")
anchor="    checks=dict(actual_PB_identity=pb_identity,actual_PB_source_consumption=navigation['passed'],"
assert raw.count(anchor)==1
raw=raw.replace(anchor,anchor+"\n        actual_goal_UUID_consumption=goal_motion['passed'] and len(goal_motion['per_goal'])==2 and all(v['nonzero_consumed_steps']>0 for v in goal_motion['per_goal'].values()),")
raw=raw.replace("navigation=navigation,overlap=overlap,relative_goal_completed", "navigation=navigation,goal_motion=goal_motion,overlap=overlap,relative_goal_completed")
raw=raw.replace('actual_offscreen_manual_infantry_real_PB_navigation_and_synthetic_source_bound_goal_hold_cancel_complete',
 'actual_server_UUID_to_PB_controller_sensor_context_and_physical_consumption_with_original_Qt_synthetic_goal_policy')
target=ROOT/'tools/qa_goal_velocity_coop_sil.py';assert not target.exists();target.write_bytes(raw.encode());compile(raw,str(target),'exec')
print('New v2-only causal probe created, not executed.')
