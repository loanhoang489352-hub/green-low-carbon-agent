"""
灾备脚本 — P6.F

全量 / 增量备份 data/ 到 backups/ 目录,生成 tar.gz + 校验和 + manifest。

用法:
    python scripts/backup.py                  # 全量备份(默认)
    python scripts/backup.py --incremental    # 增量备份(自上次 backup 改过的)
    python scripts/backup.py --keep 30        # 保留最近 30 个备份(默认 30)
    python scripts/backup.py --exclude-logs   # 不备份 logs/(节省空间)
    python scripts/backup.py --upload s3      # 上传到 S3(需 BACKUP_S3_BUCKET env)

输出:
    backups/data_YYYYMMDD_HHMMSS.tar.gz
    backups/data_YYYYMMDD_HHMMSS.tar.gz.sha256
    backups/data_YYYYMMDD_HHMMSS.manifest.json
    backups/.last_backup_ts(增量备份用)

设计要点:
- 备份时 SQLite + ChromaDB 不停服(只读快照,后续可在 WAL 模式下安全)
- 元数据 manifest 包含:文件数、总大小、SQLite 表数、ChromaDB 块数(供 restore 时校验)
- 自动清理超 --keep 数量的旧备份
- S3 上传用 boto3(env BACKUP_S3_BUCKET / BACKUP_S3_REGION)
"""
import argparse
import hashlib
import json
import os
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
# 测试覆盖:可通过 --project-root 或环境变量 BACKUP_PROJECT_ROOT 覆盖
import os as _os
PROJECT_ROOT = Path(_os.environ.get("BACKUP_PROJECT_ROOT", str(PROJECT_ROOT)))
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from paths import (
    ACCOUNTS_DB,
    BEHAVIOR_TRACKER_DB,
    DATA_DIR,
    FEEDBACK_DB,
    LONG_TERM_MEMORY_DB,
    POLICY_UPDATES_DB,
    SHORT_TERM_DB,
    USER_PROFILES_DB,
    VECTOR_DB_DIR,
    LOG_DIR,
)

BACKUPS_DIR = PROJECT_ROOT / "backups"
LAST_BACKUP_TS_FILE = BACKUPS_DIR / ".last_backup_ts"
DEFAULT_KEEP = 30


def _now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _sha256_file(path: Path) -> str:
    """文件 SHA256(流式,大文件安全)"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _gather_files(include_logs: bool) -> list[Path]:
    """收集要备份的文件列表(全部 SQLite + vector_db + memory_snapshots + 可选 logs)"""
    files = []

    # 7 个 SQLite DB(如果存在)
    for db in (
        ACCOUNTS_DB,
        USER_PROFILES_DB,
        FEEDBACK_DB,
        POLICY_UPDATES_DB,
        SHORT_TERM_DB,
        LONG_TERM_MEMORY_DB,
        BEHAVIOR_TRACKER_DB,
    ):
        if db.exists():
            files.append(db)

    # vector_db/(ChromaDB)
    if VECTOR_DB_DIR.exists():
        files.extend(VECTOR_DB_DIR.rglob("*"))
        files = [f for f in files if f.is_file()]

    # memory_snapshots/(WorkingMemory JSON)
    mem_snapshots = DATA_DIR / "memory_snapshots"
    if mem_snapshots.exists():
        files.extend(mem_snapshots.rglob("*.json"))

    # logs/(可选,日志会涨很大,通常可排除)
    if include_logs and LOG_DIR.exists():
        files.extend(LOG_DIR.rglob("*.log*"))
        files = [f for f in files if f.is_file()]

    return files


def _filter_incremental(files: list[Path], since_ts: float) -> list[Path]:
    """增量:只保留 mtime >= since_ts 的文件"""
    return [f for f in files if f.stat().st_mtime >= since_ts]


def _inspect_data(files: list[Path]) -> dict:
    """生成 manifest(SQLite 表数 / ChromaDB 块数等)"""
    import sqlite3
    manifest = {
        "file_count": len(files),
        "total_bytes": sum(f.stat().st_size for f in files),
        "sqlite_tables": {},
        "chroma_collection_count": None,
    }

    db_files = [f for f in files if str(f).endswith(".db") and not str(f).endswith(".db-wal") and not str(f).endswith(".db-shm")]
    for db in db_files:
        try:
            conn = sqlite3.connect(str(db), timeout=2.0)
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            conn.close()
            manifest["sqlite_tables"][db.name] = sorted(t[0] for t in tables)
        except Exception as e:
            manifest["sqlite_tables"][db.name] = f"ERR: {e}"

    # ChromaDB 块数(读 chroma.sqlite3 的 embeddings 表)
    chroma_sqlite = VECTOR_DB_DIR / "chroma.sqlite3"
    if chroma_sqlite.exists():
        try:
            conn = sqlite3.connect(str(chroma_sqlite), timeout=2.0)
            n = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()
            manifest["chroma_collection_count"] = n[0] if n else 0
            conn.close()
        except Exception:
            pass

    return manifest


def _cleanup_old(keep: int) -> int:
    """保留最近 keep 个备份,删除更早的"""
    backups = sorted(BACKUPS_DIR.glob("data_*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for old in backups[keep:]:
        # 删 tar + sha256 + manifest
        old.unlink(missing_ok=True)
        Path(str(old) + ".sha256").unlink(missing_ok=True)
        old_path = old.with_suffix("").with_suffix(".manifest.json")  # 兼容
        # manifest 命名:data_*.manifest.json
        manifest = BACKUPS_DIR / old.name.replace(".tar.gz", ".manifest.json")
        manifest.unlink(missing_ok=True)
        removed += 1
    return removed


def _upload_s3(local: Path) -> bool:
    """上传到 S3(env: BACKUP_S3_BUCKET + 可选 BACKUP_S3_PREFIX)"""
    bucket = os.environ.get("BACKUP_S3_BUCKET")
    if not bucket:
        print("[SKIP] BACKUP_S3_BUCKET 未设置,跳过 S3 上传")
        return False
    try:
        import boto3
    except ImportError:
        print("[WARN] boto3 未安装,跳过 S3 上传(pip install boto3)")
        return False
    prefix = os.environ.get("BACKUP_S3_PREFIX", "green-agent-backups/")
    s3 = boto3.client("s3")
    key = f"{prefix}{local.name}"
    s3.upload_file(str(local), bucket, key)
    print(f"[OK] 上传 S3: s3://{bucket}/{key}")
    return True


def main():
    parser = argparse.ArgumentParser(description="绿色低碳智能体 - 灾备脚本(P6.F)")
    parser.add_argument("--incremental", action="store_true", help="增量备份(自上次 backup 改过的)")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help=f"保留最近 N 个备份(默认 {DEFAULT_KEEP})")
    parser.add_argument("--exclude-logs", action="store_true", help="不备份 logs/")
    parser.add_argument("--upload", choices=["s3", "none"], default="none", help="上传到远端存储")
    parser.add_argument("--dry-run", action="store_true", help="只列出要备份的文件,不实际打包")
    args = parser.parse_args()

    # 1) 收集文件
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    files = _gather_files(include_logs=not args.exclude_logs)
    if not files:
        print("[ERROR] data/ 为空,无文件可备份")
        return 1

    # 2) 增量过滤
    if args.incremental:
        if not LAST_BACKUP_TS_FILE.exists():
            print("[WARN] 无 .last_backup_ts,改为全量备份")
        else:
            since_ts = float(LAST_BACKUP_TS_FILE.read_text().strip())
            files = _filter_incremental(files, since_ts)
            if not files:
                print("[INFO] 自上次 backup 以来无文件变化,跳过")
                return 0

    total_bytes = sum(f.stat().st_size for f in files)
    print(f"[INFO] 待备份 {len(files)} 个文件,共 {total_bytes / 1024 / 1024:.1f} MB")
    if args.dry_run:
        for f in files[:20]:
            print(f"   {f.relative_to(PROJECT_ROOT)} ({f.stat().st_size} bytes)")
        if len(files) > 20:
            print(f"   ... 还有 {len(files) - 20} 个")
        return 0

    # 3) 打包
    ts = _now_ts()
    suffix = "_inc" if args.incremental else ""
    backup_path = BACKUPS_DIR / f"data_{ts}{suffix}.tar.gz"
    print(f"[INFO] 打包到 {backup_path.relative_to(PROJECT_ROOT)} ...")
    start = time.time()
    with tarfile.open(backup_path, "w:gz", compresslevel=6) as tar:
        for f in files:
            # 存相对路径(便于恢复时解压到任何位置)
            tar.add(f, arcname=f.relative_to(PROJECT_ROOT), recursive=False)
    elapsed = time.time() - start
    backup_size = backup_path.stat().st_size
    print(f"[OK] 打包完成,耗时 {elapsed:.1f}s,文件 {backup_size / 1024 / 1024:.1f} MB")

    # 4) 写 sha256
    sha = _sha256_file(backup_path)
    sha_path = backup_path.with_suffix(backup_path.suffix + ".sha256")
    sha_path.write_text(f"{sha}  {backup_path.name}\n", encoding="utf-8")
    print(f"[OK] SHA256: {sha[:16]}...")

    # 5) 写 manifest
    manifest = _inspect_data(files)
    manifest["backup_path"] = str(backup_path.relative_to(PROJECT_ROOT))
    manifest["sha256"] = sha
    manifest["created_at"] = ts
    manifest["incremental"] = args.incremental
    manifest["include_logs"] = not args.exclude_logs
    manifest["elapsed_seconds"] = round(elapsed, 2)
    manifest["compressed_bytes"] = backup_size
    manifest["raw_bytes"] = total_bytes
    manifest_path = BACKUPS_DIR / f"data_{ts}{suffix}.manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[OK] Manifest: {manifest_path.relative_to(PROJECT_ROOT)}")

    # 6) 更新 last_backup_ts
    LAST_BACKUP_TS_FILE.write_text(str(time.time()), encoding="utf-8")

    # 7) 清理旧备份
    removed = _cleanup_old(args.keep)
    if removed:
        print(f"[OK] 清理 {removed} 个旧备份(保留最近 {args.keep} 个)")

    # 8) 上传 S3
    if args.upload == "s3":
        _upload_s3(backup_path)

    print(f"\n═══ 备份完成 ═══")
    print(f"  路径: {backup_path.relative_to(PROJECT_ROOT)}")
    print(f"  大小: {backup_size / 1024 / 1024:.1f} MB")
    print(f"  SHA:  {sha[:16]}...")
    print(f"  文件: {len(files)} 个")
    print(f"  SQLite 表: {sum(len(v) for v in manifest['sqlite_tables'].values() if isinstance(v, list))} 个")
    if manifest['chroma_collection_count']:
        print(f"  ChromaDB: {manifest['chroma_collection_count']} 文档块")
    return 0


if __name__ == "__main__":
    sys.exit(main())
