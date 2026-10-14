"""Strict scoped operator clock/lifecycle support without truth fallback."""
import copy
import unittest

from rm_client.sim_platform_transport import PlatformTransport
from test_operator_state_projection import Client,state


def offline():
    value=state()
    value.update(clock_profile=dict(kind='offline_modeled_latency_v1',label='OFFLINE / SIL',barrier_state='native_barrier',
        simulation_tick=5,simulation_ns=10_000_000,episode_origin_mj_time_ns=0,
        delays_are_engineering_configuration_not_device_calibration=True,host_delay_s=.15,wall_elapsed_s=1.,
        delays=dict(physics_step_ns=2_000_000,capture_period_ns=40_000_000,controller_period_ns=10_000_000,
            sensor_delay_ns=10_000_000,compute_delay_ns=10_000_000,actuation_delay_ns=0,max_age_ns=80_000_000)),
        completed_captures=3)
    return value


class OfflineClockTests(unittest.TestCase):
    def setUp(self):
        self.t=PlatformTransport(role='operator',clock=lambda:10.,client=Client());self.t.connect_once()
    def test_real_projection_shape_and_terminal_are_accepted(self):
        value=offline();self.assertTrue(self.t.install_state(value))
        value['clock_profile']['barrier_state']='HALTED';value.update(offline_final_state='HALTED',offline_halt_code='native_error')
        self.assertTrue(self.t.install_state(value))
        self.assertEqual(self.t.raw_state['offline_halt_code'],'native_error')
        self.assertEqual(self.t.raw_state['completed_captures'],3)
    def test_live_clock_shape_is_accepted(self):
        value=state();value['clock_profile']=dict(kind='wall_deadline_live',simulation_time_unit='seconds',wall_clock='server_monotonic',real_time_factor_limit=1.)
        self.assertTrue(self.t.install_state(value))
    def test_offline_private_or_unknown_nested_fields_are_rejected(self):
        cases=[]
        for container,key,value in [('clock_profile','world_pose',[1,2]),('delays','private_path','SECRET_PATH'),
            ('clock_profile','label','SECRET_PATH'),('clock_profile','barrier_state','future:SECRET_PATH')]:
            item=offline();target=item['clock_profile']['delays'] if container=='delays' else item['clock_profile'];target[key]=value;cases.append(item)
        item=offline();item['offline_halt_code']='native_error:SECRET_PATH';cases.append(item)
        item=offline();item['offline_halt_reason']='SECRET_PATH';cases.append(item)
        for item in cases:
            with self.subTest(item=item),self.assertRaises(ValueError):self.t.install_state(item)
        self.assertIsNone(self.t.raw_state)
    def test_offline_scalar_bool_nonfinite_negative_and_relaxed_age_are_rejected(self):
        for key,bad in [('simulation_ns',True),('simulation_tick',-1),('host_delay_s',float('nan')),('wall_elapsed_s',-1),('episode_origin_mj_time_ns',{})]:
            item=offline();item['clock_profile'][key]=bad
            with self.subTest(key=key),self.assertRaises(ValueError):self.t.install_state(item)
        for key,bad in [('compute_delay_ns',True),('max_age_ns',81_000_000),('capture_period_ns',40_000_001)]:
            item=offline();item['clock_profile']['delays'][key]=bad
            with self.subTest(delay=key),self.assertRaises(ValueError):self.t.install_state(item)
        for key,bad in [('completed_captures',True),('offline_final_state','future')]:
            item=offline();item[key]=bad
            with self.subTest(field=key),self.assertRaises(ValueError):self.t.install_state(item)
    def test_offline_terminal_cannot_be_smuggled_into_live_or_absent_clock(self):
        item=state();item['completed_captures']=1
        with self.assertRaises(ValueError):self.t.install_state(item)
        item['clock_profile']=dict(kind='wall_deadline_live',simulation_time_unit='seconds',wall_clock='server_monotonic',real_time_factor_limit=1.)
        with self.assertRaises(ValueError):self.t.install_state(item)


if __name__=='__main__':unittest.main()
