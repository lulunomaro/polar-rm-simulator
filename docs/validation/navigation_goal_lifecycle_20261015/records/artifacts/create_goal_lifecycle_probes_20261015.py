"""Create independent source-pinned lifecycle probes, preserving old run tools."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def fresh(name,body):
    p=ROOT/name;assert not p.exists(),name;p.write_bytes(body.encode());compile(body,str(p),'exec')
old=(ROOT/'tools/qa_pb_external_navigation_goal.py').read_text(encoding='utf8');prefix=old[:old.index('def main(argv=None):')]
extra="    'tools/qa_navigation_goal_client.py',\n    'tools/qa_navigation_goal_supervisor.py',\n    'rm_match/integrations/navigation_goal_lifecycle.py',\n    'rm_match/integrations/nav2_goal_backend.py',\n    'rm_match/platform_v2/decision_contracts.py',\n"
prefix=prefix.replace('SOURCE_FILES=(\n','SOURCE_FILES=(\n'+extra)
fresh('tools/qa_navigation_goal_client.py',prefix+(ROOT/'artifacts/goal_lifecycle_client_main_20261015.py').read_text(encoding='utf8'))
supervisor=(ROOT/'tools/qa_pb_external_goal_supervisor.py').read_text(encoding='utf8').replace('tools.qa_pb_external_navigation_goal','tools.qa_navigation_goal_client').replace("ROOT/'tools/qa_pb_external_navigation_goal.py'","ROOT/'tools/qa_navigation_goal_client.py'")
fresh('tools/qa_navigation_goal_supervisor.py',supervisor)
host=(ROOT/'tools/pb_external_goal_session.py').read_text(encoding='utf8')
begin=host.index('    def prepare(self):');end=host.index('    def request_stop(self):',begin)
prepare=host[begin:end].replace("self.root/'tools/qa_pb_external_goal_supervisor.py'","self.root/'tools/qa_navigation_goal_supervisor.py'")
imports='''"""Owned lifecycle action peer; separate source-pinned executable."""
import queue,subprocess,threading,time
from rm_match.deployment.profile import digest
from rm_match.deployment.wsl_profile import host_to_linux_path
from tools.pb_external_goal_session import ExternalGoalSession,SCHEMA,strict_json
class NavigationGoalSession(ExternalGoalSession):
'''
fresh('tools/navigation_goal_session.py',imports+prepare)
body=(ROOT/'tools/qa_qt_pb_coop_sil.py').read_text(encoding='utf8')
body=body.replace('Opt-in original manual Qt infantry plus real PB Point-LIO/Nav2 sentry SIL.','Opt-in original Qt infantry and real Nav2 source-bound goal cancellation SIL.')
body=body.replace("'tools/qa_qt_pb_coop_sil.py'","'tools/qa_navigation_goal_coop_sil.py','tools/navigation_goal_session.py','tools/qa_navigation_goal_client.py','tools/qa_navigation_goal_supervisor.py','rm_match/integrations/navigation_goal_lifecycle.py','rm_match/integrations/nav2_goal_backend.py','rm_match/platform_v2/decision_contracts.py'")
body=body.replace('from tools.pb_external_goal_session import ExternalGoalSession','from tools.navigation_goal_session import NavigationGoalSession as ExternalGoalSession')
body=body.replace('from tools.qa_pb_external_navigation_goal import SOURCE_FILES','from tools.qa_navigation_goal_client import SOURCE_FILES')
body=body.replace("goal.get('planner_status')==4 and goal.get('follow_path_accepted') is True", "goal.get('schema')=='polar.sim.navigation-goal-scenario.v1' and goal.get('completed') is True and goal.get('lifecycle',{}).get('clean') is True")
body=body.replace("relative_goal_completed=goal.get('follow_path_status')==4", "relative_goal_completed=goal.get('completed') is True,goal_lifecycle=goal.get('lifecycle',{})")
body=body.replace('actual_offscreen_original_keyboard_mouse_camera_manual_infantry_and_real_PB_navigation_MuJoCo_WSL','actual_offscreen_manual_infantry_real_PB_navigation_and_synthetic_source_bound_goal_hold_cancel_complete')
fresh('tools/qa_navigation_goal_coop_sil.py',body)
print('Created separate immutable-source lifecycle probe paths; compile only')
