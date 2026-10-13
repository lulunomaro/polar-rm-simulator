"""Local registration, immutable context and original deadline rejection."""
import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from rm_match.integrations.pb_wsl_navigation_registry import register_pb_wsl_navigation,SCHEMA,ADAPTER_ID
from rm_match.platform_v2.adapters import Registry
from rm_match.platform_v2.contracts import ContractError,IDENTITY
from tests.test_pb_navigation_bridge import observation


class Session:
    def __init__(self,*args,**kwargs):self.prepared=False;self.stopped=False;self.closed=False;self.kwargs=kwargs;self.calls=[]
    def prepare(self):self.prepared=True
    def reset(self,context,config):self.calls.append(('reset',copy.deepcopy(context),config))
    def request_stop(self):self.stopped=True
    def close(self):self.closed=True
    def exchange(self,packet,timeout):
        self.calls.append((packet,timeout));o=packet['observation']
        return dict(schema='polar.sim.adapter.jsonl.v1',op='act',ok=True,status=dict(schema='polar.sim.navigation-status.v1',
            **{k:o[k] for k in IDENTITY},kind='navigation',status='pending_localization'))


class LocalWslRegistryTests(unittest.TestCase):
    def create(self,temp,clock=lambda:10.,session_factory=Session):
        manifest=Path(temp)/'manifest.json'
        manifest.write_text(json.dumps(dict(schema=SCHEMA,config_ref={},environment_ref={},out=str(Path(temp)/'out'),diagnostics=False)))
        registry=Registry();session=register_pb_wsl_navigation(registry,manifest,repo_root=temp,clock=clock,session_factory=session_factory)
        return registry,session,manifest

    def test_prepare_precedes_single_empty_config_handover(self):
        with TemporaryDirectory() as temp:
            registry,session,path=self.create(temp)
            self.assertTrue(session.prepared);self.assertFalse(session.calls)
            with self.assertRaises(ContractError):registry.create(ADAPTER_ID,{'command':['anything']})
            adapter=registry.create(ADAPTER_ID,{})
            adapter.reset(dict(robot_id='red_sentry',episode=0,binding_epoch=1))
            self.assertEqual(session.calls[0][0],'reset')
            with self.assertRaises(ContractError):registry.create(ADAPTER_ID,{})
            adapter.close();self.assertTrue(session.stopped and session.closed)

    def test_manifest_change_cannot_claim_prepared_instance(self):
        with TemporaryDirectory() as temp:
            registry,session,path=self.create(temp);path.write_text('{}')
            with self.assertRaisesRegex(ContractError,'manifest_changed'):registry.create(ADAPTER_ID,{})
            self.assertTrue(session.stopped)

    def test_original_source_clock_is_unchanged_and_late_return_rejected(self):
        with TemporaryDirectory() as temp:
            now=[10.];registry,session,path=self.create(temp,lambda:now[0])
            adapter=registry.create(ADAPTER_ID,{});adapter.reset(dict(robot_id='red_sentry',episode=0,binding_epoch=1))
            o=observation();o.update(episode=0,binding_epoch=1,wall_deadline=10.04);original=copy.deepcopy(o)
            status=adapter.act(o);self.assertEqual(o,original)
            self.assertEqual(status['wall_deadline'],10.04);self.assertAlmostEqual(session.calls[-1][1],.04)
            exchange=session.exchange
            def delayed(packet,timeout):
                result=exchange(packet,timeout);now[0]=10.04;return result
            session.exchange=delayed
            with self.assertRaisesRegex(ContractError,'original_deadline'):adapter.act(o)
            self.assertTrue(session.stopped)
    def test_prepare_and_cleanup_failures_keep_original_cause_and_sticky_close(self):
        captured=[]
        class Failed(Session):
            def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);captured.append(self);self._close_failure=None
            def prepare(self):raise ValueError('original prepare failure')
            def close(self):
                self.closed=True;self._close_failure='sticky cleanup failure';raise RuntimeError(self._close_failure)
        with TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError,'sticky cleanup') as result:self.create(temp,session_factory=Failed)
        self.assertEqual(str(result.exception.__cause__),'original prepare failure')
        self.assertTrue(captured[0].stopped and captured[0].closed)
        with self.assertRaisesRegex(RuntimeError,'sticky cleanup'):captured[0].close()
    def test_prepare_failure_with_successful_cleanup_preserves_original_error(self):
        captured=[]
        class Failed(Session):
            def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);captured.append(self)
            def prepare(self):raise ValueError('original prepare failure')
        with TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,'original prepare'):self.create(temp,session_factory=Failed)
        self.assertTrue(captured[0].stopped and captured[0].closed)


if __name__=='__main__':unittest.main()
