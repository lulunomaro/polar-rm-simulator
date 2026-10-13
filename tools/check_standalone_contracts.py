"""Run an explicit synthetic-only test selection using existing dependencies."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

# Preserve imports when this script is invoked from a different directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MODULES = (
    'test_contracts', 'test_control', 'test_control_windows', 'test_spin',
    'test_offline_lifecycle', 'test_adapters', 'test_runtime', 'test_server',
    'test_client', 'test_window_client', 'test_adapter_activation',
    'test_observation_refresh',
)


def main():
    # This reviewed selection uses synthetic backends and bounded loopback HTTP.
    # Never replace it with discovery, which would include real physics tests.
    names = ['rm_match.platform_v2.' + name for name in MODULES]
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if any(name == 'mujoco' or name.startswith('mujoco.') for name in sys.modules):
        raise RuntimeError('Unexpected MuJoCo import in the synthetic-only selection')
    if result.wasSuccessful():
        print('Synthetic-only selection passed; no MuJoCo module was loaded.')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
