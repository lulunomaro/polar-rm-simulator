"""Real pinned dependency copies and metadata tamper rejection; no compiler/ROS."""
import hashlib
from pathlib import Path
import tempfile
from unittest.mock import patch
import pytest
from tools import prepare_pb_aim_dependencies as tool

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'artifacts/pb2025-aim-dependencies-20261014-01/source'

def test_actual_copies_only_change_four_metadata_files_and_all_messages_solver_match():
    if not SOURCE.exists():pytest.skip('Pinned dependency source evidence absent')
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.rglob('*') if p.is_file() and '.git' not in p.parts}
    with tempfile.TemporaryDirectory() as temporary:
        out=Path(temporary)/'owned';manifest=tool.prepare(SOURCE,out)
        assert len(manifest['changed'])==4 and manifest['message_and_solver_bytes_unchanged'] is True
        assert manifest['build'] is False and not (out/'install').exists()
        for rel,row in manifest['source_files'].items():
            if rel in manifest['changed']:continue
            assert (out/rel).read_bytes()==(SOURCE/row['source']).read_bytes()
        for package in ('auto_aim_interfaces','pb_rm_interfaces'):
            assert 'find_package(std_msgs REQUIRED)' in (out/'src'/package/'CMakeLists.txt').read_text()
            assert '<depend>std_msgs</depend>' in (out/'src'/package/'package.xml').read_text()
        assert '    std_msgs\n)' in (out/'src/pb_rm_interfaces/CMakeLists.txt').read_text()
        with pytest.raises(ValueError):tool.prepare(SOURCE,out)
    assert {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.rglob('*') if p.is_file() and '.git' not in p.parts}==before

def test_anchor_changes_cannot_silently_remove_an_algorithm_dependency():
    cmake='find_package(geometry_msgs REQUIRED)\n  DEPENDENCIES\n    geometry_msgs\n)'
    xml='<package>\n  <depend>geometry_msgs</depend>\n</package>'
    tool.metadata_overlay('pb_rm_interfaces',cmake,xml)
    for c,x in ((cmake+cmake,xml),(cmake,xml+xml),(cmake.replace('geometry_msgs','std_msgs'),xml)):
        with pytest.raises(ValueError):tool.metadata_overlay('pb_rm_interfaces',c,x)
    with pytest.raises(ValueError):tool.metadata_overlay('rmoss_projectile_motion',cmake,xml)

def test_actual_source_tamper_is_rejected_before_output_creation():
    if not SOURCE.exists():pytest.skip('Pinned dependency source evidence absent')
    path=SOURCE/'pb_rm_interfaces/msg/Gimbal.msg';original=Path.read_bytes
    def modified(self):
        raw=original(self)
        return raw+b'\n# unreviewed fixture edit\n' if self==path else raw
    with tempfile.TemporaryDirectory() as temporary,patch.object(Path,'read_bytes',modified):
        out=Path(temporary)/'rejected'
        with pytest.raises(ValueError,match='bytes differ'):tool.prepare(SOURCE,out)
        assert not out.exists()
