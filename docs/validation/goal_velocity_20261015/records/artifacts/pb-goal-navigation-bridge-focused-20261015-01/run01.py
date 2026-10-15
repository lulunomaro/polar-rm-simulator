"""Scoped pure bridge regression capture; does not start ROS/WSL/NN/GL."""
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
TESTS = ["tests/test_pb_goal_navigation_bridge.py", "tests/test_pb_navigation_bridge.py"]
SOURCES = TESTS + ["rm_match/integrations/pb_navigation_bridge.py",
                   "rm_match/platform_v2/contracts.py",
                   "rm_match/platform_v2/navigation_contracts.py"]


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in SOURCES}


before = hashes()
for name in SOURCES:
    target = OUT / "source01" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((ROOT / name).read_bytes())
command = [str(ROOT / ".venv-sim/Scripts/python.exe"), "-m", "pytest", *TESTS,
           "-q", "--junitxml=" + str(OUT / "junit01.xml")]
(OUT / "COMMAND01.json").write_text(json.dumps(command, indent=2), encoding="utf-8")
started = time.perf_counter()
with (OUT / "stdout01.log").open("wb") as stdout, (OUT / "stderr01.log").open("wb") as stderr:
    child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                             stdout=stdout, stderr=stderr)
    code = child.wait(timeout=60)
after = hashes()
result = dict(exit_code=code, reaped=child.poll() is not None,
              elapsed=time.perf_counter() - started, before=before, after=after,
              source_unchanged=before == after,
              scope="Controlled clock/source envelope units plus original stdlib child fixture; no ROS/WSL/NN/GL")
(OUT / "PROCESS_RESULT01.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print((OUT / "stdout01.log").read_text())
print((OUT / "stderr01.log").read_text())
print(json.dumps(result))
raise SystemExit(code)
