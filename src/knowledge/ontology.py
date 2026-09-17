"""Ontology and provenance rules for the low-carbon knowledge base.

The ontology is deliberately small and versioned.  It constrains extraction
without pretending that keyword co-occurrence is a verified factual edge.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ONTOLOGY_PATH = PROJECT_ROOT / "config" / "low_carbon_ontology.yaml"


@dataclass(frozen=True)
class ProvenanceAudit:
    missing: List[str]
    authority_tier: str
    traceable: bool


class LowCarbonOntology:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or DEFAULT_ONTOLOGY_PATH)
        self.data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self.version = str(self.data.get("version", "unknown"))
        self.entity_types = self.data.get("entity_types", {})
        self.relation_types = self.data.get("relation_types", {})
        self.required_provenance = list(self.data.get("required_provenance", []))
        self.authority_tiers = self.data.get("authority_tiers", {})

    def labels_by_type(self) -> Dict[str, List[str]]:
        return {
            entity_type: list(spec.get("labels", []))
            for entity_type, spec in self.entity_types.items()
        }

    def relation_allowed(self, relation: str, source_type: str, target_type: str) -> bool:
        spec = self.relation_types.get(relation)
        if not spec:
            return False
        domains = spec.get("domain", [])
        ranges = spec.get("range", [])
        return ("*" in domains or source_type in domains) and ("*" in ranges or target_type in ranges)

    def authority_tier(self, source_url: str) -> str:
        host = (urlparse(source_url).hostname or "").lower()
        for tier, suffixes in self.authority_tiers.items():
            if any(host == suffix or host.endswith("." + suffix) for suffix in suffixes):
                return str(tier)
        return "D"

    def enrich_metadata(self, metadata: Dict[str, Any], content: str) -> Dict[str, Any]:
        result = dict(metadata)
        source_url = str(result.get("source_url") or "")
        result.setdefault("ontology_version", self.version)
        result.setdefault("content_hash", hashlib.sha256(content.encode("utf-8")).hexdigest())
        result.setdefault("authority_tier", self.authority_tier(source_url))
        result.setdefault("evidence_status", self.evidence_grade(result))
        return result

    def evidence_grade(self, metadata: Dict[str, Any]) -> str:
        """Grade evidence without inferring missing publication or validity facts."""
        source_url = str(metadata.get("source_url") or "")
        core = (source_url, metadata.get("publisher"), metadata.get("retrieved_at"),
                metadata.get("content_hash"))
        if not all(core):
            return "unverified"
        audit = self.audit_provenance(metadata)
        if audit.traceable and audit.authority_tier in {"A", "B"}:
            validity = metadata.get("validity_status")
            if validity == "current_verified":
                return "verified_current"
            if validity == "historical_verified":
                return "verified_historical"
        return "source_linked"

    def audit_provenance(self, metadata: Dict[str, Any]) -> ProvenanceAudit:
        missing = [field for field in self.required_provenance if not metadata.get(field)]
        tier = str(metadata.get("authority_tier") or self.authority_tier(str(metadata.get("source_url") or "")))
        return ProvenanceAudit(missing=missing, authority_tier=tier, traceable=not missing)


_ontology: Optional[LowCarbonOntology] = None


def get_low_carbon_ontology() -> LowCarbonOntology:
    global _ontology
    if _ontology is None:
        _ontology = LowCarbonOntology()
    return _ontology


def normalize_document_metadata(metadata: Dict[str, Any], content: str) -> Dict[str, Any]:
    """Preserve a declared URL separately from the local source path."""
    result = dict(metadata)
    declared = str(result.get("source") or "").strip()
    if declared.startswith(("http://", "https://")):
        result.setdefault("source_url", declared)
    return get_low_carbon_ontology().enrich_metadata(result, content)
