"""Owned synthetic DDS node + generic JSONL bridge; protocol fixture only."""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def close_node(child):
    """Only this direct Popen; outer WSL owner proves its whole Linux tree."""
    deadline = time.monotonic()+1.
    if child.poll() is None:
        child.terminate()
        try: child.wait(timeout=max(0., deadline-time.monotonic()-.2))
        except subprocess.TimeoutExpired: pass
    if child.poll() is None: child.kill()
    child.wait(timeout=max(0., deadline-time.monotonic()))
    return dict(reaped=child.poll() is not None, returncode=child.returncode)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ('adapter-id', 'kind', 'node-name', 'observation-topic', 'action-topic'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--domain-id', type=int, required=True)
    args = p.parse_args(argv)
    from rm_match.integrations.robotio_ros2_bridge import RobotIOSettings, main as bridge_main
    RobotIOSettings(**vars(args))
    common = ['--adapter-id', args.adapter_id, '--kind', args.kind,
        '--observation-topic', args.observation_topic, '--action-topic', args.action_topic,
        '--domain-id', str(args.domain_id)]
    child = None; code = 2
    try:
        # Intentionally no new session: this child stays in the supervised Linux
        # peer tree. No graph readiness or capability ACK is faked by this spawn.
        child = subprocess.Popen([sys.executable, str(ROOT/'tools/robotio_ros2_fixture_node.py'),
            '--node-name', args.node_name+'_fixture', *common], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=sys.stderr)
        code = bridge_main(['--node-name', args.node_name, *common])
    finally:
        try:
            if child is not None:
                already_exited = child.poll() is not None
                original_returncode = child.returncode
                proof = close_node(child)
                if proof['reaped'] is not True: raise RuntimeError('fixture_child_unreaped')
                if already_exited and original_returncode != 0: code = 2
                print('robotio_fixture_child_reaped returncode='+str(proof['returncode']),file=sys.stderr,flush=True)
        except Exception:
            print('robotio_fixture_peer_cleanup_incomplete',file=sys.stderr,flush=True);code=2
    return code


if __name__ == '__main__': raise SystemExit(main())
