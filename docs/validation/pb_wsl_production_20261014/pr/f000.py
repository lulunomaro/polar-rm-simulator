"""Read-only plan/evidence/Git audit. No ROS/WSL/physics/test reruns."""
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent


def sha(raw):return hashlib.sha256(raw).hexdigest()


def json_file(path):
    path=Path(path)
    if not path.is_file():path=Path(str(path)+'.gz')
    raw=path.read_bytes();decoded=gzip.decompress(raw) if path.suffix=='.gz' else raw
    return json.loads(decoded)


def main():
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip()
    status_before=subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).decode()
    changed=subprocess.check_output(['git','diff-tree','--no-commit-id','--name-only','-r','-z',commit],cwd=ROOT)
    paths=[p.decode() for p in changed.split(b'\0') if p]
    queries=''.join(commit+':'+p+'\n' for p in paths).encode()
    git=subprocess.run(['git','cat-file','--batch'],cwd=ROOT,input=queries,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    raw=git.stdout;offset=0;git_rows=[]
    for path in paths:
        end=raw.index(b'\n',offset);header=raw[offset:end].decode();parts=header.split();size=int(parts[2])
        blob=raw[end+1:end+1+size];offset=end+2+size;current=(ROOT/path).read_bytes()
        git_rows.append(dict(path=path,git_blob=parts[0],bytes=size,git_sha256=sha(blob),workspace_sha256=sha(current),literal_equal=blob==current))
    if offset!=len(raw):raise ValueError('Git batch boundary mismatch')
    archives=[]
    for directory,manifest_name in [('pb_wsl_navigation_20261014','MANIFEST.json'),('quality_wsl_navigation_20261014','PRESERVATION_MANIFEST.json')]:
        base=ROOT/'docs/validation'/directory;manifest=json_file(base/manifest_name);inventory=json_file(base/'FILES.json');rows=[]
        for item in manifest['files']:
            selected=base/item['stored_path'];stored=selected.read_bytes()
            decoded=gzip.decompress(stored) if item['encoding']=='gzip_mtime0' else stored
            source=ROOT/item['source'];artifact_equal=None
            if not item.get('source_origin'):artifact_equal=source.read_bytes()==decoded
            okay=(len(stored)==item['stored_bytes'] and sha(stored)==item['stored_sha256']
                  and len(decoded)==item['original_bytes'] and sha(decoded)==item['original_sha256']
                  and artifact_equal is not False)
            if item.get('executed_sha256'):okay=okay and sha(decoded)==item['executed_sha256']
            rows.append(dict(path=item['stored_path'],literal_and_raw_sha_equal=okay,original_artifact_equal=artifact_equal))
        file_rows=[]
        for item in inventory['files']:
            selected=base/item['path'];data=selected.read_bytes()
            file_rows.append(dict(path=item['path'],bytes_equal=len(data)==item['bytes'],sha_equal=sha(data)==item['sha256']))
        archives.append(dict(directory=directory,payload_count=manifest['count'],payloads=rows,
                             git_inventory_count_including_self=inventory['count']+1,inventory_files=file_rows,
                             manifest_sha256=sha((base/manifest_name).read_bytes()),
                             index_sha256=sha((base/'INDEX.json').read_bytes()),
                             inventory_sha256=sha((base/'FILES.json').read_bytes()),
                             missing_historical_sources=manifest.get('missing_historical_sources',[])))
    quality_base=ROOT/'docs/validation/quality_wsl_navigation_20261014'
    quality=[]
    for group in ('f1','s2'):
        value=json_file(quality_base/group/'manifest.json')
        xmlpath=quality_base/group/'pytest.xml.gz';xmlraw=gzip.decompress(xmlpath.read_bytes())
        xml=ET.fromstring(xmlraw)
        quality.append(dict(group=group,status=value['status'],steps=value['steps'],
                            source_unchanged_during_checks=value.get('source_unchanged_during_checks','not_recorded'),
                            milestone_accepted=value['milestone_accepted'],
                            pytest_xml_suites=[dict(s.attrib) for s in xml.iter('testsuite')],
                            original_source='artifacts/quality-20261014-wsl-navigation-frozen'+('-02' if group=='s2' else '')))
    navigation=[]
    navbase=ROOT/'docs/validation/pb_wsl_navigation_20261014'
    for group in ('f1','s2','s3','s4'):
        value=json_file(navbase/group/'RESULT.json');spec=json_file(navbase/group/'session/SESSION_SPEC.json')
        navigation.append(dict(group=group,actual_steps=value['actual_steps'],sim_seconds=value['simulation_seconds'],
            wall_seconds=value['wall_seconds'],physics_wall_seconds=value.get('physics_wall_seconds'),
            reported_physics_rtf=value['physics_rtf'],run_and_cleanup_rtf=value.get('run_and_cleanup_rtf'),
            consumption=value['consumption_audit'],goal=value['observer_goal'],
            relative_test_goal=spec['relative_test_goal'],production_gate_exercised=not spec['relative_test_goal'],
            shutdown=value['shutdown'],session_cleanup=value['session_cleanup'],errors=value['errors'],
            bounded_navigation_passed=value['bounded_navigation_consumption_passed'],
            source_unchanged=value['source_unchanged']))
    progress=(ROOT/'docs/IMPLEMENTATION_PROGRESS.md').read_text(encoding='utf8')
    task_rows=[line for line in progress.splitlines() if line.startswith('| T')]
    milestone_rows=[line for line in progress.splitlines() if line.startswith('| M')]
    preset=json_file(ROOT/'config/acceptance/m1-v1.json')
    layers=[
        dict(level='static configuration/source/contracts',evidence='quality f1/s2 first3steps and draft acceptance preset',proves='Declared config/source attribution/static interface',does_not_prove='Frozen T01 or runtime/full match'),
        dict(level='unit/synthetic/selected physics regression',evidence='quality s2 pytest1216/48skip/776subtests',proves='Executed scoped branches and source stability during that run',does_not_prove='Explicit skips, ROS/native/camera qualification or milestones'),
        dict(level='actual harmless OS/pipe process lifecycle',evidence='nav archive clean and std1/std2',proves='Owned process groups/IO/cancellation/EOF/short writes on tested platforms',does_not_prove='ROS algorithm or neural inference throughput'),
        dict(level='actual Windows HTTP transport',evidence='quality h0/h1',proves='40before/40after bounded HTTP413 behavior with same reproducer; focused25/31',does_not_prove='Navigation attempt2 timeout root cause'),
        dict(level='actual DDS fixture and sensor codec',evidence='Humble sensor/ext4 DDS archives',proves='Real ROS type/byte/stamp/QoS configured identity and cleaning',does_not_prove='Algorithm closure or archived-frame host deadline'),
        dict(level='actual build/ELF load/plugin configuration',evidence='PB controller/PointLIO05/plugin03 build/audit archives',proves='Known source/build/ELF and actual class loading/configuration',does_not_prove='New-machine packaging, all controller cases or license acceptance'),
        dict(level='Linux single-generation SIL',evidence='pb_navigation_sil_20261014_attempt8',proves='One30s sensor→LIO/map/Smac/PID→779nonzero physical consumption',does_not_prove='Windows service/production gate/accuracy/full missions'),
        dict(level='Windows→WSL QA single-generation SIL',evidence='nav s3/s4 + a3/a4',proves='Two30s QA relative targets,553/514 rows,exact source→ACK→physical audit and raw goal/path/UUID',does_not_prove='Production NavigationGate/external goal client, image80ms/selfaim/GL, long run, nav2 failed timeout repair or complete match'),
        dict(level='archive byte integrity',evidence='Git408 and archive payload/inventory checks in this report',proves='Literal committed/raw/stored bytes and declared history gaps',does_not_prove='Rerun/pass of missing tests or milestone acceptance')]
    blockers=[
        dict(id='P0-T01',kind='plan_freeze_blocker',tasks=['T01'],evidence='config/acceptance/m1-v1.json status=draft, owner/target_hardware/rules/lidar/threshold null',closure='Assign real owners and freeze explicit hardware/calibration/rules/accepted metrics; do not invent approvals'),
        dict(id='P0-T02-T04-LIVE',kind='reproduced_runtime_defect',tasks=['T02','T03','T04'],evidence='native live12原deadline下等待41.232ms仍0response/0consumption; static OFFLINE success separate',closure='Same actual frame/model/T2 realtime80/150ms and originalQt/physical gimbal causal chain; no refresh/warm/cachedframe workaround'),
        dict(id='P0-T05',kind='plan_scope_blocker',tasks=['T05'],evidence='default native stationary red_sentry/single algorithm only',closure='At least2 actual independent vehicle instances with moving-body/role isolation and no unauthorized firing'),
        dict(id='P0-T06',kind='regression_release_blocker',tasks=['T06'],evidence='A02-A04/A11 complete static/moving/loss/reacquire/manual-auto projectiles/disconnect matrix not accepted',closure='Freeze matrix and collect real image→algorithm→gimbal/projectile/referee and fault evidence; passing unit counts insufficient'),
        dict(id='NAV-TIMEOUT-OPEN',kind='known_deadline_reliability_defect_scope_P0_candidate',tasks=['T03','T07','T09'],evidence='WindowsWSL s2 observed_seq67 host receipt beyond original activation deadline,earlystop7.674538s/0complete30s; s3/s4 not reproductions of root cause',closure='Use original host/Linux phase ledgers with separate clocks to reproduce/localize/fix and prove no changed2s/50/150ms; not closed by HTTP repair'),
        dict(id='PRODUCTION-GATE-OPEN',kind='current_phase_validation_blocker_not_yet_proven_code_defect',tasks=['T07','T09','T13','T16'],evidence='All archivedWindows runs relative_test_goal=True; NavigationGate/external client path unexercised',closure='Fresh single generation relative_test_goal=False,actual map/LIO/TF→serveractivation→external rawaction UUID/path/result→SDK consumption and fullownedcleanup')]
    report=dict(schema='polar.pb-progress-readonly-audit.v1',timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        scope='Read-only local files/Git, no fullQA/WSL/ROS/GL/NN/physics/build rerun',commit=commit,
        status_before=status_before,status_after=subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).decode(),
        git_changed_count=len(paths),git_changed_files=git_rows,git_literal_all_equal=all(r['literal_equal'] for r in git_rows),
        archives=archives,all_archive_payloads_equal=all(r['literal_and_raw_sha_equal'] for a in archives for r in a['payloads']),
        all_inventory_files_equal=all(r['bytes_equal'] and r['sha_equal'] for a in archives for r in a['inventory_files']),
        task_status_rows=task_rows,milestone_status_rows=milestone_rows,all_milestones_not_signed_off=True,
        preset_status=preset['status'],unresolved=preset['unresolved'],quality=quality,navigation=navigation,
        evidence_layers=layers,open_blockers=blockers,
        doc_drift=[dict(path='docs/ROBOT_IO_V1.md',finding='Draft final list broadly says actualIMU/pointcloud/ROS2 unimplemented; opt-inNavprofile now hasactual sensors+ROS. Genericdefault idealodom still unqualified; document profiles separately.'),
                   dict(path='docs/ACCEPTANCE_TRACEABILITY.md',finding='A02 tracked execution另测 is older than successfulstaticOFFLINE24; A09 idealodom/default64rays limitation remains but opt-in navigation should be distinguished.')],
        plan_historical_difference='Parent T12 A05–A07 includes A06; repo T12/M3 excludes7v7 and T14/M4 retains A06, not a requirement deletion')
    (OUT/'RESULT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(commit=commit,git_changed_count=len(paths),git_literal_equal=report['git_literal_all_equal'],
                         archive_payload_equal=report['all_archive_payloads_equal'],inventories_equal=report['all_inventory_files_equal'],
                         production_gate_exercised=[n['production_gate_exercised'] for n in navigation],result_sha256=sha((OUT/'RESULT.json').read_bytes()))))
    return 0 if report['git_literal_all_equal'] and report['all_archive_payloads_equal'] and report['all_inventory_files_equal'] else 2


if __name__=='__main__':raise SystemExit(main())
