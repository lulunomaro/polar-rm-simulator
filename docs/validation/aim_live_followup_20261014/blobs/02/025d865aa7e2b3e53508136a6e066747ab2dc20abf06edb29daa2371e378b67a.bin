"""Run all non-rendering regression tests without constructing a renderer.

This explicitly deselects eight camera/rendering cases; it is not a full-suite
pass. Run `python -m pytest -q` separately when a rendering slot is available.
"""
from pathlib import Path
import os
import sys


RENDER_TESTS = (
    'tests/test_camera_profile.py::test_mujoco_native_render_and_lens_warp_projection',
    'tests/test_core.py::test_rgb_observation_and_motor_changes_image',
    'tests/test_core.py::test_scan_is_sensor_only_and_world_odometry',
    'tests/test_core.py::test_rgb_closed_loop_hits_moving_armor',
    'tests/test_match_engine.py::test_match_camera_is_actual_per_robot_view',
    'tests/test_match_engine.py::test_spectator_effects_cannot_be_requested_on_actor_output',
    'tests/test_spectator_effects.py::test_recording_real_contact_and_rendering_cannot_change_agent_rgb_or_physics',
)


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    import mujoco
    import pytest

    def rendering_forbidden(*args, **kwargs):
        raise AssertionError('This qualification run must not construct a renderer')

    original_renderer = mujoco.Renderer
    mujoco.Renderer = rendering_forbidden
    try:
        return pytest.main(['-q', *('--deselect='+case for case in RENDER_TESTS), *sys.argv[1:]])
    finally:
        mujoco.Renderer = original_renderer


if __name__ == '__main__':
    raise SystemExit(main())
