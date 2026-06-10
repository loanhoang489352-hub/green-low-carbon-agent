"""逐文件跑 pytest,生成汇总"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"

files = sorted(TESTS_DIR.glob("test_*.py"))
results = []
total_pass = total_fail = total_err = 0

for f in files:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1"}
    t0 = time.time()
    r = subprocess.run(
        ["python", "-m", "pytest", str(f), "--timeout=60", "--tb=no", "-q",
         "-p", "no:cacheprovider", "--no-header"],
        cwd=str(ROOT), env=env, timeout=180, capture_output=True, text=True,
    )
    elapsed = time.time() - t0
    out = r.stdout + r.stderr
    # Extract last line with pass/fail info
    summary = None
    for line in reversed(out.splitlines()):
        if " passed" in line or " failed" in line or " error" in line:
            summary = line.strip()
            break
    results.append((f.name, elapsed, summary or "(no summary)"))
    print(f"  {f.name:40s}  {elapsed:6.1f}s  {summary or '(no summary)'}")

print()
print("=== 汇总 ===")
for name, t, s in results:
    print(f"  {name:40s}  {t:6.1f}s  {s}")