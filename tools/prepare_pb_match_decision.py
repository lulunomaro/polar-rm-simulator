"""Prepare/build an owned, real PB BT4 runner and write its explicit spec.

No tree, ROS node or simulator is executed by this tool. Building is opt-in and
Linux-only. Upstream inputs are copied byte-for-byte; only the owned XML has the
documented spin/zero-stop/local-waypoint I/O overlay.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "artifacts/pb-match-behavior-audit-20261014-01"
UPSTREAM = dict(behavior_revision="d111b635d326775c6c19aa12500a0bbd6a27a588",
    btcpp_revision="2a8a226fbbd99f524f0796e0d8a3145773c61c06",
    ros2_revision="7d177dcfbd7dbb7f5e5cd79c4e5e3e744e389c56")
PB_HASHES = {
    "include/pb2025_sentry_behavior/custom_types.hpp":"c4f10a0347a87a829bb2c7633a0504494f1b052b86e7df72ecdd54bf3f8e3381",
    "include/pb2025_sentry_behavior/plugins/action/pub_nav2_goal.hpp":"c3aa84daee045b2626ab6190b45c5d78a8aea06cbbdf3c9913ef391940cc80be",
    "include/pb2025_sentry_behavior/plugins/condition/is_game_status.hpp":"acfe266986cec2a6b87b77818d7b1a85cb610ea646f7b19e0a010e1783972354",
    "include/pb2025_sentry_behavior/plugins/condition/is_rfid_detected.hpp":"6a331f01d62f27945acc13209ec24d36f052abe282c11b1c4b6ea704e9125edd",
    "include/pb2025_sentry_behavior/plugins/condition/is_status_ok.hpp":"91ce3f90474d161ff2627cbf76818c150d46faf72fd6b390678e3a564be768b3",
    "plugins/action/pub_nav2_goal.cpp":"5b7940b34642ead7750160917269073bcfe3b955c16b268bc3e2d871fe691100",
    "plugins/condition/is_game_status.cpp":"654a75d743f11c4ce2dbbcbb8b8131715888289a10e5fa2154a043f27a5afdcb",
    "plugins/condition/is_rfid_detected.cpp":"df5601a089f0283f1a740b813af9b7961e34e5c616b6d724ec7326cacd16430f",
    "plugins/condition/is_status_ok.cpp":"4f2fa9319d257a8c0ddd2aa1ccc6a348fdda38fc576da6014d5c6005d5b182ad",
    "LICENSE":"cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
}
ROS_HASHES = {
    "include/behaviortree_ros2/plugins.hpp":"15e5a019981f8dc4e816dfb6dfa69d19c66b2b9a4c9d5c35842d39420db5c23d",
    "include/behaviortree_ros2/bt_topic_pub_node.hpp":"7e161e3e4ac6d7ba15042c971704ab1018c0197662623cb6731529e58cb04f8a",
    "include/behaviortree_ros2/ros_node_params.hpp":"5b4cab8c0a41c1d341146181785e2d405f5892d62933c0aea6f023f6ea2718d8",
}
XML_SHA256 = "68e216c145949538444bd8b9f9e97cc1b79b1536ddbc52a37eb00252e20c34f9"
OWN_FILES = ("operator_native/pb_match_decision/CMakeLists.txt", "operator_native/pb_match_decision/runner.cpp")


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else Path(value).read_bytes()).hexdigest()


def plain(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or path != path.resolve() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("pb_match_absolute_unaliased_path")
    return path


def write(path, value):
    raw = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
    with Path(path).open("xb") as f:f.write(raw)
    return sha(raw)


def render_tree(raw):
    if sha(raw) != XML_SHA256:raise ValueError("pb_match_original_xml_changed")
    tree = ET.fromstring(raw)
    if tree.attrib != {"BTCPP_format":"4"}:raise ValueError("pb_match_xml_version")
    changed = [];goals = 0
    for parent in tree.iter():
        for child in list(parent):
            if child.tag == "PublishSpinSpeed":
                replacement = ET.Element("AlwaysSuccess", name="spin_disabled_explicit_overlay")
                replacement.tail = child.tail;parent[list(parent).index(child)] = replacement
                changed.append(dict(kind="spin_disabled", original=child.attrib))
            elif child.tag == "PublishTwist":
                if any(float(child.attrib[k]) != 0. for k in ("v_x","v_y","v_yaw")) or float(child.attrib["duration"]) != 0.:
                    raise ValueError("pb_match_only_original_zero_stop")
                replacement = ET.Element("ScopedHold", name="game_safety_hold")
                replacement.tail = child.tail;parent[list(parent).index(child)] = replacement
                changed.append(dict(kind="source_bound_zero_stop", original=child.attrib))
            elif child.tag == "PubNav2Goal":
                original = dict(child.attrib)
                if original["goal"] == "0;0;0":child.set("goal","{@supply_pose}");child.set("name","supply_goal")
                elif original["goal"] == "4.65;-3.5;0":child.set("goal","{@attack_pose}");child.set("name","attack_goal")
                else:raise ValueError("pb_match_original_goal_changed")
                child.set("topic_name","goal_pose_audit");goals += 1
                changed.append(dict(kind="estimated_anchor_local_waypoint", original=original, overlay=dict(child.attrib)))
    if goals != 2 or len(changed) != 5:raise ValueError("pb_match_overlay_roster")
    ET.indent(tree, space="  ")
    return ET.tostring(tree, encoding="utf-8", xml_declaration=True) + b"\n", changed


def prepare_sources(out, *, root=ROOT, audit=AUDIT):
    out, root, audit = plain(Path(out).absolute()), plain(Path(root).absolute()), plain(Path(audit).absolute())
    if out.exists():raise ValueError("pb_match_fresh_build_required")
    selected = {}
    for package, hashes, source in (("pb",PB_HASHES,audit/"pb2025_sentry_behavior"),
                                   ("ros2",ROS_HASHES,audit/"BehaviorTree.ROS2/behaviortree_ros2")):
        for name, digest in hashes.items():
            path = plain(source/name);raw = path.read_bytes()
            if sha(raw) != digest:raise ValueError("pb_match_upstream_source_changed:"+name)
            selected["upstream/"+package+"/"+name] = (path,raw)
    xml_path = plain(audit/"pb2025_sentry_behavior/behavior_trees/rmul_2025.xml")
    xml, overlay = render_tree(xml_path.read_bytes())
    for name in OWN_FILES:selected[Path(name).name] = (plain(root/name),(root/name).read_bytes())
    inputs = {str(path):sha(raw) for path,raw in selected.values()}
    inputs[str(xml_path)] = XML_SHA256
    out.mkdir(parents=True);source = out/"src";source.mkdir()
    for name,(_,raw) in selected.items():
        path = source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    (source/"local_rmul_2025.xml").write_bytes(xml)
    manifest = dict(schema="polar.pb.match-decision-source.v1", upstream=UPSTREAM,
        inputs=inputs, files={name:sha(raw) for name,(_,raw) in selected.items()},
        original_xml_sha256=XML_SHA256, overlay_xml_sha256=sha(xml), overlay=overlay,
        generator=dict(path=str(root/"tools/prepare_pb_match_decision.py"),sha256=sha(root/"tools/prepare_pb_match_decision.py")))
    write(source/"SOURCE_IDENTITY.json",manifest)
    return manifest


def build(out, *, btcpp_prefix, interface_prefix, environment_path, timeout_s=180.):
    if sys.platform != "linux":raise ValueError("pb_match_build_linux_only")
    if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
    from rm_match.integrations.owned_linux_group import LinuxOwnedProcessGroup
    out = plain(Path(out).absolute());environment_path = plain(Path(environment_path).absolute())
    environment = json.loads(environment_path.read_bytes());env = dict(os.environ,**environment["process_environment"])
    env.pop("PYTHONPATH",None);env.pop("PYTHONHOME",None)
    btcpp_prefix, interface_prefix = plain(Path(btcpp_prefix)),plain(Path(interface_prefix))
    python = environment["venv_python"]
    if not Path(python).is_absolute() or not Path(python).is_file():raise ValueError("pb_match_verified_python")
    prefix = str(btcpp_prefix)+";"+str(interface_prefix)+";"+env.get("CMAKE_PREFIX_PATH","").replace(":",";")
    env["AMENT_PREFIX_PATH"] = str(interface_prefix)+":"+env.get("AMENT_PREFIX_PATH","")
    env["LD_LIBRARY_PATH"] = str(btcpp_prefix/"lib")+":"+str(interface_prefix/"lib")+":"+env.get("LD_LIBRARY_PATH","")
    manifest = json.loads((out/"src/SOURCE_IDENTITY.json").read_bytes())
    commands = [];deadline = time.perf_counter()+timeout_s
    def run(argv):
        index=len(commands)+1;start=time.perf_counter()
        owner=LinuxOwnedProcessGroup();timed_out=False
        with (out/f"{index:02d}.stdout.log").open("xb") as stdout,(out/f"{index:02d}.stderr.log").open("xb") as stderr:
            child=subprocess.Popen(argv,cwd=out,env=env,stdout=stdout,stderr=stderr,shell=False,start_new_session=True)
            owner.attach(child)
            try:child.wait(timeout=max(.001,deadline-time.perf_counter()))
            except subprocess.TimeoutExpired:
                timed_out=True
            finally:cleanup=owner.cleanup()
        row=dict(argv=argv,exit_code=child.returncode,reaped=child.poll() is not None,elapsed_s=time.perf_counter()-start,
            timed_out=timed_out,cleanup=cleanup)
        commands.append(row)
        if child.returncode or timed_out or cleanup.get("clean") is not True:raise RuntimeError("pb_match_build_command_failed")
    error = None
    try:
        run(["cmake","-S",str(out/"src"),"-B",str(out/"build"),"-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
            "-DCMAKE_INSTALL_PREFIX="+str(out/"install"),"-DCMAKE_PREFIX_PATH="+prefix,
            "-DPython3_EXECUTABLE="+python,"-DPYTHON_EXECUTABLE="+python])
        run(["cmake","--build",str(out/"build"),"--parallel","2"])
        run(["cmake","--install",str(out/"build")])
    except BaseException as exc:error=type(exc).__name__+":"+str(exc)
    native = out/"install/bin/polar_pb_match_decision";xml = out/"src/local_rmul_2025.xml"
    unchanged = all(sha(path)==digest for path,digest in manifest["inputs"].items()) and all(
        sha(out/"src"/name)==digest for name,digest in manifest["files"].items()) and (
        sha(manifest["generator"]["path"])==manifest["generator"]["sha256"] and sha(xml)==manifest["overlay_xml_sha256"])
    ldd = None
    if error is None:
        try:
            run(["ldd",str(native)])
            stdout=(out/f"{len(commands):02d}.stdout.log").read_bytes()
            loaded={}
            for line in stdout.decode("utf-8","replace").splitlines():
                tokens=line.split()
                candidate=(tokens[tokens.index("=>")+1] if "=>" in tokens else tokens[0] if tokens else "")
                if candidate.startswith("/"):
                    path=Path(candidate).resolve()
                    if path.is_file():loaded[str(path)]=sha(path)
            ldd=dict(exit_code=commands[-1]["exit_code"],all_resolved=b"not found" not in stdout,
                stdout_sha256=sha(stdout),cleanup=commands[-1]["cleanup"],loaded_sha256=loaded)
        except BaseException as exc:error=type(exc).__name__+":"+str(exc)
    passed = error is None and unchanged and native.is_file() and ldd["all_resolved"]
    result = dict(schema="polar.pb.match-decision-build.v1",passed=passed,upstream=UPSTREAM,
        source_manifest_sha256=sha(out/"src/SOURCE_IDENTITY.json"),
        source_manifest_ref=dict(path=str(out/"src/SOURCE_IDENTITY.json"),sha256=sha(out/"src/SOURCE_IDENTITY.json")),
        native=dict(path=str(native),sha256=sha(native) if native.is_file() else None),
        xml=dict(path=str(xml),sha256=sha(xml)),btcpp=dict(prefix=str(btcpp_prefix),version="4.6.2",
            library_ref=dict(path=str((btcpp_prefix/"lib/libbehaviortree_cpp.so").resolve()),sha256=sha(btcpp_prefix/"lib/libbehaviortree_cpp.so"))),
        interface_prefix=str(interface_prefix),environment=dict(path=str(environment_path),sha256=sha(environment_path)),
        dependency_refs=dict(pb_rm_interfaces=dict(path=str((interface_prefix/"lib/libpb_rm_interfaces__rosidl_typesupport_cpp.so").resolve()),
            sha256=sha(interface_prefix/"lib/libpb_rm_interfaces__rosidl_typesupport_cpp.so"))),
        compile_commands=dict(path=str(out/"build/compile_commands.json"),sha256=sha(out/"build/compile_commands.json") if (out/"build/compile_commands.json").is_file() else None),
        runtime_environment=env,commands=commands,source_unchanged=unchanged,ldd=ldd,error=error)
    # Store only the verified runtime delta, never inherited credentials.
    result["runtime_environment"] = {k:env[k] for k in environment["process_environment"] if k in env}
    result["runtime_environment"]["AMENT_PREFIX_PATH"] = env["AMENT_PREFIX_PATH"]
    result["runtime_environment"]["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH"]
    write(out/"BUILD_RESULT.json",result)
    if not passed:raise RuntimeError("pb_match_build_failed")
    return result


def write_spec(out, *, build_path, environment_path, root=ROOT, context=None, waypoints=None, run_uuid=None):
    if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
    from rm_match.integrations.pb_match_decision_peer import SOURCE_FILES
    from rm_match.deployment.decision_plugin import NAVIGATION_CAPABILITIES
    from rm_match.deployment.wsl_jsonl import mounted_path
    from rm_match.platform_v2.contracts import identity
    from rm_match.platform_v2.contracts import exact
    from rm_match.integrations.pb_match_decision_peer import _waypoints
    root,out = plain(Path(root).absolute()),plain(Path(out).absolute())
    if out.exists() or not out.is_relative_to(root/"artifacts"):raise ValueError("pb_match_fresh_shared_spec_required")
    build_path,environment_path = plain(Path(build_path).absolute()),plain(Path(environment_path).absolute())
    result = json.loads(build_path.read_bytes());environment=json.loads(environment_path.read_bytes())
    if result["schema"]!="polar.pb.match-decision-build.v1" or result["passed"] is not True or result["source_unchanged"] is not True or result["upstream"]!=UPSTREAM:
        raise ValueError("pb_match_actual_build_required")
    context = copy.deepcopy(context or dict(robot_id="red_sentry",episode=0,binding_epoch=1))
    exact(context,("robot_id","episode","binding_epoch"),"pb_match_expected_generation")
    identity(dict(context,observed_seq=0,sim_time=0.,wall_deadline=0.))
    run_uuid = secrets.token_hex(16) if run_uuid is None else run_uuid
    if type(run_uuid) is not str or len(run_uuid)!=32 or any(k not in "0123456789abcdef" for k in run_uuid):raise ValueError("pb_match_run_uuid")
    waypoints = copy.deepcopy(waypoints or dict(schema="polar.pb.local-waypoints.v1",attack_offset_m=[1.,0.],supply_offset_m=[0.,0.],yaw_offset_rad=0.))
    _waypoints(waypoints)
    roster = tuple(dict.fromkeys((*SOURCE_FILES,*OWN_FILES,"tools/prepare_pb_match_decision.py")))
    sources = {name:sha(root/name) for name in roster}
    out.mkdir(parents=True)
    # Native needs the freshly built BT4/msg loader prefix, without changing
    # any preserved original ENV. This explicit derived ENV is pinned itself.
    environment["process_environment"] = copy.deepcopy(result["runtime_environment"])
    derived_path = out/"ENVIRONMENT.json";write(derived_path,environment)
    spec = dict(schema="polar.pb.match-decision-peer-spec.v1",run_uuid=run_uuid,root_linux=mounted_path(root),
        out_linux=mounted_path(out/"peer-evidence"),namespace="/polar_match_"+run_uuid+"/"+context["robot_id"],domain_id=84,
        native_ref=result["native"],xml_ref=result["xml"],build_ref=dict(path=mounted_path(build_path),sha256=sha(build_path)),
        environment_ref=dict(path=mounted_path(derived_path),sha256=sha(derived_path)),source_sha256=sources,
        expected_generation=context,waypoints=waypoints,capabilities=copy.deepcopy(NAVIGATION_CAPABILITIES))
    digest = write(out/"PEER_SPEC.json",spec)
    return dict(spec_path=str(out/"PEER_SPEC.json"),spec_sha256=digest,peer_evidence_dir=str(out/"peer-evidence"),
        resources_started=False,ticks=0)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--btcpp-prefix",type=Path)
    parser.add_argument("--interface-prefix",type=Path)
    parser.add_argument("--environment",type=Path)
    parser.add_argument("--build",action="store_true")
    parser.add_argument("--spec-from-build",type=Path)
    args=parser.parse_args(argv)
    if args.spec_from_build:
        if args.environment is None:parser.error("--environment required")
        result=write_spec(args.out,build_path=args.spec_from_build,environment_path=args.environment)
    else:
        result=prepare_sources(args.out)
        if args.build:
            if any(v is None for v in (args.btcpp_prefix,args.interface_prefix,args.environment)):
                parser.error("--build needs --btcpp-prefix --interface-prefix --environment")
            result=build(args.out,btcpp_prefix=args.btcpp_prefix,interface_prefix=args.interface_prefix,environment_path=args.environment)
    print(json.dumps(result,allow_nan=False));return 0


if __name__=="__main__":raise SystemExit(main())
