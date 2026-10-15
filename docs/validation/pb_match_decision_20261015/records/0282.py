"""Copy exact owned Linux build records to a fresh host-readable evidence dir."""
from pathlib import Path
import argparse,hashlib,json,shutil
p=argparse.ArgumentParser();p.add_argument('--attempt',type=int,required=True);a=p.parse_args()
assert 1<=a.attempt<=20
ROOT=Path(__file__).resolve().parents[1]
source=Path('/root')/f'polar-pb-match-decision-build-20261015-{a.attempt:02}'
out=ROOT/'artifacts'/f'pb-match-native-build-20261015-{a.attempt:02}'
assert out.is_dir() and source.is_dir()
names=['BUILD_RESULT.json','src/SOURCE_IDENTITY.json','src/local_rmul_2025.xml',
    'ldd.stdout','ldd.stderr','build/CMakeCache.txt','build/compile_commands.json']
names.extend(x.relative_to(source).as_posix() for x in source.glob('*.log'))
names.extend(x.relative_to(source).as_posix() for x in source.glob('*CLEANUP.json'))
names.extend(x.relative_to(source).as_posix() for x in (source/'src').rglob('*') if x.is_file())
records=[]
for name in sorted(set(names)):
    path=source/name
    if not path.is_file():continue
    raw=path.read_bytes();target=out/('SOURCE_IDENTITY.json' if name=='src/SOURCE_IDENTITY.json' else name)
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as f:f.write(raw)
    records.append(dict(linux_path=str(path),mirror=target.relative_to(out).as_posix(),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
(out/'MIRROR_INDEX.json').write_bytes((json.dumps(dict(files=records,nodes_started=False),indent=2)+'\n').encode())
print(json.dumps(dict(mirrored_files=len(records))))
