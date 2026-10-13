#!/usr/bin/env python3
"""Build a separate, one-frame diagnostic using a completed portable Ninja build.
Existing object-file provenance is not independently verified; every hash is recorded.

No existing source, objects, production binary, configs, thresholds or manifests
are changed. Execution requires --run. No physics, renderer or hardware is used.
Use the same library environment that successfully starts your native build.
"""
from pathlib import Path
import argparse,gzip,hashlib,json,shlex,subprocess
ROOT=Path(__file__).resolve().parent

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--build-root',type=Path,required=True,help='Completed build_portable.py output directory, containing cmake and configs')
 ap.add_argument('--out',type=Path,required=True,help='Fresh diagnostic output directory')
 ap.add_argument('--run',action='store_true',help='Run exactly one saved-frame inference after building the diagnostic')
 args=ap.parse_args();build=args.build_root.resolve();out=args.out.resolve()
 if out.exists():raise ValueError('Choose a fresh --out directory')
 manifest=json.loads((build/'BUILD_MANIFEST.json').read_text());identity=manifest['input_identity']['algorithm_identity']
 if manifest['status']!='native_build_succeeded' or not manifest['full_clean_compile']:raise ValueError('A successful complete native build is required')
 if identity['base_commit']!='079a7fe29966fe467630f0c4ab8c3ed075edaad9' or identity['patch_sha256']!='ea1235cfd11018bde08b40a43f3aba072a0870a8906f40ff35255cfdd16e4c7d':raise ValueError('Expected recovered T2 source identity required')
 production=build/'bin/rmcs_sim_operator_fov';before=digest(production)
 if before!=manifest['binary_sha256']:raise ValueError('Production binary no longer matches build manifest')
 cmake=build/'cmake';ninja=cmake/'build.ninja'
 if not ninja.is_file():raise ValueError('This bounded replay helper requires a portable build configured with CMAKE_GENERATOR=Ninja')
 rows=json.loads((cmake/'compile_commands.json').read_text())
 input_identity=manifest['input_identity']
 source_dirs=[l.split('=',1)[1] for l in (cmake/'CMakeCache.txt').read_text().splitlines() if l.startswith('rmcs_sim_operator_fov_SOURCE_DIR:STATIC=')]
 if len(source_dirs)!=1:raise ValueError('Unable to identify original runtime source directory')
 source=Path(source_dirs[0]).resolve()
 if digest(source/'RECOVERY_MANIFEST.json')!=input_identity['recovery_manifest_sha256']:raise ValueError('Recovered-source manifest changed')
 for rel,expected in input_identity['source_files'].items():
  file=(source/rel).resolve()
  if not file.is_relative_to(source) or digest(file)!=expected:raise ValueError('Source/header binding failed: '+rel)
 for rel,expected in input_identity['generated_sha256'].items():
  file=(build/rel).resolve()
  if not file.is_relative_to(build) or digest(file)!=expected:raise ValueError('Generated input binding failed: '+rel)
 spec=json.loads((build/'operator_source.local.json').read_text())
 if spec['frozen_build']['manifest_sha256']!=digest(build/'BUILD_MANIFEST.json'):raise ValueError('Spec/build-manifest binding failed')
 autoaim=build/'configs/simulation_autoaim.yaml';executor=build/'configs/simulation_executor.yaml'
 if digest(autoaim)!=spec['sha256']['autoaim_config'] or digest(executor)!=spec['sha256']['executor_yaml']:raise ValueError('Runtime configuration changed')
 config=json.loads(autoaim.read_text());model=Path(config['detector']['model_location']);model=model if model.is_absolute() else autoaim.parent/model
 if digest(model)!=input_identity['model_sha256'] or digest(model)!=spec['model_sha256']:raise ValueError('Model binding failed')
 mainrows=[r for r in rows if Path(r['file']).resolve()==(build/'generated/main.cpp').resolve()]
 if len(mainrows)!=1 or len(rows)!=29:raise ValueError('Unexpected translation-unit layout')
 def argv(row):return list(row.get('arguments') or shlex.split(row['command']))
 row=mainrows[0];command=argv(row)
 out.mkdir(parents=True)
 diagnostic_object=out/'inspect_saved_frame.o';binary=out/'inspect_saved_frame'
 command[command.index('-o')+1]=str(diagnostic_object)
 command[command.index('-c')+1]=str(ROOT/'inspect_saved_frame.cpp')
 command.insert(1,'-I'+str(build/'generated'))
 with (out/'compile.log').open('w') as log:subprocess.run(command,cwd=row['directory'],stdout=log,stderr=subprocess.STDOUT,check=True)
 objects=[];object_bindings=[]
 for r in rows:
  if r is row:continue
  a=argv(r);p=Path(a[a.index('-o')+1]);p=p if p.is_absolute() else Path(r['directory'])/p
  if not p.is_file():raise ValueError('Native object missing: '+str(p))
  objects.append(str(p));object_bindings.append({'object_relative_to_build':str(p.relative_to(cmake)), 'sha256':digest(p)})
 libs=[l.split(' = ',1)[1] for l in ninja.read_text().splitlines() if l.startswith('  LINK_LIBRARIES = ')]
 if len(libs)!=1:raise ValueError('Unexpected native link-library layout')
 link=[command[0],'-pthread',str(diagnostic_object),*objects,*shlex.split(libs[0]),'-o',str(binary)]
 with (out/'link.log').open('w') as log:subprocess.run(link,cwd=cmake,stdout=log,stderr=subprocess.STDOUT,check=True)
 report=json.loads((ROOT/'DIAGNOSTIC_REPORT.json').read_text());frame=out/'saved_frame.bgr';frame.write_bytes(gzip.decompress((ROOT/'saved_frame.bgr.gz').read_bytes()))
 if digest(frame)!=report['saved_raw_frame_sha256']:raise ValueError('Saved diagnostic frame failed checksum')
 status={'diagnostic_built':True,'diagnostic_executed':False,'production_binary_sha256':before,'diagnostic_binary_sha256':digest(binary),'frame_sha256':digest(frame),'config_sha256':digest(build/'configs/simulation_autoaim.yaml'),'scope':'One saved image; no simulator, hardware, threshold changes or target truth supplied to algorithm.', 'verified_bindings':{'source_and_header_count':len(input_identity['source_files']),'generated_input_count':len(input_identity['generated_sha256']),'model_sha256':digest(model),'executor_config_sha256':digest(executor),'autoaim_config_sha256':digest(autoaim)},'object_provenance':'UNVERIFIED local objects: original BUILD_MANIFEST does not bind individual object hashes. These exact current hashes are recorded, but correspondence to the production ELF is not proven; this replay is a separately bound local diagnostic, not historical equivalence.','object_bindings':object_bindings}
 if args.run:
  run=[str(binary),str(build/'configs/simulation_autoaim.yaml'),str(frame),str(ROOT/'saved_frame_metadata.json')]
  with (out/'result.txt').open('w') as stdout,(out/'stderr.log').open('w') as stderr:subprocess.run(run,cwd=out,stdout=stdout,stderr=stderr,timeout=90,check=True)
  status['diagnostic_executed']=True
 for entry in object_bindings:
  if digest(cmake/entry['object_relative_to_build'])!=entry['sha256']:raise ValueError('Local object changed during diagnostic')
 if digest(production)!=before:raise ValueError('Production binary unexpectedly changed')
 (out/'REPLAY_BINDING.json').write_text(json.dumps(status,indent=2)+'\n')
 print(json.dumps(status,indent=2))
if __name__=='__main__':main()
