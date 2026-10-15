"""Read official immutable Nav2 sources, no build/ROS/downloaded execution."""
from pathlib import Path
import hashlib,json,urllib.request
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/nav2-goal-controller-source-20261015-01';OUT.mkdir()
REV='a097086719c88f781aa59788eca29ac6ca5e56db'
names=['nav2_controller/src/controller_server.cpp','nav2_controller/src/main.cpp',
 'nav2_controller/include/nav2_controller/controller_server.hpp','nav2_controller/CMakeLists.txt',
 'nav2_controller/package.xml','LICENSE']
rows=[]
for name in names:
    url=f'https://raw.githubusercontent.com/ros-navigation/navigation2/{REV}/{name}'
    with urllib.request.urlopen(url,timeout=60) as response:raw=response.read(256*1024+1)
    assert len(raw)<=256*1024
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    rows.append(dict(path=name,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),url=url))
(OUT/'UPSTREAM_SOURCE.json').write_bytes((json.dumps(dict(repository='https://github.com/ros-navigation/navigation2',
 tag='1.1.20',revision=REV,files=rows,qualification='source_only_not_build_or_runtime'),indent=2)+'\n').encode())
print(json.dumps(rows))
