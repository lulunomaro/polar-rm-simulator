"""Worker wire and cancellation rejection checks; no ROS or physics execution."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from rm_match.integrations.pb_wsl_navigation_worker import checked_rpc,StopGuard,WIRE


def packet(op='act'):
    inner={'schema':'polar.sim.adapter.jsonl.v1','op':op}
    inner.update({'observation':{'source':'untouched'}} if op=='act' else ({'context':{},'config':{}} if op=='reset' else {}))
    return dict(schema=WIRE,op=op,id=1,run_uuid='a'*32,packet=inner)


class WorkerWireTests(unittest.TestCase):
    def test_original_inner_packet_is_returned_without_retagging(self):
        request=packet();before=copy.deepcopy(request)
        op,seq,inner=checked_rpc(request,0,'a'*32)
        self.assertEqual((op,seq),('act',1));self.assertIs(inner,request['packet']);self.assertEqual(request,before)
        for op in ('reset','status'):self.assertEqual(checked_rpc(packet(op),0,'a'*32)[0],op)

    def test_transaction_generation_sequence_aliases_and_shapes_reject(self):
        for field,bad in [('id',True),('id',1.),('id',0),('id',2),('run_uuid','b'*32),('schema','old'),('op',[]),('op','old')]:
            with self.subTest(field=field,value=bad):
                request=packet();request[field]=bad
                with self.assertRaises(ValueError):checked_rpc(request,0,'a'*32)
        for change in ('unknown_outer','unknown_inner','inner_op','inner_schema','replay'):
            with self.subTest(change=change):
                request=packet()
                if change=='unknown_outer':request['late']=True
                elif change=='unknown_inner':request['packet']['late']=True
                elif change=='inner_op':request['packet']['op']='reset'
                elif change=='inner_schema':request['packet']['schema']='old'
                with self.assertRaises(ValueError):checked_rpc(request,1 if change=='replay' else 0,'a'*32)

    def test_stop_is_bound_to_actual_run_and_original_config(self):
        for match in (True,False):
            with self.subTest(match=match),TemporaryDirectory() as temp:
                spec=dict(run_uuid='a'*32,config_ref={'sha256':'c'*64})
                guard=StopGuard(Path(temp),spec);guard.prepared=True
                (Path(temp)/'STOP').write_text(json.dumps(dict(run_uuid=('a' if match else 'b')*32,config_sha256='c'*64)))
                with self.assertRaises(InterruptedError):guard.check()
                self.assertTrue(guard.stop.is_set());self.assertEqual(guard.reason,'host_stop' if match else 'stop_identity_mismatch')

    def test_prepare_has_one_local_resource_budget_without_host_clock_translation(self):
        with TemporaryDirectory() as temp,patch('rm_match.integrations.pb_wsl_navigation_worker.time.monotonic',return_value=7.) as clock:
            guard=StopGuard(Path(temp),dict(run_uuid='a'*32,config_ref={'sha256':'c'*64}))
            clock.return_value=16.999;guard.check()
            clock.return_value=17.
            with self.assertRaisesRegex(InterruptedError,'prepare_resource'):guard.check()
            self.assertTrue(guard.stop.is_set())


if __name__=='__main__':unittest.main()
