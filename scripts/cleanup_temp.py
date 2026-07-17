#!/usr/bin/env python3
"""
数据目录冗余文件清理脚本
基于 docs/HEALTH_CHECK_REPORT.md 中识别的 84 个临时文件 + 调试日志
执行前会打印预览(可加 --dry-run 只看不删)
"""
import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# 待清理文件模式(基于 P0-P5-J 阶段调试产物,与 git 无关)
TEMP_PATTERNS = [
    # P6 阶段调试日志(全部 39 个 p6s*.log)
    "p6s*.log",
    "p6r*.log",
    # 测试输出 JSON/MD
    "p6r2_kb8_result.md",
    "carbon_basic.json",
    "carbon_enhanced.json",
    "carbon_basic_msg.txt",
    "carbon_msg.txt",
    "chat_ds.txt",
    "chat_FIN.txt",
    "msg_*.txt",
    "msg_t*.txt",
    "msg_碳*.txt",
    "msg_我*.txt",
    "sim_user_msg.txt",
    "result_*.txt",
    "result_*.json",
    "final_*.json",
    "final_*.txt",
    "final_tr.txt",
    "FINAL_*.txt",
    "travel_*.json",
    "travel_msg.txt",
    "raw_response.txt",
    "R_*.txt",
    "E_*.txt",
    # 调试截图归档(实际开发用 → docs/regressions)
    "fix1_i18n.png",
    "fix2_chat.png",
    # 其他调试
    "bat_v2.log",
    "web_*.log",
    "source_test_report.md",
    "E_*.txt",
    "kb_cleanup_log.json",
    "kb_compliance_audit.json",
]

# 保护名单(绝不可删)
PROTECT = {
    "accounts.db", "accounts.db-shm", "accounts.db-wal",
    "user_profiles.db", "user_profiles.db-shm", "user_profiles.db-wal",
    "feedback.db", "feedback.db-shm", "feedback.db-wal",
    "policy_updates.db", "policy_updates.db-shm", "policy_updates.db-wal",
    "long_term_memory.db", "long_term_memory.db-shm", "long_term_memory.db-wal",
    "behavior_tracker.db", "behavior_tracker.db-shm", "behavior_tracker.db-wal",
    "short_term.db", "short_term.db-shm", "short_term.db-wal",
    "query_cache.db", "query_cache.db-shm", "query_cache.db-wal",
    "benchmark_pool.db", "benchmark_pool.db-shm", "benchmark_pool.db-wal",
    "langgraph_checkpoints.db", "langgraph_checkpoints.db-shm", "langgraph_checkpoints.db-wal",
    "graph_snapshot.json",
    "eval_report.md",
    "perf_report.md",
    "hk_ip_retest.md",
    "app.log",  # 移到 logs/
}

# 测试库(test_*.db 系列 — 由 pytest fixture 重建,生产无意义)
TEST_DB_PATTERNS = ["test_*.db", "test_*.db-shm", "test_*.db-wal"]


def find_files() -> list:
    """收集待删除文件(干跑)"""
    candidates = []

    for entry in DATA_DIR.iterdir():
        if not entry.is_file():
            continue
        name = entry.name
        # 保护名单
        if name in PROTECT:
            continue
        # 测试库
        import fnmatch
        if any(fnmatch.fnmatch(name, p) for p in TEST_DB_PATTERNS):
            candidates.append((entry, "test_db", entry.stat().st_size))
            continue
        # 临时文件模式
        if any(fnmatch.fnmatch(name, p) for p in TEMP_PATTERNS):
            candidates.append((entry, "temp", entry.stat().st_size))
            continue

    return candidates


def main():
    parser = argparse.ArgumentParser(description="清理 data/ 目录冗余临时文件")
    parser.add_argument("--dry-run", action="store_true", help="只列出待删文件,不执行")
    parser.add_argument("--yes", action="store_true", help="跳过确认,直接执行")
    args = parser.parse_args()

    if not DATA_DIR.exists():
        print(f"[ERR] data 目录不存在: {DATA_DIR}")
        sys.exit(1)

    files = find_files()
    total_size = sum(s for _, _, s in files)
    total_size_mb = total_size / 1024 / 1024

    print(f"=== 待清理文件预览 ===")
    print(f"总数: {len(files)} 个")
    print(f"总大小: {total_size_mb:.2f} MB")
    print()
    by_type = {}
    for _, t, s in files:
        by_type.setdefault(t, []).append((s, _))
    for t, items in by_type.items():
        print(f"[{t}] {len(items)} 个, {sum(s for s,_ in items)/1024:.0f} KB")
        for s, p in sorted(items, key=lambda x: -x[0])[:5]:
            print(f"  - {p.name}  ({s/1024:.1f} KB)")
        if len(items) > 5:
            print(f"  ... 及其他 {len(items)-5} 个")
    print()

    if args.dry_run:
        print("[DRY-RUN] 不执行删除")
        return

    if not args.yes:
        ans = input(f"确认删除以上 {len(files)} 个文件? (yes/no): ")
        if ans.lower() not in ("yes", "y"):
            print("已取消")
            return

    # 执行删除
    deleted = 0
    freed = 0
    for path, t, size in files:
        try:
            path.unlink()
            deleted += 1
            freed += size
        except Exception as e:
            print(f"[ERR] 删除失败 {path.name}: {e}")

    print()
    print(f"=== 完成 ===")
    print(f"已删除: {deleted} 个文件")
    print(f"释放空间: {freed/1024/1024:.2f} MB")


if __name__ == "__main__":
    main()
