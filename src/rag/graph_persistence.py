"""
图谱持久化模块
支持JSON存储、增量更新和异步构建
"""

import sys
import json
import threading
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from dataclasses import dataclass, asdict, is_dataclass
from json import JSONEncoder

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root / "src"))


class GraphEncoder(JSONEncoder):
    """图谱专用JSON编码器"""

    def default(self, obj):
        if is_dataclass(obj):
            # 处理dataclass对象
            result = {}
            for key, value in asdict(obj).items():
                if isinstance(value, list):
                    result[key] = [self.default(item) for item in value]
                elif isinstance(value, dict):
                    result[key] = {k: self.default(v) for k, v in value.items()}
                else:
                    result[key] = value
            return result
        try:
            # 尝试标准JSON序列化
            return super().default(obj)
        except TypeError:
            # 如果失败，返回字符串表示
            return str(obj)


@dataclass
class GraphSnapshot:
    """图谱快照"""

    version: str
    created_at: str
    entity_count: int
    relation_count: int
    document_count: int
    checksum: str
    data: Dict[str, Any]


class GraphPersistence:
    """图谱持久化"""

    def __init__(self, persist_path: str = None):
        if persist_path is None:
            project_root = Path(__file__).parent.parent.parent.parent
            persist_path = str(project_root / "data" / "graph_snapshot.json")

        self.persist_path = Path(persist_path)
        self.persist_path.parent.mkdir(exist_ok=True, parents=True)

        self._snapshot: Optional[GraphSnapshot] = None

    def save(self, graph: Dict[str, Any], version: str = "1.0") -> bool:
        """保存图谱到文件

        Args:
            graph: 图谱数据
            version: 版本号

        Returns:
            是否保存成功
        """
        try:
            # 预处理：将Entity对象转换为可序列化的字典
            serializable_graph = self._make_serializable(graph)

            # 计算数据校验和
            data_str = json.dumps(serializable_graph, ensure_ascii=False, sort_keys=True)
            checksum = hashlib.md5(data_str.encode("utf-8")).hexdigest()

            # 统计数据
            entity_count = sum(len(d.get("entities", {})) for d in graph.values())
            relation_count = sum(len(d.get("relations", [])) for d in graph.values())

            snapshot = GraphSnapshot(
                version=version,
                created_at=datetime.now().isoformat(),
                entity_count=entity_count,
                relation_count=relation_count,
                document_count=len(graph),
                checksum=checksum,
                data=serializable_graph,
            )

            # 保存到文件
            with open(self.persist_path, "w", encoding="utf-8") as f:
                json.dump(asdict(snapshot), f, ensure_ascii=False, indent=2)

            self._snapshot = snapshot
            print(f"[GraphPersistence] 图谱已保存: {self.persist_path}")
            print(f"  实体: {entity_count}, 关系: {relation_count}, 文档: {len(graph)}")

            return True

        except Exception as e:
            print(f"[GraphPersistence] 保存失败: {e}")
            return False

    def _make_serializable(self, obj):
        """将对象转换为可序列化的格式"""
        if isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._make_serializable(item) for item in obj]
        elif is_dataclass(obj):
            # dataclass -> dict
            result = {}
            for key, value in asdict(obj).items():
                result[key] = self._make_serializable(value)
            return result
        elif hasattr(obj, "__dict__"):
            # 普通对象 -> dict
            return {k: self._make_serializable(v) for k, v in obj.__dict__.items()}
        else:
            return obj

    def load(self) -> Optional[Dict[str, Any]]:
        """从文件加载图谱

        Returns:
            图谱数据，失败返回None
        """
        if not self.persist_path.exists():
            print(f"[GraphPersistence] 快照文件不存在: {self.persist_path}")
            return None

        try:
            with open(self.persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            snapshot = GraphSnapshot(**data)
            self._snapshot = snapshot

            print(f"[GraphPersistence] 图谱已加载: {self.persist_path}")
            print(f"  实体: {snapshot.entity_count}, 关系: {snapshot.relation_count}")
            print(f"  创建时间: {snapshot.created_at}")

            return snapshot.data

        except Exception as e:
            print(f"[GraphPersistence] 加载失败: {e}")
            return None

    def exists(self) -> bool:
        """检查快照是否存在"""
        return self.persist_path.exists()

    def get_snapshot_info(self) -> Optional[Dict[str, Any]]:
        """获取快照信息"""
        if not self.exists():
            return None

        if self._snapshot is None:
            self.load()

        if self._snapshot:
            return {
                "version": self._snapshot.version,
                "created_at": self._snapshot.created_at,
                "entity_count": self._snapshot.entity_count,
                "relation_count": self._snapshot.relation_count,
                "document_count": self._snapshot.document_count,
                "checksum": self._snapshot.checksum,
            }
        return None

    def verify_integrity(self, graph: Dict[str, Any]) -> bool:
        """验证图谱完整性

        Args:
            graph: 图谱数据

        Returns:
            是否完整
        """
        if not self.exists():
            return False

        if self._snapshot is None:
            self.load()

        if not self._snapshot:
            return False

        # 重新计算校验和
        data_str = json.dumps(graph, ensure_ascii=False, sort_keys=True)
        checksum = hashlib.md5(data_str.encode("utf-8")).hexdigest()

        return checksum == self._snapshot.checksum


class IncrementalBuilder:
    """增量构建器"""

    def __init__(self, graph: Dict[str, Any] = None):
        # 全局图谱
        self._graph = graph or {}

        # 文档哈希（用于检测变化）
        self._doc_hashes: Dict[str, str] = {}

        # 增量更新标志
        self._incremental = True

        # 最后更新时间
        self._last_update = datetime.now().isoformat()

    @property
    def graph(self) -> Dict[str, Any]:
        return self._graph

    def update_document(self, doc_id: str, content: str, entities: List[Any], relations: List[Any]):
        """更新单个文档

        Args:
            doc_id: 文档ID
            content: 文档内容
            entities: 实体列表
            relations: 关系列表
        """
        # 计算内容哈希
        content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()

        # 检查是否有变化
        if self._doc_hashes.get(doc_id) == content_hash:
            return  # 没有变化，跳过

        # 更新图谱
        self._graph[doc_id] = {"entities": {}, "relations": relations}

        # 添加实体
        for entity in entities:
            self._graph[doc_id]["entities"][entity.name] = {
                "entity": entity,
                "content": content[:200],  # 保存部分内容作为上下文
                "source": doc_id,
            }

        # 更新哈希
        self._doc_hashes[doc_id] = content_hash

        # 更新时间
        self._last_update = datetime.now().isoformat()

    def remove_document(self, doc_id: str):
        """移除文档

        Args:
            doc_id: 文档ID
        """
        if doc_id in self._graph:
            del self._graph[doc_id]
        if doc_id in self._doc_hashes:
            del self._doc_hashes[doc_id]

        self._last_update = datetime.now().isoformat()

    def get_document_ids(self) -> List[str]:
        """获取所有文档ID"""
        return list(self._graph.keys())

    def has_document(self, doc_id: str) -> bool:
        """检查文档是否存在"""
        return doc_id in self._graph

    def get_last_update_time(self) -> str:
        """获取最后更新时间"""
        return self._last_update


class AsyncGraphBuilder:
    """异步图谱构建器"""

    def __init__(self, knowledge_base_path: str = None):
        if knowledge_base_path is None:
            project_root = Path(__file__).parent.parent.parent.parent
            knowledge_base_path = str(project_root / "knowledge_base")

        self.knowledge_base_path = Path(knowledge_base_path)

        self._graph: Dict[str, Any] = {}
        self._builder = IncrementalBuilder(self._graph)

        self._build_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._building = False

        self._callbacks: List[Callable] = []

    def register_callback(self, callback: Callable):
        """注册构建完成回调"""
        self._callbacks.append(callback)

    def build_async(self):
        """异步构建图谱"""
        if self._building:
            print("[AsyncGraphBuilder] 构建已在进行中")
            return

        self._stop_event.clear()
        self._building = True

        def _build_loop():
            print("[AsyncGraphBuilder] 开始异步构建图谱...")
            try:
                self._do_build()
            except Exception as e:
                print(f"[AsyncGraphBuilder] 构建失败: {e}")
            finally:
                self._building = False

            # 执行回调
            for callback in self._callbacks:
                try:
                    callback(self._graph)
                except Exception as e:
                    print(f"[AsyncGraphBuilder] 回调执行失败: {e}")

        self._build_thread = threading.Thread(target=_build_loop, daemon=True)
        self._build_thread.start()

    def _do_build(self):
        """执行构建"""
        from rag.graphrag import GraphRAGEngine

        engine = GraphRAGEngine(str(self.knowledge_base_path))

        # 如果有持久化文件，加载它
        persistence = GraphPersistence()
        if persistence.exists():
            loaded_graph = persistence.load()
            if loaded_graph:
                self._graph = loaded_graph
                self._builder = IncrementalBuilder(self._graph)
                print(f"[AsyncGraphBuilder] 从快照加载了 {len(self._graph)} 个文档")
                return

        # 否则执行完整构建
        engine.initialize()
        self._graph = engine.graph
        self._builder = IncrementalBuilder(self._graph)

        # 保存快照
        persistence.save(self._graph)

    def stop(self):
        """停止构建"""
        self._stop_event.set()
        if self._build_thread:
            self._build_thread.join(timeout=5)

        self._building = False

    def is_building(self) -> bool:
        """是否正在构建"""
        return self._building

    @property
    def graph(self) -> Dict[str, Any]:
        return self._graph


# 单元测试
if __name__ == "__main__":
    print("=" * 60)
    print("Graph Persistence Test")
    print("=" * 60)

    # 测试持久化
    persistence = GraphPersistence("D:/绿色低碳智能体/data/test_graph.json")

    test_graph = {
        "doc1": {
            "entities": {
                "碳排放": {"name": "碳排放", "type": "concept"},
                "骑行": {"name": "骑行", "type": "action"},
            },
            "relations": [
                {
                    "source": "action:骑行",
                    "target": "concept:碳排放",
                    "type": "reduces",
                    "weight": 1.0,
                }
            ],
        }
    }

    print("\n[1] 保存图谱...")
    persistence.save(test_graph)

    print("\n[2] 加载图谱...")
    loaded = persistence.load()
    print(f"  Loaded {len(loaded) if loaded else 0} documents")

    print("\n[3] 增量构建器...")
    builder = IncrementalBuilder()
    builder.update_document("doc1", "content here", [], [])
    print(f"  Documents: {builder.get_document_ids()}")

    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)
