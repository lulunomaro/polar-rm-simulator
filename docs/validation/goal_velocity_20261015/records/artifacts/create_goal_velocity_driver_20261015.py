from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
raw=(ROOT/'artifacts/run_navigation_goal_coop_20261015.py').read_text(encoding='utf8')
raw=raw.replace('navigation-goal-coop-driver','goal-velocity-coop-driver').replace('navigation-goal-coop-actual','goal-velocity-coop-actual')
raw=raw.replace('tools/qa_navigation_goal_coop_sil.py','tools/qa_goal_velocity_coop_sil.py')
raw=raw.replace('artifacts/pb-navigation-sil-config-20261014-04.json','artifacts/goal-velocity-config-20261015-01/STACK_CONFIG.json')
raw=raw.replace("'rm_match/platform_v2/runtime.py',", "'rm_match/platform_v2/runtime.py','tools/audit_navigation_goals.py','tools/pb_navigation_stack.py','tools/qa_pb_navigation_sil.py','rm_match/integrations/pb_navigation_bridge.py','rm_match/integrations/pb_wsl_navigation_worker.py','rm_match/integrations/pb_goal_controller_context.hpp','tools/prepare_nav2_goal_controller_overlay.py',")
target=ROOT/'artifacts/run_goal_velocity_coop_20261015.py';assert not target.exists();target.write_bytes(raw.encode());compile(raw,str(target),'exec')
print('Fresh v2 actual driver ready; no native/GL started.')
