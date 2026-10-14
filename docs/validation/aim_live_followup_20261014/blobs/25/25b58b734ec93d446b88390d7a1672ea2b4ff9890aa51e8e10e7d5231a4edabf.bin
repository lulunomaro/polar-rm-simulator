#!/usr/bin/env python3
"""Link separately bound original/contour-overlay diagnostics; compare real frames.

All native processes finish before isolated offline geometry is read. Source,
objects, model/config and production ELF remain unchanged. No new clean build.
"""
import argparse
import json
import math
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

from diagnose_pnp_factors import ROOT,SAVED,argv,digest,parse_result


def parse(path):
    r=parse_result(path);r["native_poses"]=[]
    for line in path.read_text().splitlines():
        if line.startswith("native_pose "):
            r["native_poses"].append({k:float(v) for k,v in re.findall(r"(\w+)=([-+\d.eE]+)",line)})
    return r


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--build-root",type=Path,required=True)
    ap.add_argument("--binding",type=Path,required=True,help="Existing baseline REPLAY_BINDING.json")
    ap.add_argument("--frame-root",type=Path,help="Completed render-holdout directory; omit for saved-frame development test")
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--overlay",type=Path,default=ROOT/"operator_native/runtime/overlays/corners_contour_v1.cpp")
    ap.add_argument("--reuse-diagnostics",type=Path,help="Reuse exact bound diagnostic ELFs from a prior successful comparison")
    args=ap.parse_args()
    if sys.platform!="linux":raise ValueError("Run native diagnostics in Linux/WSL")
    build,out,overlay=args.build_root.resolve(),args.out.resolve(),args.overlay.resolve()
    candidate_name=overlay.stem.removeprefix("corners_")
    if out.exists():raise ValueError("Choose a fresh output directory")
    manifest_path=build/"BUILD_MANIFEST.json";manifest=json.loads(manifest_path.read_text())
    if manifest["status"]!="native_build_succeeded" or not manifest["full_clean_compile"]:raise ValueError("Clean successful build required")
    binding=json.loads(args.binding.read_text());cmake=build/"cmake"
    rows=json.loads((cmake/"compile_commands.json").read_text())
    source=Path(next(line.split("=",1)[1] for line in (cmake/"CMakeCache.txt").read_text().splitlines()
                     if line.startswith("rmcs_sim_operator_fov_SOURCE_DIR:STATIC=")))
    frozen={source/rel:expected for rel,expected in manifest["input_identity"]["source_files"].items()}
    frozen.update({build/rel:expected for rel,expected in manifest["input_identity"]["generated_sha256"].items()})
    config=build/"configs/simulation_autoaim.yaml";model=Path(json.loads(config.read_text())["detector"]["model_location"])
    model=model if model.is_absolute() else config.parent/model
    frozen.update({config:binding["config_sha256"],model:binding["verified_bindings"]["model_sha256"],
                   build/"bin/rmcs_sim_operator_fov":binding["production_binary_sha256"],
                   manifest_path:digest(manifest_path),overlay:digest(overlay)})
    for p,h in frozen.items():
        if digest(p)!=h:raise ValueError("Bound input changed: "+str(p))
    if args.frame_root:
        frame_root=args.frame_root.resolve()
        inputs=json.loads((frame_root/"ALGORITHM_INPUTS.json").read_text())
        for entry in inputs:
            for key in ("frame","metadata"):
                path=(frame_root/entry[key]).resolve()
                if not path.is_relative_to(frame_root) or digest(path)!=entry[key+"_sha256"]:raise ValueError("Holdout input binding failed")
    else:
        frame_root=args.binding.resolve().parent
        inputs=[{"name":"saved_development","frame":"saved_frame.bgr","metadata":str(SAVED/"saved_frame_metadata.json")}]
        if digest(frame_root/"saved_frame.bgr")!=binding["frame_sha256"]:raise ValueError("Saved frame changed")
    out.mkdir(parents=True)
    main_cpp=(SAVED/"inspect_saved_frame.cpp").read_text()
    anchor='std::cout<<"original_estimator_output_count="<<estimator.estimate_armor(result.armors,image).size()<<"\\n";'
    replacement=r'''const auto estimated=estimator.estimate_armor(result.armors,image);
 std::cout<<"original_estimator_output_count="<<estimated.size()<<"\n";
 for(const auto& p:estimated){const auto pos=p.translation.make<Eigen::Vector3d>();const auto rot=p.orientation.make<Eigen::Quaterniond>();
  std::cout<<"native_pose id="<<p.id<<" x="<<pos.x()<<" y="<<pos.y()<<" z="<<pos.z()<<" qw="<<rot.w()<<" qx="<<rot.x()<<" qy="<<rot.y()<<" qz="<<rot.z()<<"\n";
 }
'''
    if main_cpp.count(anchor)!=1:raise ValueError("Unexpected existing inspector layout")
    main_path=out/"inspect_overlay.cpp";main_path.write_text(main_cpp.replace(anchor,replacement))
    reused=None
    if args.reuse_diagnostics:
        reused=json.loads((args.reuse_diagnostics/"COMPARISON_REPORT.json").read_text())
        required={"overlay_sha256":digest(overlay),"diagnostic_main_sha256":digest(main_path),
                  "build_manifest_sha256":digest(manifest_path),"model_sha256":digest(model),
                  "binding_sha256":digest(args.binding),"original_native_binary_sha256":binding["production_binary_sha256"]}
        if reused["status"]!="executed" or any(reused[k]!=v for k,v in required.items()):raise ValueError("Reused diagnostic binding changed")
        for mode,h in reused["diagnostic_binaries_sha256"].items():
            if digest(args.reuse_diagnostics/("inspect_"+mode))!=h:raise ValueError("Reused diagnostic ELF changed")
    main_row=next(r for r in rows if Path(r["file"]).resolve()==(build/"generated/main.cpp").resolve())
    corner_row=next(r for r in rows if Path(r["file"]).name=="corners_optimizor.cpp")
    def compile_source(row,path,obj,name):
        if reused:return argv(row)[0]
        cmd=argv(row);cmd[cmd.index("-c")+1]=str(path);cmd[cmd.index("-o")+1]=str(obj)
        cmd.insert(1,"-I"+str(build/"generated"))
        with(out/(name+".log")).open("w") as log:subprocess.run(cmd,cwd=row["directory"],stdout=log,stderr=subprocess.STDOUT,check=True)
        return cmd[0]
    main_obj=out/"inspect_overlay.o";overlay_obj=out/"corners_contour_v1.o"
    compiler=compile_source(main_row,main_path,main_obj,"compile_main")
    compile_source(corner_row,overlay,overlay_obj,"compile_overlay")
    corner_args=argv(corner_row);corner_object=Path(corner_args[corner_args.index("-o")+1])
    corner_object=corner_object if corner_object.is_absolute() else Path(corner_row["directory"])/corner_object
    objects=[]
    for entry in binding["object_bindings"]:
        p=cmake/entry["object_relative_to_build"]
        if digest(p)!=entry["sha256"]:raise ValueError("Native object changed")
        objects.append(p)
    libs=[line.split(" = ",1)[1] for line in (cmake/"build.ninja").read_text().splitlines() if line.startswith("  LINK_LIBRARIES = ")]
    if len(libs)!=1:raise ValueError("Unexpected link layout")
    binaries={}
    for mode in ("original",candidate_name):
        native_objects=[str(p) for p in objects if mode=="original" or p.resolve()!=corner_object.resolve()]
        if mode!="original":native_objects.append(str(overlay_obj))
        binary=out/("inspect_"+mode)
        if reused:shutil.copyfile(args.reuse_diagnostics/("inspect_"+mode),binary)
        else:
            with(out/("link_"+mode+".log")).open("w") as log:
                subprocess.run([compiler,"-pthread",str(main_obj),*native_objects,*shlex.split(libs[0]),"-o",str(binary)],
                               cwd=cmake,stdout=log,stderr=subprocess.STDOUT,check=True)
        binaries[mode]=binary
    measurements=[]
    for entry in inputs:
        case_out=out/entry["name"];case_out.mkdir()
        item={"name":entry["name"],"frame_sha256":digest(frame_root/entry["frame"]),"results":{}}
        for mode,binary in binaries.items():
            result_path=case_out/(mode+".txt")
            with result_path.open("w") as stdout,(case_out/(mode+".stderr.log")).open("w") as stderr:
                subprocess.run([str(binary),str(config),str(frame_root/entry["frame"]),str(frame_root/entry["metadata"])],
                               cwd=case_out,stdout=stdout,stderr=stderr,timeout=90,check=True)
            item["results"][mode]=parse(result_path)
        baseline_labels=[(a["genre"],a["confidence"]) for a in item["results"]["original"]["armors"]]
        item["confidence_and_genre_preserved_for_retained_armors"]=all(
            (a["genre"],a["confidence"]) in baseline_labels for a in item["results"][candidate_name]["armors"])
        measurements.append(item);print(entry["name"],{m:r["original_estimator_output_count"] for m,r in item["results"].items()},flush=True)
    # Native inference is complete. Only this offline evaluator reads truth.
    if args.frame_root:
        truth=json.loads((frame_root/"OFFLINE_EVALUATION_TRUTH.json").read_text())
        truth_by_name={v["name"]:v for v in truth}
        for item in measurements:
            reference=truth_by_name[item["name"]];item["offline_evaluation"]={"negative":reference["negative"],"modes":{}}
            for mode,result in item["results"].items():
                evaluation={"detected_armors":result["armor_count"],"native_poses":len(result["native_poses"])}
                if reference["negative"]:evaluation["false_positive_pose_count"]=len(result["native_poses"])
                elif result["armors"]:
                    # Controlled one-target scene; choose the nearest armor
                    # solely in the evaluator after algorithms have exited.
                    expected=reference["source_shape_corners_px"]
                    armor=min(result["armors"],key=lambda a:sum(math.dist(a["corners_px"][k],p)**2 for k,p in zip(("tl","bl","br","tr"),expected)))
                    evaluation["corner_rmse_px"]=math.sqrt(sum(math.dist(armor["corners_px"][k],p)**2 for k,p in zip(("tl","bl","br","tr"),expected))/4)
                    if result["native_poses"]:
                        p=result["native_poses"][0];evaluation["position_error_m"]=math.dist([p["x"],p["y"],p["z"]],reference["native_frame_center_m"])
                item["offline_evaluation"]["modes"][mode]=evaluation
    for p,h in frozen.items():
        if digest(p)!=h:raise ValueError("Bound input changed during run: "+str(p))
    for entry in binding["object_bindings"]:
        if digest(cmake/entry["object_relative_to_build"])!=entry["sha256"]:raise ValueError("Original object changed during run")
    report={"schema":"rmcs-contour-overlay-comparison-v1","status":"executed","measurements":measurements,
        "original_native_binary_sha256":binding["production_binary_sha256"],"model_sha256":digest(model),
        "overlay_sha256":digest(overlay),"diagnostic_main_sha256":digest(main_path),
        "diagnostic_binaries_sha256":{m:digest(b) for m,b in binaries.items()},"build_manifest_sha256":digest(manifest_path),
        "binding_sha256":digest(args.binding),"native_objects_original_and_unchanged":True,
        "original_corner_object_replaced_only_in_candidate_diagnostic":True,"original_thresholds_unchanged":True,
        "candidate_name":candidate_name,
        "model_confidence_unchanged":all(m["confidence_and_genre_preserved_for_retained_armors"] for m in measurements),
        "model_inferences":len(inputs)*2,"algorithm_receives_truth":False,
        "truth_read_only_after_native_processes_exit":True,"full_tracker_qualified":False}
    if reused:report["reused_diagnostic_report_sha256"]=digest(args.reuse_diagnostics/"COMPARISON_REPORT.json")
    (out/"COMPARISON_REPORT.json").write_text(json.dumps(report,indent=2)+"\n")


if __name__=="__main__":main()
