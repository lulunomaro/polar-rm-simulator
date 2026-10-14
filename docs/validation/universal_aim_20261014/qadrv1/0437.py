"""Local process-startup readiness, distinct from network/control admission."""
import json
from pathlib import Path
import time
import uuid

REQUEST_SCHEMA="polar.offline.preload_request.v1"
READY_SCHEMA="polar.offline.preload_ready.v1"


def create_request(out):
    out=Path(out).resolve()
    request={"schema":REQUEST_SCHEMA,"nonce":uuid.uuid4().hex,"output_root":str(out)}
    (out/"preload_request.json").write_text(json.dumps(request)+"\n")
    return request


def write_ready(out,pid,started,versions,*,clock=time.monotonic):
    out=Path(out).resolve()
    request=json.loads((out/"preload_request.json").read_text())
    if set(request)!={"schema","nonce","output_root"} or request["schema"]!=REQUEST_SCHEMA:
        raise ValueError("invalid_preload_request")
    if request["output_root"]!=str(out) or type(request["nonce"]) is not str or len(request["nonce"])!=32:
        raise ValueError("preload_request_output_mismatch")
    ready={"schema":READY_SCHEMA,"pid":pid,"nonce":request["nonce"],"output_root":str(out),
           "started_monotonic_s":started,"ready_monotonic_s":clock(),"preloaded_versions":versions}
    temporary=out/("preload_ready."+str(pid)+".tmp")
    temporary.write_text(json.dumps(ready)+"\n")
    temporary.replace(out/"preload_ready.json")


def wait_ready(driver,out,request,started,*,timeout_s=15.,clock=time.monotonic,pause=time.sleep):
    if not 0<timeout_s<=15:raise ValueError("preload_setup_bound_invalid")
    out=Path(out).resolve();path=out/"preload_ready.json"
    while True:
        if driver.poll() is not None:raise RuntimeError("client_exited_before_preload_ready")
        now=clock()
        if now-started>=timeout_s:raise TimeoutError("client_preload_setup_timeout")
        if path.exists():
            if path.is_symlink() or path.resolve().parent!=out:raise ValueError("preload_marker_outside_output")
            value=json.loads(path.read_text())
            keys={"schema","pid","nonce","output_root","started_monotonic_s","ready_monotonic_s","preloaded_versions"}
            if set(value)!=keys or value["schema"]!=READY_SCHEMA:raise ValueError("invalid_preload_ready_schema")
            if type(value["pid"]) is not int or value["pid"]!=driver.pid:raise ValueError("preload_ready_pid_mismatch")
            if value["nonce"]!=request["nonce"] or value["output_root"]!=str(out):raise ValueError("preload_ready_fresh_output_mismatch")
            for key in ("started_monotonic_s","ready_monotonic_s"):
                if type(value[key]) not in (int,float):raise ValueError("invalid_preload_ready_clock")
            if not started<=value["started_monotonic_s"]<=value["ready_monotonic_s"]<=now:
                raise ValueError("preload_ready_clock_not_fresh")
            versions=value["preloaded_versions"]
            if type(versions) is not dict or set(versions)!={"Qt","cv2","numpy"} or any(type(v) is not str or not v for v in versions.values()):
                raise ValueError("preload_ready_modules_incomplete")
            return value
        pause(.01)
