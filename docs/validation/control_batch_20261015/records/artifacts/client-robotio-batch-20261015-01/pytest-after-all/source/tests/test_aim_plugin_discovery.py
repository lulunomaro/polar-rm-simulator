"""Actual own-client capability/plan code; synthetic catalog, no GUI/detector."""
import copy
import unittest
from rm_client.sim_platform_adapters import parse_catalog,options,make_plan,config_for,PLUGIN_CAPABILITIES

def catalog(aid='custom_independent_aim'):
    d=dict(adapter_id=aid,kind='aim',version='1.0.0',label='External reviewed aim plugin',
        available=True,required_sensors=['camera'],supported_robots=['red_sentry'],
        fire_authority='manual_only',output_modes=['gimbal_target'],ui_config_contract='empty_v1',
        aim_plugin_contract='camera_gimbal_v1',plugin_transport='jsonl_v1',
        aim_plugin_capabilities=copy.deepcopy(PLUGIN_CAPABILITIES))
    return dict(schema='rm.sim.platform.v2',adapter_ui_version=1,adapter_activation_version=1,
        readiness='declared_support_only',fire_authority='manual_only',adapters=[d],
        robots=[dict(robot_id='red_sentry',declared_sensors=['camera']),
                dict(robot_id='blue_sentry',declared_sensors=['camera'])])

class DiscoveryTests(unittest.TestCase):
    def test_unrelated_ids_negotiate_same_public_contract_and_empty_config(self):
        for aid in ('custom_independent_aim','custom_other_group_binary','custom_ros_team4'):
            with self.subTest(aid=aid):
                c=parse_catalog(catalog(aid));self.assertEqual(options(c,'red_sentry','aim'),['Manual',aid])
                plan=make_plan(c,'red_sentry',{'aim':aid},{'command':['bad'],'model_path':'bad','V2 Aim FOV':False})
                self.assertEqual(plan,{'aim':dict(adapter_id=aid,config={})})
                self.assertEqual(options(c,'blue_sentry','aim'),['Manual'])
    def test_ros_transport_negotiates_without_changing_action_channel(self):
        raw=catalog();raw['adapters'][0]['plugin_transport']='ros2_envelope_v1'
        self.assertIn('custom_independent_aim',options(parse_catalog(raw),'red_sentry','aim'))
    def test_arbitrary_id_alone_never_becomes_selectable(self):
        raw=catalog();raw['adapters'][0].pop('aim_plugin_capabilities')
        self.assertEqual(options(parse_catalog(raw),'red_sentry','aim'),['Manual'])
        with self.assertRaises(ValueError):config_for('custom_independent_aim',{})
    def test_unknown_capability_version_fire_and_missing_sensor_reject(self):
        cases=[('version','2.0'),('fire_authority','automatic'),('ui_config_contract','exec'),
            ('available',True),('test_only',True),('plugin_transport','shell')]
        for key,value in cases:
            with self.subTest(key=key):
                raw=catalog();raw['adapters'][0][key]=value
                if key=='available':raw['robots'][0]['declared_sensors']=[]
                self.assertEqual(options(parse_catalog(raw),'red_sentry','aim'),['Manual'])
        raw=catalog();raw['adapters'][0]['aim_plugin_capabilities']['unknown']=True
        self.assertEqual(options(parse_catalog(raw),'red_sentry','aim'),['Manual'])
    def test_catalog_change_does_not_keep_stale_selected_plan(self):
        c=parse_catalog(catalog());self.assertTrue(make_plan(c,'red_sentry',{'aim':'custom_independent_aim'},{}))
        raw=catalog();raw['adapters'][0]['available']=False;raw['adapters'][0]['reason']='stopped'
        with self.assertRaises(ValueError):make_plan(parse_catalog(raw),'red_sentry',{'aim':'custom_independent_aim'},{})

if __name__=='__main__':unittest.main()
