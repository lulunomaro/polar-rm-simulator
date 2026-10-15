"""Synthetic estimates/backend for protocol tests, never actual TF evidence."""
import copy
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

from active_goal_navigation_fixture import factory as goal_factory
from rm_match.integrations.navigation_jsonl_peer import run_navigation_plugin
from rm_match.platform_v2.navigation_feedback_contracts import navigation_feedback, goal_status_from_lifecycle


class SyntheticStagedCompute:
    def __init__(self):self.compute=goal_factory()
    def reset(self,context):return self.compute.reset(context)
    def observe(self,o):
        # Artificial numbers/hash strings check the protocol only. The actual
        # PB producer must obtain the transform from the owned ROS TF buffer.
        stamp=o['sensors']['pointcloud']['acquisition_end_ns']
        nav=dict(available=True,reason='available',frame='map',child_frame='base_link',
            stamp_ns=stamp,localization_stamp_ns=stamp,position_m=[0.,0.,0.],rotation_xyzw=[0.,0.,0.,1.],
            provenance=dict(method='tf_buffer_exact_localization_stamp_v1',producer_source_sha256='1'*64,
                localization_binary_sha256='2'*64,mapping_binary_sha256='3'*64))
        return navigation_feedback(o,nav,
            goal_status=goal_status_from_lifecycle(self.compute.lifecycle.snapshot(),o))
    def __call__(self,o,intent):return self.compute(o,intent)
    def close(self):return self.compute.close()


if __name__=='__main__':
    raise SystemExit(run_navigation_plugin(SyntheticStagedCompute,
        goal_input_modes=['decision_intent_v1'],goal_result_profile='staged_scan_v1'))
