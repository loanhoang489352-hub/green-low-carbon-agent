"""Audit knowledge documents for thesis-grade provenance metadata."""

from __future__ import annotations

import json
import hashlib
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from knowledge.ontology import get_low_carbon_ontology, normalize_document_metadata


def parse_frontmatter(text: str):
    result = {}
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    result[key.strip()] = value.strip().strip('"\'')
    return result


def audit(root: Path):
    ontology = get_low_carbon_ontology()
    rows = []
    for path in sorted(root.rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        metadata = normalize_document_metadata(parse_frontmatter(text), text)
        result = ontology.audit_provenance(metadata)
        body = text.split("---", 2)[2].lstrip("\r\n") if text.startswith("---") and len(text.split("---", 2)) == 3 else text
        expected_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        declared_hash = str(parse_frontmatter(text).get("content_hash") or "")
        hash_valid = declared_hash == expected_hash
        rows.append({
            "path": str(path.relative_to(root)),
            "production_candidate": not any(part.startswith("_") for part in path.relative_to(root).parts[:-1]),
            "traceable": result.traceable and hash_valid,
            "evidence_status": metadata.get("evidence_status", "unverified"),
            "authority_tier": result.authority_tier,
            "missing": result.missing,
            "content_hash_valid": hash_valid,
        })
    return rows


if __name__ == "__main__":
    kb_root = ROOT / "knowledge_base"
    rows = audit(kb_root)
    production_rows = [row for row in rows if row["production_candidate"]]
    tiers = Counter(row["authority_tier"] for row in production_rows)
    grades = Counter(row["evidence_status"] for row in production_rows)
    traceable = sum(1 for row in production_rows if row["traceable"])
    report = {
        "documents": len(production_rows),
        "documents_total_including_quarantine": len(rows),
        "quarantined_or_internal": len(rows) - len(production_rows),
        "fully_traceable": traceable,
        "traceability_rate": round(traceable / len(production_rows), 4) if production_rows else 0,
        "authority_tiers": dict(tiers),
        "evidence_grades": dict(grades),
        "documents_detail": rows,
    }
    output = ROOT / "data" / "knowledge_provenance_audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "documents_detail"}, ensure_ascii=False))
    print(output)
