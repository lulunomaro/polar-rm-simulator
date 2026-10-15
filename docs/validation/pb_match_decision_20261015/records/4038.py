"""Pure source rendering/preparation checks; no native build or tree execution."""
import json
import re
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from tools import prepare_pb_match_decision as prep


def test_owned_overlay_preserves_real_condition_graph_and_marks_unsupported_io():
    original=(prep.AUDIT/"pb2025_sentry_behavior/behavior_trees/rmul_2025.xml").read_bytes()
    rendered, changes=prep.render_tree(original)
    before,after=ET.fromstring(original),ET.fromstring(rendered)
    for tag in ("IsGameStatus","IsStatusOK","IsRfidDetected"):
        assert [n.attrib for n in before.iter(tag)] == [n.attrib for n in after.iter(tag)]
    assert len(list(after.iter("PublishSpinSpeed")))==0
    assert len(list(after.iter("PublishTwist")))==0
    assert len(list(after.iter("ScopedHold")))==1
    goals={n.attrib["name"]:n.attrib for n in after.iter("PubNav2Goal")}
    assert goals["attack_goal"]["goal"]=="{@attack_pose}"
    assert goals["supply_goal"]["goal"]=="{@supply_pose}"
    assert {n["kind"] for n in changes}=={"spin_disabled","source_bound_zero_stop","estimated_anchor_local_waypoint"}
    assert prep.sha(original)==prep.XML_SHA256 and prep.sha(rendered)!=prep.XML_SHA256


@pytest.mark.parametrize("mutation",[lambda x:x.replace(b'7.0',b'2.0',1),lambda x:x+b' ',lambda x:x.replace(b'4.65',b'1.0',1)])
def test_unreviewed_original_xml_changes_are_rejected(mutation):
    raw=(prep.AUDIT/"pb2025_sentry_behavior/behavior_trees/rmul_2025.xml").read_bytes()
    with pytest.raises(ValueError,match="original_xml_changed"):prep.render_tree(mutation(raw))


def test_prepare_copies_original_cpp_and_headers_with_full_source_pins(tmp_path):
    original={str(prep.AUDIT/"pb2025_sentry_behavior"/name):prep.sha(prep.AUDIT/"pb2025_sentry_behavior"/name) for name in prep.PB_HASHES}
    out=tmp_path/"fresh"
    manifest=prep.prepare_sources(out)
    for name,digest in prep.PB_HASHES.items():assert prep.sha(out/"src/upstream/pb"/name)==digest
    for name,digest in prep.ROS_HASHES.items():assert prep.sha(out/"src/upstream/ros2"/name)==digest
    assert manifest["upstream"]==prep.UPSTREAM
    assert manifest["original_xml_sha256"]==prep.XML_SHA256
    assert json.loads((out/"src/SOURCE_IDENTITY.json").read_bytes())==manifest
    assert all(prep.sha(path)==digest for path,digest in original.items())
    assert not (out/"build").exists() and not (out/"install").exists()
    with pytest.raises(ValueError,match="fresh_build_required"):prep.prepare_sources(out)


def test_upstream_tamper_is_detected_before_output_directory_creation(tmp_path):
    copied=tmp_path/"audit";source=copied/"pb2025_sentry_behavior"
    first=next(iter(prep.PB_HASHES));path=source/first;path.parent.mkdir(parents=True)
    path.write_bytes(b"// altered upstream fixture\n")
    out=tmp_path/"never_created"
    with pytest.raises(ValueError,match="upstream_source_changed"):prep.prepare_sources(out,audit=copied)
    assert not out.exists()


def test_native_build_is_never_started_on_windows(tmp_path):
    import sys
    if sys.platform=="linux":pytest.skip("Linux build is explicitly not invoked by this test")
    with pytest.raises(ValueError,match="build_linux_only"):
        prep.build(tmp_path/"unused",btcpp_prefix=tmp_path,interface_prefix=tmp_path,environment_path=tmp_path/"missing")


def test_all_original_pb_and_fork_local_includes_exist_in_the_owned_copy(tmp_path):
    out=tmp_path/"closed_source_set";prep.prepare_sources(out)
    source=out/"src"
    include_roots=[source/"upstream/pb/include",source/"upstream/ros2/include"]
    for path in source.rglob("*"):
        if not path.is_file() or path.suffix not in (".hpp",".cpp"):continue
        for name in re.findall(r'#include\s+"((?:pb2025_sentry_behavior|behaviortree_ros2)/[^\"]+)"',path.read_text(encoding="utf-8")):
            assert any((root/name).is_file() for root in include_roots),(str(path),name)
