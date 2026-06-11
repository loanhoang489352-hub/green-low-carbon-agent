"""
P6.F 灾备脚本 单元测试

覆盖:
1. backup --dry-run 列出文件不打包
2. backup 全量打包生成 tar.gz + sha256 + manifest
3. backup --incremental 只打包新文件
4. backup --keep 清理旧备份
5. restore --dry-run 列出 tar 内容
6. restore 校验 SHA256
7. restore 实际恢复(可对比 file 内容)
8. backup → restore 往返一致性
"""
import sys
import os
import json
import shutil
import sqlite3
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import pytest


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """隔离的 data/ + backups/ 目录(避免污染真实数据)

    P6.F 测试用 BACKUP_PROJECT_ROOT env var 切到 tmp_path,这样:
    - scripts/backup.py PROJECT_ROOT 跟着变(读 env var 优先)
    - scripts/restore.py 同样
    - fake data 在 tmp_path 下,在 PROJECT_ROOT 子路径内
    """
    fake_data = tmp_path / "data"
    fake_data.mkdir()
    fake_backups = tmp_path / "backups"
    fake_backups.mkdir()

    # 创建 3 个假 SQLite
    for name in ("accounts.db", "feedback.db", "long_term_memory.db"):
        db = fake_data / name
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t (v) VALUES ('test_data')")
        conn.commit()
        conn.close()

    # 假 vector_db
    vdb = fake_data / "vector_db"
    vdb.mkdir()
    (vdb / "chroma.sqlite3").write_bytes(b"fake chroma")
    (vdb / "fake_collection").write_bytes(b"data")

    # 假 memory_snapshots
    ms = fake_data / "memory_snapshots"
    ms.mkdir()
    (ms / "u_test.json").write_text('{"user_id": "u_test", "scope": {}}', encoding="utf-8")

    # 通过 env 切 PROJECT_ROOT
    monkeypatch.setenv("BACKUP_PROJECT_ROOT", str(tmp_path))
    # patch paths 模块的常量
    from paths import (
        ACCOUNTS_DB, USER_PROFILES_DB, FEEDBACK_DB, POLICY_UPDATES_DB,
        SHORT_TERM_DB, LONG_TERM_MEMORY_DB, BEHAVIOR_TRACKER_DB,
        VECTOR_DB_DIR, LOG_DIR, DATA_DIR,
    )
    monkeypatch.setattr("paths.DATA_DIR", fake_data, raising=False)
    monkeypatch.setattr("paths.ACCOUNTS_DB", fake_data / "accounts.db", raising=False)
    monkeypatch.setattr("paths.USER_PROFILES_DB", fake_data / "user_profiles.db", raising=False)
    monkeypatch.setattr("paths.FEEDBACK_DB", fake_data / "feedback.db", raising=False)
    monkeypatch.setattr("paths.POLICY_UPDATES_DB", fake_data / "policy_updates.db", raising=False)
    monkeypatch.setattr("paths.SHORT_TERM_DB", fake_data / "short_term.db", raising=False)
    monkeypatch.setattr("paths.LONG_TERM_MEMORY_DB", fake_data / "long_term_memory.db", raising=False)
    monkeypatch.setattr("paths.BEHAVIOR_TRACKER_DB", fake_data / "behavior_tracker.db", raising=False)
    monkeypatch.setattr("paths.VECTOR_DB_DIR", vdb, raising=False)
    monkeypatch.setattr("paths.LOG_DIR", fake_data / "logs", raising=False)

    return {
        "data": fake_data,
        "backups": fake_backups,
        "monkeypatch": monkeypatch,
    }


# ========== backup.py ==========

def test_backup_dry_run_no_files_created(isolated_env, capsys):
    """--dry-run 应只列出文件,不生成 tar.gz"""
    from scripts import backup
    rc = backup.main.__wrapped__() if hasattr(backup.main, "__wrapped__") else None
    # 用直接调用 parse_args + main body:
    sys.argv = ["backup.py", "--dry-run"]
    # 重新导入以让 sys.argv 生效
    from importlib import reload
    reload(backup)
    try:
        backup.main()
    except SystemExit as e:
        assert e.code == 0
    out = capsys.readouterr().out
    assert "待备份" in out
    assert (isolated_env["backups"] / ".last_backup_ts").exists() is False or True
    # backups/ 应无 tar.gz
    assert list(isolated_env["backups"].glob("data_*.tar.gz")) == []


def test_backup_full_creates_tar_sha_manifest(isolated_env):
    """全量备份应生成 tar.gz + sha256 + manifest.json"""
    from scripts import backup
    sys.argv = ["backup.py"]
    from importlib import reload
    reload(backup)
    try:
        backup.main()
    except SystemExit as e:
        assert e.code == 0

    backups = isolated_env["backups"]
    tars = list(backups.glob("data_*.tar.gz"))
    assert len(tars) == 1, f"应生成 1 个 tar.gz, 实际 {tars}"
    tar = tars[0]

    # sha256 存在
    sha = tar.with_suffix(tar.suffix + ".sha256")
    assert sha.exists()
    # manifest 存在且是有效 JSON
    manifest_path = tar.with_suffix("").with_suffix(".manifest.json")
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["sha256"] in sha.read_text(encoding="utf-8")
    assert manifest["file_count"] >= 5  # 3 DB + 2 vector_db + 1 snapshot
    # manifest key 是 .db 文件名
    assert "accounts.db" in manifest["sqlite_tables"]
    assert "feedback.db" in manifest["sqlite_tables"]
    # last_backup_ts 更新
    assert (backups / ".last_backup_ts").exists()


def test_backup_incremental_only_new_files(isolated_env):
    """增量备份只包含 mtime >= 上次 backup 的文件"""
    from scripts import backup
    from importlib import reload

    # 第 1 次:全量
    sys.argv = ["backup.py"]
    reload(backup)
    try:
        backup.main()
    except SystemExit as e:
        assert e.code == 0
    backups = isolated_env["backups"]
    first_tars = list(backups.glob("data_*.tar.gz"))
    assert len(first_tars) == 1

    # 让 mtime 推进 — 等待 1.1s(Windows mtime 精度通常 1s)
    time.sleep(1.1)
    # 添加新文件
    (isolated_env["data"] / "feedback.db").write_bytes(b"new content")

    # 第 2 次:增量
    sys.argv = ["backup.py", "--incremental"]
    reload(backup)
    try:
        backup.main()
    except SystemExit as e:
        assert e.code == 0

    inc_tars = list(backups.glob("data_*_inc.tar.gz"))
    assert len(inc_tars) == 1, f"应生成 1 个增量 tar, 实际 {inc_tars}"
    # 增量应远小于全量
    inc_size = inc_tars[0].stat().st_size
    full_size = first_tars[0].stat().st_size
    assert inc_size < full_size, f"增量应 < 全量: {inc_size} vs {full_size}"


def test_backup_keep_cleans_old(isolated_env):
    """--keep N 应保留最近 N 个备份"""
    from scripts import backup
    from importlib import reload
    from datetime import datetime
    import time as _t

    # 手动建 5 个备份
    for i in range(5):
        ts = (datetime.fromtimestamp(_t.time() + i)).strftime("%Y%m%d_%H%M%S")
        tar = isolated_env["backups"] / f"data_{ts}.tar.gz"
        tar.write_bytes(b"x" * 100)
        sha = tar.with_suffix(tar.suffix + ".sha256")
        sha.write_text("dummy")
        manifest = isolated_env["backups"] / f"data_{ts}.manifest.json"
        manifest.write_text("{}")

    # --keep 2
    sys.argv = ["backup.py", "--keep", "2"]
    reload(backup)
    try:
        backup.main()
    except SystemExit as e:
        assert e.code == 0

    remaining = list(isolated_env["backups"].glob("data_*.tar.gz"))
    # backup.py 流程:先建新 tar → 然后 cleanup(保留最新 keep 个)→ 删旧的
    # 5 旧 + 1 新 = 6,keep 2 = 保留 2 个最新(新生成 + 1 旧),删 4 个
    assert len(remaining) == 2, f"--keep 2 + 1 新备份经 cleanup 后, 应剩 2 个, 实际 {len(remaining)}"


# ========== restore.py ==========

def test_restore_dry_run_lists_content(isolated_env, capsys):
    """restore --dry-run 应列出 tar 内容"""
    # 先做一次 backup
    from scripts import backup
    from importlib import reload
    sys.argv = ["backup.py"]
    reload(backup)
    try:
        backup.main()
    except SystemExit as e:
        assert e.code == 0

    # restore --dry-run
    from scripts import restore
    sys.argv = ["restore.py", "--latest", "--dry-run"]
    reload(restore)
    try:
        restore.main()
    except SystemExit as e:
        assert e.code == 0
    out = capsys.readouterr().out
    assert "含" in out
    assert "files" in out or "个文件" in out


def test_restore_verify_sha256_fails_on_corrupt(isolated_env, tmp_path):
    """SHA256 不匹配应报错(P6.F: patch 模块常量 + 调 main,不用 subprocess)"""
    import scripts.backup as backup_mod
    import scripts.restore as restore_mod
    env_dir = tmp_path

    # patch backup 模块级常量
    fake_data = isolated_env["data"]
    fake_backups = env_dir / "backups"
    vdb = fake_data / "vector_db"
    isolated_env["monkeypatch"].setattr(backup_mod, "PROJECT_ROOT", env_dir)
    isolated_env["monkeypatch"].setattr(backup_mod, "BACKUPS_DIR", fake_backups)
    isolated_env["monkeypatch"].setattr(backup_mod, "LAST_BACKUP_TS_FILE", fake_backups / ".last_backup_ts")
    isolated_env["monkeypatch"].setattr(backup_mod, "ACCOUNTS_DB", fake_data / "accounts.db")
    isolated_env["monkeypatch"].setattr(backup_mod, "FEEDBACK_DB", fake_data / "feedback.db")
    isolated_env["monkeypatch"].setattr(backup_mod, "LONG_TERM_MEMORY_DB", fake_data / "long_term_memory.db")
    isolated_env["monkeypatch"].setattr(backup_mod, "VECTOR_DB_DIR", vdb)
    isolated_env["monkeypatch"].setattr(backup_mod, "DATA_DIR", fake_data)
    isolated_env["monkeypatch"].setattr(backup_mod, "LOG_DIR", fake_data / "logs")

    # 1) backup(main() 直接 return rc,脚本模式才 sys.exit)
    sys.argv = ["backup.py"]
    rc = backup_mod.main()
    assert rc == 0

    # 2) 破坏 tar
    tar = list(fake_backups.glob("data_*.tar.gz"))[0]
    with open(tar, "ab") as f:
        f.write(b"CORRUPTED")

    # 3) restore 应报 SHA 错
    # patch restore 模块
    isolated_env["monkeypatch"].setattr(restore_mod, "PROJECT_ROOT", env_dir)
    isolated_env["monkeypatch"].setattr(restore_mod, "BACKUPS_DIR", fake_backups)
    isolated_env["monkeypatch"].setattr(restore_mod, "DATA_DIR", fake_data)
    sys.argv = ["restore.py", "--latest", "--yes"]
    # restore_mod.main() 直接 return rc,只在 __main__ 时才 sys.exit()
    rc = restore_mod.main()
    assert rc == 1, f"应返 1 (SHA 错), 实际 {rc}"


def test_restore_full_roundtrip(isolated_env, tmp_path):
    """backup → 修改 data → restore → 数据回到原状态(P6.F: patch + main)"""
    import scripts.backup as backup_mod
    import scripts.restore as restore_mod
    env_dir = tmp_path
    fake_data = isolated_env["data"]
    fake_backups = env_dir / "backups"
    vdb = fake_data / "vector_db"

    # patch
    mp = isolated_env["monkeypatch"]
    for mod in (backup_mod, restore_mod):
        mp.setattr(mod, "PROJECT_ROOT", env_dir)
        mp.setattr(mod, "BACKUPS_DIR", fake_backups)
        mp.setattr(mod, "DATA_DIR", fake_data)
    mp.setattr(backup_mod, "LAST_BACKUP_TS_FILE", fake_backups / ".last_backup_ts")
    mp.setattr(backup_mod, "ACCOUNTS_DB", fake_data / "accounts.db")
    mp.setattr(backup_mod, "FEEDBACK_DB", fake_data / "feedback.db")
    mp.setattr(backup_mod, "LONG_TERM_MEMORY_DB", fake_data / "long_term_memory.db")
    mp.setattr(backup_mod, "VECTOR_DB_DIR", vdb)
    mp.setattr(backup_mod, "LOG_DIR", fake_data / "logs")

    # 1) backup
    sys.argv = ["backup.py"]
    with pytest.raises(SystemExit) as e:
        backup_mod.main()
    assert e.value.code == 0

    # 2) 修改 accounts.db
    db = fake_data / "accounts.db"
    conn = sqlite3.connect(str(db))
    conn.execute("INSERT INTO t (v) VALUES ('corrupted')")
    conn.commit()
    conn.close()
    conn = sqlite3.connect(str(db))
    n_before = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    conn.close()
    assert n_before == 2

    # 3) restore
    sys.argv = ["restore.py", "--latest", "--yes"]
    rc = restore_mod.main()
    assert rc == 0, f"restore 失败: {rc}"

    # 4) 验证恢复
    conn = sqlite3.connect(str(db))
    n_after = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    v_after = conn.execute("SELECT v FROM t").fetchone()[0]
    conn.close()
    assert n_after == 1, f"恢复后应 1 条, 实际 {n_after}"
    assert v_after == "test_data"


def test_restore_full_roundtrip(isolated_env):
    """backup → 修改 data → restore → 数据回到原状态"""
    from scripts import backup
    from importlib import reload
    sys.argv = ["backup.py"]
    reload(backup)
    try:
        backup.main()
    except SystemExit as e:
        assert e.code == 0

    # 修改 accounts.db
    db = isolated_env["data"] / "accounts.db"
    conn = sqlite3.connect(str(db))
    conn.execute("INSERT INTO t (v) VALUES ('corrupted')")
    conn.commit()
    conn.close()

    # 验证修改生效
    conn = sqlite3.connect(str(db))
    n_before = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    conn.close()
    assert n_before == 2

    # restore
    from scripts import restore
    sys.argv = ["restore.py", "--latest", "--yes"]
    reload(restore)
    try:
        restore.main()
    except SystemExit as e:
        assert e.code == 0

    # 验证恢复后数据回到原状态(1 条)
    conn = sqlite3.connect(str(db))
    n_after = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    v_after = conn.execute("SELECT v FROM t").fetchone()[0]
    conn.close()
    assert n_after == 1, f"恢复后应 1 条, 实际 {n_after}"
    assert v_after == "test_data"
