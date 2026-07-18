"""一次性脚本:从生成的样本提取 expected_text 用于 golden set"""
import fitz
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from generate_samples import DIGITAL_PDFS, SCANNED_PDFS, IMAGE_TEXTS, MIXED_PDFS

samples = Path(__file__).parent / "ocr_samples"


def extract_pdf_text(pdf_path: Path) -> str:
    doc = fitz.open(str(pdf_path))
    text = "\n".join(p.get_text() for p in doc).strip()
    doc.close()
    return text


def expected_for(case_id: str) -> dict | None:
    """从 generate_samples.py 的数据结构里提取 expected"""
    for c in DIGITAL_PDFS + SCANNED_PDFS + MIXED_PDFS:
        if c["id"] == case_id:
            pdf = samples / f"{case_id}.pdf"
            return {
                "file": f"tests/eval/ocr_samples/{pdf.name}",
                "expected_text": extract_pdf_text(pdf),
                "expected_keywords": c["keywords"],
            }
    for c in IMAGE_TEXTS:
        if c["id"] == case_id:
            img = samples / c["title"]
            # 图片的 expected_text 是行拼接(允许空白差异)
            text = "\n".join(line for line in c["content"] if line.strip())
            return {
                "file": f"tests/eval/ocr_samples/{img.name}",
                "expected_text": text,
                "expected_keywords": c["keywords"],
            }
    return None


if __name__ == "__main__":
    import json
    import io
    import sys

    buf = io.StringIO()
    # 数字 PDF(5)
    for c in DIGITAL_PDFS:
        e = expected_for(c["id"])
        buf.write(json.dumps({**{"id": c["id"], "type": "pdf_digital"}, **e}, ensure_ascii=False) + "\n")
    # 扫描件 PDF(5)
    for c in SCANNED_PDFS:
        e = expected_for(c["id"])
        buf.write(json.dumps({**{"id": c["id"], "type": "pdf_scanned"}, **e}, ensure_ascii=False) + "\n")
    # 图片(7)
    for c in IMAGE_TEXTS:
        e = expected_for(c["id"])
        buf.write(json.dumps({**{"id": c["id"], "type": "image_text"}, **e}, ensure_ascii=False) + "\n")
    # 混合版式(3)
    for c in MIXED_PDFS:
        e = expected_for(c["id"])
        buf.write(json.dumps({**{"id": c["id"], "type": "mixed_layout"}, **e}, ensure_ascii=False) + "\n")

    sys.stdout.buffer.write(buf.getvalue().encode("utf-8"))