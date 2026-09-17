import json
from pathlib import Path

from knowledge.updater import KnowledgeUpdater, ParsedContent, UpdateResult


def test_archive_version_is_content_addressed_and_deduplicated(tmp_path):
    updater = KnowledgeUpdater(knowledge_base_path=str(tmp_path))
    parsed = ParsedContent(
        title="测试政策", content="具有来源的政策正文", update_time="2026-01-01",
        source_url="https://www.gov.cn/example", publisher="国务院",
    )
    result = UpdateResult(
        source="国务院", url=parsed.source_url, has_update=True,
        new_content=[parsed.content], update_time=parsed.update_time,
        timestamp="2026-09-10T00:00:00",
    )
    first = updater._archive_version(parsed, result)
    second = updater._archive_version(parsed, result)
    assert first == second
    files = list((tmp_path / "_versions").rglob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["source_url"] == parsed.source_url
    assert payload["published_at"] == "2026-01-01"
    assert len(payload["content_hash"]) == 64


def test_new_ingested_document_records_provenance_without_inventing_validity(tmp_path):
    updater = KnowledgeUpdater(knowledge_base_path=str(tmp_path))
    parsed = ParsedContent(
        title="测试政策", content="政策正文", update_time="2026-01-01",
        source_url="https://www.gov.cn/example", publisher="国务院",
    )
    path = Path(updater._save_new_document(parsed, "国务院"))
    text = path.read_text(encoding="utf-8")
    assert "source_url: https://www.gov.cn/example" in text
    assert "publisher: 国务院" in text
    assert "content_hash:" in text
    assert "authority_tier: A" in text
    assert "validity_status: not_verified" in text
