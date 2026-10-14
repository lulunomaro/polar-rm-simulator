"""Actual Windows->WSL original model loading and original 2s reset, no image."""
from pathlib import Path
import hashlib,json,sys,time,traceback
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from rm_match.deployment.aim_plugin import CAPABILITIES,MANIFEST_SCHEMA,register_aim_plugins
from rm_match.deployment.wsl_jsonl import PreparedWslAimPlugins
from rm_match.platform_v2.adapters import Registry
out=ROOT/'artifacts/tongji-aim-actual-prepare-reset-20261014-01';out.mkdir()
instance=ROOT/'artifacts/tongji-aim-instance-20261014-01/instance.json'
linux=lambda p:'/mnt/c/'+p.relative_to(Path('C:/')).as_posix()
row=dict(adapter_id='custom_tongji_original_camera_aim',label='Tongji original native algorithm, actual startup only',
    command=[linux(ROOT/'.venv-linux/bin/python'),'-u',linux(ROOT/'artifacts/tongji-aim-native-preparation-20261014-04/jsonl_wrapper.py'),
        '--spec',linux(instance),'--spec-sha256',hashlib.sha256(instance.read_bytes()).hexdigest()],
    cwd=linux(ROOT),supported_robots=['red_sentry'],transport='wsl_jsonl_v1',capabilities=CAPABILITIES,
    wsl=dict(distribution='Ubuntu',python='/usr/bin/python3',process_env={}))
manifest=out/'aim-plugins.json';manifest.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA,adapters=[row]),indent=2)+'\n',encoding='utf8')
pool=adapter=None;result=dict(images_submitted=0,physics_steps=0,scope='Actual native model loading, prepare and reset only; no NN/image/live/GUI qualification')
try:
    start=time.perf_counter();pool=PreparedWslAimPlugins(manifest,repo_root=ROOT,shared_root=ROOT/'artifacts/aim-wsl',startup_timeout=15.)
    result['prepare_s']=time.perf_counter()-start
    registry=Registry();register_aim_plugins(registry,manifest,wsl_prepared=pool)
    adapter=registry.create(row['adapter_id'],{})
    start=time.perf_counter();adapter.reset(dict(episode=1,robot_id='red_sentry',binding_epoch=2))
    result.update(reset_s=time.perf_counter()-start,prepare_ack=True,reset_ack=True)
except BaseException as error:
    result['error']=type(error).__name__+':'+str(error);(out/'error.log').write_text(traceback.format_exc(),encoding='utf8')
finally:
    errors=[]
    if adapter is not None:
        try:adapter.close()
        except BaseException as error:errors.append(type(error).__name__+':'+str(error))
        result['adapter_shutdown']=adapter.shutdown_status
    if pool is not None:
        try:pool.close_unclaimed()
        except BaseException as error:errors.append(type(error).__name__+':'+str(error))
    result['cleanup_errors']=errors;result['passed']=result.get('prepare_ack') is True and result.get('reset_ack') is True and not errors
    (out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 2)
