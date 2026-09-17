"""One-way, local-only observation wiki. Never reads wiki text into user profiles.

LLM/profile inference stays upstream. This projection deliberately does not turn
model prose, default values, or repeated observations into confirmed evidence.
"""
from __future__ import annotations

import hashlib
from contextlib import closing
import html
import json
import logging
import os
import re
from pathlib import Path
import sqlite3
import threading
from datetime import datetime, timezone

from paths import DATA_DIR, USER_PROFILES_DB, HOUSEHOLDS_DB

log = logging.getLogger(__name__)
_lock = threading.Lock()
CONFIG_PATH = DATA_DIR / "profile_wiki_config.json"
from agent.energy.personalization import FIELDS as HOUSEHOLD_FIELDS
TRAVEL_FIELDS = (
    "preferred_mode", "preferred_modes", "transport_mode", "commute_mode",
    "max_duration_min", "max_cycling_minutes", "max_walking_minutes",
    "rain_preference", "budget", "frequency",
)


def _digest(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:24]


def _text(value):
    """Strip active Markdown/HTML and redact PII even inside allowed fields."""
    from utils.pii import mask_phone, mask_email, mask_id_card, mask_bank_card
    value = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    for masker in (mask_phone, mask_email, mask_id_card, mask_bank_card):
        value = masker(value)
    # Free text in otherwise allowed legacy fields may still contain an address.
    value = re.sub(r"[\w\u4e00-\u9fff]{0,20}(?:路|街|巷|栋|单元|室)[\w\u4e00-\u9fff-]{0,30}", "（地址已隐藏）", value)
    value = re.sub(r"https?://\S+", "（链接已隐藏）", value)
    value = html.escape(value, quote=False)
    for char in "[]|`#*":
        value = value.replace(char, "")
    return value.replace("\n", " ").replace("\r", " ")[:500]


def _read(path, sql):
    path = Path(path)
    if not path.exists():
        return []
    # Read-only prevents accidental creation/migration of production databases.
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql)]


def _atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _facts(profile, household):
    facts = {}

    def add(key, value, source, status="未确认", observed=""):
        if value is None or value == "" or value == [] or value == {}:
            return
        facts[key] = {"value": _text(value), "source": source,
                      "status": status, "source_updated_at": _text(observed)}

    eco = profile.get("eco_profile") or {}
    for key in ("primary_interests", "behavior_stage", "knowledge_level"):
        add("画像." + key, eco.get(key), "user_profiles.eco_profile." + key)
    learning = profile.get("preference_learning") or {}
    for key in ("confirmed_interests", "inferred_interests", "rejected_topics"):
        # Legacy 'confirmed' labels do not prove an actual source message exists.
        add("学习." + key, learning.get(key), "user_profiles.preference_learning." + key)
    habits = (profile.get("behavior_profile") or {}).get("travel_habits") or {}
    if isinstance(habits, dict):
        for key in TRAVEL_FIELDS:
            add("出行." + key, habits.get(key), "user_profiles.behavior_profile.travel_habits." + key)
    from agent.energy.personalization import resolve_profile
    from agent.energy.models import HouseholdProfile
    merged, sources = resolve_profile(str(profile.get("user_id", "observation")), profile,
        HouseholdProfile.from_dict({**household, "user_id": "observation"}) if household else None)
    usage = (profile.get("behavior_profile") or {}).get("home_energy_usage") or {}
    evidence = usage.get("_evidence") or {}
    for key in HOUSEHOLD_FIELDS:
        value = getattr(merged, key)
        if key not in sources:
            continue
        ev = evidence.get(key) or {}
        confirmed = ev.get("source") == "chat_explicit" and ev.get("value") == value
        add("家庭." + key, value, "user_profiles.behavior_profile.home_energy_usage." + key
            if key in usage else ("user_profiles.basic_info." + ("family_type" if key == "family_size" else "region"))
            if sources.get(key, "").startswith("用户填写") else "household_profiles." + key,
            "对话明确提供" if confirmed else "未确认", ev.get("confirmed_at", "") if confirmed else "")
    return facts


def export_wiki(destination, profiles_db=USER_PROFILES_DB, households_db=HOUSEHOLDS_DB):
    """Export a complete snapshot; failed reads never trigger stale-user cleanup.

    destination is a dedicated generated folder, not the root of a personal vault.
    The manifest owns exact files only. Unmanaged developer notes are preserved.
    """
    with _lock:
        root = Path(destination).resolve()
        profile_rows = _read(profiles_db, "SELECT user_id, profile_data FROM user_profiles")
        house_rows = _read(households_db, "SELECT user_id, profile_json FROM household_profiles")
        profiles = {str(r["user_id"]): json.loads(r["profile_data"]) for r in profile_rows}
        households = {str(r["user_id"]): json.loads(r["profile_json"]) for r in house_rows}
        manifest_path = root / ".profile-wiki-manifest.json"
        old = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        for name, path in (("profiles", profiles_db), ("households", households_db)):
            if old.get("sources", {}).get(name) and not Path(path).exists():
                raise FileNotFoundError("Previously observed source database is missing")
        now = datetime.now(timezone.utc).isoformat()
        current = {"version": 1, "users": {}, "files": [], "sources": {
            "profiles": Path(profiles_db).exists(), "households": Path(households_db).exists()}}
        pages = {}
        index = ["# 绿色画像观察", "", "自动生成的单向观察视图。修改这里不会改变业务画像。",
                 "未确认包含历史默认值和模型推测；数据库字段位置不是原始对话证据。",
                 "变化时间表示同步观察时间，不代表用户表达时间。", ""]
        for uid in sorted(set(profiles) | set(households)):
            alias = "u-" + _digest(uid)
            profile, household = profiles.get(uid, {}), households.get(uid, {})
            facts = _facts(profile, household)
            prev = old.get("users", {}).get(alias, {})
            previous = prev.get("facts", {})
            changes = list(prev.get("changes", []))
            for key in sorted(set(previous) | set(facts)):
                if previous.get(key) != facts.get(key):
                    kind = "移除" if key not in facts else "新增" if key not in previous else "更新"
                    # Do not retain removed/replaced values in generated history.
                    changes.append({"at": now, "kind": kind, "field": key})
            changes = changes[-200:]
            current["users"][alias] = {"facts": facts, "changes": changes}
            index.append(f"- [[{alias}/总览|{alias}]]")

            def page(name, lines):
                rel = f"{alias}/{name}.md"
                pages[rel] = "\n".join(["---", f"profile_alias: {alias}", "generated: true",
                    "tags: [green-profile]", "---", f"# {name}", "",
                    f"[[{alias}/总览|总览]] · [[{alias}/出行|出行]] · [[{alias}/家庭节能|家庭节能]] · "
                    f"[[{alias}/证据|证据]] · [[{alias}/变化记录|变化记录]] · [[{alias}/图谱|图谱]]", ""] + lines) + "\n"

            def fact_lines(prefix):
                return [f"- **{_text(k)}**：{v['value']}（{v['status']}） "
                        f"[[{alias}/证据|查看来源]]" for k, v in facts.items() if k.startswith(prefix)]

            page("总览", [f"内部观察编号：{alias}", "",
                "本页由已存结构化字段生成，不调用额外模型，不编造个人事实。",
                "原始聊天、账户信息、精确位置不导出。", ""] + fact_lines("画像.") + fact_lines("学习."))
            page("出行", fact_lines("出行.") or ["尚无可导出的结构化出行限制；咨询出行不等于偏好某种交通方式。"])
            page("家庭节能", ["这里展示节能对话使用的合并画像。标注对话来源的字段由用户明确提供；其他旧记录仍需核对。", ""] +
                 (fact_lines("家庭.") or ["尚未保存家庭画像。 "]))
            page("证据", [f"- {_text(k)}：`{v['source']}`；状态：{v['status']}；"
                          f"来源时间：{v['source_updated_at'] or '未知'}；不导出原始消息。" for k, v in facts.items()] or ["尚无字段来源。"])
            page("变化记录", [f"- {c['at']}：{c['kind']} {_text(c['field'])}" for c in reversed(changes)] or ["尚无变化。"])
            graph = profile.get("graph") or {}
            nodes = graph.get("nodes") or {}
            if isinstance(nodes, list):
                nodes = {n["node_id"]: n for n in nodes}
            links, node_lines = {}, {}
            for nid, node in nodes.items():
                node_type = node.get("node_type", "unknown")
                # Free-text action/context nodes may contain addresses or raw speech.
                if node_type not in ("user", "interest", "behavior_stage", "knowledge_level", "preference", "household_fact"):
                    continue
                filename = "节点-" + _digest(nid)
                links[nid] = filename
                props = node.get("properties") or {}
                safe_props = {k: _text(props[k]) for k in ("interest_id", "confidence", "source", "stage", "level", "field", "value") if k in props}
                node_lines[nid] = [f"类型：{_text(node_type)}", "", "来源：user_profiles.graph（现有图谱记录，未独立核验）", ""] + [f"- {k}：{v}" for k, v in safe_props.items()]
            graph_lines = []
            for edge in graph.get("edges", []):
                source, target = edge.get("source"), edge.get("target")
                if source in links and target in links:
                    relation = _text(edge.get("relation_type", "RELATED_TO"))
                    line = f"- [[{alias}/{links[source]}]] — {relation} → [[{alias}/{links[target]}]]"
                    graph_lines.append(line)
                    node_lines[source].append(f"- {relation} → [[{alias}/{links[target]}]]")
            for nid, lines in node_lines.items():
                page(links[nid], lines)
            page("图谱", ["仅投影允许的节点类型；行为原文和精确位置不导出。", ""] + graph_lines +
                 [f"- [[{alias}/{name}]]" for name in links.values()])
        pages["画像索引.md"] = "\n".join(index) + "\n"
        # Refuse symlink/junction escapes before writing or deleting any file.
        for rel in set(pages) | set(old.get("files", [])):
            if rel != "画像索引.md" and not re.fullmatch(r"u-[a-f0-9]{24}/(?:总览|出行|家庭节能|证据|变化记录|图谱|节点-[a-f0-9]{24})\.md", rel):
                raise ValueError("Unmanaged file in wiki manifest")
            target = (root / rel).resolve()
            if not target.is_relative_to(root) or target == root:
                raise ValueError("Wiki manifest path escapes destination")
        changed = 0
        for rel, content in pages.items():
            target = root / rel
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                _atomic(target, content)
                changed += 1
        for rel in set(old.get("files", [])) - set(pages):
            target = root / rel
            if target.is_file():
                target.unlink()
        current["files"] = sorted(pages)
        _atomic(manifest_path, json.dumps(current, ensure_ascii=False, indent=2))
        return {"users": len(current["users"]), "pages": len(pages), "changed": changed, "destination": str(root)}


def sync_configured_wiki():
    """Optional scheduled export; exporter errors never break chat or scheduling."""
    try:
        if not CONFIG_PATH.exists():
            return None
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if config.get("enabled"):
            return export_wiki(config["destination"])
    except Exception:
        log.exception("Profile observation wiki sync failed")
    return None
