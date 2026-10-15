"""Build an owned, UUID-associated Nav2 1.1.20 controller executable.

No nodes are started. The installed server, PB PID plugin, and old manifests are
read-only inputs. The original upstream notices remain in every copied source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

UPSTREAM_REVISION = "a097086719c88f781aa59788eca29ac6ca5e56db"
UPSTREAM_URL = "https://github.com/ros-navigation/navigation2"
SOURCE_HASHES = {
    "src/controller_server.cpp": "b9bc6dc7bb90602f65971d8c5eed2b73ffeaf5aa3e9ebd4ec1de3e725552d705",
    "src/main.cpp": "cdec7e6f5e7bdbe95eadac16371c9aaa74d78855b67812ebae9b4525e32ed3ea",
    "include/nav2_controller/controller_server.hpp": "b607b9d512a830046b26130e240655098bac6c17ec6a5596d4f604a172237e09",
    "CMakeLists.txt": "cc309424fc72f65d1ef79badf8a65288c20993b05f6d14298b062899ae46070d",
    "package.xml": "79a576e2b2faf6a368ed7b4e8c5e209f72bd2233f53afc5c2feb27c1e3634e8e",
}
SIMPLE_ACTION_SERVER_SHA256 = "942c09496c49f8343e360a549819582b299ddae7b07fc3e2678a57568d2df8cc"
ORIGINAL_SERVER_SHA256 = "16b8ccba3f17203480a065787caef9a6f312c8090c1943ad346766008a7d274d"
ROOT = Path(__file__).resolve().parents[1]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def replace_once(raw, old, new):
    if raw.count(old) != 1:
        raise ValueError("goal_controller_overlay_anchor_mismatch")
    return raw.replace(old, new, 1)


GOAL_GUARD = r'''
  // A token owns the actual accepted handle of this compute call, not a
  // subscriber's latest UUID. No lock is held while the algorithm runs.
  struct PolarGoalToken {
    std::shared_ptr<rclcpp_action::ServerGoalHandle<ActionT>> handle;
    rclcpp_action::GoalUUID uuid{};
  };

  PolarGoalToken polar_capture_goal() const
  {
    std::lock_guard<std::recursive_mutex> lock(update_mutex_);
    if (!polar_current_usable_locked()) {return {};}
    return {current_handle_, get_current_goal_id()};
  }

  template<class Publish>
  bool polar_finish_goal(const PolarGoalToken & token, Publish publish)
  {
    std::lock_guard<std::recursive_mutex> lock(update_mutex_);
    if (!token.handle || current_handle_ != token.handle ||
      !polar_current_usable_locked() || get_current_goal_id() != token.uuid)
    {
      return false;
    }
    // Serialize accepted cancel/preempt/deactivate callbacks with publication.
    publish();
    return true;
  }

protected:
  std::set<rclcpp_action::GoalUUID> polar_cancel_accepted_;

  void polar_prune_cancel_ids_locked()
  {
    for (auto it = polar_cancel_accepted_.begin(); it != polar_cancel_accepted_.end(); ) {
      if ((!current_handle_ || current_handle_->get_goal_id() != *it) &&
        (!pending_handle_ || pending_handle_->get_goal_id() != *it))
      {
        it = polar_cancel_accepted_.erase(it);
      } else {++it;}
    }
  }

  bool polar_current_usable_locked() const
  {
    // Upstream is_cancel_requested checks pending instead of current whenever
    // pending exists. Check the actual current handle and reject any preempt.
    return server_active_ && !stop_execution_ && !preempt_requested_ &&
      !is_active(pending_handle_) && is_active(current_handle_) &&
      !current_handle_->is_canceling() &&
      !polar_cancel_accepted_.count(current_handle_->get_goal_id());
  }
'''


def action_server_overlay(raw):
    text = raw.decode("utf8")
    text = text.replace("NAV2_UTIL__SIMPLE_ACTION_SERVER_HPP_", "POLAR_NAV2_UTIL__GOAL_ACTION_SERVER_HPP_")
    text = replace_once(text, "#include <memory>", "#include <memory>\n#include <set>")
    text = replace_once(text, "namespace nav2_util\n{", "namespace polar_nav2_util\n{")
    text = text.replace("SimpleActionServer", "GoalActionServer")
    text = replace_once(text, "    debug_msg(\"Received request for goal cancellation\");",
        "    polar_prune_cancel_ids_locked();\n"
        "    polar_cancel_accepted_.insert(handle->get_goal_id());\n"
        "    debug_msg(\"Received request for goal cancellation\");")
    text = replace_once(text, "protected:\n  // The GoalActionServer", GOAL_GUARD + "\n  // The GoalActionServer")
    return text.encode()


def controller_overlay(files, simple_header, context_header, request_header):
    """Pure rendering after independently verifying all immutable inputs."""
    files = dict(files)
    cpp = files["src/controller_server.cpp"].decode()
    hpp = files["include/nav2_controller/controller_server.hpp"].decode()
    main = files["src/main.cpp"].decode()
    # Preserve pluginlib IDs such as nav2_controller::SimpleGoalChecker. Only
    # the owned server symbols and its private include path are renamed.
    cpp = cpp.replace("namespace nav2_controller", "namespace polar_nav2_controller")
    hpp = hpp.replace("namespace nav2_controller", "namespace polar_nav2_controller")
    for original in ('"nav2_controller/controller_server.hpp"',):
        cpp = cpp.replace(original, '"polar_nav2_controller/controller_server.hpp"')
        main = main.replace(original, '"polar_nav2_controller/controller_server.hpp"')
    main = main.replace("nav2_controller::ControllerServer", "polar_nav2_controller::ControllerServer")
    hpp = hpp.replace("NAV2_CONTROLLER__CONTROLLER_SERVER_HPP_", "POLAR_NAV2_CONTROLLER__CONTROLLER_SERVER_HPP_")
    hpp = replace_once(hpp, '#include "nav2_util/simple_action_server.hpp"',
        '#include "polar_nav2_controller/goal_action_server.hpp"\n'
        '#include "polar_nav2_controller/pb_goal_controller_context.hpp"')
    hpp = replace_once(hpp, "using ActionServer = nav2_util::SimpleActionServer<Action>;",
        "using ActionServer = polar_nav2_util::GoalActionServer<Action>;")
    hpp = replace_once(hpp, "  std::unique_ptr<ActionServer> action_server_;",
        "  std::unique_ptr<ActionServer> action_server_;\n"
        "  polar_pb::GoalControllerContext polar_goal_sourced_;")
    anchor = '  vel_publisher_ = create_publisher<geometry_msgs::msg::Twist>("cmd_vel", 1);'
    cpp = replace_once(cpp, anchor, anchor + "\n  polar_goal_sourced_.configure(node, costmap_ros_->getBaseFrameID());")
    cpp = replace_once(cpp, "  action_server_->activate();", "  action_server_->activate();\n  polar_goal_sourced_.activate();")
    cpp = replace_once(cpp, "  action_server_->deactivate();", "  polar_goal_sourced_.deactivate();\n  action_server_->deactivate();")
    cpp = replace_once(cpp, "  action_server_.reset();", "  polar_goal_sourced_.cleanup();\n  action_server_.reset();")
    anchor = "  try {\n    cmd_vel_2d =\n      controllers_[current_controller_]->computeVelocityCommands("
    cpp = replace_once(cpp, anchor,
        "  try {\n    const auto polar_goal = action_server_->polar_capture_goal();\n"
        "    const auto polar_request = polar_goal_sourced_.begin(pose);\n"
        "    cmd_vel_2d =\n      controllers_[current_controller_]->computeVelocityCommands(")
    anchor = "      goal_checkers_[current_goal_checker_].get());\n    last_valid_cmd_time_ = now();"
    cpp = replace_once(cpp, anchor,
        "      goal_checkers_[current_goal_checker_].get());\n"
        "    action_server_->polar_finish_goal(polar_goal, [&]() {\n"
        "      polar_goal_sourced_.finish(polar_request, pose, cmd_vel_2d, polar_goal.uuid);\n"
        "    });\n    last_valid_cmd_time_ = now();")
    # This executable owns its class; do not load/register a second core.so.
    cpp = replace_once(cpp, '#include "rclcpp_components/register_node_macro.hpp"',
        "// Standalone owned executable: no component registration or core.so.")
    cpp = replace_once(cpp, "RCLCPP_COMPONENTS_REGISTER_NODE(nav2_controller::ControllerServer)", "")
    return {
        "src/controller_server.cpp": cpp.encode(), "src/main.cpp": main.encode(),
        "include/polar_nav2_controller/controller_server.hpp": hpp.encode(),
        "include/polar_nav2_controller/goal_action_server.hpp": action_server_overlay(simple_header),
        "include/polar_nav2_controller/pb_goal_controller_context.hpp": context_header,
        "include/polar_nav2_controller/pb_request_context.hpp": request_header,
        "UPSTREAM_PACKAGE.xml": files["package.xml"], "UPSTREAM_CMakeLists.txt": files["CMakeLists.txt"],
        "CMakeLists.txt": CMAKE.encode(),
    }


CMAKE = '''cmake_minimum_required(VERSION 3.8)
project(polar_nav2_goal_controller)
find_package(ament_cmake REQUIRED)
find_package(nav2_common REQUIRED)
find_package(nlohmann_json 3.2.0 REQUIRED)
set(dependencies angles rclcpp rclcpp_action rclcpp_components std_msgs nav2_msgs nav_2d_utils nav_2d_msgs nav2_util nav2_core pluginlib)
foreach(dependency ${dependencies})
  find_package(${dependency} REQUIRED)
endforeach()
nav2_package()
add_executable(polar_goal_controller_server src/main.cpp src/controller_server.cpp)
target_include_directories(polar_goal_controller_server PRIVATE include)
target_compile_features(polar_goal_controller_server PRIVATE cxx_std_17)
ament_target_dependencies(polar_goal_controller_server ${dependencies})
target_link_libraries(polar_goal_controller_server nlohmann_json::nlohmann_json)
install(TARGETS polar_goal_controller_server RUNTIME DESTINATION lib/polar_nav2_goal_controller)
'''


def prepare(source_root, prefix, out):
    source_root, prefix, out = map(Path, (source_root, prefix, out))
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError("goal_controller_requires_new_owned_directory")
    originals = {name: (source_root / name).read_bytes() for name in SOURCE_HASHES}
    if any(sha(originals[name]) != digest for name, digest in SOURCE_HASHES.items()):
        raise ValueError("goal_controller_upstream_source_hash_mismatch")
    action_raw = (prefix / "include/nav2_util/simple_action_server.hpp").read_bytes()
    if sha(action_raw) != SIMPLE_ACTION_SERVER_SHA256:
        raise ValueError("goal_controller_action_server_header_hash_mismatch")
    original_server = prefix / "lib/nav2_controller/controller_server"
    if sha(original_server.read_bytes()) != ORIGINAL_SERVER_SHA256:
        raise ValueError("goal_controller_original_executable_hash_mismatch")
    context = ROOT / "rm_match/integrations/pb_goal_controller_context.hpp"
    request = ROOT / "rm_match/integrations/pb_request_context.hpp"
    files = controller_overlay(originals, action_raw, context.read_bytes(), request.read_bytes())
    identity = dict(schema="polar.nav2.goal-controller-source.v1", upstream_revision=UPSTREAM_REVISION,
        upstream_url=UPSTREAM_URL, upstream_file_sha256=SOURCE_HASHES,
        installed_action_server_header_sha256=sha(action_raw),
        generator_sha256=sha(Path(__file__).read_bytes()), overlay_header_sha256=sha(context.read_bytes()),
        request_header_sha256=sha(request.read_bytes()),
        original_controller_server=dict(path=str(original_server), sha256=ORIGINAL_SERVER_SHA256),
        files={name: dict(bytes=len(raw), sha256=sha(raw)) for name, raw in sorted(files.items())},
        qualification="source_overlay_only_not_navigation_acceptance",
        algorithm="unchanged_pluginlib_loaded_controller", component_core_library=False)
    out.mkdir(parents=True)
    for name, raw in files.items():
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (out / "SOURCE_IDENTITY.json").write_text(json.dumps(identity, indent=2) + "\n", encoding="utf8")
    return identity


def terminate_group(proc):
    for sig, timeout in ((signal.SIGTERM, .5), (signal.SIGKILL, 1.)):
        try: os.killpg(proc.pid, sig)
        except ProcessLookupError: pass
        try: proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired: continue
    if proc.poll() is None:
        raise RuntimeError("goal_controller_build_process_unreaped")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, help="fixed nav2_controller source directory")
    parser.add_argument("--nav2-prefix", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--build-timeout-seconds", type=int, default=600)
    args = parser.parse_args(argv)
    if sys.platform != "linux" or not 60 <= args.build_timeout_seconds <= 1800:
        raise ValueError("goal_controller_requires_linux_and_bounded_build")
    out, prefix = Path(args.out).absolute(), Path(args.nav2_prefix).absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError("goal_controller_requires_new_owned_directory")
    env_raw = Path(args.environment).read_bytes()
    settings = json.loads(env_raw)
    env = dict(os.environ, **settings["process_environment"])
    identity = prepare(Path(args.source_root).absolute(), prefix, out / "src")
    if not args.build:
        return 0
    commands = [["cmake", "-S", str(out / "src"), "-B", str(out / "build"),
        "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_TESTING=OFF", "-DCMAKE_INSTALL_PREFIX=" + str(out / "install"),
        "-DPython3_EXECUTABLE=" + settings["venv_python"], "-DPYTHON_EXECUTABLE=" + settings["venv_python"]],
        ["cmake", "--build", str(out / "build"), "--parallel", "2"],
        ["cmake", "--install", str(out / "build")]]
    began = time.perf_counter()
    records = []
    timed_out = False
    for index, command in enumerate(commands):
        proc = None
        with (out / f"build-{index}.log").open("wb") as log:
            started = time.perf_counter()
            try:
                proc = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                proc.wait(timeout=max(.01, args.build_timeout_seconds - (time.perf_counter() - began)))
            except subprocess.TimeoutExpired:
                timed_out = True
                terminate_group(proc)
            finally:
                if proc is not None and proc.poll() is None:
                    terminate_group(proc)
            records.append(dict(command=command, exit_code=proc.returncode,
                reaped=proc.poll() is not None, elapsed_s=time.perf_counter() - started))
        if proc.returncode != 0 or timed_out:
            break
    executable = out / "install/lib/polar_nav2_goal_controller/polar_goal_controller_server"
    loader = None
    if len(records) == 3 and not timed_out and all(r["exit_code"] == 0 for r in records):
        check = subprocess.run(["ldd", str(executable)], env=env, stdin=subprocess.DEVNULL,
            capture_output=True, timeout=30)
        (out / "loader.stdout").write_bytes(check.stdout)
        (out / "loader.stderr").write_bytes(check.stderr)
        loader = dict(command=["ldd", str(executable)], exit_code=check.returncode,
            resolved=check.returncode == 0 and b"not found" not in check.stdout,
            stdout_sha256=sha(check.stdout), stderr_sha256=sha(check.stderr))
    source_unchanged = all(sha((out / "src" / name).read_bytes()) == item["sha256"]
        for name, item in identity["files"].items())
    original_unchanged = sha((prefix / "lib/nav2_controller/controller_server").read_bytes()) == ORIGINAL_SERVER_SHA256
    passed = bool(loader and loader["resolved"] and source_unchanged and original_unchanged)
    result = dict(schema="polar.nav2.goal-controller-build.v1", passed=passed,
        upstream_revision=UPSTREAM_REVISION,
        source_manifest_sha256=sha((out / "src/SOURCE_IDENTITY.json").read_bytes()),
        executable=dict(path=str(executable), sha256=sha(executable.read_bytes()) if executable.is_file() else None),
        original_controller_server=identity["original_controller_server"],
        environment_sha256=sha(env_raw), environment=settings["process_environment"],
        commands=records, timed_out=timed_out, elapsed_s=time.perf_counter() - began,
        loader=loader, generated_source_unchanged=source_unchanged, original_server_unchanged=original_unchanged,
        nodes_started=False, qualification="compile_and_loader_only_not_navigation_acceptance")
    (out / "BUILD_RESULT.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
