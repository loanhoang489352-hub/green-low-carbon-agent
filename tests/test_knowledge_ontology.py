from knowledge.ontology import LowCarbonOntology, normalize_document_metadata


def test_ontology_loads_controlled_types_and_relations():
    ontology = LowCarbonOntology()
    labels = ontology.labels_by_type()
    assert "transport_mode" in labels and "地铁" in labels["transport_mode"]
    assert ontology.relation_allowed("has_factor", "transport_mode", "metric")
    assert not ontology.relation_allowed("has_factor", "policy", "location")


def test_metadata_keeps_url_and_marks_traceability_truthfully():
    meta = normalize_document_metadata(
        {"source": "https://www.gov.cn/example", "publisher": "国务院"}, "正文"
    )
    assert meta["source_url"] == "https://www.gov.cn/example"
    assert meta["authority_tier"] == "A"
    assert len(meta["content_hash"]) == 64
    assert meta["evidence_status"] == "unverified"
    audit = LowCarbonOntology().audit_provenance(meta)
    assert "published_at" in audit.missing


def test_document_without_url_is_explicitly_unverified():
    meta = normalize_document_metadata({}, "只有正文")
    assert meta["authority_tier"] == "D"
    assert meta["evidence_status"] == "unverified"


def test_source_link_is_not_misrepresented_as_current_validity():
    ontology = LowCarbonOntology()
    meta = ontology.enrich_metadata({
        "source_url": "https://www.gov.cn/example",
        "publisher": "国务院",
        "retrieved_at": "2026-09-10T00:00:00",
    }, "政策正文")
    assert meta["evidence_status"] == "source_linked"
    assert "valid_to" in ontology.audit_provenance(meta).missing


def test_complete_authoritative_provenance_can_be_current():
    ontology = LowCarbonOntology()
    meta = ontology.enrich_metadata({
        "source_url": "https://www.gov.cn/example",
        "publisher": "国务院",
        "published_at": "2026-01-01",
        "retrieved_at": "2026-09-10T00:00:00",
        "valid_from": "2026-01-01",
        "valid_to": "2027-01-01",
        "validity_status": "current_verified",
    }, "政策正文")
    assert meta["evidence_status"] == "verified_current"


def test_complete_historical_evidence_is_not_called_current():
    ontology = LowCarbonOntology()
    meta = ontology.enrich_metadata({
        "source_url": "https://www.mee.gov.cn/example.pdf",
        "publisher": "生态环境部、国家统计局",
        "published_at": "2025-12-31",
        "retrieved_at": "2026-09-10T00:00:00+08:00",
        "valid_from": "2023-01-01",
        "valid_to": "2023-12-31",
        "validity_status": "historical_verified",
    }, "2023年数据")
    assert meta["evidence_status"] == "verified_historical"
