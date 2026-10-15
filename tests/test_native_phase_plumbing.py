"""Real local preparation/ownership with a fake bridge; no ELF/model execution."""
import os
from pathlib import Path
import runpy
from unittest.mock import patch
import pytest
from rm_match.deployment import wsl_profile
from rm_match.integrations.phase_timing import NumericPhaseProbe

fixture=runpy.run_path(str(Path(__file__).with_name('test_wsl_profile.py')))['fixture']
ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name!='nt',reason='Windows local C: WSL registration profile')
def test_probe_reaches_same_prepared_transport_and_actual_writer_and_is_source_pinned():
    class Bridge:
        def __init__(self,*args,**kwargs):self.kwargs=kwargs;self.stopped=False;self.closed=False
        def reset(self,context):self.context=context
        def request_stop(self):self.stopped=True
        def close(self):self.closed=True
    with fixture() as f:
        for rel in ('wsl_operator_pipe.py','wsl_operator_pipe_worker.py','wsl_aim_async.py','wsl_aim_async_worker.py','phase_timing.py'):
            target=f['repo']/'rm_match/integrations'/rel;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((ROOT/'rm_match/integrations'/rel).read_bytes())
        probe=NumericPhaseProbe()
        registry=wsl_profile.own_wsl_registry(f['spec_path'],f['out'],repo_root=f['repo'],
            transport='wsl_async_bgr_v3',phase_probe=probe)
        prepared=None
        try:
            with patch('rm_match.integrations.wsl_aim_async.WslAsyncAimProcess',Bridge):
                prepared=registry.prepare_native()
            bridge=prepared.process;writer=prepared._evidence_writer
            assert bridge.kwargs['phase_probe'] is probe
            assert writer._phase_probe is probe
            assert prepared._phase_probe is probe
            assert registry.create('aim_native_rmcs_v1',{}) is prepared
            helper=f['repo']/'rm_match/integrations/phase_timing.py'
            assert str(helper) in registry.checked._identities
            original=helper.read_bytes();helper.write_bytes(original+b'\n# changed\n')
            with pytest.raises(ValueError,match='changed_after_validation'):registry.checked.verify_unchanged()
            helper.write_bytes(original)
        finally:
            registry.close()
            if prepared is not None:prepared.cancel();prepared.close()
        assert bridge.stopped and bridge.closed and not writer.thread.is_alive()
        assert writer.shutdown_status['clean'] is True


def test_non_async_probe_is_rejected_before_reading_assets_or_starting_children(tmp_path):
    with patch('rm_match.deployment.wsl_registry.validate_wsl_spec') as validate:
        with pytest.raises(ValueError,match='phase_probe_requires_async_transport'):
            wsl_profile.own_wsl_registry(tmp_path/'not-read',tmp_path/'not-created',repo_root=tmp_path,
                transport='wsl_stdio_v1',phase_probe=NumericPhaseProbe())
        validate.assert_not_called()
    assert not (tmp_path/'not-created').exists()
