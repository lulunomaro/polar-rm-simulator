from pathlib import Path
p=Path(__file__).resolve().parent/'run_navigation_goal_coop_20261015.py';assert not p.exists()
s=p.with_name('run_qt_pb_coop_20261015.py').read_text(encoding='utf8')
s=s.replace('qt-pb-coop-driver-20261015','navigation-goal-coop-driver-20261015').replace('qt-pb-coop-actual-20261015','navigation-goal-coop-actual-20261015')
s=s.replace('tools/qa_qt_pb_coop_sil.py','tools/qa_navigation_goal_coop_sil.py')
s=s.replace('names=[',"names=['tools/qa_navigation_goal_client.py','tools/qa_navigation_goal_supervisor.py','tools/navigation_goal_session.py','rm_match/integrations/navigation_goal_lifecycle.py','rm_match/integrations/nav2_goal_backend.py','rm_match/platform_v2/decision_contracts.py',",1)
p.write_bytes(s.encode());compile(s,str(p),'exec')
