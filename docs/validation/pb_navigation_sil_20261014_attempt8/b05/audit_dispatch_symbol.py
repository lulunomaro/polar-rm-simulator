import hashlib
import json
import subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
ELF=Path('/root/polar-navigation-humble-e05eb08e/lio_tf_build_20261014_05_02/install/point_lio/lib/point_lio/pointlio_mapping')
result=subprocess.run(['/usr/bin/nm','-D',str(ELF)],capture_output=True,text=True,check=True)
symbols=[s for s in result.stdout.splitlines() if 'spin_all' in s or 'spin_some' in s]
record=dict(schema='polar.pb2025.dispatch-symbol-audit.v1',elf_path=str(ELF),elf_sha256=hashlib.sha256(ELF.read_bytes()).hexdigest(),
            command=['/usr/bin/nm','-D',str(ELF)],symbols=symbols,
            actual_spin_all_import=any('Executor8spin_all' in s for s in symbols),
            actual_spin_some_import=any('Executor9spin_some' in s for s in symbols),nodes_started=False)
record['passed']=record['actual_spin_all_import'] and not record['actual_spin_some_import']
out=HERE/'DISPATCH_SYMBOL_AUDIT.json'
if out.exists():raise RuntimeError('fresh symbol audit required')
out.write_text(json.dumps(record,indent=2)+'\n',encoding='utf8')
print(json.dumps(record))
if not record['passed']:raise SystemExit(1)
