"""Locked source generation and actual lightweight C++ sim-stamp regression."""
import ast
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import prepare_pb2025_lio_tf_overlay as overlay

SOURCE = overlay.ROOT/'artifacts/polarbear-navigation-source-e05eb08e'

class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SOURCE.is_dir(): raise unittest.SkipTest('explicit locked upstream source audit not present')
        cls.tmp=tempfile.TemporaryDirectory();cls.out=Path(cls.tmp.name)/'owned'
        cls.manifest=overlay.generate(SOURCE,cls.out)
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def test_edited_source_sha_and_unique_anchor_fail_closed(self):
        text=subprocess.check_output(['git','show','HEAD:sensor_scan_generation/src/sensor_scan_generation.cpp'],cwd=SOURCE/'pb2025_sentry_nav').decode()
        with self.assertRaisesRegex(ValueError,'original_sha'):
            overlay.transform('sensor_scan_generation/src/sensor_scan_generation.cpp',text+'\n')
        for text in ('absent','one one'):
            with self.assertRaisesRegex(ValueError,'anchor_not_unique'): overlay.replace_once(text,'one','fixed')

    def test_upstream_pristine_and_all_output_bytes_bound(self):
        for name in overlay.HEADS:
            self.assertEqual(subprocess.check_output(['git','status','--porcelain=v1'],cwd=SOURCE/name),b'')
        for name,row in self.manifest['files'].items():
            with self.subTest(name=name): self.assertEqual(hashlib.sha256((self.out/name).read_bytes()).hexdigest(),row['sha256'])
        self.assertFalse(self.manifest['build_executed'])

    def test_fresh_target_only_and_invalid_namespace_or_generation(self):
        with self.assertRaisesRegex(ValueError,'fresh'): overlay.generate(SOURCE,self.out)
        for ns in ('../red','/red','red;touch',''):
            with self.subTest(ns=ns),self.assertRaisesRegex(ValueError,'namespace'):overlay.generate(SOURCE,self.out/'invalid',namespace=ns)
        with self.assertRaisesRegex(ValueError,'generation'): overlay.generate(SOURCE,self.out/'invalid',episode=True)

    def test_head_change_rejected_before_output_creation(self):
        target=self.out/'wronghead'
        with patch.object(overlay,'command',return_value=b'wrong\n'):
            with self.assertRaisesRegex(ValueError,'source_head'):overlay.generate(SOURCE,target)
        self.assertFalse(target.exists())

    def test_exact_pair_missing_tf_and_body_velocity_sources(self):
        cpp=(self.out/'sensor_scan_generation/src/sensor_scan_generation.cpp').read_text()
        h=(self.out/'sensor_scan_generation/include/sensor_scan_generation/sensor_scan_generation.hpp').read_text()
        self.assertIn('sync_policies::ExactTime',h);self.assertNotIn('ApproximateTime',h)
        self.assertIn('odometry_msg->header.stamp != pcd_msg->header.stamp',cpp)
        self.assertIn('pb_missing_calibration_tf',cpp);self.assertNotIn('getIdentity()',cpp)
        self.assertNotIn('steady_clock',cpp)
        self.assertIn('current_ns - previous_stamp_ns_',cpp)
        self.assertIn('tf2::quatRotate(rotation_to_body, world_v)',cpp)
        self.assertIn('stamp_sequence_.accept',cpp)
        self.assertLess(cpp.index('stamp_sequence_.accept'),cpp.index('  publishTransform('))

    def test_static_mount_must_exist_before_cloud_transform(self):
        cpp=(self.out/'loam_interface/src/loam_interface.cpp').read_text()
        self.assertIn('rclcpp::Time(0, 0, RCL_ROS_TIME)',cpp)
        self.assertIn('calibrated.header.stamp).nanoseconds() != 0',cpp)
        start=cpp.index('void LoamInterfaceNode::pointCloudCallback')
        self.assertLess(cpp.index('!ensureCalibration',start),cpp.index('pcl_ros::transformPointCloud',start))

    def test_context_captured_ingress_and_carried_in_measure_not_latest(self):
        inp=(self.out/'point_lio/src/li_initialization.cpp').read_text()
        out=(self.out/'point_lio/src/laserMapping.cpp').read_text()
        self.assertEqual(inp.count('meas.pb_context = pb_context_buffer.front();'),2)
        self.assertEqual(inp.count('pb_context_buffer.pop_front();'),2)
        self.assertIn('pb_scan_source.add_raw(start, msg->timebase, start + max_offset, msg)',inp)
        self.assertIn('pb_scan_source.take(raw, context)',inp)
        self.assertIn('pb_process_bound_scan(raw, std::move(context))',inp)
        self.assertIn('pb_raw_join_rejected: %s',inp)
        self.assertIn('lidar_buffer.size() < 8',inp)
        self.assertIn('pb_scan_queue_alignment',inp)
        self.assertIn('imu_deque.size() >= 4096',inp)
        self.assertIn('pb_imu_buffer_overflow_stop',inp)
        self.assertIn('msg->header.stamp = msg_in->header.stamp;',inp)
        self.assertNotIn('get_time_sec(msg_in->header.stamp) - timediff_imu_wrt_lidar',inp)
        self.assertIn('msg->header.frame_id != "livox_frame"',inp)
        begin=out.index('void publish_odometry(');end=out.index('void publish_path(',begin)
        publisher=out[begin:end]
        self.assertIn('localization_event(Measures.pb_context',publisher)
        self.assertIn('SensorDataQoS().keep_last(1024)',out)
        self.assertIn('catch (const polar_pb::GenerationFault &)',out)
        self.assertNotIn('pb_scan_source',publisher)
        self.assertLess(publisher.index('localization_event'),publisher.index('pubOdomAftMapped->publish'))

    def test_both_ingress_callbacks_drain_bounded_exact_join(self):
        inp=(self.out/'point_lio/src/li_initialization.cpp').read_text()
        out=(self.out/'point_lio/src/laserMapping.cpp').read_text()
        h=(self.out/'point_lio/include/pb_scan_source.hpp').read_text()
        self.assertIn('while (lidar_buffer.size() < 8)',inp)
        self.assertIn('msg->point_num > 40000',inp)
        self.assertIn('pb_drain_scans();',inp[inp.index('void livox_pcl_cbk('):inp.index('void imu_cbk(')])
        self.assertIn('pb_drain_scans();',inp[inp.index('bool sync_packages('):])
        req=out[out.index('auto pb_request_subscription'):out.index('  std::cout << "lidar_type:')]
        self.assertIn('rclcpp::QoS(8).reliable()',req)
        self.assertLess(req.index('pb_scan_source.install'),req.index('pb_drain_scans();'))
        self.assertIn('raw_.clear(); discarded_ = {}; throw;',h)
        self.assertIn('capacity = 8',h)
        self.assertNotIn('steady_clock',h)
        self.assertNotIn('wall_deadline',h)
        self.assertIn('pb_join_original_sim_window_expired',inp)
        self.assertIn('!source_.has_request(header_ns)',h)
        self.assertIn('acquisition_end_ns',h)
        self.assertIn('std::numeric_limits<int64_t>::max() - max_offset',inp)

    def test_owned_launch_correct_config_and_no_fake_controller(self):
        text=(self.out/'owned_lio.launch.py').read_text()
        ast.parse(text)
        self.assertIn("'odometry.publish_odometry_without_downsample': False",text)
        self.assertIn("'mapping.imu_time_inte': 0.002",text)
        self.assertIn("'mapping.acc_norm': 9.81",text)
        self.assertIn("'mapping.extrinsic_T': [0.0, 0.0, 0.0]",text)
        self.assertEqual(text.count("Node(package="),3)
        self.assertNotIn("package='fake_vel_transform'",text)
        self.assertNotIn("package='livox_ros_driver2'",text)

    def test_bounded_dispatch_preserves_main_rate_and_disabled_diagnostics(self):
        out=(self.out/'point_lio/src/laserMapping.cpp').read_text()
        self.assertIn('rclcpp::Rate rate(500);',out)
        self.assertIn('rate.sleep();',out)
        self.assertIn('executor.spin_all(std::chrono::milliseconds(1));',out)
        self.assertNotIn('executor.spin_some();',out)
        self.assertIn('declare_parameter<bool>("pb.dispatch_diagnostics", false)',out)
        self.assertIn('"polar/pb/dispatch"',out)
        self.assertNotIn('"/polar/pb/dispatch"',out)
        self.assertIn('"linux_steady_diagnostic_only"',out)
        self.assertIn('"exceeded_budget_calls_since_scan"',out)
        self.assertIn('pb_report_time - pb_last_dispatch_report >= std::chrono::milliseconds(100)',out)
        publish=out.index('pb_dispatch_publisher->publish(event)')
        self.assertLess(out.index('if (sync_packages(Measures)) {'),publish)
        self.assertIn('pb_imu_callbacks - pb_before_imu',out)
        # All other compiled translation units and shared headers stay byte-exact
        # versus the already audited 04, allowing a proven main-only build.
        previous=overlay.ROOT/'artifacts/pb2025-lio-tf-source-20261014-04/OVERLAY_MANIFEST.json'
        if previous.exists():
            old=json.loads(previous.read_text())
            for name,row in self.manifest['files'].items():
                if name.startswith('point_lio/') and name!='point_lio/src/laserMapping.cpp':
                    with self.subTest(name=name):self.assertEqual(row['sha256'],old['files'][name]['sha256'])

    @unittest.skipUnless(os.environ.get('POLAR_TEST_PB_CPP')=='1','explicit lightweight C++/WSL regression opt-in')
    def test_actual_cpp_stamp_sequence(self):
        # Actual owned C++ helper: CPU arrival delays do not enter simulation dt.
        cpp=self.out/'stamp_regression.cpp';exe=self.out/'stamp_regression'
        cpp.write_text('''#include "pb_sim_stamp.hpp"
#include <cassert>
#include <cmath>
int main(){polar_pb::SimStampSequence s;double dt=9;
assert(!s.accept(0,dt)); assert(s.accept(100000000,dt)&&dt==0);
assert(s.accept(200000000,dt)&&std::abs(dt-.1)<1e-12);
assert(!s.accept(200000000,dt));assert(!s.accept(150000000,dt));
assert(s.accept(300000000,dt)&&std::abs(dt-.1)<1e-12);
s.reset();assert(s.accept(1000000,dt)&&dt==0);}
''')
        def linux(p):
            p=p.resolve();return '/mnt/'+p.drive[0].lower()+p.as_posix()[2:]
        compile=subprocess.run(['wsl','-d','Ubuntu-22.04','--exec','g++','-std=c++14','-Wall','-Wextra','-Werror',linux(cpp),'-I'+linux(overlay.TEMPLATES),'-o',linux(exe)],capture_output=True,timeout=25)
        self.assertEqual(compile.returncode,0,compile.stderr.decode(errors='replace'))
        result=subprocess.run(['wsl','-d','Ubuntu-22.04','--exec',linux(exe)],capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))

    @unittest.skipUnless(os.environ.get('POLAR_TEST_PB_JSON_CPP')=='1','explicit standalone C++ JSON regression opt-in')
    def test_actual_cpp_scan_provenance_identity_and_window(self):
        def linux(p):
            p=p.resolve();return '/mnt/'+p.drive[0].lower()+p.as_posix()[2:]
        distro=os.environ.get('POLAR_PB_CPP_DISTRO','Ubuntu-22.04')
        exe=self.out/'source_regression'
        args=['wsl','-d',distro,'--exec','g++','-std=c++14','-Wall','-Wextra','-Werror',linux(overlay.ROOT/'tests/fixtures/pb_scan_source_test.cpp'),'-I'+linux(self.out/'point_lio/include')]
        if os.environ.get('POLAR_PB_JSON_INCLUDE'):args+=['-I'+os.environ['POLAR_PB_JSON_INCLUDE']]
        compile=subprocess.run(args+['-o',linux(exe)],capture_output=True,timeout=40)
        self.assertEqual(compile.returncode,0,compile.stderr.decode(errors='replace'))
        result=subprocess.run(['wsl','-d',distro,'--exec',linux(exe)],capture_output=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))

if __name__=='__main__':unittest.main()
