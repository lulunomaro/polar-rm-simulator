"""Saved-observation CPU microdiagnostic, never an act/deadline/live test."""
from pathlib import Path
import copy
import gc
import gzip
import hashlib
import json
import math
import os
import platform
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
FILES = ('rm_match/integrations/pb_wsl_navigation.py',
         'rm_match/integrations/pb_wsl_navigation_registry.py',
         'rm_match/platform_v2/navigation_contracts.py',
         'rm_match/platform_v2/contracts.py', 'rm_match/platform_v2/runtime.py')
INPUT = ROOT/'artifacts/navigation-sensors-actual-20261013-attempt2-lines4/first_observation.json.gz'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values, q):
    v = sorted(values)
    pos = (len(v)-1)*q
    lo, hi = math.floor(pos), math.ceil(pos)
    return v[lo]+(v[hi]-v[lo])*(pos-lo)


def stats(values):
    return dict(n=len(values), p50_ms=statistics.median(values)/1e6,
                p95_ms=percentile(values,.95)/1e6,
                p99_ms=percentile(values,.99)/1e6,
                max_ms=max(values)/1e6, min_ms=min(values)/1e6)


def main():
    started=time.perf_counter()
    source_before={n:sha(ROOT/n) for n in FILES}
    input_before=sha(INPUT)
    from rm_match.platform_v2.navigation_contracts import validate_navigation_observation, decode_points
    observation=json.loads(gzip.decompress(INPUT.read_bytes()))
    payload_json=json.dumps(observation,sort_keys=True,separators=(',',':'),allow_nan=False)
    # Original timestamps are deliberately kept. Validation has no authority
    # clock comparison and this program never calls act/exchange or resets.
    checked=validate_navigation_observation(observation)
    packet=dict(op='act',observation=observation)
    detached=copy.deepcopy(packet)
    cloud=observation['sensors']['pointcloud']
    text=cloud['data_base64']
    input_facts=dict(schema=observation['schema'],point_count=cloud['point_count'],
        packed_point_bytes=len(decode_points(cloud)),base64_characters=len(text),
        imu_count=len(observation['sensors']['imu']['samples']),
        detached_string_same_identity=detached['observation']['sensors']['pointcloud']['data_base64'] is text,
        validator_return_string_same_identity=checked['sensors']['pointcloud']['data_base64'] is text,
        original_identity={k:observation[k] for k in ('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')})
    rows=[];gc_rows=[];active=None;pending={}
    def gc_event(phase,info):
        generation=info['generation']
        if phase=='start':pending[generation]=(time.perf_counter_ns(),time.thread_time_ns(),active)
        else:
            beginning=pending.pop(generation,None)
            if beginning:
                gc_rows.append(dict(generation=generation,operation=beginning[2],
                    wall_ns=time.perf_counter_ns()-beginning[0],thread_cpu_ns=time.thread_time_ns()-beginning[1],
                    collected=info['collected'],uncollectable=info['uncollectable']))
    operations={
        'packet_deepcopy_only':lambda:copy.deepcopy(packet),
        'validator_only':lambda:validate_navigation_observation(observation),
        'current_hot_segment':lambda:validate_navigation_observation(copy.deepcopy(packet)['observation']),
    }
    thresholds=gc.get_threshold();enabled=gc.isenabled();counts=gc.get_count()
    gc.callbacks.append(gc_event)
    try:
        for name,operation in operations.items():
            for index in range(100):
                active=dict(operation=name,index=index)
                wall=time.perf_counter_ns();thread=time.thread_time_ns();process=time.process_time_ns()
                result=operation()
                row=dict(operation=name,index=index,wall_ns=time.perf_counter_ns()-wall,
                         thread_cpu_ns=time.thread_time_ns()-thread,process_cpu_ns=time.process_time_ns()-process)
                rows.append(row)
                del result
    finally:
        active=None
        gc.callbacks.remove(gc_event)
    summary={name:{metric:stats([r[metric] for r in rows if r['operation']==name])
        for metric in ('wall_ns','thread_cpu_ns','process_cpu_ns')} for name in operations}
    report=dict(schema='polar.pb.hotpath-cpu-diagnostic.v1',scope='idle saved-input CPU prep only, not actual runtime/GIL contention/ROS/WSL/deadline acceptance',
        input_path=str(INPUT),input_sha256=input_before,input_facts=input_facts,
        source_sha256=source_before,script_sha256=sha(Path(__file__)),samples=rows,gc_events=gc_rows,summary=summary,
        gc_settings=dict(enabled=enabled,thresholds=thresholds,counts_before=counts,counts_after=gc.get_count()),
        source_unchanged=source_before=={n:sha(ROOT/n) for n in FILES},input_unchanged=input_before==sha(INPUT),
        observation_unchanged=payload_json==json.dumps(observation,sort_keys=True,separators=(',',':'),allow_nan=False),
        timestamps_changed=False,authority_or_act_called=False,ROS_started=False,WSL_started=False,GL_started=False,
        python=sys.version,executable=sys.executable,system=platform.platform(),cpu_count=os.cpu_count(),
        switch_interval_s=sys.getswitchinterval(),elapsed_s=time.perf_counter()-started)
    if not all(report[k] for k in ('source_unchanged','input_unchanged','observation_unchanged')):
        raise RuntimeError('diagnostic_source_or_input_changed')
    (OUT/'CPU_DIAGNOSTIC.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf8')
    (OUT/'PROCESS_RESULT.json').write_text(json.dumps({k:report[k] for k in ('source_unchanged','input_unchanged','observation_unchanged','elapsed_s','script_sha256','ROS_started','WSL_started','GL_started')},indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(summary=summary,input_facts=input_facts,gc_events=gc_rows,elapsed_s=report['elapsed_s']),indent=2))


if __name__=='__main__':main()
