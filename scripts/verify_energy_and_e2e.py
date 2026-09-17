#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性验证脚本(把本轮 5 项整改的"静态交付"变成"可复核"的一键入口)

用途:在正常、装有依赖的 shell 里执行一次,即可完成:
  1. 语法自检(本轮改动的所有 .py)
  2. 运行 P4-G e2e + P12 energy 测试(覆盖 ②③ 的修复点)
  3. 打印结果与提示

用法:
    cd D:\\green-agent
    python scripts/verify_energy_and_e2e.py

注意:本脚本只是"验证聚合器",它本身不做业务改动;若你想逐项跑,可改用下面的原始命令。
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _ast_check(files: list[Path]) -> int:
    """对所有改动文件做 AST 语法解析,失败即报。"""
    bad = 0
    print("\n[1/3] 语法自检(ast.parse) —— 本轮改动文件:")
    for f in files:
        try:
            ast.parse(f.read_text(encoding="utf-8"))
            print(f"  ✅ {f.relative_to(PROJECT_ROOT)}")
        except SyntaxError as e:
            bad += 1
            print(f"  ❌ {f.relative_to(PROJECT_ROOT)} 语法错误: {e}")
    return bad


def _run_pytest(tests: list[str]) -> int:
    print("\n[2/3] 运行 pytest —— 每个测试文件独立子进程跑(隔离跨文件状态残留),带 60s 超时:")
    env = {**os.environ, "USE_REACT": "false"}
    total_pass = 0
    total_fail = 0
    overall_rc = 0
    for t in tests:
        cmd = [sys.executable, "-m", "pytest", "--timeout=60", t, "-q"]
        try:
            proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, env=env)
        except FileNotFoundError:
            print("  ❌ 未找到 pytest,请先 `pip install -r requirements.txt`")
            return 127
        out = proc.stdout or ""
        tail = (out.strip().splitlines()[-1] if out.strip() else "")
        # 用正则跨末尾多行抓 pytest 汇总计数(比只取最后一行更稳:兼容超时/集合错误时
        # 最后一行可能不是 "N passed/N failed" 汇总,导致误报 "0 passed, 0 failed")。
        # "N error" 归入失败; "N deselected" 不计入。
        summary = "\n".join((out.strip().splitlines() or [])[-12:])
        passed = failed = 0
        try:
            m = re.search(r"(\d+)\s+passed\b", summary)
            if m:
                passed = int(m.group(1))
            m = re.search(r"(\d+)\s+failed\b", summary)
            if m:
                failed = int(m.group(1))
            m = re.search(r"(\d+)\s+error\b", summary)
            if m:
                failed += int(m.group(1))
        except Exception:
            pass
        total_pass += passed
        total_fail += failed
        status = "✅" if proc.returncode == 0 else "❌"
        print(f"  {status} {t}  ->  {tail}")
        if proc.returncode != 0:
            overall_rc = 1
            for line in (proc.stdout or "").splitlines():
                if line.startswith("FAILED"):
                    print(f"       {line}")
    print(f"\n[隔离跑合计] {total_pass} passed, {total_fail} failed")
    return overall_rc


def main() -> int:
    files = [
        # 本会话改动的所有 Python 文件(语法自检)
        "src/agent/trace.py",
        "src/agent/core.py",
        "src/agent/conversation_store.py",
        "src/agent/tools/extended.py",
        "src/agent/tool_dispatcher.py",
        "src/agent/intent.py",
        "src/agent/energy/policies.py",
        "src/agent/energy/planner.py",
        "src/user_profile/personalized_recommender.py",
        "src/user_profile/user_profile.py",
        "src/user_profile/dynamic_updater.py",
        "src/agent/skills/builtin.py",
        "src/agent/skills/skill.py",
        "src/agent/skills/energy_planning_skill.py",
        "src/plugin_system/loader.py",
        "src/server/identity.py",
        "src/server/app.py",
        "src/server/routers/chat.py",
        "src/server/routers/energy.py",
        "src/server/routers/onboarding.py",
        "src/server/routers/profile.py",
        "src/server/routers/system.py",
        "src/server/routers/__init__.py",
    ]
    bad = _ast_check([PROJECT_ROOT / f for f in files])

    tests = [
        "tests/test_p4g_e2e.py",
        "tests/test_p4b_memory.py",
        "tests/test_p4h_working_memory.py",
        "tests/test_energy_planner.py",
        "tests/test_energy_api.py",
        "tests/test_energy_e2e.py",
        "tests/test_energy_no_hallucination.py",
        "tests/test_auth_e2e.py",
        "tests/test_p5i_security.py",
        "tests/test_p5c_reliability.py",
        "tests/test_p5e_health.py",
        "tests/test_p6c_query_cache.py",
        "tests/test_p6e_connection_pool.py",
        "tests/test_p6s15_tools_skills.py",
        "tests/test_p6s16_mcp_integration.py",
        "tests/test_p6s22_geolocation.py",
    ]
    # 只跑真实存在的测试文件,缺失的跳过(避免 pytest 遇到不存在的路径整体报错)
    missing = [t for t in tests if not (PROJECT_ROOT / t).exists()]
    tests = [t for t in tests if (PROJECT_ROOT / t).exists()]
    if missing:
        print("\n[提示] 跳过不存在的测试文件(可忽略):")
        for m in missing:
            print(f"  - {m}")
    ret = _run_pytest(tests)

    print("\n[3/3] 结果:")
    if bad == 0 and ret == 0:
        print("  ✅ 语法通过 + 测试全过 —— 本轮整改可认定为已通过运行时复核。")
    else:
        print(f"  ⚠️ 语法错误={bad}, pytest 退出码={ret}(非 0 则有失败)。")
        print("     请把失败用例贴给我,我继续静态定位/修复。")

    print("\n提示:④ 前端(web/energy.html / index.html)与⑤ 链接需在浏览器手测;")
    print("     本脚本无法代替真实浏览器联调。")
    return 0 if (bad == 0 and ret == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
