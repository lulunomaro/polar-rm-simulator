"""Preserve only completed archive/preflight driver logs; no recursive payload."""
import hashlib,json,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
DEST=ROOT/'docs/validation/aim_live_followup_20261014/archive_driver'
DEST.mkdir(exist_ok=False);rows=[]
for group in ('preflight01','preflight02','preflight03','preflight04','preflight05','generation01'):
    for original in sorted((HERE/group).glob('*')):
        if not original.is_file():continue
        target=DEST/group/original.name;target.parent.mkdir(parents=True,exist_ok=True)
        raw=original.read_bytes();target.write_bytes(raw)
        assert target.read_bytes()==raw
        rows.append(dict(original_path=original.relative_to(ROOT).as_posix(),stored_path=target.relative_to(DEST).as_posix(),
            bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
(DEST/'PRESERVATION.json').write_text(json.dumps(dict(files=rows,scope='Literal completed preflight failures/success and actual generation driver'),indent=2)+'\n')
(DEST/'preserve_archive_driver.py').write_bytes(Path(__file__).read_bytes())
print(json.dumps(dict(files=len(rows),all_literal_equal=True)))
