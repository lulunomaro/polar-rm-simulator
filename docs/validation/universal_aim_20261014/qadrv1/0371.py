"""Local phase evidence fixtures: no ROS processes or sensor publications."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from rm_match.integrations.pb_navigation_phases import PhaseRecorder,MAX_RECORDS,MAX_RECORD_BYTES
from rm_match.integrations.pb_navigation_bridge import NavigationBridge,NavigationSettings,serve_navigation
from rm_match.integrations.pb_navigation_transport import HumbleNavigationTransport
from rm_match.integrations.ros2_bridge import BridgeError,JSONL_SCHEMA


class PhaseTests(unittest.TestCase):
    def test_opt_in_bounded_no_environment_or_protocol_payload_logged(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'artifacts').mkdir();path=root/'artifacts/phase.jsonl'
            recorder=PhaseRecorder(path,repo_root=root)
            recorder.mark('module')
            for index in range(300):recorder.mark('graph_counts',(index,1,0,2))
            recorder.mark('reset_ack');recorder.mark('cleanup_end');recorder.close();recorder.close()
            rows=[json.loads(row) for row in path.read_text().splitlines()]
            self.assertLessEqual(len(rows),MAX_RECORDS)
            self.assertLessEqual(path.stat().st_size,MAX_RECORDS*MAX_RECORD_BYTES)
            self.assertEqual(sum(r['phase']=='graph_counts' for r in rows),32)
            self.assertEqual(rows[-3]['phase'],'reset_ack');self.assertEqual(rows[-1]['phase'],'diagnostic_closed')
            for row in rows:
                self.assertLessEqual(set(row),{'phase','pid','monotonic_ns','perf_counter_ns','counts'})
                self.assertIs(type(row['pid']),int);self.assertIs(type(row['monotonic_ns']),int)
            with self.assertRaises(FileExistsError):PhaseRecorder(path,repo_root=root)

    def test_disabled_recorder_performs_no_file_or_clock_io(self):
        with patch('rm_match.integrations.pb_navigation_phases.os.open') as opened,patch('rm_match.integrations.pb_navigation_phases.time.monotonic_ns') as clock:
            recorder=PhaseRecorder();recorder.mark('module');recorder.close()
            opened.assert_not_called();clock.assert_not_called()

    def test_path_scope_relative_traversal_missing_parent_and_link_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'artifacts').mkdir()
            for path in ('relative.jsonl',root/'outside.jsonl',root/'artifacts/../escape.jsonl',root/'artifacts/missing/log'):
                with self.subTest(path=str(path)),self.assertRaises(ValueError):PhaseRecorder(path,repo_root=root)
            outside=root/'other';outside.mkdir();link=root/'artifacts/link'
            try:link.symlink_to(outside,target_is_directory=True)
            except (OSError,NotImplementedError):return
            with self.assertRaises(ValueError):PhaseRecorder(link/'log',repo_root=root)
            self.assertFalse((outside/'log').exists())

    def test_phase_fields_are_fixed_and_counts_strict(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'artifacts').mkdir();recorder=PhaseRecorder(root/'artifacts/log',repo_root=root)
            try:
                for phase,counts in [('secret_value',None),('module',(1,2,3,4)),('graph_counts',(True,1,1,1)),('graph_counts',(65536,1,1,1)),('graph_counts',[1,1,1,1])]:
                    with self.subTest(phase=phase,counts=counts),self.assertRaises(ValueError):recorder.mark(phase,counts)
            finally:recorder.close()

    @unittest.skipUnless(os.open in getattr(os,'supports_dir_fd',()) and hasattr(os,'O_NOFOLLOW'),'actual no-follow directory handles required')
    def test_parent_link_swap_after_validation_cannot_escape_owned_scope(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'artifacts').mkdir();outside=root/'outside';outside.mkdir()
            original_open=os.open;swapped=False
            def raced_open(path,flags,*args,**kwargs):
                nonlocal swapped
                if path=='artifacts' and 'dir_fd' in kwargs and not swapped:
                    swapped=True;(root/'artifacts').rename(root/'original_artifacts')
                    (root/'artifacts').symlink_to(outside,target_is_directory=True)
                return original_open(path,flags,*args,**kwargs)
            with patch('rm_match.integrations.pb_navigation_phases.os.open',raced_open),patch('rm_match.integrations.pb_navigation_phases.os.supports_dir_fd',os.supports_dir_fd|{raced_open}):
                with self.assertRaises(OSError):PhaseRecorder(root/'artifacts/log',repo_root=root)
            self.assertTrue(swapped);self.assertFalse((outside/'log').exists())

    def test_reset_phase_does_not_change_jsonl_ack_or_ready_budget(self):
        request=dict(schema=JSONL_SCHEMA,op='reset',context=dict(robot_id='red_sentry',episode=0,binding_epoch=1),config={})
        output=io.BytesIO();transport=Mock();phases=Mock()
        with patch('rm_match.integrations.pb_navigation_bridge.PHASES',phases):
            serve_navigation(NavigationBridge(NavigationSettings()),transport,io.BytesIO((json.dumps(request)+'\n').encode()),output)
        self.assertEqual(json.loads(output.getvalue()),dict(schema=JSONL_SCHEMA,op='reset',ok=True))
        transport.wait_ready.assert_called_once_with(1.)
        self.assertEqual([c.args[0] for c in phases.mark.call_args_list],['reset_received','reset_ack'])

    def test_graph_records_changed_counts_and_ready_without_dummy_publish(self):
        t=HumbleNavigationTransport.__new__(HumbleNavigationTransport);t.settings=SimpleNamespace(result_topic='/result')
        t.cloud_pub=Mock();t.imu_pub=Mock();t.request_pub=Mock();t.node=Mock();t.spin_once=Mock()
        t.cloud_pub.get_subscription_count.side_effect=[0,1,1]
        t.imu_pub.get_subscription_count.side_effect=[0,1,1]
        t.request_pub.get_subscription_count.side_effect=[0,1,1]
        t.node.count_publishers.side_effect=[0,0,1]
        phases=Mock()
        with patch('rm_match.integrations.pb_navigation_transport.PHASES',phases):t.wait_ready(1.)
        self.assertEqual([c.args for c in phases.mark.call_args_list],[('graph_wait_enter',),('graph_counts',(0,0,0,0)),('graph_counts',(1,1,1,0)),('graph_counts',(1,1,1,1)),('graph_ready',)])
        t.cloud_pub.publish.assert_not_called();t.imu_pub.publish.assert_not_called();t.request_pub.publish.assert_not_called()

    def test_graph_timeout_keeps_original_deadline(self):
        t=HumbleNavigationTransport.__new__(HumbleNavigationTransport);t.settings=SimpleNamespace(result_topic='/result')
        t.cloud_pub=Mock();t.imu_pub=Mock();t.request_pub=Mock();t.node=Mock();t.spin_once=Mock()
        for publisher in (t.cloud_pub,t.imu_pub,t.request_pub):publisher.get_subscription_count.return_value=0
        t.node.count_publishers.return_value=0;phases=Mock()
        with patch('rm_match.integrations.pb_navigation_transport.PHASES',phases),patch('rm_match.integrations.pb_navigation_transport.time.monotonic',side_effect=[5.,6.]):
            with self.assertRaises(BridgeError):t.wait_ready(1.)
        t.spin_once.assert_not_called();self.assertEqual(phases.mark.call_args_list[-1].args,('graph_timeout',))


if __name__=='__main__':unittest.main()
