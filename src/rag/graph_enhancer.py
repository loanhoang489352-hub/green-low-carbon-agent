"""
图谱增强模块
实体消歧、重要性评分、关系权重计算
"""

import sys
from pathlib import Path
from typing import Dict, List, Tuple, Any
from collections import defaultdict, Counter
from dataclasses import dataclass
import math

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root / "src"))


@dataclass
class EntityScore:
    """实体评分"""

    name: str
    type: str
    importance: float = 0.0
    pagerank: float = 0.0
    degree: int = 0
    in_degree: int = 0
    out_degree: int = 0


@dataclass
class RelationWeight:
    """关系权重"""

    source: str
    target: str
    relation_type: str
    weight: float = 1.0
    cooccurrence_count: int = 1
    semantic_similarity: float = 0.0


class EntityDisambiguator:
    """实体消歧：同名不同义检测"""

    def __init__(self):
        # 常用多义词（需要消歧）
        self.ambiguous_terms = {
            "碳": ["碳元素", "碳排放", "碳中和"],
            "绿色": ["绿色出行", "绿色能源", "绿色建筑"],
            "节能": ["节约能源", "节能技术", "节能减排"],
        }

        # 上下文特征词
        self.context_keywords = {
            "emission": ["排放", "碳排放", "温室气体"],
            "energy": ["能源", "电力", "节能"],
            "travel": ["出行", "交通", "出行方式"],
        }

    def disambiguate(self, entity: str, context: str) -> str:
        """根据上下文消歧

        Args:
            entity: 实体名称
            context: 上下文文本

        Returns:
            消歧后的实体（最可能的含义）
        """
        if entity not in self.ambiguous_terms:
            return entity

        candidates = self.ambiguous_terms[entity]
        scores = {}

        for candidate in candidates:
            score = 0
            for feature_group, keywords in self.context_keywords.items():
                if candidate in feature_group:
                    for kw in keywords:
                        if kw in context:
                            score += 1
            scores[candidate] = score

        if scores:
            return max(scores.keys(), key=lambda x: scores[x])
        return entity

    def build_entity_aliases(self, entity: str, context: str) -> List[str]:
        """构建实体别名列表"""
        aliases = [entity]

        # 添加可能的别名
        if entity in self.ambiguous_terms:
            aliases.extend(self.ambiguous_terms[entity])

        return aliases


class GraphScorer:
    """图谱评分：基于PageRank的重要性计算"""

    def __init__(self, damping: float = 0.85, iterations: int = 20):
        self.damping = damping
        self.iterations = iterations

    def calculate_pagerank(self, graph: Dict[str, Any]) -> Dict[str, float]:
        """计算PageRank

        Args:
            graph: 图谱数据结构

        Returns:
            实体->PageRank分数的映射
        """
        # 构建邻接表
        nodes = set()
        outgoing = defaultdict(set)
        incoming = defaultdict(set)

        for doc_id, doc_data in graph.items():
            for entity_name in doc_data.get("entities", {}).keys():
                nodes.add(entity_name)
                outgoing[entity_name]  # 初始化

            for rel in doc_data.get("relations", []):
                # 关系格式: source:source_name -> target:target_name
                source = rel.source.split(":")[-1] if ":" in rel.source else rel.source
                target = rel.target.split(":")[-1] if ":" in rel.target else rel.target

                if source and target:
                    outgoing[source].add(target)
                    incoming[target].add(source)

        # 初始化PageRank
        n = len(nodes)
        if n == 0:
            return {}

        pagerank = {node: 1.0 / n for node in nodes}

        # 迭代计算
        for _ in range(self.iterations):
            new_pr = {}
            for node in nodes:
                rank_sum = 0.0
                for incoming_node in incoming[node]:
                    out_deg = len(outgoing[incoming_node])
                    if out_deg > 0:
                        rank_sum += pagerank[incoming_node] / out_deg
                new_pr[node] = (1 - self.damping) / n + self.damping * rank_sum

            pagerank = new_pr

        return pagerank

    def calculate_importance(
        self, graph: Dict[str, Any], pagerank: Dict[str, float] = None
    ) -> Dict[str, EntityScore]:
        """计算实体重要性

        Args:
            graph: 图谱数据结构
            pagerank: 可选的预先计算的PageRank

        Returns:
            实体->重要性评分的映射
        """
        if pagerank is None:
            pagerank = self.calculate_pagerank(graph)

        # 计算度数
        in_degree = Counter()
        out_degree = Counter()

        for doc_id, doc_data in graph.items():
            for rel in doc_data.get("relations", []):
                source = rel.source.split(":")[-1] if ":" in rel.source else rel.source
                target = rel.target.split(":")[-1] if ":" in rel.target else rel.target

                if source:
                    out_degree[source] += 1
                if target:
                    in_degree[target] += 1

        # 构建结果
        importance = {}
        for entity_name in pagerank.keys():
            pr = pagerank.get(entity_name, 0)
            out_d = out_degree.get(entity_name, 0)
            in_d = in_degree.get(entity_name, 0)

            # 综合评分：PageRank * 度数权重
            score = pr * (1 + 0.1 * (out_d + in_d))

            importance[entity_name] = EntityScore(
                name=entity_name,
                type=self._get_entity_type(entity_name),
                importance=score,
                pagerank=pr,
                degree=out_d + in_d,
                in_degree=in_d,
                out_degree=out_d,
            )

        return importance

    def _get_entity_type(self, name: str) -> str:
        """获取实体类型"""
        from rag.graphrag import EntityExtractor

        for etype, keywords in EntityExtractor.ENTITY_PATTERNS.items():
            if name in keywords:
                return etype
        return "concept"


class RelationWeightCalculator:
    """关系权重计算"""

    def __init__(self):
        # 关系类型权重基数
        self.relation_base_weights = {
            "causes": 1.0,
            "reduces": 1.0,
            "affects": 0.9,
            "promotes": 0.9,
            "achieves": 0.9,
            "contains": 0.8,
            "belongs_to": 0.8,
            "is_type_of": 0.8,
            "related_to": 0.6,
            "co_occurs": 0.5,
            "via": 0.7,
            "adopts": 0.7,
            "depends_on": 0.7,
        }

    def calculate_weight(
        self,
        relation_type: str,
        cooccurrence_count: int = 1,
        source_importance: float = 0.0,
        target_importance: float = 0.0,
    ) -> float:
        """计算关系权重

        Args:
            relation_type: 关系类型
            cooccurrence_count: 共现次数
            source_importance: 源实体重要性
            target_importance: 目标实体重要性

        Returns:
            计算后的权重值
        """
        # 基础权重
        base_weight = self.relation_base_weights.get(relation_type, 0.5)

        # 共现次数加权（对数衰减）
        freq_weight = math.log2(cooccurrence_count + 1) / math.log2(10)

        # 实体重要性加权
        entity_weight = (source_importance + target_importance) / 2

        # 综合权重
        weight = base_weight * (0.5 + 0.3 * freq_weight + 0.2 * entity_weight)

        return min(weight, 1.0)  # 最高不超过1.0

    def update_relation_weights(
        self, graph: Dict[str, Any], entity_scores: Dict[str, EntityScore]
    ) -> Dict[Tuple[str, str], float]:
        """更新图中所有关系的权重

        Args:
            graph: 图谱数据结构
            entity_scores: 实体评分

        Returns:
            (source, target) -> weight 的映射
        """
        relation_counts = Counter()
        relation_weights = {}

        # 统计共现次数
        for doc_id, doc_data in graph.items():
            rels = doc_data.get("relations", [])
            for rel in rels:
                source = rel.source
                target = rel.target
                key = (source, target, rel.type)
                relation_counts[key] += 1

        # 计算权重
        for (source, target, rel_type), count in relation_counts.items():
            src_name = source.split(":")[-1] if ":" in source else source
            tgt_name = target.split(":")[-1] if ":" in target else target

            src_importance = entity_scores.get(
                src_name, EntityScore(name=src_name, type="concept", importance=0)
            ).importance
            tgt_importance = entity_scores.get(
                tgt_name, EntityScore(name=tgt_name, type="concept", importance=0)
            ).importance

            weight = self.calculate_weight(rel_type, count, src_importance, tgt_importance)

            relation_weights[(source, target)] = weight

        return relation_weights


class GraphEnhancer:
    """图谱增强器（整合上述功能）"""

    def __init__(self):
        self.disambiguator = EntityDisambiguator()
        self.scorer = GraphScorer()
        self.weight_calculator = RelationWeightCalculator()

    def enhance(self, graph: Dict[str, Any], preserve_scores: bool = True) -> Dict[str, Any]:
        """增强图谱

        Args:
            graph: 原始图谱
            preserve_scores: 是否保留评分信息

        Returns:
            增强后的图谱
        """
        # 1. 计算PageRank
        pagerank = self.scorer.calculate_pagerank(graph)

        # 2. 计算实体重要性
        entity_scores = self.scorer.calculate_importance(graph, pagerank)

        # 3. 更新关系权重
        relation_weights = self.weight_calculator.update_relation_weights(graph, entity_scores)

        # 4. 构建增强图谱
        enhanced_graph = {}
        for doc_id, doc_data in graph.items():
            enhanced_doc = {"entities": {}, "relations": []}

            # 增强实体
            for entity_name, entity_data in doc_data.get("entities", {}).items():
                score = entity_scores.get(entity_name)
                if score and preserve_scores:
                    entity_data["importance"] = score.importance
                    entity_data["pagerank"] = score.pagerank
                    entity_data["degree"] = score.degree
                enhanced_doc["entities"][entity_name] = entity_data

            # 增强关系
            for rel in doc_data.get("relations", []):
                key = (rel.source, rel.target)
                weight = relation_weights.get(key, rel.weight)
                rel.weight = weight
                enhanced_doc["relations"].append(rel)

            enhanced_graph[doc_id] = enhanced_doc

        return enhanced_graph

    def get_top_entities(
        self, entity_scores: Dict[str, EntityScore], top_k: int = 10, entity_type: str = None
    ) -> List[EntityScore]:
        """获取最重要的实体

        Args:
            entity_scores: 实体评分
            top_k: 返回数量
            entity_type: 过滤类型

        Returns:
            最重要的实体列表
        """
        scores = list(entity_scores.values())

        if entity_type:
            scores = [s for s in scores if s.type == entity_type]

        scores.sort(key=lambda x: -x.importance)
        return scores[:top_k]


# 单元测试
if __name__ == "__main__":
    print("=" * 60)
    print("Graph Enhancer Test")
    print("=" * 60)

    # 测试实体消歧
    disambiguator = EntityDisambiguator()
    test_cases = [
        ("碳", "碳排放导致温室气体增加"),
        ("碳", "碳中和是中国的目标"),
        ("节能", "我们需要节约用水"),
    ]

    print("\n[Entity Disambiguation]")
    for entity, context in test_cases:
        result = disambiguator.disambiguate(entity, context)
        print(f"  '{entity}' in '{context[:20]}...' -> '{result}'")

    # 测试PageRank计算
    print("\n[PageRank Calculation]")
    scorer = GraphScorer()
    test_graph = {
        "doc1": {
            "entities": {
                "碳排放": {"name": "碳排放", "type": "concept"},
                "骑行": {"name": "骑行", "type": "action"},
            },
            "relations": [
                type(
                    "Relation",
                    (),
                    {
                        "source": "action:骑行",
                        "target": "concept:碳排放",
                        "type": "reduces",
                        "weight": 1.0,
                    },
                )()
            ],
        }
    }
    pr = scorer.calculate_pagerank(test_graph)
    print(f"  PageRank scores: {pr}")

    # 测试关系权重计算
    print("\n[Relation Weight Calculation]")
    calculator = RelationWeightCalculator()
    weight = calculator.calculate_weight(
        "reduces", cooccurrence_count=5, source_importance=0.8, target_importance=0.6
    )
    print(f"  Weight for 'reduces' (count=5): {weight:.3f}")

    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)
