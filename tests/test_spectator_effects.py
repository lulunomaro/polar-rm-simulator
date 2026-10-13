from types import SimpleNamespace

import mujoco
import numpy as np
import pytest

from rm_match.match_engine import MatchSimulation
from rm_match.spectator_effects import SpectatorEffects


def projectile(uid="0:0", owner="red_sentry", position=(0, 0, 1)):
    return SimpleNamespace(uid=uid, owner=owner, position=np.array(position, dtype=float), radius=.0084)


def contact(when=.05, uid="0:0", position=(1, 0, 1),
            geom="blue_sentry__armor_front", damage=True):
    return dict(projectile=uid, owner="red_sentry", geom=geom, sim_time=when,
                position=list(position), damage_applied=damage)


def scene(maxgeom=100):
    return mujoco.MjvScene(mujoco.MjModel.from_xml_string("<mujoco/>"), maxgeom=maxgeom)


def test_samples_are_copied_and_only_actual_contact_endpoint_is_appended():
    effects = SpectatorEffects()
    p = projectile()
    effects.update(0, [p], [])
    p.position[:] = (.1, .2, 1)
    effects.update(.002, [p], [])
    events = [contact(.003, position=(.15, .3, .99))]
    effects.update(.004, [], events)
    events[0]["position"][0] = 999
    assert [s.position for s in effects.trail_history[0].samples] == [
        (0., 0., 1.), (.1, .2, 1.), (.15, .3, .99)]
    assert [s.sim_time for s in effects.trail_history[0].samples] == [0., .002, .003]
    assert effects.impact_history[0].position == (.15, .3, .99)
    assert effects.draw(scene(), impacts=False) == 2


def test_no_trail_is_invented_from_an_impact_or_one_sample():
    effects = SpectatorEffects()
    effects.update(.1, [], [contact()])
    assert effects.trail_history == ()
    assert effects.draw(scene(), impacts=False) == 0
    effects.update(.12, [projectile(uid="0:1")], [contact()])
    assert effects.draw(scene(), impacts=False) == 0


def test_chronological_indices_preserve_original_ledger_indices():
    effects = SpectatorEffects()
    events = [contact(.06, uid="late"), contact(.02, uid="early"), contact(.06, uid="tie")]
    effects.update(.1, [], events)
    assert [e.projectile_uid for e in effects.impact_history] == ["early", "late", "tie"]
    assert [e.event_index for e in effects.impact_history] == [0, 1, 2]
    assert [e.ledger_index for e in effects.impact_history] == [1, 0, 2]
    effects.update(.1, [], events)
    assert effects.event_count == 3
    events.append(contact(.11, uid="next"))
    effects.update(.12, [], events)
    assert effects.impact_history[-1].event_index == 3


def test_deduplication_on_repeated_update_at_unchanged_time():
    effects = SpectatorEffects()
    p = projectile()
    for _ in range(10):
        effects.update(0, [p], [])
    assert len(effects.trail_history[0].samples) == 1
    # A new shot sampled before the next integration can share the same time.
    effects.update(0, [p, projectile(uid="0:1")], [])
    assert len(effects.trail_history) == 2


def test_expiry_uses_simulation_time_and_retains_total_event_count():
    effects = SpectatorEffects(trail_seconds=.1, impact_seconds=.3)
    effects.update(0, [projectile()], [])
    events = [contact(.01)]
    effects.update(.02, [], events)
    effects.update(.02, [], events)  # Pause or redraw does not age history.
    assert effects.trail_history and effects.impact_history
    effects.update(.2, [], events)
    assert not effects.trail_history and effects.impact_history
    effects.update(.4, [], events)
    assert not effects.impact_history and effects.event_count == 1
    assert effects.draw(scene()) == 0


def test_all_histories_have_hard_size_bounds():
    effects = SpectatorEffects(trail_seconds=5, impact_seconds=5,
                               max_projectiles=2, max_points_per_projectile=3, max_impacts=2)
    ps = [projectile(uid=f"0:{i}") for i in range(4)]
    for i in range(10):
        for p in ps:
            p.position[0] += .001
        effects.update(i * .002, ps, [])
    assert len(effects.trail_history) == 2
    assert all(len(t.samples) <= 3 for t in effects.trail_history)
    events = [contact(.02 + i * .001, uid=str(i)) for i in range(5)]
    effects.update(.03, [], events)
    assert len(effects.impact_history) == 2
    assert [e.event_index for e in effects.impact_history] == [3, 4]
    assert effects.event_count == 5


def test_reset_rewind_and_shrinking_ledger_clear_episode_history():
    effects = SpectatorEffects()
    events = [contact()]
    effects.update(.1, [projectile()], events)
    effects.reset()
    assert effects.trail_history == effects.impact_history == ()
    assert effects.event_count == 0
    effects.update(.1, [projectile()], events)
    effects.update(0, [], [])
    assert effects.trail_history == effects.impact_history == ()
    effects.update(.1, [projectile()], events)
    effects.update(.2, [], [])
    assert effects.trail_history == effects.impact_history == ()


def test_markers_distinguish_damage_from_nondamaging_contacts():
    effects = SpectatorEffects()
    events = [contact(.01, uid="damage"),
              contact(.02, uid="armor", damage=False),
              contact(.03, uid="body", geom="blue_sentry__chassis", damage=False),
              contact(.04, uid="wall", geom="arena_wall", damage=False)]
    effects.update(.05, [], events)
    assert [e.kind for e in effects.impact_history] == [
        "damage", "armor_no_damage", "body", "environment"]
    scn = scene()
    assert effects.draw(scn, trails=False) == 12
    # Most recent contact is rendered first, keeping capacity for new evidence.
    np.testing.assert_allclose(scn.geoms[0].rgba[:3], effects.IMPACT_COLORS["environment"][:3])
    np.testing.assert_allclose(scn.geoms[9].rgba[:3], effects.IMPACT_COLORS["damage"][:3])


def test_switches_and_scene_capacity_are_safe():
    effects = SpectatorEffects(enabled=False)
    p = projectile()
    effects.update(0, [p], [])
    p.position[0] = 1
    effects.update(.01, [p], [])
    events = [contact(.012)]
    effects.update(.02, [], events)
    assert effects.draw(scene()) == 0
    effects.enabled = True
    assert effects.draw(scene(), trails=False, impacts=False) == 0
    assert effects.draw(scene(), trails=False) == 3
    assert effects.draw(scene(), impacts=False) == 1
    tiny = scene(2)
    tiny.ngeom = 1
    tiny.geoms[0].rgba[:] = (.1, .2, .3, .4)
    before = tiny.geoms[0].rgba.copy()
    assert effects.draw(tiny) == 1
    assert tiny.ngeom == 2
    np.testing.assert_array_equal(tiny.geoms[0].rgba, before)
    assert effects.draw(tiny) == 0
    assert tiny.geoms[1].category == mujoco.mjtCatBit.mjCAT_DECOR
    assert tiny.geoms[1].objid == tiny.geoms[1].segid == -1


@pytest.mark.parametrize("kwargs", [dict(trail_seconds=0), dict(impact_seconds=float("nan")),
    dict(max_projectiles=0), dict(max_points_per_projectile=1), dict(max_impacts=1.5),
    dict(line_width=-1), dict(marker_half_size=0)])
def test_invalid_limits_fail_explicitly(kwargs):
    with pytest.raises(ValueError):
        SpectatorEffects(**kwargs)


def test_invalid_or_unfinalized_data_cannot_become_visual_evidence():
    effects = SpectatorEffects()
    with pytest.raises(ValueError, match="future"):
        effects.update(0, [], [contact(.1)])
    with pytest.raises(ValueError, match="boolean"):
        effects.update(.1, [], [contact(damage="false")])
    with pytest.raises(ValueError, match="finite three"):
        effects.update(.1, [projectile(position=(0, float("nan"), 1))], [])
    effects.update(.1, [], [contact()])
    with pytest.raises(ValueError, match="Late contact"):
        effects.update(.2, [], [contact(), contact(.01)])


def test_recording_real_contact_and_rendering_cannot_change_agent_rgb_or_physics():
    sim = MatchSimulation()
    try:
        effects = SpectatorEffects()
        sim._fire("red_sentry")
        p = sim.projectiles[0]
        armor = sim.model.geom("blue_sentry__armor_front").id
        normal = sim.data.geom_xmat[armor].reshape(3, 3)[:, 0]
        p.position = sim.data.geom_xpos[armor].copy() + normal * .2
        p.velocity = -normal * 22.5
        effects.update(sim.time, sim.projectiles, sim.contact_events)
        for _ in range(12):
            sim.step()
            effects.update(sim.time, sim.projectiles, sim.contact_events)
        assert sim.contact_events, "Test must produce actual simulated contact"
        assert effects.event_count == len(sim.contact_events)
        hit = effects.impact_history[0]
        event = sim.contact_events[hit.ledger_index]
        assert hit.position == tuple(event["position"])
        assert hit.damage_applied == event["damage_applied"]
        assert effects.trail_history[0].samples[-1].position == hit.position

        agent_before = sim.observe("red_sentry").rgb
        qpos = sim.data.qpos.copy()
        qvel = sim.data.qvel.copy()
        model_size = sim.model.geom_size.copy()
        hp = {rid: robot.hp for rid, robot in sim.judge.robots.items()}
        spectator_before = sim.image()
        sim.renderer.update_scene(sim.data, camera="arena_overview")
        sim.draw_projectiles(sim.renderer.scene)
        assert effects.draw(sim.renderer.scene) > 0
        spectator = sim.renderer.render().copy()
        assert spectator.shape == (240, 320, 3)
        assert np.any(spectator != spectator_before)
        # Raw camera refresh removes all spectator scene decorations, including
        # when the same renderer is reused serially for spectator and sensors.
        np.testing.assert_array_equal(sim.observe("red_sentry").rgb, agent_before)
        np.testing.assert_array_equal(sim.data.qpos, qpos)
        np.testing.assert_array_equal(sim.data.qvel, qvel)
        np.testing.assert_array_equal(sim.model.geom_size, model_size)
        assert hp == {rid: robot.hp for rid, robot in sim.judge.robots.items()}
    finally:
        sim.close()
