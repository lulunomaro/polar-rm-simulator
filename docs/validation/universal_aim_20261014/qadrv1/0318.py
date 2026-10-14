import numpy as np
from rm_match.aim_scenarios import make_fixture,ROSTER,target_command,evaluate_truth
from rm_match.match_engine import MatchSimulation

def test_lateral_fixture_moves_through_actuation_and_truth_is_separate():
    xml,spawns,visual=make_fixture('lateral')
    s=MatchSimulation(render=False,model_xml=xml,roster=ROSTER,spawns=spawns)
    initial=s.data.qpos[s.qindices['blue_infantry']].copy()
    for _ in range(500):s.step({'blue_infantry':target_command(s,'lateral',0)})
    assert abs(s.data.qpos[s.qindices['blue_infantry'][1]]-initial[1])>.1
    observation=s.observe('red_sentry',include_rgb=False,include_ranges=False)
    assert observation.rgb.size==0 and observation.camera_sim_time is None
    assert not hasattr(observation,'armor_samples')
    assert 'armor_samples' in evaluate_truth(s)
    s.close()

def test_v21_fixture_and_cover_compile_without_spawn_contacts():
    for scenario in ['stationary_near','stationary_far','variable_spin','occlusion']:
        xml,spawns,visual=make_fixture(scenario)
        s=MatchSimulation(render=False,model_xml=xml,roster=ROSTER,spawns=spawns)
        assert s.data.ncon==0 and 'v2.1' in visual
        s.close()
