"""Read frozen offline outputs only; no ROS/WSL/native/NN or tests."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).parent
RUN=ROOT/'artifacts/native-opencv-thread-comparison-20261014-01'
BUILD=ROOT/'artifacts/native-compiled-properties-trace-build-20261014'
sys.path.insert(0,str(ROOT))
from tools.native_model_properties import parse_native_model_properties
from tools.diagnose_native_saved_compute import parse_native_phase_stderr
inputs={}


def read(path):
    raw=path.read_bytes();inputs[path.relative_to(ROOT).as_posix()]=hashlib.sha256(raw).hexdigest();return raw


def js(path):return json.loads(read(path))


r=js(RUN/'RESULT.json');original_request=js(RUN/'SAVED_REQUEST.json');cases=[];all_checks=[]
for index,variant in enumerate(('default','cv1','cv1','default','default','cv1','cv1','default'),1):
    directory=RUN/f'{index:02}_{variant}'
    row=js(directory/'RESULT.json');command=js(directory/'COMMAND.json')
    properties=js(directory/'PROPERTIES.json');phases=js(directory/'PHASE_REPORT.json')
    startup=js(directory/'STARTUP_PROPERTIES.json');packet=js(directory/'PACKET.json')
    raw_packet=read(directory/'REQUEST_BYTES.jsonl');raw_stderr=read(directory/'native_stderr.log')
    cleanup=js(directory/'CLEANUP.json');raw_matches=json.loads(raw_packet)==packet
    identity=dict(frame_id=packet['frame']['frame_id'],exposure_timestamp_ns=packet['frame']['exposure_timestamp_ns'],control_time_ns=packet['control_time_ns'])
    mode=command['relevant_environment'].get('OPENCV_FOR_THREADS_NUM')
    clean=cleanup['clean'] is True and cleanup['reaped'] is True and cleanup['group_empty'] is True and cleanup['remaining_members']==[] and cleanup['errors']==[]
    cv=properties['record']['cv_num_threads']['value']
    core_equal=all(value['status']=='known' and type(value['value']) is type(r['plan']['expected_compiled_properties'][key]) and value['value']==r['plan']['expected_compiled_properties'][key] for key,value in properties['record']['properties'].items())
    checks=dict(typed_clock_identity=identity==r['plan']['saved_identity'],raw_packet_matches=raw_matches,
                actual_bgr_sha=packet['frame']['image']['sha256']==r['plan']['image_sha256'],
                correct_environment=mode==('1' if variant=='cv1' else None),core_equal=core_equal,
                same_startup_properties=startup==properties,owned_clean=clean,
                stderr_sha=row['stderr_sha256']==hashlib.sha256(raw_stderr).hexdigest())
    checks['raw_properties_reparsed']=parse_native_model_properties(raw_stderr,expected_profile='first-frame-trace')==properties
    checks['raw_phases_reparsed']=parse_native_phase_stderr(raw_stderr.decode('utf-8'),original_request,
        expected_profile='first-frame-trace',eof_complete=cleanup['reaped'] is True)==phases
    if variant=='default':
        raw_reply=read(directory/'RESPONSE_BYTES.jsonl');response=js(directory/'FIRST_RESPONSE.json')
        checks.update(actual_first_detection=response['response']['detector_executed'] is True,
            preserved_response_clock=type(response['response']['clock_time_ns']) is int and response['response']['clock_time_ns']==packet['control_time_ns'],
            raw_reply_match=json.loads(raw_reply)==response['response'],all_first_phases=phases['first_frame_complete'] is True,
            actual_input_complete=row['io_evidence']['stdin_written_bytes']==row['io_evidence']['stdin_expected_bytes']==len(raw_packet))
    else:
        checks.update(no_packet_submitted='io_evidence' not in row and 'first_response' not in row,
            no_native_first_tick_or_infer=not any(not phase['startup'] for phase in phases['completed_phases']),
            rejected_unapplied_factor=any('opencv_threads_not_effective' in error for error in row['errors']))
    all_checks.extend(checks.values())
    cases.append(dict(index=index,variant=variant,cv_num_threads=cv,
        response_ms=None if 'first_response' not in row else row['first_response']['response_s']*1000,
        actual_stdin_written_bytes=row.get('io_evidence',{}).get('stdin_written_bytes',0),
        first_phase_ms={phase['phase']:phase['elapsed_ns']/1e6 for phase in phases['completed_phases'] if not phase['startup']},checks=checks))
cache=read(BUILD/'cmake/CMakeCache.txt').decode();link=read(BUILD/'cmake/CMakeFiles/rmcs_sim_operator_fov.dir/link.txt').decode()
report=dict(schema='polar.native-opencv-env-readonly-audit.v1',scope='Existing frozen Linux offline evidence only; no new execution.',
    raw_checks_pass=all(all_checks),cases=cases,actual_default_first_inferences=4,actual_cv1_first_inferences=0,
    comparison_qualified=False,live_qualified=False,comparison_failure='Requested env factor was not effective at verified zero-tick readiness; strict guard blocked all four cv1 requests.',
    source_unchanged=r['source_unchanged'],tmpfs_removed=r['tmpfs_removed'],
    build_opencv=dict(cmake_found_4_10='v4.10.0(4.10)' in cache,core_linked_4_10='/usr/lib/x86_64-linux-gnu/libopencv_core.so.4.10.0' in link,
        configured_package='/usr/lib/x86_64-linux-gnu/cmake/opencv4',parallel_backend_not_recorded=True,
        qualification='Actual CMake/link inputs identify 4.10.0; runtime getBuildInformation/backend/loaded library SHA was not recorded.'),
    next_single_factor=dict(implementation='New explicit diagnostic generated main: cv::setNumThreads(1) before Runner construction and compiled property report. Original diagnostic baseline does not call setter.',
        prerequisite='Zero-tick API candidate must report cv_num_threads=1 and all seven compiled OV properties identical to baseline before any saved request.',
        unchanged='Original 94 recovered sources/model/ROI/precision/confidence/PnP gates/80ms/150ms, source sample8/476ms/486ms/BGR3951, OV16 threads/1stream/LATENCY and affinity.',
        identity='New diagnostic-only source composition/spec/ELF/profile, never old default deployment identity.',
        study='Only after zero-tick prerequisite, new preregistered ABBAABBA four fresh per arm on exact saved frame; two-second offline first replies do not qualify live80ms.',
        no_inference_warmup=True,no_environment_effect_assumed=True),
    official_references=[dict(url='https://docs.opencv.org/4.10.0/d6/dea/tutorial_env_reference.html',finding='Lists OPENCV_FOR_THREADS_NUM; does not override actual ineffective observation.'),
        dict(url='https://raw.githubusercontent.com/opencv/opencv/4.10.0/modules/core/src/parallel.cpp',finding='getNumThreads is backend-specific; setNumThreads sets numThreads and invokes backend API or TBB arena setup. Exact installed backend/cause remains unconfirmed.'),
        dict(url='https://docs.opencv.org/4.10.0/db/de0/group__core__utils.html',finding='setNumThreads is the explicit API; invoke before parallel work, not concurrently.')],
    input_sha256=inputs,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
target=OUT/'RESULT.json';target.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(raw_checks_pass=report['raw_checks_pass'],actual_default_first_inferences=4,actual_cv1_first_inferences=0,
    build_opencv=report['build_opencv'],cases=[{k:c[k] for k in ('index','variant','cv_num_threads','response_ms','actual_stdin_written_bytes')} for c in cases],
    report_sha256=hashlib.sha256(target.read_bytes()).hexdigest()),indent=2))
