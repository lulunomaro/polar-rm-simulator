"""Owned source generation and real C++ goal-gate tests; no ROS nodes/algorithm."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("goal_controller_prepare", ROOT / "tools/prepare_nav2_goal_controller_overlay.py")
overlay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(overlay)


@pytest.fixture
def originals():
    # Minimal independent source preserving the exact reviewed insertion sites.
    cpp = '''#include "nav2_controller/controller_server.hpp"
namespace nav2_controller {
const char* checker="nav2_controller::SimpleGoalChecker";
  vel_publisher_ = create_publisher<geometry_msgs::msg::Twist>("cmd_vel", 1);
  action_server_->activate();
  action_server_->deactivate();
  action_server_.reset();
  try {
    cmd_vel_2d =
      controllers_[current_controller_]->computeVelocityCommands(
      pose,
      nav_2d_utils::twist2Dto3D(twist),
      goal_checkers_[current_goal_checker_].get());
    last_valid_cmd_time_ = now();
  } catch (...) {cmd_vel_2d.twist.linear.x = 0;}
}
#include "rclcpp_components/register_node_macro.hpp"
RCLCPP_COMPONENTS_REGISTER_NODE(nav2_controller::ControllerServer)
'''
    hpp = '''#ifndef NAV2_CONTROLLER__CONTROLLER_SERVER_HPP_
#include "nav2_util/simple_action_server.hpp"
namespace nav2_controller {
using ActionServer = nav2_util::SimpleActionServer<Action>;
  std::unique_ptr<ActionServer> action_server_;
}
'''
    main = '#include "nav2_controller/controller_server.hpp"\nnav2_controller::ControllerServer server;\n'
    return {"src/controller_server.cpp": cpp.encode(), "src/main.cpp": main.encode(),
        "include/nav2_controller/controller_server.hpp": hpp.encode(),
        "CMakeLists.txt": b"upstream CMake", "package.xml": b"upstream license"}


@pytest.fixture
def action_header():
    return b'''#ifndef NAV2_UTIL__SIMPLE_ACTION_SERVER_HPP_
#include <memory>
namespace nav2_util
{
class SimpleActionServer {
    debug_msg("Received request for goal cancellation");
protected:
  // The SimpleActionServer isn't itself a node
};
}
'''


def test_render_keeps_plugin_ids_and_algorithm_call_but_owns_symbols(originals, action_header):
    before = dict(originals)
    result = overlay.controller_overlay(originals, action_header, b"owned context", b"strict parser")
    cpp = result["src/controller_server.cpp"].decode()
    assert originals == before
    assert 'checker="nav2_controller::SimpleGoalChecker"' in cpp
    assert 'namespace polar_nav2_controller' in cpp
    assert 'make_shared' not in cpp
    assert cpp.count("->computeVelocityCommands(") == 1
    assert "RCLCPP_COMPONENTS_REGISTER_NODE(" not in cpp
    assert "controller_server_core" not in result["CMakeLists.txt"].decode()
    assert 'target_compile_features(polar_goal_controller_server PRIVATE cxx_std_17)' in result["CMakeLists.txt"].decode()
    hpp = result["include/polar_nav2_controller/controller_server.hpp"].decode()
    assert 'polar_nav2_util::GoalActionServer<Action>' in hpp


def test_capture_source_before_actual_compute_and_finish_only_in_success_branch(originals, action_header):
    result = overlay.controller_overlay(originals, action_header, b"ctx", b"parser")
    cpp = result["src/controller_server.cpp"].decode()
    capture, source = cpp.index("polar_capture_goal()"), cpp.index("polar_goal_sourced_.begin(pose)")
    compute, finish, catch = cpp.index("->computeVelocityCommands("), cpp.index("polar_finish_goal"), cpp.index("catch")
    assert capture < source < compute < finish < catch
    assert cpp.count("polar_goal_sourced_.finish(") == 1
    assert "polar_goal_sourced_.finish(polar_request, pose, cmd_vel_2d, polar_goal.uuid)" in cpp
    assert cpp.index("polar_goal_sourced_.deactivate()") < cpp.index("action_server_->deactivate()")


def test_cancel_acceptance_is_recorded_inside_actual_cancel_callback(action_header):
    result = overlay.action_server_overlay(action_header).decode()
    assert "namespace polar_nav2_util" in result
    assert "polar_cancel_accepted_.insert(handle->get_goal_id())" in result
    assert result.index("polar_cancel_accepted_.insert") < result.index('debug_msg("Received request for goal cancellation")')
    assert "!current_handle_->is_canceling()" in result
    assert "!is_active(pending_handle_)" in result
    assert "get_current_goal_id() != token.uuid" in result


@pytest.mark.parametrize("site", ["  action_server_->activate();",
    "  try {\n    cmd_vel_2d =\n      controllers_[current_controller_]->computeVelocityCommands(",
    "      goal_checkers_[current_goal_checker_].get());\n    last_valid_cmd_time_ = now();"])
def test_ambiguous_or_missing_compute_anchor_rejected(originals, action_header, site):
    for replacement in ("", site + site):
        changed = dict(originals)
        changed["src/controller_server.cpp"] = changed["src/controller_server.cpp"].replace(site.encode(), replacement.encode())
        with pytest.raises(ValueError, match="anchor_mismatch"):
            overlay.controller_overlay(changed, action_header, b"ctx", b"parser")


@pytest.mark.parametrize("corrupt", ["source", "action", "server"])
def test_prepare_hash_failure_never_creates_output(tmp_path, monkeypatch, originals, action_header, corrupt):
    source, prefix, out = tmp_path / "upstream", tmp_path / "prefix", tmp_path / "owned"
    for name, raw in originals.items():
        p = source / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
    action = prefix / "include/nav2_util/simple_action_server.hpp"
    action.parent.mkdir(parents=True)
    action.write_bytes(action_header)
    server = prefix / "lib/nav2_controller/controller_server"
    server.parent.mkdir(parents=True)
    server.write_bytes(b"original executable")
    monkeypatch.setattr(overlay, "SOURCE_HASHES", {k: overlay.sha(v) for k, v in originals.items()})
    monkeypatch.setattr(overlay, "SIMPLE_ACTION_SERVER_SHA256", overlay.sha(action_header))
    monkeypatch.setattr(overlay, "ORIGINAL_SERVER_SHA256", overlay.sha(server.read_bytes()))
    {"source": source / "src/main.cpp", "action": action, "server": server}[corrupt].write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash_mismatch"):
        overlay.prepare(source, prefix, out)
    assert not out.exists()


def test_prepare_existing_output_rejected_before_read(tmp_path):
    out = tmp_path / "existing"
    out.mkdir()
    sentinel = out / "sentinel"
    sentinel.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="new_owned_directory"):
        overlay.prepare(tmp_path / "missing", tmp_path / "missing", out)
    assert sentinel.read_bytes() == b"preserve"


def test_context_v2_has_same_typed_source_and_no_synthetic_velocity():
    text = (ROOT / "rm_match/integrations/pb_goal_controller_context.hpp").read_text()
    assert '"polar.sim.pb-navigation-result.v2"' in text
    assert '"nav2_server_pb_pid_goal_v1"' in text
    assert '{"goal_uuid",uuid_text.str()}' in text
    assert 'j[k].type()!=pending_[k].type() || j[k]!=pending_[k]' in text
    assert 'end*1e-9-j["sim_time"].get<double>()>.5e-9' in text
    assert 'param<bool>(node,"polar_sourced.enabled",false)' in text
    assert 'if(v==stamp)found=true' in text
    assert text.count('output_->publish(message)') == 1
    assert 'vx_mps",v.linear.x' in text


CPP_PREFIX = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <memory>
#include <mutex>
#include <set>
#include <iostream>
namespace rclcpp_action {
using GoalUUID = std::array<uint8_t, 16>;
template<class T> struct ServerGoalHandle {
  GoalUUID uuid{}; bool active=true, canceling=false;
  bool is_active() const {return active;}
  bool is_canceling() const {return canceling;}
  GoalUUID get_goal_id() const {return uuid;}
};
}
template<class ActionT> class Server {
public:
  using Handle=rclcpp_action::ServerGoalHandle<ActionT>;
  mutable std::recursive_mutex update_mutex_;
  bool server_active_=true,stop_execution_=false,preempt_requested_=false;
  std::shared_ptr<Handle> current_handle_,pending_handle_;
  bool is_active(std::shared_ptr<Handle> h) const {return h && h->is_active();}
  rclcpp_action::GoalUUID get_current_goal_id() const {return current_handle_->get_goal_id();}
'''
CPP_SUFFIX = r'''
public:
  void accept_cancel() {std::lock_guard<std::recursive_mutex> lock(update_mutex_);
    polar_prune_cancel_ids_locked();polar_cancel_accepted_.insert(current_handle_->get_goal_id());}
};
int main() {
  Server<int> s;using H=Server<int>::Handle;
  auto a=std::make_shared<H>();a->uuid[0]=1;s.current_handle_=a;
  int publications=0;auto emit=[&](){++publications;};
  auto token=s.polar_capture_goal();assert(token.handle==a);
  assert(s.polar_finish_goal(token,emit));assert(publications==1);
  s.accept_cancel(); // Real accepted cancel recorded before ROS is_canceling changes.
  assert(!a->canceling);assert(!s.polar_finish_goal(token,emit));
  auto b=std::make_shared<H>();b->uuid[0]=2;s.current_handle_=b;
  assert(!s.polar_finish_goal(token,emit)); // Late old compute cannot borrow new UUID.
  auto next=s.polar_capture_goal();assert(next.handle==b);
  s.preempt_requested_=true;assert(!s.polar_finish_goal(next,emit));s.preempt_requested_=false;
  s.pending_handle_=a;assert(!s.polar_finish_goal(next,emit));s.pending_handle_.reset();
  b->canceling=true;assert(!s.polar_finish_goal(next,emit));b->canceling=false;
  b->active=false;assert(!s.polar_finish_goal(next,emit));b->active=true;
  s.server_active_=false;assert(!s.polar_finish_goal(next,emit));s.server_active_=true;
  s.stop_execution_=true;assert(!s.polar_finish_goal(next,emit));s.stop_execution_=false;
  b->uuid[0]=3;assert(!s.polar_finish_goal(next,emit));b->uuid[0]=2;
  assert(s.polar_finish_goal(next,emit));assert(publications==2);
  assert(!s.polar_finish_goal({},emit));assert(publications==2);
  std::cout<<"goal_gate_actual_cpp: accepted_cancel/late_compute/preempt/pending/inactive/stop/uuid/success passed\n";
}
'''


def test_actual_cpp_gate_interleavings(tmp_path):
    distro = os.environ.get("POLAR_GOAL_CPP_WSL_DISTRO")
    if sys.platform == "win32" and not distro:
        pytest.skip("explicit WSL CPU-only compiler opt-in required on Windows")
    directory = Path(os.environ.get("POLAR_GOAL_CPP_EVIDENCE_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "goal_gate.cpp"
    source.write_text(CPP_PREFIX + overlay.GOAL_GUARD + CPP_SUFFIX, encoding="utf8", newline="\n")
    executable = directory / "goal_gate"
    if distro:
        def linux(p):
            value = p.resolve().as_posix()
            return "/mnt/" + value[0].lower() + value[2:]
        prefix = ["wsl.exe", "-d", distro, "--"]
        compile_cmd = prefix + ["/usr/bin/g++", "-std=c++17", "-pthread", linux(source), "-o", linux(executable)]
        run_cmd = prefix + [linux(executable)]
    else:
        compiler = shutil.which("g++")
        if not compiler:
            pytest.skip("C++ compiler unavailable")
        compile_cmd = [compiler, "-std=c++17", "-pthread", str(source), "-o", str(executable)]
        run_cmd = [str(executable)]
    records = []
    for index, command in enumerate((compile_cmd, run_cmd)):
        completed = subprocess.run(command, capture_output=True, timeout=60)
        (directory / f"cpp-{index}.stdout").write_bytes(completed.stdout)
        (directory / f"cpp-{index}.stderr").write_bytes(completed.stderr)
        records.append(dict(command=command, exit_code=completed.returncode, reaped=True))
        (directory / "cpp-commands.json").write_text(json.dumps(records, indent=2) + "\n")
        assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert b"goal_gate_actual_cpp:" in completed.stdout
