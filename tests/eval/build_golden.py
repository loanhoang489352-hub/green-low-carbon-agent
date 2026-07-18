"""一次性脚本:把 ocr_golden_raw.jsonl 转成正式 golden set + 加 tolerance"""
import json
from pathlib import Path

raw_path = Path(__file__).parent / "ocr_golden_raw.jsonl"
out_path = Path(__file__).parent / "ocr_golden_set.jsonl"

# 类别 -> tolerance(归一化编辑距离阈值)
TOLERANCE = {
    "pdf_digital": 0.05,    # 文本层完美,容许 5% 误差
    "pdf_scanned": 0.10,    # 扫描件转换,容许 10%
    "image_text": 0.20,     # 图片 OCR,容许 20%(mock OCR 完美但真 OCR 一般会超)
    "mixed_layout": 0.15,   # 多栏版式,容许 15%
}

# 类别 -> 子集标记(curated 进 CI gate)
SUBSET = {
    "pdf_digital": "curated",
    "pdf_scanned": "curated",
    "mixed_layout": "curated",
    "image_text": "full",   # 图片 OCR 慢,只跑全集信息性
}

# 类别 -> 中文描述(报告里用)
CATEGORY_DESC = {
    "pdf_digital": "数字 PDF",
    "pdf_scanned": "扫描 PDF",
    "image_text": "图片文字",
    "mixed_layout": "混合版式",
}

with open(raw_path, encoding="utf-8") as f_in, \
     open(out_path, "w", encoding="utf-8") as f_out:
    for line in f_in:
        line = line.strip()
        if not line:
            continue
        e = json.loads(line)
        doc_type = e["type"]
        out = {
            "id": e["id"],
            "file": e["file"],
            "type": doc_type,
            "category": CATEGORY_DESC[doc_type],
            "subset": SUBSET[doc_type],
            "expected_text": e["expected_text"],
            "expected_keywords": e["expected_keywords"],
            "tolerance": TOLERANCE[doc_type],
        }
        f_out.write(json.dumps(out, ensure_ascii=False) + "\n")

print(f"[OK] 写入 {out_path}")