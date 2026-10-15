from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'artifacts/goal-velocity-config-20261015-02';out.mkdir()
old=ROOT/'artifacts/goal-velocity-config-20261015-01/STACK_CONFIG.json'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(old)=='fcc973501ec24a371d1af71980ec5738ba293da66d09bfb4bc9162508159621a'
value=json.loads(old.read_bytes());value['mapping_profile']='stationary_scan_accumulation_v1'
p=out/'STACK_CONFIG.json';p.write_bytes((json.dumps(value,indent=2)+'\n').encode())
(out/'CONFIG_PROOF.json').write_bytes((json.dumps(dict(original_path=str(old),original_sha256=sha(old),
 new_sha256=sha(p),only_added_field='mapping_profile',no_asset_change=True,
 original_SI_time_interval=.2,original_mapping_algorithm=True,no_map_or_pose_synthesis=True,
 source='https://raw.githubusercontent.com/SteveMacenski/slam_toolbox/2.6.10/src/slam_toolbox_common.cpp',
 qualification='explicit config only, not runtime acceptance'),indent=2)+'\n').encode())
raw=(ROOT/'artifacts/run_goal_velocity_coop_20261015.py').read_text(encoding='utf8')
raw=raw.replace('goal-velocity-config-20261015-01','goal-velocity-config-20261015-02')
p=ROOT/'artifacts/run_stationary_goal_velocity_coop_20261015.py';assert not p.exists();p.write_bytes(raw.encode())
print('New explicit real-SLAM configuration and driver prepared; old configs unchanged.')
