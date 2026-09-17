import json
from contextlib import closing
import sqlite3
from pathlib import Path

import pytest

from user_profile.obsidian_export import export_wiki, _digest, sync_configured_wiki


@pytest.fixture
def store(tmp_path):
    p, h = tmp_path / "profiles.db", tmp_path / "households.db"
    with closing(sqlite3.connect(p)) as c:
        c.execute("CREATE TABLE user_profiles(user_id TEXT, profile_data TEXT)")
    with closing(sqlite3.connect(h)) as c:
        c.execute("CREATE TABLE household_profiles(user_id TEXT, profile_json TEXT)")
    return p, h, tmp_path / "wiki"


def put(db, uid, value, household=False):
    table, column = ("household_profiles", "profile_json") if household else ("user_profiles", "profile_data")
    with closing(sqlite3.connect(db)) as c:
        c.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
        c.execute(f"INSERT INTO {table} VALUES (?, ?)", (uid, json.dumps(value)))
        c.commit()


def test_links_privacy_and_idempotency(store):
    p, h, root = store
    put(p, "../private-alice", {"basic_info": {"address": "private-address"},
        "behavior_profile": {"travel_habits": {"origin": "private-address", "preferred_mode": "地铁"}},
        "graph": {"nodes": [{"node_id": "a", "node_type": "user"}, {"node_id": "b", "node_type": "interest", "properties": {"interest_id": "low_carbon_travel"}}],
                  "edges": [{"source": "a", "target": "b", "relation_type": "HAS_INTEREST"}]}})
    put(h, "../private-alice", {"family_size": 3, "appliances": ["冰箱"]}, True)
    before = p.read_bytes()
    result = export_wiki(root, p, h)
    assert result["users"] == 1
    all_text = "\n".join(f.read_text(encoding="utf-8") for f in root.rglob("*.md"))
    assert "private-alice" not in all_text and "private-address" not in all_text
    assert "HAS_INTEREST" in all_text and "未确认" in all_text and "冰箱" in all_text
    import re
    for link in re.findall(r"\[\[([^]|]+)(?:\|[^]]+)?\]\]", all_text):
        assert (root / (link + ".md")).exists()
    assert export_wiki(root, p, h)["changed"] == 0
    assert p.read_bytes() == before


def test_change_and_removal_preserve_developer_notes(store):
    p, h, root = store
    put(h, "alice", {"family_size": 3}, True)
    export_wiki(root, p, h)
    alias = "u-" + _digest("alice")
    note = root / alias / "我的观察.md"
    note.write_text("keep", encoding="utf-8")
    put(h, "alice", {"family_size": 4}, True)
    export_wiki(root, p, h)
    assert "更新 家庭.family_size" in (root / alias / "变化记录.md").read_text(encoding="utf-8")
    with closing(sqlite3.connect(h)) as c:
        c.execute("DELETE FROM household_profiles")
        c.commit()
    export_wiki(root, p, h)
    assert note.read_text() == "keep"
    assert not (root / alias / "总览.md").exists()
    assert alias not in (root / "画像索引.md").read_text(encoding="utf-8")


def test_missing_source_does_not_delete_previous_export(store):
    p, h, root = store
    put(p, "alice", {})
    export_wiki(root, p, h)
    h.rename(h.with_suffix(".offline"))
    with pytest.raises(FileNotFoundError):
        export_wiki(root, p, h)
    assert (root / ("u-" + _digest("alice")) / "总览.md").exists()


def test_manifest_cannot_delete_arbitrary_files(store):
    p, h, root = store
    export_wiki(root, p, h)
    note = root / "private.md"
    note.write_text("keep")
    manifest = root / ".profile-wiki-manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["files"].append("private.md")
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        export_wiki(root, p, h)
    assert note.read_text() == "keep"


def test_wiki_edits_never_write_back(store):
    p, h, root = store
    put(h, "alice", {"family_size": 3}, True)
    export_wiki(root, p, h)
    page = root / ("u-" + _digest("alice")) / "家庭节能.md"
    page.write_text("family_size: 99", encoding="utf-8")
    export_wiki(root, p, h)
    assert "99" not in page.read_text(encoding="utf-8")
    with closing(sqlite3.connect(h)) as c:
        assert json.loads(c.execute("SELECT profile_json FROM household_profiles").fetchone()[0])["family_size"] == 3


def test_sync_failure_isolated(tmp_path, monkeypatch):
    import user_profile.obsidian_export as module
    config = tmp_path / "config.json"
    config.write_text('{"enabled": true, "destination": "unused"}')
    monkeypatch.setattr(module, "CONFIG_PATH", config)
    monkeypatch.setattr(module, "export_wiki", lambda *a: (_ for _ in ()).throw(RuntimeError("offline")))
    assert sync_configured_wiki() is None


def test_scheduler_registers_observation_job(monkeypatch):
    import scheduler
    # No real threads, RAG rebuilds or production sync in this registration test.
    class FakeScheduler:
        def __init__(self, **kwargs):
            self.jobs = {}
        def add_job(self, func, *args, **kwargs):
            self.jobs[kwargs["id"]] = (func, kwargs)
        def start(self):
            pass
        def get_jobs(self):
            return list(self.jobs)
    monkeypatch.setattr(scheduler, "_scheduler", None)
    monkeypatch.setattr(scheduler, "BackgroundScheduler", FakeScheduler)
    monkeypatch.setattr(scheduler.threading.Thread, "start", lambda self: None)
    sched = scheduler.start_scheduler()
    func, config = sched.jobs["profile_observation_wiki"]
    assert func is sync_configured_wiki
    assert config["seconds"] == 60 and config["max_instances"] == 1
