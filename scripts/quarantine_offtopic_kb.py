"""
P6.S.21 KB 合规清洗:
- 把真正无关的(只有首页标题/英文无关/明显党媒/统计局首页)归档到 _quarantine/
- 保留边界模糊的(政府站首页但有低碳内容的)
- 记录清理日志到 data/kb_cleanup_log.json
"""
import os
import json
import shutil
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path("d:/绿色低碳智能体")
KB_DIR = PROJECT_ROOT / "knowledge_base"
QUARANTINE_DIR = KB_DIR / "_quarantine"
LOG_FILE = PROJECT_ROOT / "data" / "kb_cleanup_log.json"

# 真正应归档的(明确无关 + 内容极薄,只有首页标题)
# 分类:
# A. 英文无关:0227 / 0255(IPCC 0256 保留是权威)
# B. 党媒/政治无关:0238 共产党员网
# C. 内容极薄(< 1KB)且无低碳信号:0002 / 0003 看着是政策但 0.1KB 没正文(可能是抓取失败)
# D. 纯政府首页且绿词=0:0253 发改委首页(实际只 5KB 一条新闻),0254 统计局(全统计首页)
QUARANTINE_LIST = [
    # 文件路径(相对 knowledge_base/) | 原因
    ("policies/0227_China_Power_System_Transformat.md", "英文无关,中国电力系统转型,无中文低碳内容"),
    ("policies/0255_Environmental_Defense_Fund_-_F.md", "英文,EDF 首页只有标题,无内容"),
    ("policies/0238_共产党员网_中共中央组织部.md", "党媒,与绿色低碳无关,内容为空(只有标题)"),
    ("policies/0253_中华人民共和国国家发展和改革委员会.md", "发改委首页快照,内容薄,绿词少,大量无关"),
    ("policies/0254_国家统计局.md", "统计局首页,与绿色低碳无关,大量统计无关内容"),
    ("policies/0002_2024年新能源汽车推广应用财政补贴政策.md", "0.1KB 内容薄(可能是抓取失败占位),绿词=0"),
    ("policies/0003_绿色建材下乡活动实施方案.md", "0.1KB 内容薄(可能是抓取失败占位),绿词=0"),
]

# 保留的边界条目(政府站首页但有部分低碳内容,继续用):
# 0221 ESG, 0223 财新, 0224 人民网科技, 0225 中国循环经济协会, 0226 IPCC
# 0233/0234 生态环境部, 0236 北京市生态环境局, 0237 广州市, 0240 中国能源网
# 0241 财新, 0242 人民网, 0243 界面, 0248 首页, 0249 新华能源
# 0250 经济参考, 0251 财新环境, 0252 南方周末, 0256 国家能源局
# 0257 节能与综合利用司, 0258 农业农村部, 0259 国家林业和草原局
# 0221 已经有 ESG 关键词
# 这些是"政府/媒体首页,包含部分低碳内容"的合理 KB 条目,LLM 检索时会被过滤

# policy/ 目录 13 个全保留
# basic/ + guide/ 全保留(明显绿色低碳)
# regional/ 全保留(明显绿色低碳)


def main():
    QUARANTINE_DIR.mkdir(exist_ok=True)
    log = {
        "cleanup_time": datetime.now().isoformat(),
        "total_files_quarantined": 0,
        "total_size_kb": 0,
        "files": [],
    }
    for rel, reason in QUARANTINE_LIST:
        src = KB_DIR / rel
        if not src.exists():
            log["files"].append({"path": rel, "status": "NOT_FOUND", "reason": reason})
            continue
        size = src.stat().st_size
        # 目标路径(保留目录结构)
        dst = QUARANTINE_DIR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        # 移走(不是删,保留可恢复)
        shutil.move(str(src), str(dst))
        log["files"].append({
            "path": rel,
            "status": "QUARANTINED",
            "reason": reason,
            "size_kb": round(size / 1024, 1),
            "quarantined_to": str(dst.relative_to(PROJECT_ROOT)),
        })
        log["total_files_quarantined"] += 1
        log["total_size_kb"] += round(size / 1024, 1)
        print(f"  归档: {rel} ({size // 1024}KB) - {reason}")

    LOG_FILE.parent.mkdir(exist_ok=True)
    LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n共归档 {log['total_files_quarantined']} 个文件, 总 {log['total_size_kb']}KB")
    print(f"日志: {LOG_FILE}")
    print(f"归档位置: {QUARANTINE_DIR}")
    print("可恢复: 用 'mv <QUARANTINE_DIR>/<file> knowledge_base/<path>' 还原")


if __name__ == "__main__":
    main()
