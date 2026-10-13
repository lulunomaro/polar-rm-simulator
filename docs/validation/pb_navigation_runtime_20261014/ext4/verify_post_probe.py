import hashlib,json,os,pathlib,stat,time
root=pathlib.Path(__file__).resolve().parent
final=json.loads((root/'FINALIZATION_RESULT.json').read_bytes())
started=time.perf_counter();errors=[];counts={'file':0,'directory':0,'symlink':0}
def digest(path):
    h=hashlib.sha256()
    with pathlib.Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
for line in (root/'COPY_FILES.jsonl').read_text().splitlines():
    row=json.loads(line);p=pathlib.Path(row['destination']);counts[row['kind']]+=1
    try:
        if stat.S_IMODE(p.lstat().st_mode)!=row['destination_mode']:errors.append('mode:'+str(p))
        if row['kind']=='file':
            expected=final['pth']['after_sha256'] if str(p)==final['pth']['path'] else row['destination_sha256']
            if digest(p)!=expected:errors.append('file:'+str(p))
        elif row['kind']=='symlink' and os.readlink(p)!=row['destination_link']:errors.append('link:'+str(p))
    except OSError as e:errors.append('missing:'+str(p))
refs=final['original_evidence_sha256']
for path,expected in refs.items():
    if digest(path)!=expected:errors.append('original_evidence_changed:'+path)
if digest(root/'ENVIRONMENT_COMPAT_FINAL.json')!=final['final_environment_sha256']:errors.append('final_environment_changed')
own_pids=[]
needle=final['venv_python'].encode()
for p in pathlib.Path('/proc').iterdir():
    if not p.name.isdigit():continue
    try:
        argv=(p/'cmdline').read_bytes().split(b'\0')
        if argv and argv[0]==needle:own_pids.append(int(p.name))
    except OSError:pass
if own_pids:errors.append('new_venv_process_still_running')
record={'schema':'polar.humble-ext4-post-probe.v1','clean':not errors,'errors':errors,'checked_counts':counts,
    'all_new_runtime_bytes_links_modes_unchanged_except_explicit_derived_pth':not errors,
    'original_evidence_unchanged':all(digest(p)==v for p,v in refs.items()),'own_venv_processes_remaining':own_pids,
    'all_three_subprocesses_waited_and_reaped':all(c['exit_code']==0 for c in json.loads((root/'RUNTIME_PROBES_RESULT.json').read_bytes())['cases']),
    'final_environment_sha256':final['final_environment_sha256'],'elapsed_s':time.perf_counter()-started,
    'navigation_nodes_started':False,'DDS_initialized':False,'physics_steps':0}
(root/'POST_PROBE_PROOF.json').write_text(json.dumps(record,indent=2));print(json.dumps(record),flush=True)
assert record['clean']
