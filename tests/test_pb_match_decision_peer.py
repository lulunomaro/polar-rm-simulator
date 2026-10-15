"""Pinned exec handover units, not a real BT build/tick or WSL qualification."""
import copy
import json
from pathlib import Path

import pytest

from rm_match.integrations import pb_match_decision_peer as module
from rm_match.deployment.decision_plugin import NAVIGATION_CAPABILITIES
from rm_match.platform_v2.contracts import ContractError


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
    return dict(path=str(path), sha256=module.sha(path))


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    root = tmp_path / "repo";root.mkdir()
    prep = root / "artifacts" / "prep";prep.mkdir(parents=True)
    source = root / "source.py";source.write_text("# pinned fixture source\n", encoding="utf-8")
    binary = prep / "runner"
    # Header-only inert bytes. No test executes or claims this is a real ELF.
    binary.write_bytes(b"\x7fELF\x02\x01" + b"\0" * 12 + (62).to_bytes(2, "little"))
    tree = prep / "tree.xml";tree.write_text('<root BTCPP_format="4"/>', encoding="utf-8")
    native_ref, xml_ref = (dict(path=str(p), sha256=module.sha(p)) for p in (binary, tree))
    env = write(prep / "ENV.json", dict(venv_python="unused-by-native-exec",
        process_environment=dict(LD_LIBRARY_PATH="/fixture/owned/lib")))
    source_manifest = write(prep / "SOURCE_IDENTITY.json", dict(
        schema="polar.pb.match-decision-source.v1", upstream=dict(module.UPSTREAM),
        overlay_xml_sha256=xml_ref["sha256"]))
    build = dict(schema=module.BUILD_SCHEMA, passed=True, upstream=dict(module.UPSTREAM),
        source_manifest_sha256=source_manifest["sha256"], source_manifest_ref=source_manifest,
        native=native_ref, xml=xml_ref, runtime_environment=dict(LD_LIBRARY_PATH="/fixture/owned/lib"),
        btcpp=dict(prefix="/fixture/bt4", version="4.6.2"),
        commands=[dict(argv=["cmake", "--build", "/fixture/build"], exit_code=0, reaped=True, elapsed_s=.1)],
        source_unchanged=True)
    build_ref = write(prep / "BUILD.json", build)
    context = dict(robot_id="red_sentry", episode=0, binding_epoch=1)
    spec = dict(schema=module.SPEC_SCHEMA, run_uuid="a" * 32, root_linux=str(root),
        out_linux=str(prep / "evidence"), namespace="/polar_match_" + "a" * 32 + "/red_sentry",
        domain_id=84, native_ref=native_ref, xml_ref=xml_ref, build_ref=build_ref, environment_ref=env,
        source_sha256={"source.py":module.sha(source)}, expected_generation=context,
        waypoints=dict(schema=module.WAYPOINT_SCHEMA, attack_offset_m=[1., 0.],
                       supply_offset_m=[0., 0.], yaw_offset_rad=0.),
        capabilities=copy.deepcopy(NAVIGATION_CAPABILITIES))
    path = prep / "SPEC.json";write(path, spec)
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "SOURCE_FILES", ("source.py",))
    monkeypatch.setattr(module.os, "access", lambda *_: True)
    return root, path, spec


def test_read_only_pins_return_fresh_spec_without_resources(pinned):
    _, path, spec = pinned
    before = path.read_bytes()
    actual, out = module.load_spec(path, module.sha(path))
    assert actual == spec and not out.exists() and path.read_bytes() == before
    actual["waypoints"]["attack_offset_m"][0] = 99.
    assert module.load_spec(path, module.sha(path))[0] == spec


@pytest.mark.parametrize("change", [
    lambda s: s.update(unreviewed_command=["curl", "https://invalid"]),
    lambda s: s.update(domain_id=True),
    lambda s: s.update(namespace="/another_run/red_sentry"),
    lambda s: s["expected_generation"].update(episode=False),
    lambda s: s["expected_generation"].update(binding_epoch=1.),
    lambda s: s["capabilities"].update(fire_authority="automatic"),
    lambda s: s["capabilities"].update(sensor_profile="own_referee_v1"),
    lambda s: s["waypoints"].update(attack_offset_m=[True, 0.]),
    lambda s: s["waypoints"].update(yaw_offset_rad=4.),
    lambda s: s["waypoints"].update(world_truth=[1., 2.]),
    lambda s: s["source_sha256"].update({"../escape.py":"c" * 64}),
    lambda s: s.update(source_sha256={}),
])
def test_untrusted_spec_scope_rejected_before_output(pinned, change):
    _, path, spec = pinned;change(spec);write(path, spec)
    with pytest.raises((ContractError, ValueError)):
        module.load_spec(path, module.sha(path))
    assert not Path(spec["out_linux"]).exists()


@pytest.mark.parametrize("target", ["spec", "native", "xml", "build", "environment", "source"])
def test_each_changed_raw_input_fails_closed_before_exec(pinned, target):
    root, path, spec = pinned;original_sha = module.sha(path)
    selected = (path if target == "spec" else root / "source.py" if target == "source"
                else Path(spec[target + "_ref"]["path"]))
    selected.write_bytes(selected.read_bytes() + b" ")
    with pytest.raises((ContractError, ValueError)):
        module.load_spec(path, original_sha)
    assert not Path(spec["out_linux"]).exists()


@pytest.mark.parametrize("change", [
    lambda b: b.update(passed=False), lambda b: b.update(source_unchanged=False),
    lambda b: b["native"].update(sha256="d" * 64),
    lambda b: b["xml"].update(sha256="d" * 64),
    lambda b: b["upstream"].update(btcpp_revision="d" * 40),
    lambda b: b["btcpp"].update(version="3.8"),
    lambda b: b["btcpp"].update(prefix="C:\\foreign\\bt4"),
    lambda b: b["btcpp"].update(prefix="/fixture/../bt4"),
])
def test_build_cannot_mix_another_elf_tree_or_upstream(pinned, change):
    _, path, spec = pinned
    build_path = Path(spec["build_ref"]["path"])
    build = json.loads(build_path.read_text());change(build)
    spec["build_ref"] = write(build_path, build);write(path, spec)
    with pytest.raises(ContractError):module.load_spec(path, module.sha(path))
    assert not Path(spec["out_linux"]).exists()


@pytest.mark.parametrize("change", [
    lambda b: b["commands"][0].update(exit_code=False),
    lambda b: b["commands"][0].update(exit_code=1),
    lambda b: b["commands"][0].update(exit_code=0.),
    lambda b: b["commands"][0].update(reaped=False),
    lambda b: b["commands"][0].update(reaped=1),
    lambda b: b["commands"][0].update(elapsed_s=True),
    lambda b: b["commands"][0].update(elapsed_s=-.01),
    lambda b: b["commands"][0].update(argv=[]),
    lambda b: b["commands"][0].update(argv=["cmake", False]),
    lambda b: b["commands"][0].pop("elapsed_s"),
    lambda b: b.update(commands=[False]),
    lambda b: b["runtime_environment"].update(LD_LIBRARY_PATH="/different/loader"),
    lambda b: b["runtime_environment"].update(EXTRA=1),
    lambda b: b.update(source_manifest_sha256="e" * 64),
])
def test_passed_label_cannot_hide_failed_command_or_mixed_build_metadata(pinned, change):
    _, path, spec = pinned;build_path = Path(spec["build_ref"]["path"])
    build = json.loads(build_path.read_text());change(build)
    spec["build_ref"] = write(build_path, build);write(path, spec)
    with pytest.raises(ContractError):module.load_spec(path, module.sha(path))
    assert not Path(spec["out_linux"]).exists()


def test_nonfinite_command_elapsed_rejected_even_when_json_hash_is_repinned(pinned):
    _, path, spec = pinned;build_path = Path(spec["build_ref"]["path"])
    build = json.loads(build_path.read_text());build["commands"][0]["elapsed_s"] = float("nan")
    build_path.write_text(json.dumps(build), encoding="utf-8")
    spec["build_ref"]["sha256"] = module.sha(build_path);write(path, spec)
    with pytest.raises(ValueError):module.load_spec(path, module.sha(path))


def test_changed_source_manifest_rejected_before_resources(pinned):
    _, path, spec = pinned
    build = json.loads(Path(spec["build_ref"]["path"]).read_text())
    source = Path(build["source_manifest_ref"]["path"])
    source.write_bytes(source.read_bytes() + b" ")
    with pytest.raises(ContractError, match="reference_changed"):
        module.load_spec(path, module.sha(path))
    assert not Path(spec["out_linux"]).exists()


@pytest.mark.parametrize("values", [dict(PYTHONPATH="/foreign"), dict(PYTHONHOME="/foreign"),
    dict(SDK_CREDENTIAL="never-a-real-credential"), dict(LD_LIBRARY_PATH=True)])
def test_environment_is_pinned_data_not_script_or_credentials(pinned, values):
    _, path, spec = pinned
    spec["environment_ref"] = write(Path(spec["environment_ref"]["path"]),
        dict(process_environment=values))
    write(path, spec)
    with pytest.raises(ContractError):module.load_spec(path, module.sha(path))


def test_duplicate_json_key_and_reused_output_are_not_accepted(pinned):
    _, path, spec = pinned
    raw = path.read_text();path.write_text(raw[:-1] + ',"domain_id":84}', encoding="utf-8")
    with pytest.raises(ValueError):module.load_spec(path, module.sha(path))
    write(path, spec);Path(spec["out_linux"]).mkdir()
    with pytest.raises(ContractError, match="fresh_output"):
        module.load_spec(path, module.sha(path))


def test_symlink_reference_rejected_even_with_matching_bytes(pinned):
    _, path, spec = pinned;link = path.parent / "runner-link"
    try:link.symlink_to(spec["native_ref"]["path"])
    except OSError:pytest.skip("symlink permission unavailable on this Windows account")
    spec["native_ref"]["path"] = str(link);write(path, spec)
    with pytest.raises(ContractError, match="unaliased"):
        module.load_spec(path, module.sha(path))


def test_fixed_exec_argv_env_and_no_prepare_tick_in_python(pinned, monkeypatch):
    root, path, spec = pinned;calls = []
    monkeypatch.setattr(module, "_linux_host", lambda: True)
    monkeypatch.setenv("PYTHONPATH", "/foreign")
    monkeypatch.setenv("POLAR_SIM_ADMISSION_CREDENTIAL", "unit-placeholder-not-a-secret")
    monkeypatch.setattr(module.os, "chdir", lambda p: calls.append(("cwd", p)))
    class Exec(Exception):pass
    def fake_exec(native, argv, env):
        calls.append((native, argv, env));raise Exec
    monkeypatch.setattr(module.os, "execve", fake_exec)
    expected_sha = module.sha(path)
    with pytest.raises(Exec):module.execute(path, expected_sha)
    assert calls[0] == ("cwd", root)
    native, argv, env = calls[1]
    assert native == spec["native_ref"]["path"]
    assert argv == [native, "--spec", str(path), "--sha256", expected_sha]
    assert "PYTHONPATH" not in env and "POLAR_SIM_ADMISSION_CREDENTIAL" not in env
    assert env["LD_LIBRARY_PATH"] == "/fixture/owned/lib"
    assert Path(spec["out_linux"]).is_dir() and list(Path(spec["out_linux"]).iterdir()) == []


def test_handover_rechecks_inputs_and_failure_does_not_exec(pinned, monkeypatch):
    _, path, spec = pinned;calls = []
    monkeypatch.setattr(module, "_linux_host", lambda: True)
    original = module._environment
    count = 0
    def change_after_check(ref):
        nonlocal count
        result = original(ref);count += 1
        if count == 2:
            selected = Path(spec["xml_ref"]["path"])
            selected.write_bytes(selected.read_bytes() + b"<!-- changed before exec -->")
        return result
    monkeypatch.setattr(module, "_environment", change_after_check)
    monkeypatch.setattr(module.os, "execve", lambda *a: calls.append(a))
    with pytest.raises(ContractError, match="reference_changed"):
        module.execute(path, module.sha(path))
    assert not calls and not Path(spec["out_linux"]).exists()
