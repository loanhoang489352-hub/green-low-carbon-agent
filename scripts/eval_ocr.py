"""
P9: OCR 评估脚本

读 tests/eval/ocr_golden_set.jsonl,跑 OCR 引擎,聚合指标:
- char_error_rate: 归一化编辑距离(NED = edit_distance / max(len_pred, len_gold))
- keyword_hit_rate: 必须关键词命中率
- page_extraction_success: 多页 PDF 页数 >= 1 视为成功

输出到控制台 + data/eval_report_ocr.md。

CI gate:
    curated: char_error_rate_avg ≤ 0.10 且 keyword_hit_rate ≥ 0.85 → exit 0
    full:    仅信息性(不返 1)

使用方法:
    # 默认 mock(PyMuPDF 抽文本 + 简单模拟 OCR),快速跑通
    python scripts/eval_ocr.py

    # 真 OCR(PaddleOCR / Tesseract)
    pip install paddleocr
    USE_REAL_OCR=1 python scripts/eval_ocr.py

    # 只跑 curated 子集
    python scripts/eval_ocr.py --subset curated

    # 不根据阈值 exit code(本地诊断)
    python scripts/eval_ocr.py --no-exit-code
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

GOLDEN_SET = PROJECT_ROOT / "tests" / "eval" / "ocr_golden_set.jsonl"
REPORT_PATH = PROJECT_ROOT / "data" / "eval_report_ocr.md"

# CI gate 阈值(curated 子集)
THRESHOLD_CER = 0.10      # char_error_rate 平均值
THRESHOLD_KW = 0.85       # keyword_hit_rate


# ---------------------------------------------------------------------------
# 归一化 + 编辑距离
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """统一空白 + 去标点 + 全角转半角,降低编辑距离对版式的敏感度"""
    if not text:
        return ""
    # 全角 -> 半角
    text = unicodedata.normalize("NFKC", text)
    # 统一换行/空格
    text = re.sub(r"\s+", " ", text).strip()
    return text


def edit_distance(a: str, b: str, max_ops: int = 5000) -> int:
    """带上限的 Levenshtein 距离(超长字符串早停)
    使用单行 DP + 单数组滚动,O(min(len(a), len(b))) 内存
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    # 始终让 b 较短,减少内存
    if len(a) < len(b):
        a, b = b, a

    if len(b) == 0:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        row_min = curr[0]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                prev[j] + 1,        # 删除
                curr[j - 1] + 1,    # 插入
                prev[j - 1] + cost, # 替换
            )
            if curr[j] < row_min:
                row_min = curr[j]
        # 行最小值已超过上限,提前返回
        if row_min > max_ops:
            return max_ops
        prev = curr
    return prev[-1]


def normalized_edit_distance(pred: str, gold: str) -> float:
    """NED = edit_distance / max(len_pred, len_gold)
    注:gold 长度一般 ≥ pred(预测残缺),所以分母用 gold 更严格
    """
    p = normalize(pred)
    g = normalize(gold)
    if not g:
        return 0.0 if not p else 1.0
    dist = edit_distance(p, g)
    # 用更长的字符串做归一化,避免预测比 gold 长时过度惩罚
    norm = max(len(p), len(g))
    return min(1.0, dist / norm) if norm > 0 else 0.0


def keyword_hit(pred: str, keywords: List[str]) -> Tuple[int, int]:
    """必须关键词命中:casefold 后 substring 匹配即可"""
    p = normalize(pred).lower()
    hit = sum(1 for kw in keywords if kw.lower() in p)
    return hit, len(keywords)


# ---------------------------------------------------------------------------
# OCR 引擎接口
# ---------------------------------------------------------------------------

class OCREngine:
    """OCR 引擎抽象接口

    extract(path) -> {
        "text": str,
        "pages": int,           # PDF 页数,图片为 1
        "success": bool,        # 是否成功抽出文本
    }

    实现:
    - MockOCREngine(默认):PyMuPDF 抽 PDF 文本层,图片用 PIL 占位字符
    - RealOCREngine:用 PaddleOCR / Tesseract(可选,需要装 paddleocr)
    """

    def extract(self, path: Path) -> Dict:
        raise NotImplementedError


class MockOCREngine(OCREngine):
    """默认 mock 引擎 — PDF 用 PyMuPDF 抽文本层,图片优先 Tesseract,缺失则空
    目的:跑通评估脚本 + 验证 schema/数据/格式,非真 OCR 性能测试

    注:图片 OCR 即使有 Tesseract 也只能拿到中英文字符级结果,
    中文手写/复杂字体仍需 PaddleOCR。可通过 USE_REAL_OCR=1 切换。
    """

    def __init__(self):
        try:
            import fitz  # noqa
            self._has_fitz = True
        except ImportError:
            self._has_fitz = False

        self._tesseract_cmd = None
        self._tesseract_langs = None
        try:
            import pytesseract  # noqa
            import shutil
            cmd = shutil.which("tesseract")
            if cmd:
                self._tesseract_cmd = cmd
                try:
                    langs = pytesseract.get_languages()
                    chosen = [l for l in ("chi_sim", "chi_tra", "eng") if l in langs]
                    self._tesseract_langs = "+".join(chosen) if chosen else "eng"
                except Exception:
                    self._tesseract_langs = "eng"
        except ImportError:
            pass

    def extract(self, path: Path) -> Dict:
        suffix = path.suffix.lower()
        if suffix == ".pdf" and self._has_fitz:
            return self._extract_pdf(path)
        if suffix in (".png", ".jpg", ".jpeg"):
            return self._extract_image(path)
        return {"text": "", "pages": 0, "success": False}

    def _extract_pdf(self, path: Path) -> Dict:
        try:
            import fitz
            doc = fitz.open(str(path))
            text = "\n".join(p.get_text() for p in doc)
            pages = doc.page_count
            doc.close()
            return {
                "text": text,
                "pages": pages,
                "success": pages > 0 and len(text.strip()) > 0,
            }
        except Exception as ex:
            return {"text": "", "pages": 0, "success": False, "error": str(ex)}

    def _extract_image(self, path: Path) -> Dict:
        """图片 OCR:有 Tesseract 用 Tesseract(轻量),否则空文本
        真生产用 PaddleOCR — 通过 USE_REAL_OCR=1 启用
        """
        if not self._tesseract_cmd:
            return {
                "text": "",
                "pages": 1,
                "success": False,
                "engine": "mock-image-no-tesseract",
            }
        try:
            import pytesseract
            from PIL import Image as PILImage
            img = PILImage.open(str(path))
            text = pytesseract.image_to_string(img, lang=self._tesseract_langs or "eng")
            return {
                "text": text,
                "pages": 1,
                "success": bool(text.strip()),
                "engine": f"tesseract-{self._tesseract_langs}",
            }
        except Exception as ex:
            return {
                "text": "",
                "pages": 1,
                "success": False,
                "error": str(ex),
                "engine": "mock-image-error",
            }


class RealOCREngine(OCREngine):
    """真 OCR 引擎占位 — 用 PaddleOCR
    启用: USE_REAL_OCR=1 + pip install paddleocr
    """

    def __init__(self):
        try:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        except ImportError as ex:
            raise RuntimeError(
                "RealOCREngine 需要 paddleocr,pip install paddleocr 或 "
                "去掉 USE_REAL_OCR=1 环境变量"
            ) from ex

    def extract(self, path: Path) -> Dict:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._extract_pdf(path)
        if suffix in (".png", ".jpg", ".jpeg"):
            return self._extract_image(path)
        return {"text": "", "pages": 0, "success": False}

    def _extract_image(self, path: Path) -> Dict:
        result = self._ocr.ocr(str(path), cls=True)
        text_lines = []
        for line in result[0] or []:
            if line and len(line) >= 2:
                text_lines.append(line[1][0])
        text = "\n".join(text_lines)
        return {"text": text, "pages": 1, "success": bool(text.strip())}

    def _extract_pdf(self, path: Path) -> Dict:
        # PaddleOCR 不能直接读 PDF,先用 PyMuPDF 转图
        import fitz
        doc = fitz.open(str(path))
        all_text = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            tmp = PROJECT_ROOT / "data" / "_ocr_tmp.png"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            pix.save(str(tmp))
            r = self._extract_image(tmp)
            all_text.append(r["text"])
            try:
                tmp.unlink()
            except OSError:
                pass
        text = "\n".join(all_text)
        pages = doc.page_count
        doc.close()
        return {"text": text, "pages": pages, "success": pages > 0 and bool(text.strip())}


def build_engine() -> OCREngine:
    """按环境变量选择 mock 或真 OCR"""
    if os.getenv("USE_REAL_OCR") == "1":
        print("[OCR] USE_REAL_OCR=1 → RealOCREngine (PaddleOCR)")
        return RealOCREngine()
    print("[OCR] 默认 mock → MockOCREngine (PyMuPDF 文本层 + 占位)")
    print("[OCR] 换真 OCR: USE_REAL_OCR=1 python scripts/eval_ocr.py")
    return MockOCREngine()


# ---------------------------------------------------------------------------
# 评估主流程
# ---------------------------------------------------------------------------

def load_golden(subset: str | None = None) -> List[Dict]:
    cases = []
    with open(GOLDEN_SET, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            if subset and c.get("subset") != subset:
                continue
            cases.append(c)
    return cases


def evaluate(cases: List[Dict], engine: OCREngine) -> Dict:
    """跑所有 case,聚合指标"""
    rows = []
    per_type = defaultdict(lambda: {"n": 0, "cer_sum": 0.0, "kw_hit": 0, "kw_total": 0,
                                    "page_ok": 0})
    misses = []

    for c in cases:
        path = PROJECT_ROOT / c["file"]
        if not path.exists():
            print(f"[WARN] 缺失样本: {path}")
            continue

        result = engine.extract(path)
        pred_text = result.get("text", "")
        pages = result.get("pages", 0)
        success = result.get("success", False)

        cer = normalized_edit_distance(pred_text, c["expected_text"])
        kw_hit, kw_total = keyword_hit(pred_text, c["expected_keywords"])
        page_ok = 1 if pages >= 1 else 0

        # 是否通过(tolerance 内)
        kw_rate = (kw_hit / kw_total) if kw_total else 0.0
        passed = cer <= c["tolerance"] and kw_rate >= 0.75

        row = {
            "id": c["id"],
            "type": c["type"],
            "cer": cer,
            "kw_hit": kw_hit,
            "kw_total": kw_total,
            "kw_rate": kw_rate,
            "pages": pages,
            "page_ok": page_ok,
            "success": success,
            "tolerance": c["tolerance"],
            "passed": passed,
        }
        rows.append(row)

        per_type[c["type"]]["n"] += 1
        per_type[c["type"]]["cer_sum"] += cer
        per_type[c["type"]]["kw_hit"] += kw_hit
        per_type[c["type"]]["kw_total"] += kw_total
        per_type[c["type"]]["page_ok"] += page_ok

        if not passed:
            misses.append({
                "id": c["id"],
                "cer": cer,
                "tolerance": c["tolerance"],
                "kw_hit": kw_hit,
                "kw_total": kw_total,
                "missing_keywords": [
                    kw for kw in c["expected_keywords"]
                    if kw.lower() not in normalize(pred_text).lower()
                ],
            })

    n = len(rows)
    avg_cer = sum(r["cer"] for r in rows) / n if n else 0.0
    total_kw_hit = sum(r["kw_hit"] for r in rows)
    total_kw = sum(r["kw_total"] for r in rows)
    kw_rate = total_kw_hit / total_kw if total_kw else 0.0
    page_success = sum(r["page_ok"] for r in rows) / n if n else 0.0
    passed_count = sum(1 for r in rows if r["passed"])

    return {
        "n": n,
        "passed": passed_count,
        "avg_cer": avg_cer,
        "kw_hit_rate": kw_rate,
        "page_extraction_success": page_success,
        "rows": rows,
        "per_type": dict(per_type),
        "misses": misses,
    }


def write_report(result: Dict, subset: str) -> None:
    """写 data/eval_report_ocr.md"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"# OCR 评估报告 — subset={subset}", ""]
    lines.append(f"- 总样本数: **{result['n']}**")
    lines.append(f"- 通过(cer ≤ tolerance & kw_hit ≥ 75%): **{result['passed']}**")
    lines.append(f"- 平均 char_error_rate: **{result['avg_cer']:.4f}**")
    lines.append(f"- keyword_hit_rate: **{result['kw_hit_rate']:.4f}**")
    lines.append(f"- page_extraction_success: **{result['page_extraction_success']:.4f}**")
    lines.append("")
    lines.append("## 按类型")
    lines.append("")
    lines.append("| 类型 | n | avg_cer | kw_hit_rate | page_ok |")
    lines.append("|---|---|---|---|---|")
    for t, v in sorted(result["per_type"].items()):
        n = v["n"]
        cer = v["cer_sum"] / n if n else 0
        kw = v["kw_hit"] / v["kw_total"] if v["kw_total"] else 0
        page_ok = v["page_ok"] / n if n else 0
        lines.append(f"| {t} | {n} | {cer:.4f} | {kw:.4f} | {page_ok:.4f} |")
    lines.append("")

    if result["misses"]:
        lines.append(f"## 未通过明细({len(result['misses'])} 条)")
        lines.append("")
        for m in result["misses"]:
            lines.append(f"- **{m['id']}**: cer={m['cer']:.4f} (tol={m['tolerance']}), "
                         f"kw={m['kw_hit']}/{m['kw_total']}")
            if m["missing_keywords"]:
                lines.append(f"  - 缺失关键词: {m['missing_keywords']}")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="OCR 评估脚本")
    parser.add_argument("--subset", choices=["curated", "full"], default="curated")
    parser.add_argument("--no-exit-code", action="store_true",
                        help="不根据阈值 exit code(本地诊断用)")
    parser.add_argument("--engine", choices=["mock", "real"], default="mock",
                        help="mock=PyMuPDF 抽文本层(快)/ real=PaddleOCR(慢)")
    args = parser.parse_args()

    if args.subset == "full":
        cases = load_golden(subset=None)
    else:
        cases = load_golden(subset="curated")

    if not cases:
        print(f"[ERR] golden set 为空(subset={args.subset})")
        sys.exit(2)

    print(f"[eval] subset={args.subset} → {len(cases)} cases")

    if args.engine == "real" or os.getenv("USE_REAL_OCR") == "1":
        engine = RealOCREngine() if args.engine == "real" else build_engine()
    else:
        engine = build_engine()

    result = evaluate(cases, engine)

    print()
    print("=== OCR Eval Results ===")
    print(f"  total:               {result['n']}")
    print(f"  passed:              {result['passed']}")
    print(f"  char_error_rate:     avg {result['avg_cer']:.4f}")
    print(f"  keyword_hit_rate:    {result['kw_hit_rate']:.4f}")
    print(f"  page_extraction_ok:  {result['page_extraction_success']:.4f}")
    print()
    print("  按类型:")
    for t, v in sorted(result["per_type"].items()):
        n = v["n"]
        cer = v["cer_sum"] / n if n else 0
        kw = v["kw_hit"] / v["kw_total"] if v["kw_total"] else 0
        page_ok = v["page_ok"] / n if n else 0
        print(f"    {t:14s} n={n:2d} cer={cer:.4f} kw={kw:.4f} page_ok={page_ok:.4f}")
    print()
    print(f"  未通过: {len(result['misses'])} 条")
    print(f"  报告:   {REPORT_PATH}")

    write_report(result, args.subset)

    # CI gate
    passed = result["avg_cer"] <= THRESHOLD_CER and result["kw_hit_rate"] >= THRESHOLD_KW
    print()
    print(f"  阈值: cer ≤ {THRESHOLD_CER} & kw ≥ {THRESHOLD_KW} "
          f"→ {'PASS' if passed else 'FAIL'}")

    if args.no_exit_code:
        sys.exit(0)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()