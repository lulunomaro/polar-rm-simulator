"""Generate fresh preservation/sealing tools; do not run quality or mutate Git."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
base='97828ded30b823fac8b14542aba153548a33340a'
package='navigation_goal_lifecycle_20261015'
old=(ROOT/'artifacts/preserve_qt_pb_coop_20261015.py').read_text(encoding='utf8')
old=old.replace('qt_pb_coop_20261015',package).replace('82029a6aec74a303253fb9417d63a6d669e54cc1',base)
old=old.replace('aim-followup-quality-driver-20261014-10','aim-followup-quality-driver-20261014-11')
start=old.index("directories=['pb-coop-preflight");end=old.index('\nfiles=[]',start)
dirs=['navigation-goal-lifecycle-focused-20261015-01']+[f'nav2-goal-backend-focused-20261015-{n:02}' for n in range(1,4)]
dirs+=['quality-aim-followup-20261014-11','aim-followup-quality-driver-20261014-11']
dirs+=[f'navigation-goal-coop-{kind}-20261015-{n:02}' for kind in ('actual','driver') for n in range(1,5)]
old=old[:start]+'directories='+repr(dirs)+old[end:]
start=old.index("source=['rm_match/integrations/pb_wsl");end=old.index('\nfiles +=',start)
sources=['rm_match/integrations/navigation_goal_lifecycle.py','rm_match/integrations/nav2_goal_backend.py',
 'rm_match/platform_v2/decision_contracts.py','tools/pb_coop_cleanup.py','tools/navigation_goal_session.py',
 'tools/qa_navigation_goal_client.py','tools/qa_navigation_goal_supervisor.py','tools/qa_navigation_goal_coop_sil.py',
 'tests/test_navigation_goal_lifecycle.py','tests/test_nav2_goal_backend.py',
 'docs/NAVIGATION_GOAL_LIFECYCLE.md','docs/UNIVERSAL_PLUGIN_INTERFACES.md','docs/COOP_PLAYABLE_PATH.md',
 'docs/IMPLEMENTATION_PROGRESS.md','artifacts/goal_lifecycle_client_main_20261015.py',
 'artifacts/create_goal_lifecycle_probes_20261015.py','artifacts/create_goal_driver_20261015.py',
 'artifacts/run_navigation_goal_coop_20261015.py','artifacts/run_aim_followup_quality_20261014.py',
 'artifacts/create_navigation_goal_preservation_20261015.py','artifacts/preserve_navigation_goal_lifecycle_20261015.py']
old=old[:start]+'source='+repr(sources)+old[end:]
old=old.replace("qualification='real original offscreen Qt manual infantry plus Windows/WSL PB sourced navigation single-goal coexistent five/thirty second SIL; middle reset-deadline failure retained; no match tree/aim/visible desktop/performance/LAN/full match acceptance'", "qualification='goal-only asynchronous library and real original offscreen Qt/PB Nav2 cancellation then second-goal completion; synthetic high-level policy, first three actual failures retained; no match tree/feedback-linked velocity/aim/visible desktop/performance/LAN/full match acceptance'")
assert "quality-aim-followup-20261014-10" not in old
target=ROOT/'artifacts/preserve_navigation_goal_lifecycle_20261015.py';assert not target.exists()
target.write_bytes(old.encode());compile(old,str(target),'exec')
seal=(ROOT/'artifacts/seal_qt_pb_coop_20261015.py').read_text(encoding='utf8')
seal=seal.replace('qt_pb_coop_20261015',package).replace('aim-followup-quality-driver-20261014-10','aim-followup-quality-driver-20261014-11')
seal=seal.replace('qt_pb_coop_archive_readme_20261015.md','navigation_goal_lifecycle_archive_readme_20261015.md')
target=ROOT/'artifacts/seal_navigation_goal_lifecycle_20261015.py';assert not target.exists()
target.write_bytes(seal.encode());compile(seal,str(target),'exec')
print('Fresh preservation/seal scripts generated; no archive or Git mutation.')
