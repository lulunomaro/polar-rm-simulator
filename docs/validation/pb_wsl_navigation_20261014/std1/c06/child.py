
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from tests.test_pb_wsl_navigation_stdio import FakeStack,FakeTransport,FakeGate
from rm_match.integrations import pb_wsl_navigation_worker as w
from rm_match.integrations.pb_wsl_navigation import SOURCE_FILES
out=Path(sys.argv[2]);mode=sys.argv[3];spec=json.loads((out/'FIXTURE_SPEC.json').read_bytes())
assert all(w.sha(w.ROOT/name)==h for name,h in spec['source_sha256'].items())
original_write=w.os.write
if mode=='short_write':
    def short(fd,view):return original_write(fd,view[:7]) if fd==1 else original_write(fd,view)
    w.os.write=short
marker=out/'fixture-source.txt'
if mode=='deleted_source':
    marker.write_bytes(b'actual fixture source, never repository source\n')
    spec['source_sha256'][str(marker)]=w.sha(marker)
class Transport(FakeTransport):
    def close(self):
        if mode=='deleted_source':marker.unlink()
        if mode=='close_error':raise RuntimeError('intentional fixture transport close failure')
w.NavigationGate=FakeGate
code=w.session_worker(spec,out,stack_factory=FakeStack,transport_factory=Transport)
assert not any(k=='rclpy' or k.startswith('rclpy.') for k in sys.modules)
(out/'CHILD_RESULT.json').write_text(json.dumps(dict(
    qualification='actual Linux stdio/cancel only; injected fake stack and transport; no ROS/DDS/NN/SIL',
    returncode=code,ros_imported=False,worker_sha256=w.sha(w.__file__),
    source_sha256={n:w.sha(w.ROOT/n) for n in SOURCE_FILES})))
raise SystemExit(code)
