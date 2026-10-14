"""Final preserved byte verification; does not rerun simulation or algorithms."""
import argparse,hashlib,json,os,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'docs/validation/git_prepared_bgr_20261014'
archive=root/'docs/validation/native_prepared_bgr_20261014';verifier=archive/'verify_archives.py'
p=argparse.ArgumentParser();p.add_argument('--revision',default='final');args=p.parse_args();prefix=args.revision
(out/(prefix+'_driver.py')).write_bytes(Path(__file__).read_bytes())
for name,extra in [(prefix+'.package',[]),(prefix+'.originals',['--check-originals'])]:
 command=[str(root/'.venv-sim/Scripts/python.exe'),str(verifier),'--archive',str(archive),*extra]
 identity={n:hashlib.sha256((archive/n).read_bytes()).hexdigest() for n in ('verify_archives.py','PRESERVATION_MANIFEST.json')}
 started=time.perf_counter()
 with (out/(name+'.stdout.bin')).open('xb') as stdout,(out/(name+'.stderr.bin')).open('xb') as stderr:
  child=subprocess.Popen(command,cwd=root,stdout=stdout,stderr=stderr,stdin=subprocess.DEVNULL,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
  code=child.wait()
 after={n:hashlib.sha256((archive/n).read_bytes()).hexdigest() for n in identity}
 result=dict(command=command,pid=child.pid,driver_pid=os.getpid(),returncode=code,reaped=child.poll() is not None,
  elapsed_s=time.perf_counter()-started,inputs_before=identity,inputs_after=after,inputs_unchanged=identity==after)
 (out/(name+'.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
 assert code==0 and identity==after,result
qa=json.loads((root/'artifacts/quality-20261014-prepared-bgr-frozen-02/manifest.json').read_bytes())
allowed={'docs/IMPLEMENTATION_PROGRESS.md','docs/WSL_NATIVE_TRANSPORT.md'};changed=[];checked=0
for n,h in qa['source_files_sha256'].items():
 p=root/n;current=hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
 if current!=h:
  assert n in allowed,'Post-QA program/source changed: '+n
  changed.append(dict(path=n,qa_sha256=h,current_sha256=current))
 if n not in allowed:checked+=1
names=set(filter(None,subprocess.check_output(['git','diff','--cached','--name-only','-z'],cwd=root).decode('utf-8').split('\0')))
index=[]
for item in subprocess.check_output(['git','ls-files','--stage','-z'],cwd=root).split(b'\0'):
 if not item:continue
 header,n=item.split(b'\t',1);n=n.decode('utf-8');mode,oid,stage=header.split()
 assert stage==b'0','Unmerged index entry'
 if n in names:index.append((n,oid))
batch=subprocess.check_output(['git','cat-file','--batch'],cwd=root,input=b''.join(oid+b'\n' for _,oid in index))
position=0;rows=[];programs=0
for n,oid in index:
 end=batch.index(b'\n',position);fields=batch[position:end].split();position=end+1
 assert fields[0]==oid and fields[1]==b'blob'
 size=int(fields[2]);raw=batch[position:position+size];position+=size
 assert batch[position:position+1]==b'\n';position+=1
 assert raw==(root/n).read_bytes(),'Git altered literal bytes: '+n
 sha=hashlib.sha256(raw).hexdigest()
 if n=='DEVELOPMENT_CHANGES.json' or n.startswith(('rm_match/','tests/','tools/')):
  assert sha==qa['source_files_sha256'][n],'Staged code differs from frozen QA: '+n
  programs+=1
 rows.append(dict(path=n,sha256=sha,bytes=len(raw),git_blob=oid.decode()))
assert position==len(batch) and programs==13
proof=dict(schema='polar.final-staged-literal-qa-proof.v1',passed=True,
 qa_manifest_sha256=hashlib.sha256((root/'artifacts/quality-20261014-prepared-bgr-frozen-02/manifest.json').read_bytes()).hexdigest(),
 checked_source_files=checked,only_post_qa_changed_files=changed,staged_programs=programs,staged_literal_files=len(rows),files=rows,
 scope='All indexed files listed retain current literal bytes; 13 programs match final QA. This proof and final verifier receipts are staged afterward and separately checked.')
staged={r['path'] for r in rows}
for path in archive.rglob('*'):
 if path.is_file():assert path.relative_to(root).as_posix() in staged,'Archive file missing from index: '+str(path)
(out/(prefix.upper()+'_INDEX_PROOF.json')).write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
print(json.dumps(dict(passed=True,checked_source_files=checked,staged_programs=programs,staged_literal_files=len(rows))))
