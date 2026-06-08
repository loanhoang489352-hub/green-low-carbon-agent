"""
GraphRAG 引擎
基于知识图谱的检索增强，支持多跳推理问答
"""

import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set
from dataclasses import dataclass, field
from collections import defaultdict
import re

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root / 'src'))


@dataclass
class Entity:
    """实体"""
    id: str
    name: str
    type: str  # concept, action, policy, metric, location
    description: str = ""
    aliases: List[str] = field(default_factory=list)

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        return self.id == other.id


@dataclass
class Relation:
    """关系"""
    source: str  # 源实体ID
    target: str  # 目标实体ID
    type: str    # contains, affects, causes, belongs_to, related_to
    weight: float = 1.0
    description: str = ""

    def __hash__(self):
        return hash((self.source, self.target, self.type))


@dataclass
class GraphResult:
    """图谱检索结果"""
    content: str
    score: float
    entities: List[str]  # 涉及的实体ID列表
    relations: List[str]  # 涉及的边
    path: List[str] = field(default_factory=list)  # 推理路径


class EntityExtractor:
    """实体提取器"""

    ENTITY_PATTERNS = {
        'concept': [
            '碳中和', '碳达峰', '碳足迹', '碳交易', '碳排放', '低碳', '减排',
            '温室气体', '二氧化碳', '可再生能源', '再生能源', '可持续发展'
        ],
        'action': [
            '骑行', '步行', '公交', '地铁', '开车', '拼车', '乘坐', '出行',
            '节能', '省电', '节约', '分类', '回收', '减少', '替换'
        ],
        'policy': [
            '双碳目标', '碳达峰', '碳中和', '政策', '补贴', '奖励', '优惠',
            '碳市场', '碳配额', '碳积分', '绿色认证', '环境标志'
        ],
        'metric': [
            'kg CO2', '碳排放量', '节能效果', '回本周期', '年省电', '年减碳',
            '能效', '碳足迹', '排放量'
        ],
        'location': [
            '北京', '上海', '广州', '深圳', '中国', '全国', '各地', '城市', '农村'
        ]
    }

    def extract(self, text: str) -> List[Entity]:
        """从文本中提取实体"""
        entities = []
        found = set()

        for entity_type, keywords in self.ENTITY_PATTERNS.items():
            for keyword in keywords:
                if keyword in text and keyword not in found:
                    entities.append(Entity(
                        id=f"{entity_type}_{keyword}",
                        name=keyword,
                        type=entity_type,
                        description=f"从文本中识别的{entity_type}类型实体"
                    ))
                    found.add(keyword)

        return entities


class RelationExtractor:
    """关系提取器"""

    # 关系模式：[(触发词, 关系类型, 方向)]
    # 方向1: source在前，target在后
    # 方向-1: target在前，source在后
    RELATION_PATTERNS = [
        # 减少关系
        ('可以减少', 'reduces', 1),
        ('有助于减少', 'reduces', 1),
        ('降低', 'reduces', 1),
        ('减少', 'reduces', 1),
        # 增加关系
        ('导致增加', 'causes', 1),
        ('增加', 'causes', 1),
        ('提高', 'increases', 1),
        # 类型关系
        ('是的一种', 'is_type_of', 1),
        ('属于', 'belongs_to', 1),
        # 包含关系
        ('包括', 'contains', 1),
        ('包含', 'contains', 1),
        ('涵盖', 'contains', 1),
        # 相关关系
        ('与相关', 'related_to', 1),
        ('和相关', 'related_to', 1),
        ('涉及', 'related_to', 1),
        # 影响关系
        ('影响', 'affects', 1),
        ('作用于', 'affects', 1),
        # 促进关系
        ('促进', 'promotes', 1),
        ('推动', 'promotes', 1),
        ('助力', 'promotes', 1),
        # 实现关系
        ('实现', 'achieves', 1),
        ('达成', 'achieves', 1),
        # 通过关系
        ('通过', 'via', 1),
        ('借助', 'via', 1),
        # 采用关系
        ('采用', 'adopts', 1),
        ('使用', 'adopts', 1),
        ('应用', 'adopts', 1),
        # 替代关系
        ('替代', 'replaces', 1),
        ('取代', 'replaces', 1),
        ('代替', 'replaces', 1),
        # 依赖关系
        ('依赖', 'depends_on', 1),
        ('需要', 'depends_on', 1),
    ]

    # 逆向关系映射
    REVERSE_RELATIONS = {
        'contains': 'belongs_to',
        'belongs_to': 'contains',
        'reduces': 'increases_by',
        'increases': 'reduces_by',
        'promotes': 'promoted_by',
        'achieves': 'achieved_by',
        'via': 'used_by',
        'adopts': 'adopted_by',
        'replaces': 'replaced_by',
        'depends_on': 'enables',
        'affects': 'affected_by',
        'related_to': 'related_to',
    }

    def extract(self, text: str, entities: List[Entity] = None) -> List[Relation]:
        """从文本和实体中提取关系

        Args:
            text: 输入文本
            entities: 已知实体列表（可选，不提供时自动提取）
        """
        relations = []
        entity_list = list(entities) if entities else []

        # 如果没有提供实体，从关键词提取
        if not entity_list:
            from rag.entity_linking import NLPEntityExtractor
            nlp_extractor = NLPEntityExtractor()
            entity_list = nlp_extractor.extract_entities(text)

        # 转换为实体名称集合用于快速查找
        entity_names = {e.text for e in entity_list}

        for keyword, rel_type, direction in self.RELATION_PATTERNS:
            idx = 0
            while True:
                pos = text.find(keyword, idx)
                if pos == -1:
                    break

                idx = pos + len(keyword)  # 移动到下一个位置避免无限循环

                # 在关键词前后寻找已知实体（限制搜索范围）
                max_search_dist = 15
                before_text = text[max(0, pos - max_search_dist):pos]
                after_text = text[pos + len(keyword):pos + len(keyword) + max_search_dist]

                # 向前找实体（取最后一个匹配）
                source = None
                source_pos = -1
                for entity in entity_names:
                    if entity in before_text:
                        last_pos = before_text.rfind(entity)
                        if source is None or last_pos > source_pos:
                            source = entity
                            source_pos = last_pos

                # 向后找实体（取第一个匹配）
                target = None
                target_pos = len(after_text)
                for entity in entity_names:
                    if entity in after_text:
                        first_pos = after_text.find(entity)
                        if first_pos < target_pos:
                            target = entity
                            target_pos = first_pos

                if source and target:
                    source_type = self._get_entity_type(source)
                    target_type = self._get_entity_type(target)

                    relations.append(Relation(
                        source=f"{source_type}:{source}",
                        target=f"{target_type}:{target}",
                        type=rel_type,
                        weight=1.0
                    ))

                    # 添加逆向关系
                    reverse_type = self.REVERSE_RELATIONS.get(rel_type)
                    if reverse_type:
                        relations.append(Relation(
                            source=f"{target_type}:{target}",
                            target=f"{source_type}:{source}",
                            type=reverse_type,
                            weight=0.8
                        ))

        return relations

    def _get_entity_type(self, name: str) -> str:
        """获取实体类型"""
        for etype, keywords in EntityExtractor.ENTITY_PATTERNS.items():
            if name in keywords:
                return etype
        return "concept"


class GraphRAGEngine:
    """基于知识图谱的检索增强引擎"""

    def __init__(self, knowledge_base_path: str = None):
        if knowledge_base_path is None:
            project_root = Path(__file__).parent.parent.parent.parent
            knowledge_base_path = str(project_root / "knowledge_base")

        self.knowledge_base_path = knowledge_base_path
        self.graph: Dict[str, Dict] = defaultdict(lambda: {
            'entities': {},
            'relations': []
        })
        self.entity_extractor = EntityExtractor()
        self.relation_extractor = RelationExtractor()
        self._initialized = False

        # 持久化支持
        self._persistence = None

    def enable_persistence(self, persist_path: str = None):
        """启用图谱持久化"""
        from rag.graph_persistence import GraphPersistence
        self._persistence = GraphPersistence(persist_path)
        print("[GraphRAG] 持久化已启用")

    def initialize(self, force_rebuild: bool = False):
        """初始化图谱引擎

        Args:
            force_rebuild: 是否强制重建（忽略持久化）
        """
        if self._initialized:
            return

        print("[GraphRAG] 初始化知识图谱...")

        # 尝试从持久化加载
        if not force_rebuild and self._persistence and self._persistence.exists():
            loaded_graph = self._persistence.load()
            if loaded_graph:
                self.graph = loaded_graph
                self._initialized = True
                print(f"[GraphRAG] 从持久化加载图谱完成，节点数: {len(self.graph)}")
                return

        # 执行完整构建
        self._load_documents()
        self._initialized = True
        print(f"[GraphRAG] 图谱初始化完成，节点数: {len(self.graph)}")

        # 保存持久化
        if self._persistence:
            self._persistence.save(self.graph)

    def _load_documents(self):
        """从知识库目录加载文档并构建图谱"""
        kb_path = Path(self.knowledge_base_path)

        # 收集所有markdown文件
        md_files = list(kb_path.rglob("*.md"))
        print(f"[GraphRAG] 发现 {len(md_files)} 个文档")

        for md_file in md_files:
            try:
                content = md_file.read_text(encoding='utf-8')
                self._process_document(md_file.stem, content, str(md_file))
            except Exception as e:
                print(f"[GraphRAG] 处理文档失败 {md_file}: {e}")

    def _process_document(self, doc_id: str, content: str, source: str):
        """处理单个文档，构建实体和关系"""
        # 提取标题作为实体
        lines = content.split('\n')
        title = lines[0] if lines else doc_id

        # 提取段落作为节点内容
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]

        # O(1) 查重的 (source, target) 集合 — 取代原来的 O(N) 线性扫描
        seen_pairs: set = set()

        for para in paragraphs:
            if len(para) < 20:
                continue

            # 提取实体
            entities = self.entity_extractor.extract(para)
            for entity in entities:
                if entity.name not in self.graph[doc_id]['entities']:
                    self.graph[doc_id]['entities'][entity.name] = {
                        'entity': entity,
                        'content': para,
                        'source': source
                    }

                # 建立实体间的共现关系
                for other_entity in entities:
                    if entity.name != other_entity.name:
                        pair_key = (entity.id, other_entity.id)
                        if pair_key in seen_pairs:
                            continue
                        seen_pairs.add(pair_key)
                        self.graph[doc_id]['relations'].append(Relation(
                            source=entity.id,
                            target=other_entity.id,
                            type='co_occurs',
                            weight=0.5
                        ))

    def build_graph(self):
        """显式构建全局知识图谱"""
        print("[GraphRAG] 构建全局知识图谱...")

        global_entities = {}
        global_relations = []

        # 合并所有文档的实体和关系
        for doc_id, doc_data in self.graph.items():
            for entity_name, entity_data in doc_data['entities'].items():
                entity = entity_data['entity']
                if entity.name not in global_entities:
                    global_entities[entity.name] = {
                        'entity': entity,
                        'documents': [],
                        'contents': []
                    }
                global_entities[entity.name]['documents'].append(doc_id)
                global_entities[entity.name]['contents'].append(entity_data['content'])

        # 跨文档关系
        for doc_id, doc_data in self.graph.items():
            for rel in doc_data['relations']:
                global_relations.append(rel)

        print(f"[GraphRAG] 全局实体: {len(global_entities)}, 全局关系: {len(global_relations)}")

        return global_entities, global_relations

    def query(self, question: str, top_k: int = 5) -> List[GraphResult]:
        """多跳推理查询"""
        self.initialize()

        # 提取问题中的实体
        question_entities = self.entity_extractor.extract(question)

        if not question_entities:
            return []

        # 查找相关实体
        relevant_contents = []
        for q_entity in question_entities:
            for doc_id, doc_data in self.graph.items():
                if q_entity.name in doc_data['entities']:
                    entity_info = doc_data['entities'][q_entity.name]
                    relevant_contents.append({
                        'entity': q_entity.name,
                        'content': entity_info['content'],
                        'source': entity_info['source'],
                        'score': 1.0
                    })

        # 构建结果
        results = []
        for item in relevant_contents[:top_k]:
            results.append(GraphResult(
                content=item['content'],
                score=item['score'],
                entities=[item['entity']],
                relations=[],
                path=[item['entity']]
            ))

        return results

    def query_multihop(self, question: str, max_hops: int = 2) -> List[GraphResult]:
        """多跳推理查询

        Args:
            question: 用户问题
            max_hops: 最大跳数

        Returns:
            推理结果列表
        """
        self.initialize()

        # 提取问句实体
        start_entities = self.entity_extractor.extract(question)
        if not start_entities:
            return self.query(question)

        results = []

        # BFS多跳搜索
        visited = set()
        queue = [(e, [e.name]) for e in start_entities]  # (实体, 路径)

        while queue and len(results) < 10:
            entity, path = queue.pop(0)

            if entity.name in visited:
                continue
            visited.add(entity.name)

            # 查找关联内容
            for doc_id, doc_data in self.graph.items():
                if entity.name in doc_data['entities']:
                    entity_info = doc_data['entities'][entity.name]
                    results.append(GraphResult(
                        content=entity_info['content'],
                        score=1.0 / len(path),
                        entities=path,
                        relations=[],
                        path=path
                    ))

            # 扩展邻居
            if len(path) < max_hops:
                for doc_id, doc_data in self.graph.items():
                    if entity.name in doc_data['entities']:
                        for rel in doc_data['relations']:
                            if rel.source == entity.id:
                                # 找到目标实体
                                target_name = rel.target.split(':')[-1] if ':' in rel.target else rel.target
                                if target_name not in visited:
                                    # 获取实体类型
                                    target_type = 'concept'
                                    for etype, keywords in EntityExtractor.ENTITY_PATTERNS.items():
                                        if target_name in keywords:
                                            target_type = etype
                                            break
                                    new_entity = Entity(
                                        id=f"{target_type}_{target_name}",
                                        name=target_name,
                                        type=target_type
                                    )
                                    queue.append((new_entity, path + [target_name]))

        # 去重并排序
        seen = set()
        unique_results = []
        for r in results:
            key = r.content[:50]
            if key not in seen:
                seen.add(key)
                unique_results.append(r)

        return unique_results[:5]  # 返回最多5个结果

    def get_entity_info(self, entity_name: str) -> Optional[Dict]:
        """获取实体详情"""
        for doc_id, doc_data in self.graph.items():
            if entity_name in doc_data['entities']:
                return {
                    'name': entity_name,
                    'type': doc_data['entities'][entity_name]['entity'].type,
                    'content': doc_data['entities'][entity_name]['content'],
                    'source': doc_data['entities'][entity_name]['source']
                }
        return None

    def get_related_entities(self, entity_name: str, max_results: int = 5) -> List[Dict]:
        """获取相关实体"""
        related = []

        for doc_id, doc_data in self.graph.items():
            if entity_name in doc_data['entities']:
                for rel in doc_data['relations']:
                    if rel.source == doc_data['entities'][entity_name]['entity'].id:
                        target_name = rel.target.split(':')[-1] if ':' in rel.target else rel.target
                        related.append({
                            'name': target_name,
                            'relation': rel.type
                        })
                        if len(related) >= max_results:
                            return related

        return related

    def get_stats(self) -> Dict:
        """获取图谱统计"""
        total_entities = sum(len(d['entities']) for d in self.graph.values())
        total_relations = sum(len(d['relations']) for d in self.graph.values())
        return {
            'documents': len(self.graph),
            'total_entities': total_entities,
            'total_relations': total_relations,
            'initialized': self._initialized
        }

    def get_subgraph(self, entity_name: str, depth: int = 2) -> Dict:
        """获取给定实体的局部子图

        Args:
            entity_name: 实体名称
            depth: 扩展深度

        Returns:
            子图数据
        """
        self.initialize()

        subgraph = {
            'entities': {},
            'relations': []
        }

        visited = set()
        queue = [(entity_name, 0)]

        while queue:
            current, current_depth = queue.pop(0)

            if current in visited or current_depth > depth:
                continue
            visited.add(current)

            # 收集实体
            for doc_id, doc_data in self.graph.items():
                if current in doc_data['entities']:
                    entity_info = doc_data['entities'][current]
                    if current not in subgraph['entities']:
                        subgraph['entities'][current] = entity_info

                    # 收集关系
                    for rel in doc_data['relations']:
                        if rel.source == entity_info['entity'].id:
                            target_name = rel.target.split(':')[-1] if ':' in rel.target else rel.target
                            subgraph['relations'].append(rel)

                            # 添加邻居实体
                            if current_depth < depth and target_name not in visited:
                                for other_doc_id, other_doc_data in self.graph.items():
                                    if target_name in other_doc_data['entities']:
                                        queue.append((target_name, current_depth + 1))

        return subgraph

    def find_path(self, source: str, target: str, max_depth: int = 3) -> Optional[List[str]]:
        """查找两个实体间的最短路径

        Args:
            source: 源实体名
            target: 目标实体名
            max_depth: 最大深度

        Returns:
            路径列表，失败返回None
        """
        self.initialize()

        if source == target:
            return [source]

        # BFS查找最短路径
        visited = {source}
        queue = [(source, [source])]

        while queue:
            current, path = queue.pop(0)

            if len(path) > max_depth:
                continue

            # 查找当前实体的邻居
            for doc_id, doc_data in self.graph.items():
                if current not in doc_data['entities']:
                    continue

                entity_id = doc_data['entities'][current]['entity'].id

                for rel in doc_data['relations']:
                    if rel.source == entity_id or rel.target == entity_id:
                        target_name = rel.target.split(':')[-1] if ':' in rel.target else rel.target

                        if target_name == target:
                            return path + [target_name]

                        if target_name not in visited:
                            visited.add(target_name)
                            queue.append((target_name, path + [target_name]))

        return None

    def query_with_attention(
        self,
        question: str,
        top_k: int = 5,
        use_embedding: bool = False
    ) -> List[GraphResult]:
        """基于注意力的查询（优先返回与问题语义相关的实体）

        Args:
            question: 用户问题
            top_k: 返回数量
            use_embedding: 是否使用嵌入向量计算语义相似度

        Returns:
            排序后的结果
        """
        self.initialize()

        # 提取问题中的实体
        question_entities = self.entity_extractor.extract(question)

        if not question_entities:
            return self.query(question, top_k)

        # 获取所有相关结果
        results = []
        for q_entity in question_entities:
            for doc_id, doc_data in self.graph.items():
                if q_entity.name in doc_data['entities']:
                    entity_info = doc_data['entities'][q_entity.name]

                    # 计算相关性评分
                    score = 1.0

                    # 实体匹配得分
                    if q_entity.name == entity_info['entity'].name:
                        score *= 1.5

                    # 类型匹配
                    if q_entity.type == entity_info['entity'].type:
                        score *= 1.2

                    results.append(GraphResult(
                        content=entity_info['content'],
                        score=score,
                        entities=[q_entity.name],
                        relations=[],
                        path=[q_entity.name]
                    ))

        # 去重并排序
        seen = set()
        unique_results = []
        for r in results:
            key = r.content[:50]
            if key not in seen:
                seen.add(key)
                unique_results.append(r)

        # 按分数排序
        unique_results.sort(key=lambda x: -x.score)

        return unique_results[:top_k]


# 全局实例
_graph_rag_engine = None


def get_graph_rag_engine(knowledge_base_path: str = None) -> GraphRAGEngine:
    """获取GraphRAG引擎单例"""
    global _graph_rag_engine
    if _graph_rag_engine is None:
        _graph_rag_engine = GraphRAGEngine(knowledge_base_path)
    return _graph_rag_engine


if __name__ == "__main__":
    print("=" * 60)
    print("GraphRAG 引擎测试")
    print("=" * 60)

    engine = GraphRAGEngine()

    print("\n[1] 初始化图谱...")
    engine.initialize()

    print("\n[2] 图谱统计:")
    stats = engine.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")

    print("\n[3] 单跳查询测试:")
    results = engine.query("碳中和政策对出行有什么影响")
    print(f"   找到 {len(results)} 个结果")
    for i, r in enumerate(results[:3], 1):
        print(f"   [{i}] {r.content[:100]}...")

    print("\n[4] 多跳查询测试:")
    results = engine.query_multihop("碳中和政策和低碳出行有什么关系", max_hops=2)
    print(f"   找到 {len(results)} 个结果")
    for i, r in enumerate(results[:3], 1):
        print(f"   [{i}] 路径: {' -> '.join(r.path)}")
        print(f"       内容: {r.content[:80]}...")

    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)