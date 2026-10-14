import json
import pytest
from tools.offline_smoke.preload_contract import create_request,write_ready,wait_ready


class Driver:
    pid=42
    def __init__(self,exitcode=None):self.exitcode=exitcode
    def poll(self):return self.exitcode


def ready(tmp_path):
    request=create_request(tmp_path)
    write_ready(tmp_path,42,1.,{"Qt":"6.12.0","cv2":"5.0.0","numpy":"2.5.4"},clock=lambda:2.)
    return request


def test_valid_readiness_is_only_local_startup(tmp_path):
    request=ready(tmp_path)
    value=wait_ready(Driver(),tmp_path,request,0.,clock=lambda:3.)
    assert value["pid"]==42
    assert not {"session_id","lease_epochs","watch_epoch","frame_id"}.intersection(value)


@pytest.mark.parametrize("field,value,error",[
    ("pid",43,"pid_mismatch"),
    ("nonce","other_attempt","fresh_output_mismatch"),
    ("output_root","/other/attempt","fresh_output_mismatch"),
    ("started_monotonic_s",-1.,"clock_not_fresh"),
    ("ready_monotonic_s",4.,"clock_not_fresh"),
    ("preloaded_versions",{"Qt":"6.12.0"},"modules_incomplete"),
])
def test_wrong_or_stale_readiness_does_not_start_admission(tmp_path,field,value,error):
    request=ready(tmp_path);path=tmp_path/"preload_ready.json"
    payload=json.loads(path.read_text());payload[field]=value;path.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match=error):
        wait_ready(Driver(),tmp_path,request,0.,clock=lambda:3.)


def test_exited_driver_fails_before_setup_deadline(tmp_path):
    request=create_request(tmp_path)
    with pytest.raises(RuntimeError,match="client_exited"):
        wait_ready(Driver(7),tmp_path,request,0.,clock=lambda:0.,pause=lambda _:pytest.fail("waited after exit"))


def test_setup_wait_bound_preserved(tmp_path):
    request=create_request(tmp_path)
    with pytest.raises(TimeoutError,match="setup_timeout"):
        wait_ready(Driver(),tmp_path,request,0.,clock=lambda:15.)


def test_unexpected_schema_field_rejected(tmp_path):
    request=ready(tmp_path);path=tmp_path/"preload_ready.json"
    payload=json.loads(path.read_text());payload["network_ready"]=True;path.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match="schema"):
        wait_ready(Driver(),tmp_path,request,0.,clock=lambda:3.)
