"""
用户画像知识图谱
基于图结构存储和查询用户画像，支持多跳推理个性化分析
"""

import sys
from pathlib import Path

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field

try:
    import networkx as nx

    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


@dataclass
class ProfileNode:
    """画像节点"""

    node_id: str
    node_type: str  # user, interest, action, behavior_stage, knowledge_level, preference
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "properties": self.properties,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ProfileEdge:
    """画像边"""

    source: str
    target: str
    relation_type: str  # HAS_INTEREST, PERFORMS, AT_STAGE, REJECTS, etc.
    weight: float = 1.0
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "relation_type": self.relation_type,
            "weight": self.weight,
            "properties": self.properties,
            "created_at": self.created_at,
        }


class UserProfileGraph:
    """
    用户画像知识图谱

    支持：
    - 添加用户兴趣、行为、偏好节点
    - 节点间关系建立
    - 图遍历查询个性化推荐
    - 多跳推理路径查找
    """

    # 关系类型定义
    RELATION_TYPES = {
        "HAS_INTEREST": {"inverse": "INTERESTED_BY", "weight_default": 0.8},
        "PERFORMS": {"inverse": "PERFORMED_BY", "weight_default": 1.0},
        "AT_STAGE": {"inverse": "STAGE_OF", "weight_default": 1.0},
        "HAS_KNOWLEDGE": {"inverse": "KNOWLEDGE_OF", "weight_default": 1.0},
        "REJECTS": {"inverse": "REJECTED_BY", "weight_default": 0.5},
        "PREFERS": {"inverse": "PREFERRED_BY", "weight_default": 0.7},
        "RELATED_TO": {"inverse": "RELATED_TO", "weight_default": 0.3},
        "ENABLES": {"inverse": "ENABLED_BY", "weight_default": 0.6},
        "ACHIEVES": {"inverse": "ACHIEVED_BY", "weight_default": 0.6},
    }

    # 兴趣类别映射
    INTEREST_CATEGORIES = {
        "low_carbon_travel": "出行",
        "energy_saving": "家居",
        "waste_classification": "垃圾",
        "green_consumption": "消费",
        "diet_eco": "饮食",
        "water_conservation": "用水",
        "renewable_energy": "能源",
        "carbon_offset": "碳补偿",
    }

    # 行为阶段层级
    BEHAVIOR_STAGES = ["无意向", "意向", "准备", "行动", "维持"]

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.nodes: Dict[str, ProfileNode] = {}
        self.edges: List[ProfileEdge] = []

        if HAS_NETWORKX:
            self._graph = nx.DiGraph()
        else:
            self._graph = None

        self._now = datetime.now().isoformat()

        # 初始化用户根节点
        self._init_user_node()

    def _init_user_node(self):
        """初始化用户根节点"""
        user_node = ProfileNode(
            node_id=f"user_{self.user_id}",
            node_type="user",
            properties={"user_id": self.user_id},
            created_at=self._now,
            updated_at=self._now,
        )
        self.nodes[user_node.node_id] = user_node

        if self._graph is not None:
            self._graph.add_node(user_node.node_id, **user_node.to_dict())

    def add_interest(self, interest_id: str, confidence: float = 0.5, source: str = "inferred"):
        """
        添加用户兴趣

        Args:
            interest_id: 兴趣ID (如 low_carbon_travel)
            confidence: 置信度 0-1
            source: 来源 (explicit=用户明确表达, inferred=推测)
        """
        node_id = f"interest_{interest_id}"
        if node_id not in self.nodes:
            category = self.INTEREST_CATEGORIES.get(interest_id, "其他")
            node = ProfileNode(
                node_id=node_id,
                node_type="interest",
                properties={
                    "interest_id": interest_id,
                    "name": category,
                    "confidence": confidence,
                    "source": source,
                },
                created_at=self._now,
                updated_at=self._now,
            )
            self.nodes[node_id] = node

            if self._graph is not None:
                self._graph.add_node(node_id, **node.to_dict())

        # P4-G: 去重边 — 同一 user-兴趣对只保留一条边, 取最高置信度
        user_node = f"user_{self.user_id}"
        existing_edge = None
        for e in self.edges:
            if e.source == user_node and e.target == node_id and e.relation_type == "HAS_INTEREST":
                existing_edge = e
                break
        if existing_edge is None:
            self._add_edge(user_node, node_id, "HAS_INTEREST", weight=confidence)
        else:
            # 已有边:更新置信度为本次与上次较高者
            existing_edge.weight = max(existing_edge.weight or 0, confidence)
            existing_edge.properties["confidence"] = existing_edge.weight
            existing_edge.updated_at = self._now
            # 同步更新节点上的 confidence
            if node_id in self.nodes:
                self.nodes[node_id].properties["confidence"] = existing_edge.weight
                self.nodes[node_id].updated_at = self._now

        return node_id

    def add_action(
        self,
        action: str,
        sentiment: str = "positive",
        context: str = "",
        carbon_saved: float = None,
    ):
        """
        记录用户行为

        Args:
            action: 行为描述
            sentiment: 情感 (positive/negative)
            context: 上下文
            carbon_saved: P4-C 新增:该行为带来的碳减排量(kg CO2e)
        """
        # P4-G: 同一行为(action 文本相同)在 user 节点上只保留一条节点+边
        # 已有则只更新元数据(碳减排、context、sentiment)
        for existing in self.nodes.values():
            if existing.node_type == "action" and existing.properties.get("action") == action:
                # 更新元数据
                if carbon_saved is not None:
                    existing.properties["carbon_saved"] = (
                        existing.properties.get("carbon_saved") or 0
                    ) + carbon_saved
                if context:
                    existing.properties["context"] = context
                existing.properties["sentiment"] = sentiment
                existing.updated_at = self._now
                if self._graph is not None:
                    self._graph.nodes[existing.node_id].update(existing.properties)
                return existing.node_id

        action_count = len([n for n in self.nodes.values() if n.node_type == "action"])
        node_id = f"action_{action_count + 1}"

        node = ProfileNode(
            node_id=node_id,
            node_type="action",
            properties={
                "action": action,
                "sentiment": sentiment,
                "context": context,
                "carbon_saved": carbon_saved,
            },
            created_at=self._now,
            updated_at=self._now,
        )
        self.nodes[node_id] = node

        if self._graph is not None:
            self._graph.add_node(node_id, **node.to_dict())

        # 建立用户-行为关系
        weight = 1.0 if sentiment == "positive" else 0.5
        self._add_edge(f"user_{self.user_id}", node_id, "PERFORMS", weight=weight)

        return node_id

    def set_behavior_stage(self, stage: str):
        """设置用户行为阶段"""
        if stage not in self.BEHAVIOR_STAGES:
            return None

        node_id = f"stage_{stage}"
        if node_id not in self.nodes:
            node = ProfileNode(
                node_id=node_id,
                node_type="behavior_stage",
                properties={"stage": stage, "level": self.BEHAVIOR_STAGES.index(stage)},
                created_at=self._now,
                updated_at=self._now,
            )
            self.nodes[node_id] = node

            if self._graph is not None:
                self._graph.add_node(node_id, **node.to_dict())

        # 建立用户-阶段关系
        self._add_edge(f"user_{self.user_id}", node_id, "AT_STAGE", weight=1.0)

        return node_id

    def add_rejection(self, topic: str, reason: str = ""):
        """记录用户拒绝的话题"""
        rejected_count = len([n for n in self.nodes.values() if n.node_type == "rejected"])
        node_id = f"rejected_{rejected_count + 1}"

        node = ProfileNode(
            node_id=node_id,
            node_type="rejected",
            properties={"topic": topic, "reason": reason},
            created_at=self._now,
            updated_at=self._now,
        )
        self.nodes[node_id] = node

        if self._graph is not None:
            self._graph.add_node(node_id, **node.to_dict())

        # 建立用户-拒绝关系
        self._add_edge(f"user_{self.user_id}", node_id, "REJECTS", weight=0.5)

        return node_id

    def add_knowledge_level(self, level: str):
        """设置用户知识水平 (beginner/intermediate/advanced)"""
        node_id = f"knowledge_{level}"

        if node_id not in self.nodes:
            level_value = {"beginner": 1, "intermediate": 2, "advanced": 3}.get(level, 2)
            node = ProfileNode(
                node_id=node_id,
                node_type="knowledge_level",
                properties={"level": level, "value": level_value},
                created_at=self._now,
                updated_at=self._now,
            )
            self.nodes[node_id] = node

            if self._graph is not None:
                self._graph.add_node(node_id, **node.to_dict())

        self._add_edge(f"user_{self.user_id}", node_id, "HAS_KNOWLEDGE", weight=1.0)

        return node_id

    def _add_edge(self, source: str, target: str, relation: str, weight: float = 1.0):
        """添加边"""
        edge = ProfileEdge(
            source=source,
            target=target,
            relation_type=relation,
            weight=weight,
            created_at=self._now,
        )
        self.edges.append(edge)

        if self._graph is not None:
            self._graph.add_edge(source, target, relation=relation, weight=weight)

    def get_interests(self) -> List[Tuple[str, float]]:
        """获取用户兴趣及置信度"""
        results = []
        for edge in self.edges:
            if edge.source == f"user_{self.user_id}" and edge.relation_type == "HAS_INTEREST":
                node = self.nodes.get(edge.target)
                if node:
                    confidence = node.properties.get("confidence", 0.5)
                    results.append((node.properties.get("interest_id", ""), confidence))
        return sorted(results, key=lambda x: x[1], reverse=True)

    def get_actions(self) -> List[str]:
        """获取用户所有行为(P4-C 新增)"""
        results = []
        for edge in self.edges:
            if edge.source == f"user_{self.user_id}" and edge.relation_type == "PERFORMS":
                node = self.nodes.get(edge.target)
                if node:
                    results.append(node.properties.get("action", ""))
        return [a for a in results if a]

    def get_behavior_stage(self) -> Optional[str]:
        """获取用户行为阶段"""
        for edge in self.edges:
            if edge.source == f"user_{self.user_id}" and edge.relation_type == "AT_STAGE":
                node = self.nodes.get(edge.target)
                if node:
                    return node.properties.get("stage")
        return None

    def get_knowledge_level(self) -> Optional[str]:
        """获取用户知识水平"""
        for edge in self.edges:
            if edge.source == f"user_{self.user_id}" and edge.relation_type == "HAS_KNOWLEDGE":
                node = self.nodes.get(edge.target)
                if node:
                    return node.properties.get("level")
        return None

    def get_rejected_topics(self) -> List[str]:
        """获取用户拒绝的话题"""
        results = []
        for edge in self.edges:
            if edge.source == f"user_{self.user_id}" and edge.relation_type == "REJECTS":
                node = self.nodes.get(edge.target)
                if node:
                    results.append(node.properties.get("topic", ""))
        return results

    def query_personalized_actions(
        self, max_depth: int = 3, min_confidence: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        图谱查询：基于用户当前状态查询适合的行动

        Returns:
            行动列表，包含推理路径
        """
        if not HAS_NETWORKX or not self._graph:
            return []

        results = []
        user_node = f"user_{self.user_id}"

        # 获取用户当前状态
        stage = self.get_behavior_stage()
        interests = self.get_interests()
        knowledge = self.get_knowledge_level()
        rejected = set(self.get_rejected_topics())

        # 行为阶段对应的推荐难度
        stage_difficulty_map = {
            "无意向": ["easy"],
            "意向": ["easy", "medium"],
            "准备": ["easy", "medium"],
            "行动": ["medium", "hard"],
            "维持": ["hard"],
        }

        # 兴趣到行动的映射
        interest_action_map = {
            "low_carbon_travel": [
                {"action": "短距离骑行", "difficulty": "easy", "carbon_saving": "0.5-2kg"},
                {"action": "公交出行一天", "difficulty": "easy", "carbon_saving": "2-5kg"},
                {"action": "拼车通勤", "difficulty": "medium", "carbon_saving": "3-6kg"},
            ],
            "energy_saving": [
                {"action": "关闭待机电源", "difficulty": "easy", "carbon_saving": "0.3-1kg"},
                {"action": "调低热水器温度", "difficulty": "easy", "carbon_saving": "1-3kg"},
                {"action": "安装智能插座", "difficulty": "medium", "carbon_saving": "5-10kg"},
            ],
            "waste_classification": [
                {"action": "厨余垃圾分开", "difficulty": "easy", "carbon_saving": "0.2-0.5kg"},
                {"action": "可回收物分类", "difficulty": "easy", "carbon_saving": "0.3-0.8kg"},
            ],
            "green_consumption": [
                {"action": "自带环保袋购物", "difficulty": "easy", "carbon_saving": "0.1-0.3kg"},
                {"action": "减少一次性餐具", "difficulty": "easy", "carbon_saving": "0.2-0.5kg"},
            ],
            "carbon_offset": [
                {"action": "种植一棵树", "difficulty": "medium", "carbon_saving": "5-10kg/年"},
                {"action": "碳汇投资", "difficulty": "medium", "carbon_saving": "可量化"},
            ],
        }

        # 基于兴趣推荐行动
        for interest_id, confidence in interests:
            if confidence < min_confidence:
                continue

            if interest_id in interest_action_map:
                allowed_difficulties = stage_difficulty_map.get(stage, ["easy", "medium"])

                for action_info in interest_action_map[interest_id]:
                    if action_info["difficulty"] in allowed_difficulties:
                        # 构建推理路径
                        path = self._build_reasoning_path(interest_id, action_info["action"])

                        results.append(
                            {
                                "action": action_info["action"],
                                "difficulty": action_info["difficulty"],
                                "carbon_saving": action_info["carbon_saving"],
                                "confidence": confidence,
                                "interest": interest_id,
                                "reasoning_path": path,
                                "stage_match": stage or "unknown",
                            }
                        )

        # 按置信度排序
        results.sort(key=lambda x: x["confidence"], reverse=True)

        return results[:10]  # 最多返回10个

    def _build_reasoning_path(self, interest_id: str, action: str) -> str:
        """构建推理路径说明"""
        interest_name = self.INTEREST_CATEGORIES.get(interest_id, interest_id)

        stage = self.get_behavior_stage()
        stage_descriptions = {
            "无意向": "了解环保意义",
            "意向": "开始考虑行动",
            "准备": "准备采取行动",
            "行动": "正在执行",
            "维持": "保持良好习惯",
        }

        if stage:
            return f"您对 {interest_name} 感兴趣（{stage_descriptions.get(stage, '')}），推荐：{action}"
        else:
            return f"您对 {interest_name} 感兴趣，推荐：{action}"

    def get_interest_path(self, from_interest: str, to_action: str) -> List[str]:
        """
        查询从兴趣到行动的推理路径
        用于生成"因为您对X感兴趣，而X可以通过Y实现..."类型的个性化解释
        """
        path = [from_interest]

        # 简化的路径构建
        interest_action_links = {
            "low_carbon_travel": {"骑行": "减少碳排放", "公交": "公共交通"},
            "energy_saving": {"关灯": "减少用电", "空调": "降低能耗"},
            "green_consumption": {"环保袋": "减少塑料", "一次性筷": "森林保护"},
        }

        if from_interest in interest_action_links:
            links = interest_action_links[from_interest]
            for key, value in links.items():
                if key in to_action:
                    path.append(value)
                    path.append(to_action)
                    break

        return path

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典"""
        return {
            "user_id": self.user_id,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfileGraph":
        """从字典恢复"""
        graph = cls(data["user_id"])
        graph.nodes = {n["node_id"]: ProfileNode(**n) for n in data.get("nodes", [])}
        graph.edges = [ProfileEdge(**e) for e in data.get("edges", [])]

        if HAS_NETWORKX and graph._graph:
            for node_id, node in graph.nodes.items():
                graph._graph.add_node(node_id, **node.to_dict())
            for edge in graph.edges:
                graph._graph.add_edge(
                    edge.source, edge.target, relation=edge.relation_type, weight=edge.weight
                )

        return graph

    def summary(self) -> str:
        """获取图谱摘要"""
        stage = self.get_behavior_stage()
        interests = self.get_interests()
        knowledge = self.get_knowledge_level()
        rejected = self.get_rejected_topics()

        parts = [f"用户 {self.user_id} 画像图谱"]

        if stage:
            parts.append(f"行为阶段: {stage}")
        if knowledge:
            parts.append(f"知识水平: {knowledge}")
        if interests:
            interest_str = ", ".join([f"{i[0]}({i[1]:.2f})" for i in interests[:3]])
            parts.append(f"兴趣: {interest_str}")
        if rejected:
            parts.append(f"已拒绝话题: {', '.join(rejected[:2])}")

        parts.append(f"节点数: {len(self.nodes)}, 边数: {len(self.edges)}")

        return " | ".join(parts)
