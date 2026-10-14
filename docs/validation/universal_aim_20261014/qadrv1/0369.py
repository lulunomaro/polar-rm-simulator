"""No ROS here: codec fixture and original-byte preservation only."""
import json
from pathlib import Path
import sys
import unittest
from tools.diagnose_pb_humble_sensors import ArchivedCodecChild,fixture
from rm_match.platform_v2.navigation_contracts import validate_navigation_observation


class DiagnosticTests(unittest.TestCase):
    def test_fixture_is_explicit_and_has_zero_deadline_until_host_request(self):
        o=validate_navigation_observation(fixture())
        self.assertEqual(o['wall_deadline'],0.)
        self.assertEqual(o['sensors']['pointcloud']['acquisition_end_ns'],100000000)
        self.assertNotIn('odom_xyyaw',o['own'])

    @unittest.skipUnless(sys.platform=='linux','owned POSIX process group diagnostic')
    def test_actual_codec_fixture_echoes_expired_wall_stamp_without_host_authority(self):
        script='''import json,sys
for line in sys.stdin:
 r=json.loads(line);v=dict(schema=r['schema'],op=r['op'],ok=True)
 if r['op']=='act':
  o=r['observation'];v['status']=dict(schema='polar.sim.navigation-status.v1',kind='navigation',status='pending_localization',**{k:o[k] for k in ('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')})
 print(json.dumps(v),flush=True)
'''
        o=fixture();c=ArchivedCodecChild([sys.executable,'-u','-c',script]);child=c.process
        try:
            c.reset(dict(robot_id='red_sentry',episode=0,binding_epoch=1))
            status=c.act(o);self.assertEqual(status['wall_deadline'],0.)
            self.assertEqual(status['sim_time'],.1);self.assertNotIn('command',status)
            self.assertEqual(o['sensors']['pointcloud']['acquisition_end_ns'],100000000)
        finally:c.close()
        self.assertIsNotNone(child.poll());self.assertTrue(child.stdin.closed);self.assertTrue(child.stdout.closed);self.assertFalse(c.thread.is_alive())


if __name__=='__main__':unittest.main()
