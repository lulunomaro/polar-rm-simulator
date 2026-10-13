import copy
import unittest
from tools.qa_pb_navigation_sil import audit_navigation_consumption


def evidence():
    action=dict(schema='polar.sim.action.v2',robot_id='red_sentry',episode=0,binding_epoch=1,
        observed_seq=1,sim_time=.1,wall_deadline=100.24,kind='navigation',mode='velocity_body',
        command=dict(frame='base_link',vx_mps=.2,vy_mps=0.,wz_rps=0.))
    source={k:action[k] for k in ('robot_id','episode','binding_epoch','observed_seq','sim_time','wall_deadline')}
    localization=dict(source,schema='polar.sim.pb-localization-result.v1',adapter_id='custom_pb_navigation',cloud_frame_id=0,
        acquisition_start_ns=0,acquisition_end_ns=100000000,localization_stamp_ns=98000000)
    result=dict(schema='polar.sim.pb-navigation-result.v1',adapter_id='custom_pb_navigation',action=action,
        source=dict(cloud_frame_id=0,localization_stamp_ns=98000000,controller_stamp_ns=100000000,controller_id='pb_controller_sourced_v1'))
    budget=dict(source='navigation_sensor_v1',frame_id=0,profile_sha256='a'*64,capture_wall=100.1,wall_deadline=100.25,capture_sim_time=.1,sim_deadline=.25)
    authorization=dict(epoch=1,activation_required=True,activation_seq=0,activation_window_id=1,activation_expires=100.24,activation_window_deadline=100.24)
    receipt=dict(event='navigation_consumed',phase='integration_entry',consume_wall=100.12,consume_sim_time=.12,target=dict(motion=action['command'],gimbal=None,fire=False),
        action=action,navigation_budget=budget,authorization=authorization,output_authorization=authorization)
    request={k:v for k,v in localization.items() if k!='localization_stamp_ns'}
    request['schema']='polar.sim.pb-navigation-request.v1'
    enqueue=dict(event='adapter_enqueue',kind='navigation',**source,sensor_budget=copy.deepcopy(budget),
        cloud_acquisition=dict(frame_id=0,acquisition_start_ns=0,acquisition_end_ns=100000000,profile_sha256='a'*64))
    enqueue['observation_sim_time']=enqueue.pop('sim_time')
    ros=[dict(topic_kind='localization',value=localization),dict(topic_kind='controller_result',value=result),dict(topic_kind='request',value=request)]
    sdk=dict(event='sdk_adapter_activation',wall_time=100.1,
        window=dict(window_id=1,issued_wall=100.09,expires_wall=100.24,valid_for_s=.15,lease_epochs={'motion':1}),
        activation=dict(binding_epoch=1,seq=0,window_id=1,activation_expires=100.24))
    return [receipt,enqueue,sdk],ros


class ConsumptionAuditTests(unittest.TestCase):
    def test_matching_real_source_records_and_receipts_count_physics_steps_once(self):
        rows,ros=evidence();rows.append(copy.deepcopy(rows[0]))
        result=audit_navigation_consumption(rows,ros)
        self.assertTrue(result['passed']);self.assertEqual(result['consumed_steps'],1)

    def test_missing_localization_and_retagged_current_context_rejected(self):
        for corruption in ('missing','old_seq','retimed_pose','retimed_frame'):
            with self.subTest(corruption=corruption):
                rows,ros=evidence()
                if corruption=='missing':ros.pop(0)
                if corruption=='old_seq':ros[0]['value']['observed_seq']=0
                if corruption=='retimed_pose':ros[0]['value']['localization_stamp_ns']=100000000
                if corruption=='retimed_frame':ros[0]['value']['cloud_frame_id']=1
                self.assertFalse(audit_navigation_consumption(rows,ros)['passed'])

    def test_original_wall_sim_and_sdk_expirations_rejected(self):
        for corruption in ('wall','sim','current_sdk','old_output_sdk','deadline_extension'):
            with self.subTest(corruption=corruption):
                rows,ros=evidence();row=rows[0]
                if corruption=='wall':row['consume_wall']=100.26
                if corruption=='sim':row['consume_sim_time']=.251
                if corruption=='current_sdk':row['authorization']=dict(row['authorization'],activation_expires=100.11)
                if corruption=='old_output_sdk':row['output_authorization']=dict(row['authorization'],activation_expires=100.11)
                if corruption=='deadline_extension':row['navigation_budget']['wall_deadline']=100.5
                self.assertFalse(audit_navigation_consumption(rows,ros)['passed'])

    def test_no_motion_no_fire_or_other_generation_cannot_claim_navigation(self):
        for corruption in ('neutral','fire','epoch','different_velocity','overspeed'):
            with self.subTest(corruption=corruption):
                rows,ros=evidence();row=rows[0]
                if corruption=='neutral':row['target']['motion']=None
                if corruption=='fire':row['target']['fire']=True
                if corruption=='epoch':row['action']['binding_epoch']=2
                if corruption=='different_velocity':row['target']['motion']=dict(row['target']['motion'],vx_mps=.1)
                if corruption=='overspeed':row['action']['command']['vx_mps']=1.1
                self.assertFalse(audit_navigation_consumption(rows,ros)['passed'])

    def test_early_consumption_cannot_hide_later_sticky_fault(self):
        rows,ros=evidence()
        rows.append(dict(event='adapter_result',robot_id='red_sentry',kind='navigation',error='TimeoutError'))
        self.assertFalse(audit_navigation_consumption(rows,ros)['passed'])

    def test_original_scan_request_and_profile_are_required(self):
        for corruption in ('missing_request','missing_enqueue','old_scan','different_profile','enqueue_bool'):
            with self.subTest(corruption=corruption):
                rows,ros=evidence()
                if corruption=='missing_request':ros.pop(2)
                if corruption=='missing_enqueue':rows.pop(1)
                if corruption=='old_scan':
                    for i in (0,2):ros[i]['value']['acquisition_end_ns']=60000000
                    ros[0]['value']['localization_stamp_ns']=50000000
                    ros[1]['value']['source'].update(localization_stamp_ns=50000000,controller_stamp_ns=60000000)
                if corruption=='different_profile':rows[1]['cloud_acquisition']['profile_sha256']='b'*64
                if corruption=='enqueue_bool':rows[1]['cloud_acquisition']['frame_id']=False
                self.assertFalse(audit_navigation_consumption(rows,ros)['passed'])

    def test_integer_aliases_invalid_actions_and_nonfinite_clocks_rejected(self):
        for corruption in ('auth_bool','cloud_bool','cloud_float','schema','kind','mode','clock_bool','clock_nan','velocity_bool'):
            with self.subTest(corruption=corruption):
                rows,ros=evidence()
                if corruption=='auth_bool':rows[0]['authorization']['epoch']=True
                if corruption.startswith('cloud_'):
                    alias=False if corruption=='cloud_bool' else 0.
                    ros[0]['value']['cloud_frame_id']=alias;ros[1]['value']['source']['cloud_frame_id']=alias
                if corruption in ('schema','kind','mode'):rows[0]['action'][corruption]='invalid'
                if corruption=='clock_bool':rows[0]['consume_wall']=True
                if corruption=='clock_nan':rows[0]['consume_wall']=float('nan')
                if corruption=='velocity_bool':rows[0]['action']['command']['vy_mps']=False
                self.assertFalse(audit_navigation_consumption(rows,ros)['passed'])

    def test_control_receipts_require_actual_original_sdk_ack(self):
        for corruption in ('missing','extended','wrong_epoch','bool_epoch','wrong_sequence','wrong_window','before_issue'):
            with self.subTest(corruption=corruption):
                rows,ros=evidence()
                if corruption=='missing':rows.pop(2)
                if corruption=='extended':rows[2]['window']['expires_wall']=100.5
                if corruption=='wrong_epoch':rows[2]['activation']['binding_epoch']=2
                if corruption=='bool_epoch':rows[2]['window']['lease_epochs']['motion']=True
                if corruption=='wrong_sequence':rows[0]['output_authorization']['activation_seq']=1
                if corruption=='wrong_window':rows[0]['output_authorization']['activation_window_id']=2
                if corruption=='before_issue':rows[0]['consume_wall']=100.08
                self.assertFalse(audit_navigation_consumption(rows,ros)['passed'])


if __name__=='__main__':unittest.main()
