#!/usr/bin/env python3
"""Bounded native saved-frame diagnosis; run in Linux against a clean Ninja build.

First executes the existing unchanged replay helper, then links a separate
diagnostic main to the same bound native objects. Five runs: identity, two gamma
values, and two Gaussian sigmas. No model/source/config/threshold edits and no
geometric truth is supplied. Image transforms are diagnostic only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SAVED = ROOT / "docs/validation/pnp_saved_frame_20261013"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def argv(row):
    return list(row.get("arguments") or shlex.split(row["command"]))


def parse_result(path):
    result = {"armors": [], "candidates": []}
    armor = None
    for line in Path(path).read_text().splitlines():
        if line.startswith("candidate="):
            fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
            numeric = ("candidate", "z", "back_dot", "pitch_degrees",
                       "expected_pitch_degrees", "pitch_delta_degrees",
                       "reprojection_error", "depth_pass", "facing_pass", "pitch_pass")
            candidate = {k: float(fields[k]) for k in numeric}
            candidate["reject_reasons"] = [k.removesuffix("_pass") for k in
                ("depth_pass", "facing_pass", "pitch_pass") if not candidate[k]]
            result["candidates"].append(candidate)
            if armor is not None:
                armor.setdefault("candidates", []).append(candidate)
        elif "=" in line:
            key, value = line.split("=", 1)
            if key == "armors":
                result["armor_count"] = int(value)
            elif key == "armor_genre":
                armor = {"genre": value, "corners_px": {}}
                result["armors"].append(armor)
            elif armor is not None and key in ("tl", "bl", "br", "tr"):
                armor["corners_px"][key] = [float(x) for x in value.split(",")]
            elif armor is not None and key in ("armor_color", "confidence", "original_robust_pnp_result"):
                armor[key] = value if key == "armor_color" else float(value)
            else:
                result[key] = float(value) if re.fullmatch(r"[-+\d.eE]+", value) else value
    for armor in result["armors"]:
        corners = armor["corners_px"]
        armor["lightbar_lengths_px"] = [math.dist(corners[a], corners[b])
            for a, b in (("tl", "bl"), ("tr", "br"))]
    return result


def diagnostic_source():
    source = (SAVED / "inspect_saved_frame.cpp").read_text()
    source = source.replace('#include <opencv2/calib3d.hpp>',
        '#include <opencv2/calib3d.hpp>\n#include <opencv2/imgproc.hpp>\n'
        '#include "utility/math/corners_optimizor.hpp"')
    source = source.replace("if(argc!=4)return 1;", "if(argc!=7)return 1;")
    anchor = "const auto result=d.detect(image);"
    replacement = r'''
 const std::string operation=argv[4]; const double factor=std::stod(argv[5]);
 if(operation=="gamma") {
  cv::Mat lut(1,256,CV_8U);
  for(int i=0;i<256;++i)lut.at<unsigned char>(i)=cv::saturate_cast<unsigned char>(255*std::pow(i/255.0,factor));
  cv::LUT(image,lut,image);
 } else if(operation=="gaussian") {
  cv::GaussianBlur(image,image,cv::Size(0,0),factor,factor,cv::BORDER_REFLECT_101);
 } else if(operation!="identity")throw std::runtime_error("unknown experiment");
 std::ofstream pixels(argv[6],std::ios::binary);pixels.write(reinterpret_cast<const char*>(image.data),image.total()*image.elemSize());pixels.close();
 if(!pixels)throw std::runtime_error("processed frame write failed");
 std::cout<<"image_operation="<<operation<<"\nimage_factor="<<factor<<"\n";
 const auto result=d.detect(image);
 auto check=result.armors;util::optimize_corners(image,check);bool unchanged=true;
 for(size_t i=0;i<check.size();++i){const auto& a=check[i];const auto& b=result.armors[i];
  unchanged=unchanged && a.tl==b.tl && a.bl==b.bl && a.br==b.br && a.tr==b.tr;
  auto bar=Lightbar2d{.color=a.color,.upper=Point2d{a.tl.x,a.tl.y},.lower=Point2d{a.bl.x,a.bl.y}};
  auto prior=bar;util::optimize_corners(image,bar);
  unchanged=unchanged && bar.upper.x==prior.upper.x && bar.upper.y==prior.upper.y && bar.lower.x==prior.lower.x && bar.lower.y==prior.lower.y;
 }
 std::cout<<"optimizer_overloads_unchanged="<<unchanged<<"\noptimizer_sample_count="<<check.size()<<"\n";
 if(!unchanged)throw std::runtime_error("unexpected optimizer behavior");
'''
    if source.count(anchor) != 1:
        raise ValueError("Unexpected existing diagnostic source layout")
    return source.replace(anchor, replacement)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Fresh output directory")
    args = parser.parse_args()
    if sys.platform != "linux":
        raise ValueError("Run this tool using Linux/WSL Python; the native binary is ELF")
    build, out = args.build_root.resolve(), args.out.resolve()
    if out.exists():
        raise ValueError("Choose a fresh --out directory")
    out.mkdir(parents=True)
    baseline = out / "baseline"
    # Existing helper validates full-clean manifest, source/header/generated input,
    # model/config, spec, ELF, and records each object's hash before and after use.
    with (out / "baseline_replay.log").open("w") as log:
        subprocess.run([sys.executable, str(SAVED / "reproduce_saved_frame.py"),
            "--build-root", str(build), "--out", str(baseline), "--run"],
            stdout=log, stderr=subprocess.STDOUT, check=True)
    binding = json.loads((baseline / "REPLAY_BINDING.json").read_text())
    cmake = build / "cmake"
    manifest_path = build / "BUILD_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    source_dirs = [line.split("=", 1)[1] for line in (cmake / "CMakeCache.txt").read_text().splitlines()
                   if line.startswith("rmcs_sim_operator_fov_SOURCE_DIR:STATIC=")]
    if len(source_dirs) != 1:
        raise ValueError("Unexpected original source root")
    original_source = Path(source_dirs[0])
    frozen_files = {original_source / rel: expected
        for rel, expected in manifest["input_identity"]["source_files"].items()}
    frozen_files.update({build / rel: expected
        for rel, expected in manifest["input_identity"]["generated_sha256"].items()})
    runtime_config = build / "configs/simulation_autoaim.yaml"
    model = Path(json.loads(runtime_config.read_text())["detector"]["model_location"])
    if not model.is_absolute():
        model = runtime_config.parent / model
    frozen_files.update({runtime_config: binding["config_sha256"],
        build / "configs/simulation_executor.yaml": binding["verified_bindings"]["executor_config_sha256"],
        model: binding["verified_bindings"]["model_sha256"],
        original_source / "RECOVERY_MANIFEST.json": manifest["input_identity"]["recovery_manifest_sha256"],
        manifest_path: digest(manifest_path), build / "operator_source.local.json": digest(build / "operator_source.local.json")})
    rows = json.loads((cmake / "compile_commands.json").read_text())
    row = next(r for r in rows if Path(r["file"]).resolve() == (build / "generated/main.cpp").resolve())
    source, obj, binary = out / "inspect_factors.cpp", out / "inspect_factors.o", out / "inspect_factors"
    source.write_text(diagnostic_source())
    command = argv(row)
    command[command.index("-o") + 1] = str(obj)
    command[command.index("-c") + 1] = str(source)
    command.insert(1, "-I" + str(build / "generated"))
    with (out / "compile.log").open("w") as log:
        subprocess.run(command, cwd=row["directory"], stdout=log, stderr=subprocess.STDOUT, check=True)
    objects = []
    for entry in binding["object_bindings"]:
        path = cmake / entry["object_relative_to_build"]
        if digest(path) != entry["sha256"]:
            raise ValueError("Bound native object changed")
        objects.append(str(path))
    libs = [line.split(" = ", 1)[1] for line in (cmake / "build.ninja").read_text().splitlines()
            if line.startswith("  LINK_LIBRARIES = ")]
    if len(libs) != 1:
        raise ValueError("Unexpected native link layout")
    with (out / "link.log").open("w") as log:
        subprocess.run([command[0], "-pthread", str(obj), *objects, *shlex.split(libs[0]),
            "-o", str(binary)], cwd=cmake, stdout=log, stderr=subprocess.STDOUT, check=True)
    cases = []
    for operation, factor in (("identity", 1), ("gamma", 0.8), ("gamma", 1.2),
                              ("gaussian", 0.5), ("gaussian", 1.0)):
        name = f"{operation}_{factor}"
        text_path = out / f"{name}.txt"
        pixels_path = out / f"{name}.bgr"
        with text_path.open("w") as stdout, (out / f"{name}.stderr.log").open("w") as stderr:
            subprocess.run([str(binary), str(build / "configs/simulation_autoaim.yaml"),
                str(baseline / "saved_frame.bgr"), str(SAVED / "saved_frame_metadata.json"),
                operation, str(factor), str(pixels_path)], cwd=out, stdout=stdout, stderr=stderr, timeout=90, check=True)
        cases.append({"case": name, "operation": operation, "factor": factor,
            "image_sha256": digest(pixels_path), "image_file": pixels_path.name,
            "result_sha256": digest(text_path), "result": parse_result(text_path)})
    original = parse_result(baseline / "result.txt")
    identity = cases[0]["result"]
    equivalent = all(original[k] == identity[k] for k in
        ("armors", "candidates", "original_estimator_output_count"))
    if not equivalent:
        raise ValueError("Identity experiment changed native baseline results")
    if cases[0]["image_sha256"] != binding["frame_sha256"]:
        raise ValueError("Identity experiment changed image bytes")
    for entry in binding["object_bindings"]:
        if digest(cmake / entry["object_relative_to_build"]) != entry["sha256"]:
            raise ValueError("Native object changed during experiments")
    if digest(build / "bin/rmcs_sim_operator_fov") != binding["production_binary_sha256"]:
        raise ValueError("Production ELF changed")
    for path, expected in frozen_files.items():
        if digest(path) != expected:
            raise ValueError("Bound source/model/config/generated input changed: " + str(path))
    report = {"schema": "rmcs-bounded-pnp-factors-v1", "status": "executed",
        "baseline": original, "identity_equals_original_replay": equivalent,
        "model_sha256": binding["verified_bindings"]["model_sha256"],
        "saved_frame_sha256": binding["frame_sha256"],
        "production_binary_sha256": binding["production_binary_sha256"],
        "diagnostic_binary_sha256": digest(binary), "diagnostic_source_sha256": digest(source),
        "build_manifest_sha256": digest(manifest_path), "unchanged_input_binding_count": len(frozen_files),
        "baseline_binding_sha256": digest(baseline / "REPLAY_BINDING.json"),
        "thresholds_modified": False, "ground_truth_sent_to_algorithm": False,
        "source_files_modified": False, "model_inferences": 6,
        "optimizer_no_op_confirmed": identity["optimizer_sample_count"] > 0 and
            all(c["result"]["optimizer_overloads_unchanged"] == 1 for c in cases),
        "cases": cases,
        "limitations": ["One saved synthetic camera frame; no physical camera calibration or dataset generalization.",
            "Gamma/blur are single-factor diagnostic transforms, not deployment or baseline changes.",
            "Native object correspondence to production ELF is not independently proven; exact object hashes are in baseline binding.",
            "No full tracker, controller, physics rollout, training or hardware qualification."]}
    (out / "DIAGNOSTIC_REPORT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"out": str(out), "identity_equals_original_replay": equivalent,
        "optimizer_no_op_confirmed": report["optimizer_no_op_confirmed"],
        "outputs": {c["case"]: c["result"]["original_estimator_output_count"] for c in cases}}, indent=2))


if __name__ == "__main__":
    main()
