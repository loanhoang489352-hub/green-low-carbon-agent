"""
P13 Step 2: KnowledgeGraph SQLite 持久化

设计要点:
  · 3 张表:kg_entities / kg_relations / kg_sources
  · 节点类型对应 ontology 实体:concept → Goal, action → Action, policy → Policy, metric → Bill, location → Household
  · 关系类型对应 ontology 关系(子集)
  · 提供 CRUD + n_hop_subgraph() 子图查询
  · 提供 add_extraction() 一次性插入 entity-relation-entity + 它们的 source(批量)
  · 不依赖 networkx,纯 SQL,启动时 init_schema() 幂等迁移

表结构:
  kg_entities(id, entity_type, name, properties_json, source_doc, created_at)
  kg_relations(id, source_entity, target_entity, relation_type, properties_json, weight, created_at)
  kg_sources(id, entity_id | relation_id, doc_id, quote, created_at)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from paths import DATA_DIR

_log = logging.getLogger(__name__)

_DEFAULT_DB = DATA_DIR / "knowledge_graph.db"

# 实体类型 → ontology 实体映射(与 config/ontology.json 同步)
ENTITY_TYPE_MAPPING = {
    "concept": "Goal",
    "action": "Action",
    "policy": "Policy",
    "metric": "Bill",
    "location": "Household",
}

# 允许的关系类型(子集,够用即可)
ALLOWED_RELATION_TYPES = {
    "CITES",         # Action → Policy
    "AFFORDS",       # Action → Goal
    "CONTAINS",      # Policy → Concept
    "APPLIES_TO",    # Action → Location
    "RELATED_TO",    # 任意
    "MEASURED_BY",   # Concept → Metric
    "PRACTICES",     # User → Habit (画像侧会用,但这里保留)
}


@dataclass
class KGEntity:
    entity_type: str  # raw: concept/action/policy/metric/location
    name: str
    id: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)
    source_doc: str = ""
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "entity_type": self.entity_type,
            "name": self.name,
            "properties": self.properties,
            "source_doc": self.source_doc,
            "created_at": self.created_at,
        }


@dataclass
class KGRelation:
    source_entity: str
    target_entity: str
    relation_type: str
    id: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_entity": self.source_entity,
            "target_entity": self.target_entity,
            "relation_type": self.relation_type,
            "properties": self.properties,
            "weight": self.weight,
            "created_at": self.created_at,
        }


@dataclass
class Subgraph:
    """N-hop 子图查询结果"""
    entities: List[KGEntity] = field(default_factory=list)
    relations: List[KGRelation] = field(default_factory=list)
    roots: List[str] = field(default_factory=list)
    hop_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "relations": [r.to_dict() for r in self.relations],
            "roots": self.roots,
            "hop_count": self.hop_count,
        }


class KnowledgeGraphStore:
    """KnowledgeGraph SQLite 存储层 — 线程安全"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.init_schema()

    # ============ 连接 ============

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.db_path), timeout=10)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        c.execute("PRAGMA foreign_keys=ON")
        c.row_factory = sqlite3.Row
        return c

    # ============ Schema ============

    def init_schema(self) -> None:
        """幂等初始化 3 张表"""
        with self._lock:
            with closing(self._conn()) as c:
                c.executescript("""
                CREATE TABLE IF NOT EXISTS kg_entities (
                    id           TEXT PRIMARY KEY,
                    entity_type  TEXT NOT NULL,
                    name         TEXT NOT NULL,
                    properties_json TEXT NOT NULL DEFAULT '{}',
                    source_doc   TEXT NOT NULL DEFAULT '',
                    created_at   TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS kg_relations (
                    id              TEXT PRIMARY KEY,
                    source_entity   TEXT NOT NULL,
                    target_entity   TEXT NOT NULL,
                    relation_type   TEXT NOT NULL,
                    properties_json TEXT NOT NULL DEFAULT '{}',
                    weight          REAL NOT NULL DEFAULT 1.0,
                    created_at      TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (source_entity) REFERENCES kg_entities(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_entity) REFERENCES kg_entities(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS kg_sources (
                    id          TEXT PRIMARY KEY,
                    entity_id   TEXT,
                    relation_id TEXT,
                    doc_id      TEXT NOT NULL,
                    quote       TEXT NOT NULL DEFAULT '',
                    created_at  TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (entity_id) REFERENCES kg_entities(id) ON DELETE CASCADE,
                    FOREIGN KEY (relation_id) REFERENCES kg_relations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_kg_entities_type ON kg_entities(entity_type);
                CREATE INDEX IF NOT EXISTS idx_kg_entities_name ON kg_entities(name);
                CREATE INDEX IF NOT EXISTS idx_kg_relations_source ON kg_relations(source_entity);
                CREATE INDEX IF NOT EXISTS idx_kg_relations_target ON kg_relations(target_entity);
                CREATE INDEX IF NOT EXISTS idx_kg_relations_type ON kg_relations(relation_type);
                CREATE INDEX IF NOT EXISTS idx_kg_sources_doc ON kg_sources(doc_id);
                """)
                c.commit()

    # ============ 实体 CRUD ============

    def add_entity(self, entity: KGEntity) -> str:
        """添加实体(已存在则更新)"""
        if not entity.id:
            entity.id = "ent-" + uuid.uuid4().hex[:12]
        if not entity.created_at:
            entity.created_at = datetime.utcnow().isoformat() + "Z"
        with self._lock:
            with closing(self._conn()) as c:
                c.execute("""
                    INSERT OR REPLACE INTO kg_entities
                      (id, entity_type, name, properties_json, source_doc, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    entity.id, entity.entity_type, entity.name,
                    json.dumps(entity.properties, ensure_ascii=False),
                    entity.source_doc, entity.created_at,
                ))
                c.commit()
        return entity.id

    def get_entity(self, entity_id: str) -> Optional[KGEntity]:
        with self._lock:
            with closing(self._conn()) as c:
                row = c.execute(
                    "SELECT * FROM kg_entities WHERE id = ?", (entity_id,)
                ).fetchone()
        if not row:
            return None
        return KGEntity(
            id=row["id"],
            entity_type=row["entity_type"],
            name=row["name"],
            properties=json.loads(row["properties_json"] or "{}"),
            source_doc=row["source_doc"],
            created_at=row["created_at"],
        )

    def find_entity_by_name(self, name: str, entity_type: Optional[str] = None) -> Optional[KGEntity]:
        """按 name 查(知识图谱常用:同名复用)"""
        with self._lock:
            with closing(self._conn()) as c:
                if entity_type:
                    row = c.execute(
                        "SELECT * FROM kg_entities WHERE name = ? AND entity_type = ?",
                        (name, entity_type),
                    ).fetchone()
                else:
                    row = c.execute(
                        "SELECT * FROM kg_entities WHERE name = ? ORDER BY created_at DESC LIMIT 1",
                        (name,),
                    ).fetchone()
        if not row:
            return None
        return self.get_entity(row["id"])

    def list_entities(self, entity_type: Optional[str] = None, limit: int = 100) -> List[KGEntity]:
        with self._lock:
            with closing(self._conn()) as c:
                if entity_type:
                    rows = c.execute(
                        "SELECT * FROM kg_entities WHERE entity_type = ? ORDER BY created_at DESC LIMIT ?",
                        (entity_type, limit),
                    ).fetchall()
                else:
                    rows = c.execute(
                        "SELECT * FROM kg_entities ORDER BY created_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
        return [self.get_entity(r["id"]) for r in rows if r]

    # ============ 关系 CRUD ============

    def add_relation(self, relation: KGRelation) -> str:
        if relation.relation_type not in ALLOWED_RELATION_TYPES:
            raise ValueError(f"未允许的关系类型: {relation.relation_type} (允许: {ALLOWED_RELATION_TYPES})")
        if not relation.id:
            relation.id = "rel-" + uuid.uuid4().hex[:12]
        if not relation.created_at:
            relation.created_at = datetime.utcnow().isoformat() + "Z"
        with self._lock:
            with closing(self._conn()) as c:
                c.execute("""
                    INSERT OR REPLACE INTO kg_relations
                      (id, source_entity, target_entity, relation_type, properties_json, weight, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    relation.id, relation.source_entity, relation.target_entity,
                    relation.relation_type,
                    json.dumps(relation.properties, ensure_ascii=False),
                    relation.weight, relation.created_at,
                ))
                c.commit()
        return relation.id

    def list_relations(self, entity_id: Optional[str] = None,
                       relation_type: Optional[str] = None) -> List[KGRelation]:
        """列关系(可选按实体 / 类型过滤)"""
        with self._lock:
            with closing(self._conn()) as c:
                query = "SELECT * FROM kg_relations WHERE 1=1"
                params: List[Any] = []
                if entity_id:
                    query += " AND (source_entity = ? OR target_entity = ?)"
                    params.extend([entity_id, entity_id])
                if relation_type:
                    query += " AND relation_type = ?"
                    params.append(relation_type)
                rows = c.execute(query, params).fetchall()
        out = []
        for r in rows:
            out.append(KGRelation(
                id=r["id"],
                source_entity=r["source_entity"],
                target_entity=r["target_entity"],
                relation_type=r["relation_type"],
                properties=json.loads(r["properties_json"] or "{}"),
                weight=r["weight"],
                created_at=r["created_at"],
            ))
        return out

    # ============ Source 链接 ============

    def add_source(self, entity_id: Optional[str] = None,
                   relation_id: Optional[str] = None,
                   doc_id: str = "",
                   quote: str = "") -> str:
        sid = "src-" + uuid.uuid4().hex[:12]
        if not entity_id and not relation_id:
            raise ValueError("必须提供 entity_id 或 relation_id 之一")
        with self._lock:
            with closing(self._conn()) as c:
                c.execute("""
                    INSERT INTO kg_sources
                      (id, entity_id, relation_id, doc_id, quote, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    sid, entity_id, relation_id, doc_id, quote,
                    datetime.utcnow().isoformat() + "Z",
                ))
                c.commit()
        return sid

    # ============ N-hop 子图 ============

    def n_hop_subgraph(self, root_entity_ids: List[str], hop: int = 1) -> Subgraph:
        """从根实体出发,扩展 N hop 子图

        实现:BFS,每层 SQL JOIN kg_relations。
        """
        if hop < 0:
            raise ValueError(f"hop 必须 ≥ 0,实际 {hop}")
        if not root_entity_ids:
            return Subgraph(roots=[], hop_count=0)

        visited_entities: Dict[str, KGEntity] = {}
        visited_relations: Dict[str, KGRelation] = {}
        frontier: set = set(root_entity_ids)

        # 把根加入
        for rid in root_entity_ids:
            e = self.get_entity(rid)
            if e:
                visited_entities[rid] = e

        for current_hop in range(1, hop + 1):
            if not frontier:
                break
            placeholders = ",".join("?" for _ in frontier)
            with self._lock:
                with closing(self._conn()) as c:
                    rows = c.execute(f"""
                        SELECT * FROM kg_relations
                        WHERE source_entity IN ({placeholders})
                           OR target_entity IN ({placeholders})
                    """, list(frontier) * 2).fetchall()

            next_frontier: set = set()
            for r in rows:
                rel = KGRelation(
                    id=r["id"], source_entity=r["source_entity"],
                    target_entity=r["target_entity"],
                    relation_type=r["relation_type"],
                    properties=json.loads(r["properties_json"] or "{}"),
                    weight=r["weight"], created_at=r["created_at"],
                )
                visited_relations[rel.id] = rel
                for nid in (rel.source_entity, rel.target_entity):
                    if nid not in visited_entities:
                        e = self.get_entity(nid)
                        if e:
                            visited_entities[nid] = e
                            next_frontier.add(nid)
            frontier = next_frontier

        return Subgraph(
            entities=list(visited_entities.values()),
            relations=list(visited_relations.values()),
            roots=list(root_entity_ids),
            hop_count=hop,
        )

    # ============ 批量插入 ============

    def add_extraction(self,
                       entities: List[KGEntity],
                       relations: List[KGRelation],
                       sources: Optional[List[Dict[str, str]]] = None) -> List[str]:
        """一次性插入 entity-relation-entity + source(原子事务)

        sources 格式:[{entity_id|relation_id, doc_id, quote}]
        """
        eids = []
        rids = []
        with self._lock:
            with closing(self._conn()) as c:
                try:
                    for ent in entities:
                        if not ent.id:
                            ent.id = "ent-" + uuid.uuid4().hex[:12]
                        if not ent.created_at:
                            ent.created_at = datetime.utcnow().isoformat() + "Z"
                        c.execute("""
                            INSERT OR REPLACE INTO kg_entities
                              (id, entity_type, name, properties_json, source_doc, created_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            ent.id, ent.entity_type, ent.name,
                            json.dumps(ent.properties, ensure_ascii=False),
                            ent.source_doc, ent.created_at,
                        ))
                        eids.append(ent.id)

                    for rel in relations:
                        if rel.relation_type not in ALLOWED_RELATION_TYPES:
                            raise ValueError(f"未允许的关系类型: {rel.relation_type}")
                        if not rel.id:
                            rel.id = "rel-" + uuid.uuid4().hex[:12]
                        if not rel.created_at:
                            rel.created_at = datetime.utcnow().isoformat() + "Z"
                        c.execute("""
                            INSERT OR REPLACE INTO kg_relations
                              (id, source_entity, target_entity, relation_type, properties_json, weight, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            rel.id, rel.source_entity, rel.target_entity,
                            rel.relation_type,
                            json.dumps(rel.properties, ensure_ascii=False),
                            rel.weight, rel.created_at,
                        ))
                        rids.append(rel.id)

                    for src in (sources or []):
                        sid = "src-" + uuid.uuid4().hex[:12]
                        c.execute("""
                            INSERT INTO kg_sources
                              (id, entity_id, relation_id, doc_id, quote, created_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            sid, src.get("entity_id"), src.get("relation_id"),
                            src.get("doc_id", ""), src.get("quote", ""),
                            datetime.utcnow().isoformat() + "Z",
                        ))
                    c.commit()
                except Exception:
                    c.rollback()
                    raise
        return eids + rids

    # ============ 统计 ============

    def stats(self) -> Dict[str, int]:
        with self._lock:
            with closing(self._conn()) as c:
                ec = c.execute("SELECT COUNT(*) FROM kg_entities").fetchone()[0]
                rc = c.execute("SELECT COUNT(*) FROM kg_relations").fetchone()[0]
                sc = c.execute("SELECT COUNT(*) FROM kg_sources").fetchone()[0]
        return {"entities": ec, "relations": rc, "sources": sc}

    def clear(self) -> None:
        """测试用 — 清空所有数据"""
        with self._lock:
            with closing(self._conn()) as c:
                c.execute("DELETE FROM kg_sources")
                c.execute("DELETE FROM kg_relations")
                c.execute("DELETE FROM kg_entities")
                c.commit()


# ============ 单例 ============

_kg_store: Optional[KnowledgeGraphStore] = None
_kg_lock = threading.Lock()


def get_kg_store(db_path: Optional[Path] = None) -> KnowledgeGraphStore:
    global _kg_store
    if _kg_store is not None and db_path is None:
        return _kg_store
    with _kg_lock:
        if _kg_store is not None and db_path is None:
            return _kg_store
        _kg_store = KnowledgeGraphStore(db_path)
        _log.info("[kg_store] initialized at %s", _kg_store.db_path)
        return _kg_store


def reset_kg_store() -> None:
    """测试用"""
    global _kg_store
    with _kg_lock:
        _kg_store = None


__all__ = [
    "KGEntity",
    "KGRelation",
    "Subgraph",
    "KnowledgeGraphStore",
    "get_kg_store",
    "reset_kg_store",
    "ENTITY_TYPE_MAPPING",
    "ALLOWED_RELATION_TYPES",
]