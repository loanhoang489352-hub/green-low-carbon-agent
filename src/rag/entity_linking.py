"""
实体链接模块
基于NLP的实体提取，支持词性标注和领域词典
"""

import sys
from pathlib import Path
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass, field

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root / 'src'))

# 延迟导入jieba
_jieba = None

def _get_jieba():
    """延迟加载jieba"""
    global _jieba
    if _jieba is None:
        import jieba
        import jieba.posseg
        jieba.initialize()
        _jieba = jieba
    return _jieba


@dataclass
class EntityCandidate:
    """实体候选"""
    text: str
    type: str
    start: int
    end: int
    score: float = 1.0
    pos_tag: str = ""
    synonyms: List[str] = field(default_factory=list)


class DomainDictionary:
    """领域专有名词词典"""

    def __init__(self):
        self.concepts: Set[str] = set()
        self.actions: Set[str] = set()
        self.policies: Set[str] = set()
        self.metrics: Set[str] = set()
        self.locations: Set[str] = set()
        self._synonyms: Dict[str, str] = {}  # 同义词 -> 主词

        self._load_default_dictionary()

    def _load_default_dictionary(self):
        """加载默认领域词典"""
        # 概念类
        concepts = [
            '碳中和', '碳达峰', '碳足迹', '碳交易', '碳排放', '低碳', '减排',
            '温室气体', '二氧化碳', '可再生能源', '再生能源', '可持续发展',
            '碳足迹核算', '碳配额', '碳积分', '碳信用', '碳核查', '碳资产',
            '绿色电力', '零碳', '负碳', '碳汇', '碳捕集', '碳封存'
        ]
        self.concepts.update(concepts)

        # 行动类
        actions = [
            '骑行', '步行', '公交', '地铁', '开车', '拼车', '乘坐', '出行',
            '节能', '省电', '节约', '分类', '回收', '减少', '替换', '复用',
            '步行上班', '骑行通勤', '公交出行', '地铁通勤', '垃圾分类',
            '节约用水', '节约用电', '减少一次性', '低碳出行', '绿色出行'
        ]
        self.actions.update(actions)

        # 政策类
        policies = [
            '双碳目标', '碳达峰', '碳中和', '政策', '补贴', '奖励', '优惠',
            '碳市场', '碳配额', '碳积分', '绿色认证', '环境标志', '能效标准',
            '排放标准', '绿色采购', '环保税', '碳税', '绿色金融', '绿色信贷'
        ]
        self.policies.update(policies)

        # 指标类
        metrics = [
            'kg CO2', '碳排放量', '节能效果', '回本周期', '年省电', '年减碳',
            '能效', '碳足迹', '排放量', 'CO2排放', '温室气体排放', '人均排放',
            '单位GDP排放', '碳强度', '能效比', '节能率'
        ]
        self.metrics.update(metrics)

        # 地点类
        locations = [
            '北京', '上海', '广州', '深圳', '中国', '全国', '各地', '城市', '农村',
            '雄安新区', '长三角', '珠三角', '京津冀', '成渝地区', '粤港澳大湾区'
        ]
        self.locations.update(locations)

    def add_term(self, term: str, term_type: str):
        """添加领域术语"""
        if term_type == 'concept':
            self.concepts.add(term)
        elif term_type == 'action':
            self.actions.add(term)
        elif term_type == 'policy':
            self.policies.add(term)
        elif term_type == 'metric':
            self.metrics.add(term)
        elif term_type == 'location':
            self.locations.add(term)

    def add_synonym(self, synonym: str, main_term: str):
        """添加同义词映射"""
        self._synonyms[synonym] = main_term

    def get_main_term(self, term: str) -> str:
        """获取主术语（处理同义词）"""
        return self._synonyms.get(term, term)

    def match_term_type(self, term: str) -> Optional[str]:
        """匹配术语类型"""
        if term in self.concepts:
            return 'concept'
        if term in self.actions:
            return 'action'
        if term in self.policies:
            return 'policy'
        if term in self.metrics:
            return 'metric'
        if term in self.locations:
            return 'location'
        return None


class NLPEntityExtractor:
    """基于NLP的实体提取器"""

    # 词性标注映射
    POS_TAG_MAP = {
        'n': 'concept',      # 名词
        'nr': 'location',    # 人名
        'ns': 'location',    # 地名
        'nt': 'organization', # 机构名
        'nz': 'concept',     # 其他名词
        'v': 'action',      # 动词
        'vd': 'action',     # 副动词
        'vn': 'action',     # 动名词
        'a': 'action',      # 形容词
        'an': 'action',     # 名形词
        'm': 'metric',      # 数词
        'mq': 'metric',     # 数量词
    }

    # 实体类型优先级
    TYPE_PRIORITY = {'policy': 5, 'metric': 4, 'concept': 3, 'action': 2, 'location': 1}

    def __init__(self, domain_dict: DomainDictionary = None):
        self.domain_dict = domain_dict or DomainDictionary()
        self._entity_cache: Dict[str, List[EntityCandidate]] = {}

    def extract_entities(self, text: str, use_nlp: bool = True) -> List[EntityCandidate]:
        """
        提取实体

        Args:
            text: 输入文本
            use_nlp: 是否使用NLP增强提取

        Returns:
            实体候选列表
        """
        candidates = []
        found_terms = set()

        # 1. 基于领域词典的精确匹配
        for term in self.domain_dict.concepts | self.domain_dict.actions | \
                   self.domain_dict.policies | self.domain_dict.metrics | \
                   self.domain_dict.locations:
            start = 0
            while True:
                idx = text.find(term, start)
                if idx == -1:
                    break
                if idx not in found_terms:
                    term_type = self.domain_dict.match_term_type(term)
                    candidates.append(EntityCandidate(
                        text=term,
                        type=term_type,
                        start=idx,
                        end=idx + len(term),
                        score=1.0,
                        pos_tag='keyword'
                    ))
                    found_terms.add(idx)
                start = idx + 1

        # 2. 基于jieba分词的NLP提取
        if use_nlp:
            nlp_candidates = self._extract_with_jieba(text, found_terms)
            candidates.extend(nlp_candidates)

        # 3. 去除重叠实体，保留高优先级
        candidates = self._resolve_overlaps(candidates)

        # 4. 处理同义词
        for candidate in candidates:
            main_term = self.domain_dict.get_main_term(candidate.text)
            if main_term != candidate.text:
                candidate.synonyms.append(candidate.text)
                candidate.text = main_term

        return candidates

    def _extract_with_jieba(self, text: str, found_terms: Set[int]) -> List[EntityCandidate]:
        """使用jieba进行分词和词性标注"""
        candidates = []
        jieba = _get_jieba()

        # 分词
        words = list(jieba.cut(text))
        posseg = list(jieba.posseg.cut(text))

        # 建立位置索引
        char_pos = 0
        word_positions = []
        for word in words:
            idx = text.find(word, char_pos)
            if idx != -1:
                word_positions.append((idx, word))
                char_pos = idx + len(word)

        # 词性标注提取
        for i, (word, flag) in enumerate(posseg):
            if len(word) < 2:
                continue

            # 检查是否已提取
            start = text.find(word)
            if start == -1 or start in found_terms:
                continue

            # 根据词性判断类型
            entity_type = self._infer_type_from_pos(flag, word)
            if entity_type:
                candidates.append(EntityCandidate(
                    text=word,
                    type=entity_type,
                    start=start,
                    end=start + len(word),
                    score=0.8,
                    pos_tag=flag
                ))

        return candidates

    def _infer_type_from_pos(self, pos_tag: str, word: str) -> Optional[str]:
        """根据词性推断实体类型"""
        # 优先使用词典
        term_type = self.domain_dict.match_term_type(word)
        if term_type:
            return term_type

        # 根据词性推断
        first_char = pos_tag[0] if pos_tag else ''

        if first_char == 'n':
            # 名词优先作为概念
            return 'concept'
        elif first_char == 'v':
            return 'action'
        elif first_char == 'm':
            return 'metric'

        # 检查是否像地点（北京、上海等）
        if word in self.domain_dict.locations:
            return 'location'

        return None

    def _resolve_overlaps(self, candidates: List[EntityCandidate]) -> List[EntityCandidate]:
        """解决重叠实体问题，保留高优先级"""
        if not candidates:
            return []

        # 按起始位置和优先级排序
        candidates.sort(key=lambda x: (x.start, -self.TYPE_PRIORITY.get(x.type, 0)))

        resolved = []
        last_end = -1

        for candidate in candidates:
            # 跳过重叠
            if candidate.start < last_end:
                continue
            resolved.append(candidate)
            last_end = candidate.end

        return resolved

    def extract_with_context(self, text: str, window_size: int = 50) -> Dict[str, any]:
        """提取实体并附带上下文"""
        entities = self.extract_entities(text)

        # 为每个实体提取上下文
        for entity in entities:
            start = max(0, entity.start - window_size)
            end = min(len(text), entity.end + window_size)
            entity.context = text[start:end]

        return {
            'entities': entities,
            'text': text,
            'entity_count': len(entities)
        }


class ChineseTokenizer:
    """中文分词器（简单封装）"""

    def __init__(self):
        self.stop_words = set([
            '的', '了', '和', '是', '在', '我', '有', '就', '不', '人',
            '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去',
            '你', '会', '着', '没有', '看', '好', '自己', '这', '那', '他'
        ])

    def tokenize(self, text: str) -> List[str]:
        """分词"""
        jieba = _get_jieba()
        words = list(jieba.cut(text))

        # 过滤停用词和单字符
        return [w for w in words if w not in self.stop_words and len(w) > 1]

    def extract_keywords(self, text: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """提取关键词"""
        import re
        jieba = _get_jieba()

        # 使用TF-IDF风格评分
        words = self.tokenize(text)
        word_freq = {}
        for w in words:
            if w not in self.stop_words and len(w) > 1:
                word_freq[w] = word_freq.get(w, 0) + 1

        # 计算频率评分
        total = sum(word_freq.values())
        keywords = [(w, f/total) for w, f in word_freq.items()]
        keywords.sort(key=lambda x: -x[1])

        return keywords[:top_k]


# 单元测试
if __name__ == "__main__":
    print("=" * 60)
    print("NLP Entity Extractor Test")
    print("=" * 60)

    extractor = NLPEntityExtractor()

    test_text = "碳中和政策对出行有什么影响？采用公共交通可以减少碳排放。"

    print(f"\n[Input Text]: {test_text}")

    # 基础提取
    entities = extractor.extract_entities(test_text)
    print(f"\n[Extracted Entities]: {len(entities)} found")
    for e in entities:
        print(f"  - {e.text} ({e.type}) at [{e.start}:{e.end}], score={e.score}")

    # 带上下文的提取
    result = extractor.extract_with_context(test_text)
    print(f"\n[Entity Count]: {result['entity_count']}")

    # 分词测试
    tokenizer = ChineseTokenizer()
    tokens = tokenizer.tokenize(test_text)
    print(f"\n[Tokenized]: {tokens}")

    # 关键词提取
    keywords = tokenizer.extract_keywords(test_text)
    print(f"\n[Keywords]: {keywords}")

    print("\n" + "=" * 60)