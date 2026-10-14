#!/usr/bin/env python3
"""EXPERIMENTAL: bounded ROI/search-factor replay of the isolated corner body.

Requires a completed diagnose_pnp_factors run and an executed corner candidate.
Changes exactly one ROI/search parameter relative to that candidate reference;
retains all other constants and original PnP gates. Never edits or substitutes
the original native algorithm objects. Allowed padding: 12/20; axis end: .7/.9.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import shlex
import subprocess
import sys

from diagnose_pnp_factors import ROOT, SAVED, argv, digest, parse_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--factor-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True,
                        help="Existing experimental candidate output serving as this single-factor reference")
    parser.add_argument("--roi-padding", type=int, required=True, choices=(12, 20))
    parser.add_argument("--axis-end", type=float, default=0.7, choices=(0.7, 0.9))
    args = parser.parse_args()
    if sys.platform != "linux":
        raise ValueError("Run in Linux/WSL")
    build, factors, out = (p.resolve() for p in (args.build_root, args.factor_root, args.out))
    if out.exists():
        raise ValueError("Choose a fresh output directory")
    report = json.loads((factors / "DIAGNOSTIC_REPORT.json").read_text())
    if report["status"] != "executed" or not report["identity_equals_original_replay"]:
        raise ValueError("Completed unchanged-factor replay is required")
    if digest(build / "BUILD_MANIFEST.json") != report["build_manifest_sha256"]:
        raise ValueError("Factor/native build binding changed")
    binding_path = factors / "baseline/REPLAY_BINDING.json"
    if digest(binding_path) != report["baseline_binding_sha256"]:
        raise ValueError("Baseline binding changed")
    binding = json.loads(binding_path.read_text())
    reference_path = args.reference_root.resolve() / "DIAGNOSTIC_REPORT.json"
    reference = json.loads(reference_path.read_text())
    if reference["status"] != "executed" or reference["frame_sha256"] != report["saved_frame_sha256"]:
        raise ValueError("Executed reference on the same frame is required")
    reference_parameters = reference.get("parameters", {"roi_padding": 5, "axis_end": 0.7})
    changed = [name for name, value in {"roi_padding": args.roi_padding, "axis_end": args.axis_end}.items()
               if reference_parameters[name] != value]
    if len(changed) != 1:
        raise ValueError("Exactly one parameter must differ from the experimental reference")
    if args.axis_end == 0.9 and reference_parameters != {"roi_padding": 20, "axis_end": 0.7}:
        raise ValueError("Axis-end experiment requires fixed pad20/axis0.7 reference")
    reference_body = reference_path.parent / "experimental_corners.cpp"
    if digest(reference_body) != reference["source_copy_sha256"]:
        raise ValueError("Reference candidate source binding changed")
    cmake = build / "cmake"
    manifest = json.loads((build / "BUILD_MANIFEST.json").read_text())
    source_dir = Path(next(line.split("=", 1)[1] for line in
        (cmake / "CMakeCache.txt").read_text().splitlines()
        if line.startswith("rmcs_sim_operator_fov_SOURCE_DIR:STATIC=")))
    original = source_dir / "candidate/src/utility/math/corners_optimizor.cpp"
    original_hash = digest(original)
    source = original.read_text()
    marker = "    return; // @FIXME:"
    if source.count(marker) != 2 or source.count("namespace rmcs::util {") != 1:
        raise ValueError("Unexpected original disabled corner implementation")
    source = source.replace(marker, "    // EXPERIMENTAL: original unconditional return removed.")
    source = source.replace('"corners_optimizor.hpp"', '"utility/math/corners_optimizor.hpp"')
    source = source.replace("namespace rmcs::util {", "namespace rmcs::experimental {")
    pad_marker, axis_marker = "kPad           = 5.0;", "kAxisEnd       = 0.7;"
    if source.count(pad_marker) != 1 or source.count(axis_marker) != 1:
        raise ValueError("Unexpected original ROI/search constants")
    source = source.replace(pad_marker, f"kPad           = {args.roi_padding}.0;")
    source = source.replace(axis_marker, f"kAxisEnd       = {args.axis_end};")
    frozen_files = {source_dir / rel: expected for rel, expected in
                    manifest["input_identity"]["source_files"].items()}
    frozen_files.update({build / rel: expected for rel, expected in
                        manifest["input_identity"]["generated_sha256"].items()})
    config = build / "configs/simulation_autoaim.yaml"
    model = Path(json.loads(config.read_text())["detector"]["model_location"])
    model = model if model.is_absolute() else config.parent / model
    frozen_files.update({config: binding["config_sha256"], model: report["model_sha256"],
                        build / "bin/rmcs_sim_operator_fov": report["production_binary_sha256"]})
    for path, expected in frozen_files.items():
        if digest(path) != expected:
            raise ValueError("Frozen input changed: " + str(path))
    frame = factors / "baseline/saved_frame.bgr"
    if digest(frame) != report["saved_frame_sha256"]:
        raise ValueError("Saved frame changed")
    out.mkdir(parents=True)
    body = out / "experimental_corners.cpp"
    body.write_text(source)
    main_cpp = (SAVED / "inspect_saved_frame.cpp").read_text()
    main_cpp = main_cpp.replace("using namespace rmcs;", '#include "experimental_corners.cpp"\nusing namespace rmcs;', 1)
    main_cpp = main_cpp.replace("const auto result=d.detect(image);", r'''
 const auto raw=d.detect(image);auto result=raw;
 std::ofstream rawlog("RAW_MODEL_CORNERS.csv");rawlog<<std::setprecision(17);
 rawlog<<"index,genre,confidence,tl_x,tl_y,bl_x,bl_y,br_x,br_y,tr_x,tr_y\n";
 for(size_t i=0;i<raw.armors.size();++i){const auto& a=raw.armors[i];
  rawlog<<i<<","<<get_enum_name(a.genre)<<","<<a.confidence;
  for(auto p:std::array{a.tl,a.bl,a.br,a.tr})rawlog<<","<<p.x<<","<<p.y;
  rawlog<<"\n";
 }
 rawlog.close();if(!rawlog)throw std::runtime_error("raw corner log failed");
 rmcs::experimental::optimize_corners(image,result.armors);
 std::cout<<"experimental_refinement=isolated_body_roi_search_factor\n";
''')
    main_path = out / "inspect_corner_body.cpp"
    main_path.write_text(main_cpp)
    rows = json.loads((cmake / "compile_commands.json").read_text())
    row = next(r for r in rows if Path(r["file"]).resolve() == (build / "generated/main.cpp").resolve())
    obj, binary = out / "inspect_corner_body.o", out / "inspect_corner_body"
    command = argv(row)
    command[command.index("-o") + 1] = str(obj)
    command[command.index("-c") + 1] = str(main_path)
    command.insert(1, "-I" + str(build / "generated"))
    with (out / "compile.log").open("w") as log:
        subprocess.run(command, cwd=row["directory"], stdout=log, stderr=subprocess.STDOUT, check=True)
    objects = []
    for entry in binding["object_bindings"]:
        path = cmake / entry["object_relative_to_build"]
        if digest(path) != entry["sha256"]:
            raise ValueError("Original native object changed")
        objects.append(str(path))
    libraries = [line.split(" = ", 1)[1] for line in (cmake / "build.ninja").read_text().splitlines()
                 if line.startswith("  LINK_LIBRARIES = ")]
    if len(libraries) != 1:
        raise ValueError("Unexpected native link layout")
    with (out / "link.log").open("w") as log:
        subprocess.run([command[0], "-pthread", str(obj), *objects, *shlex.split(libraries[0]),
                        "-o", str(binary)], cwd=cmake, stdout=log, stderr=subprocess.STDOUT, check=True)
    with (out / "result.txt").open("w") as stdout, (out / "stderr.log").open("w") as stderr:
        subprocess.run([str(binary), str(config), str(frame), str(SAVED / "saved_frame_metadata.json")],
                       cwd=out, stdout=stdout, stderr=stderr, timeout=90, check=True)
    with (out / "RAW_MODEL_CORNERS.csv").open() as csv_file:
        raw = list(csv.DictReader(csv_file))
    if len(raw) != len(report["baseline"]["armors"]):
        raise ValueError("Model detection count changed")
    for r, expected in zip(raw, report["baseline"]["armors"]):
        if r["genre"] != expected["genre"] or float(r["confidence"]) != expected["confidence"]:
            raise ValueError("Raw model output changed")
        if any([float(r[f"{corner}_x"]), float(r[f"{corner}_y"])] != expected["corners_px"][corner]
               for corner in ("tl", "bl", "br", "tr")):
            raise ValueError("Raw model corners changed")
    for path, expected in frozen_files.items():
        if digest(path) != expected:
            raise ValueError("Original frozen input changed during experiment: " + str(path))
    for entry in binding["object_bindings"]:
        if digest(cmake / entry["object_relative_to_build"]) != entry["sha256"]:
            raise ValueError("Original native object changed during experiment")
    refined = parse_result(out / "result.txt")
    proxies = []
    for original_armor, refined_armor in zip(report["baseline"]["armors"], refined["armors"]):
        original_corners, refined_corners = original_armor["corners_px"], refined_armor["corners_px"]
        proxies.append({"genre": original_armor["genre"],
            "corner_displacement_from_raw_px": {corner: math.dist(original_corners[corner], refined_corners[corner])
                                                  for corner in original_corners},
            "raw_lengths_px": original_armor["lightbar_lengths_px"],
            "refined_lengths_px": refined_armor["lightbar_lengths_px"],
            "length_difference_abs_px": abs(refined_armor["lightbar_lengths_px"][0] - refined_armor["lightbar_lengths_px"][1]),
            "reprojection_residuals_px": [candidate["reprojection_error"] for candidate in refined_armor["candidates"]],
            "original_gate_accepted_candidate_count": sum(all(candidate[k] for k in
                ("depth_pass", "facing_pass", "pitch_pass")) for candidate in refined_armor["candidates"])})
    experiment = {"schema": "rmcs-experimental-corner-roi-factor-v1", "status": "executed",
        "scope": "New isolated corner-refinement candidate, not recovered T2 completion or production fix",
        "candidate_basis": "Original disabled corner body with only two unconditional returns removed in rmcs::experimental namespace",
        "parameters": {"roi_padding": args.roi_padding, "axis_end": args.axis_end},
        "reference_parameters": reference_parameters, "single_changed_factor_from_reference": changed[0],
        "reference_report_sha256": digest(reference_path),
        "reference_candidate_source_sha256": digest(reference_body),
        "reference_output_count": reference["refined"]["original_estimator_output_count"],
        "roi_or_constants_changed": True, "original_pnp_thresholds_changed": False,
        "ground_truth_sent_to_algorithm": False, "raw_model_matches_baseline": True,
        "model_inferences": 1, "source_original_sha256": original_hash,
        "source_copy_sha256": digest(body), "diagnostic_source_sha256": digest(main_path),
        "diagnostic_binary_sha256": digest(binary), "model_sha256": report["model_sha256"],
        "frame_sha256": digest(frame), "production_binary_sha256": report["production_binary_sha256"],
        "build_manifest_sha256": report["build_manifest_sha256"],
        "baseline_binding_sha256": report["baseline_binding_sha256"],
        "raw_model": report["baseline"], "refined": refined, "corner_proxies": proxies,
        "limitations": report["limitations"] + ["Original implementation is explicitly FIXME-disabled; enabling the copy is an unqualified experiment.",
            "No multi-frame or negative-case qualification. Do not adopt this candidate from one frame.",
            "Corner displacement, left/right length agreement and reprojection residuals are proxies, not ground-truth corner accuracy."]}
    (out / "DIAGNOSTIC_REPORT.json").write_text(json.dumps(experiment, indent=2) + "\n")
    print(json.dumps({"out": str(out), "raw_output_count": report["baseline"]["original_estimator_output_count"],
        "parameters": experiment["parameters"], "reference_parameters": reference_parameters,
        "experimental_output_count": experiment["refined"]["original_estimator_output_count"],
        "corner_proxies": proxies}, indent=2))


if __name__ == "__main__":
    main()
