"""
灾备恢复脚本 — P6.F

从 backups/ 选择 tar.gz 恢复到 data/。

用法:
    python scripts/restore.py              # 列出备份,选最新
    python scripts/restore.py --latest     # 直接选最新
    python scripts/restore.py FILE=backups/data_xxx.tar.gz  # 指定
    python scripts/restore.py --dry-run    # 只列出内容,不实际解压
    python scripts/restore.py --yes        # 跳过确认(谨慎)

安全:
- 默认要求 --yes 才覆盖现有 data/
- 解压前自动 SHA256 校验
- 自动备份当前 data/(backups/data_BEFORE_RESTORE_*.tar.gz)
"""
import argparse
import hashlib
import os
import sys
import tarfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
import os as _os
PROJECT_ROOT = Path(_os.environ.get("BACKUP_PROJECT_ROOT", str(PROJECT_ROOT)))
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from paths import DATA_DIR

BACKUPS_DIR = PROJECT_ROOT / "backups"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _list_backups():
    """列出可用备份(按时间倒序)"""
    backups = sorted(BACKUPS_DIR.glob("data_*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    return backups


def _list_tar(tar_path: Path):
    """列出 tar 内容(用于 --dry-run)"""
    with tarfile.open(tar_path, "r:gz") as tar:
        members = tar.getmembers()
        print(f"[INFO] {tar_path.name} 含 {len(members)} 个文件:")
        for m in members[:30]:
            print(f"   {m.name} ({m.size} bytes)")
        if len(members) > 30:
            print(f"   ... 还有 {len(members) - 30} 个")


def _verify_sha(tar_path: Path) -> bool:
    """校验 SHA256"""
    sha_path = tar_path.with_suffix(tar_path.suffix + ".sha256")
    if not sha_path.exists():
        print(f"[WARN] 无 SHA256 文件 {sha_path.name},跳过校验")
        return True
    expected = sha_path.read_text(encoding="utf-8").split()[0]
    actual = _sha256_file(tar_path)
    if actual != expected:
        print(f"[ERROR] SHA256 不匹配!")
        print(f"  期望: {expected[:16]}...")
        print(f"  实际: {actual[:16]}...")
        return False
    print(f"[OK] SHA256 校验通过: {actual[:16]}...")
    return True


def _backup_current_data():
    """恢复前先备份当前 data/(防覆盖丢失)"""
    if not DATA_DIR.exists() or not any(DATA_DIR.iterdir()):
        return None
    import time as _t
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUPS_DIR / f"data_BEFORE_RESTORE_{ts}.tar.gz"
    print(f"[INFO] 先备份当前 data/ 到 {backup_path.name} ...")
    with tarfile.open(backup_path, "w:gz", compresslevel=6) as tar:
        for f in DATA_DIR.rglob("*"):
            if f.is_file():
                tar.add(f, arcname=f.relative_to(PROJECT_ROOT), recursive=False)
    print(f"[OK] 备份完成: {backup_path.name} ({backup_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return backup_path


def main():
    parser = argparse.ArgumentParser(description="绿色低碳智能体 - 灾备恢复脚本(P6.F)")
    parser.add_argument("--latest", action="store_true", help="选最新备份")
    parser.add_argument("--file", help="指定备份文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只列出 tar 内容")
    parser.add_argument("--yes", action="store_true", help="跳过确认(谨慎使用)")
    args = parser.parse_args()

    # 1) 选备份
    if args.file:
        target = Path(args.file)
        if not target.is_absolute():
            target = PROJECT_ROOT / args.file
    elif args.latest:
        backups = _list_backups()
        if not backups:
            print("[ERROR] backups/ 无备份")
            return 1
        target = backups[0]
    else:
        backups = _list_backups()
        if not backups:
            print("[ERROR] backups/ 无备份")
            return 1
        print("[INFO] 可用备份(按时间倒序):")
        for i, b in enumerate(backups[:10], 1):
            manifest = b.with_suffix("").with_suffix(".manifest.json")
            note = ""
            if manifest.exists():
                try:
                    import json
                    m = json.loads(manifest.read_text(encoding="utf-8"))
                    note = f" ({m['file_count']} files, {m['compressed_bytes'] / 1024 / 1024:.1f} MB)"
                except Exception:
                    pass
            print(f"  {i}. {b.name}{note}")
        if len(backups) > 10:
            print(f"  ... 还有 {len(backups) - 10} 个")
        try:
            choice = int(input(f"\n选哪个? (1-{min(10, len(backups))}, 0=取消): "))
        except (ValueError, EOFError):
            print("[ERROR] 无效输入")
            return 1
        if choice == 0:
            print("[INFO] 取消")
            return 0
        if choice < 1 or choice > len(backups):
            print("[ERROR] 编号超出范围")
            return 1
        target = backups[choice - 1]

    if not target.exists():
        print(f"[ERROR] 备份文件不存在: {target}")
        return 1
    print(f"\n[INFO] 选定备份: {target.name} ({target.stat().st_size / 1024 / 1024:.1f} MB)")

    # 2) Dry-run
    if args.dry_run:
        _list_tar(target)
        return 0

    # 3) 校验
    if not _verify_sha(target):
        return 1

    # 4) 确认
    if not args.yes:
        print(f"\n[WARNING] 将覆盖现有 data/ 目录!")
        try:
            confirm = input("确认继续? (yes/no): ")
        except EOFError:
            confirm = "no"
        if confirm != "yes":
            print("[INFO] 取消")
            return 0

    # 5) 先备份当前 data
    _backup_current_data()

    # 6) 解压
    print(f"[INFO] 解压到 {DATA_DIR.relative_to(PROJECT_ROOT)}/ ...")
    with tarfile.open(target, "r:gz") as tar:
        # 安全检查:防止 path traversal
        for member in tar.getmembers():
            target_path = PROJECT_ROOT / member.name
            if not str(target_path.resolve()).startswith(str(PROJECT_ROOT.resolve())):
                print(f"[ERROR] 危险路径: {member.name}")
                return 1
        tar.extractall(PROJECT_ROOT)
    print(f"[OK] 恢复完成")

    # 7) 加载 manifest 报告
    manifest_path = target.with_suffix("").with_suffix(".manifest.json")
    if manifest_path.exists():
        try:
            import json
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
            print(f"\n═══ 恢复摘要 ═══")
            print(f"  备份时间: {m.get('created_at', '?')}")
            print(f"  文件数:   {m.get('file_count', '?')}")
            print(f"  原始大小: {m.get('raw_bytes', 0) / 1024 / 1024:.1f} MB")
            print(f"  压缩大小: {m.get('compressed_bytes', 0) / 1024 / 1024:.1f} MB")
            print(f"  SQLite:   {len(m.get('sqlite_tables', {}))} 个 DB")
            chroma = m.get('chroma_collection_count')
            if chroma:
                print(f"  ChromaDB: {chroma} 文档块")
        except Exception as e:
            print(f"[WARN] 解析 manifest 失败: {e}")

    print(f"\n[INFO] 请重启 agent: make stop && cd src && python main.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
