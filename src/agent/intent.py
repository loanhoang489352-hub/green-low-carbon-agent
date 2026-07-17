"""
意图识别模块
基于规则和关键词的轻量级意图识别
"""

from typing import Dict, List, Tuple
from dataclasses import dataclass
from enum import Enum


class IntentType(Enum):
    """意图类型枚举"""

    KNOWLEDGE_QUERY = "knowledge_query"  # 知识查询
    ADVICE_REQUEST = "advice_request"  # 建议请求
    ACTION_REPORT = "action_report"  # 行动报告
    FEEDBACK = "feedback"  # 反馈
    GREETING = "greeting"  # 问候
    SUGGESTION_ACCEPT = "suggestion_accept"  # 采纳建议
    SUGGESTION_REJECT = "suggestion_reject"  # 拒绝建议
    QUESTION = "question"  # 一般问题
    TRAVEL_PLANNING = "travel_planning"  # P6.S.3: 出行规划 — 调地图+天气
    LOCATION_QUERY = "location_query"  # P6.S.23: 当前位置查询(直接答 city,不绕 LLM)
    UNKNOWN = "unknown"  # 未知


@dataclass
class IntentResult:
    """意图识别结果"""

    intent: IntentType
    confidence: float
    entities: List[str]
    context: Dict
    suggested_response_type: str  # knowledge, advice, encouragement, clarification


class IntentRecognizer:
    """意图识别器"""

    # 意图关键词映射
    INTENT_PATTERNS = {
        IntentType.KNOWLEDGE_QUERY: [
            "什么是",
            "什么叫",
            "请问",
            "解释",
            "碳足迹",
            "碳中和",
            "碳达峰",
            "温室气体",
            "减排",
            "低碳",
            "环保",
            "再生能源",
            "再生能源",
            # P6.S.12: 移除 "什么"(太泛),保留"怎么"作为问句信号
            "怎么",
            "如何",
            "哪些",
            "为什么",
            "多少",
            "区别",
            "介绍一下",
            "能说说",
            "科普",
            "知识",
            "概念",
            "定义",
            # P6.S.12: 兴趣表达(用户对某话题感兴趣,等价为咨询型)
            "感兴趣",
            "想了解",
            "想知道",
            "想学习",
        ],
        IntentType.ADVICE_REQUEST: [
            "建议",
            "怎么办",
            "有什么好",
            "推荐",
            "怎么选",
            "如何做",
            "能不能",
            "可以吗",
            "帮忙",
            "帮助",
            "指点",
            "指导",
            "想买",
            "想换",
            "考虑",
            "计划",
            "打算",
            "准备",
        ],
        IntentType.ACTION_REPORT: [
            "我今天",
            "我昨天",
            "刚买了",
            "做了",
            "尝试了",
            "安装了",
            "换了",
            "开始",
            "已经",
            "完成了",
            "入手了",
            "骑行",
            "走路",
            "坐公交",
            "开车",
            "用电",
            "用了",
            "买了",
        ],
        IntentType.FEEDBACK: [
            "采纳了",
            "有用",
            "不错",
            "不行",
            "太难了",
            "不适合",
            "太贵",
            "不方便",
            "学会了",
            "懂了",
            "谢谢",
            "好",
            "不好",
            "满意",
            "不满意",
            "继续",
            "加油",
        ],
        IntentType.GREETING: [
            "你好",
            "您好",
            "嗨",
            "hi",
            "hello",
            "早",
            "晚上好",
            "初次见面",
            "初次见面",
            "很高兴",
        ],
        IntentType.SUGGESTION_ACCEPT: [
            "好的",
            "可以",
            "试试",
            "了解了",
            "明白了",
            "同意",
            "就这样",
            "按照你说的",
            "好的建议",
            "不错的主意",
        ],
        IntentType.SUGGESTION_REJECT: [
            "算了",
            "不要",
            "不想",
            "不合适",
            "太麻烦",
            "太复杂",
            "不需要",
            "不需要",
            "再说吧",
            "改天",
            "不了",
        ],
        # P6.S.23: 位置查询 — 用户问"我在哪/我的位置/当前位置/where am i"
        # 早返分支,直接调 best_location() 答 city,不再让 LLM 瞎答
        IntentType.LOCATION_QUERY: [
            "我在哪",
            "我的位置",
            "当前位置",
            "现在位置",
            "所在位置",
            "我在哪里",
            "我在哪儿",
            "where am i",
            "where i am",
            "my location",
            "current location",
            "current position",
            "what city",
            "which city",
            "i am in",
            "where is me",
            "定位",
            "你定位",
            "定位我",
        ],
        # P6.S.3: 出行规划 — 与 ADVICE_REQUEST 区别是会调工具
        IntentType.TRAVEL_PLANNING: [
            "出行计划",
            "出行规划",
            "规划出行",
            "行程规划",
            "路线规划",
            "怎么去",
            "怎么走",
            "怎么到",
            "如何去",
            "如何走",
            "如何到",
            "公交路线",
            "地铁路线",
            "驾车路线",
            "骑行路线",
            "最环保",
            "最绿色",
            "最节能",
            "最省时",
            "最快",
            "查路线",
            "查地图",
            "查导航",
            "查路况",
        ],
    }

    # 实体关键词
    ENTITY_PATTERNS = {
        "出行方式": [
            "开车",
            "骑车",
            "步行",
            "公交",
            "地铁",
            "打车",
            "电动车",
            "自行车",
            "飞机",
            "火车",
        ],
        "家电产品": ["空调", "冰箱", "洗衣机", "热水器", "电视", "灯", "LED", "油烟机"],
        "食品类型": ["肉", "蔬菜", "素食", "外卖", "一次性", "塑料", "素", "荤"],
        "行为动作": ["买", "换", "安装", "使用", "减少", "节约", "省电", "省钱"],
        "时间相关": ["今天", "昨天", "明天", "每天", "经常", "偶尔", "最近", "平时"],
        "政策相关": ["补贴", "政策", "碳市场", "碳积分", "奖励", "优惠", "减税"],
    }

    # P6.S.3 + P6.S.12: 出行规划意图关键词(收紧,避免误伤 advice/knowledge/action_report)
    # 拆分三层:
    #   STRONG_TRAVEL: 单命中即覆盖其他意图(明确出行模式)
    #   WEAK_TRAVEL:   需 ≥2 同时命中才覆盖(交通方式/方向词)
    #   已删除:      通用位置词("公司"/"家"/"学校")、通用"去/到/出发"、
    #               "碳排放/碳排"等低碳主题词(只"低碳出行/绿色出行"留)
    STRONG_TRAVEL = [
        # 明确规划
        "出行计划",
        "出行规划",
        "规划出行",
        "行程规划",
        "路线规划",
        # 明确"怎么去"型
        "怎么去",
        "怎么走",
        "怎么到",
        "如何去",
        "如何走",
        "如何到",
        # 交通方式 + 路线
        "公交路线",
        "地铁路线",
        "驾车路线",
        "骑行路线",
        # 查工具
        "查路线",
        "查地图",
        "查导航",
        "查路况",
    ]
    WEAK_TRAVEL = [
        # 方向标记(单字泛,需 ≥2 组合才有意义)
        "从",
        "到",
        "出发",
        "前往",
        "到达",
        "去往",
        # 路线工具
        "路线",
        "导航",
        "地图",
        "路况",
        # 交通方式(单字弱,需多词组合)
        "公交",
        "地铁",
        "打车",
        "网约车",
        "出租车",
        "驾车",
        "开车",
        "骑车",
        "骑行",
        "自行车",
        "步行",
        "走路",
        "拼车",
        "顺风车",
        # 出行相关
        "低碳出行",
        "环保出行",
        "绿色出行",
        "最环保",
        "最绿色",
        "最节能",
        # 时间
        "几点出发",
        "多久能到",
        "几小时",
        "多长时间",
        "路上要多久",
        "路上花多久",
    ]
    # 兼容旧代码
    TRAVEL_KEYWORDS = STRONG_TRAVEL + WEAK_TRAVEL

    # 低碳领域关键词
    LOW_CARBON_KEYWORDS = [
        "碳",
        "低碳",
        "环保",
        "绿色",
        "节能",
        "减排",
        "减碳",
        "可持续",
        "生态",
        "再生能源",
        "太阳能",
        "电动车",
        "植树",
        "碳汇",
        "碳足迹",
        "碳中和",
        "碳达峰",
        "温室气体",
        "二氧化碳",
    ]

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        """预处理模式匹配"""
        pass  # 当前使用简单的字符串匹配

    def recognize(self, text: str) -> IntentResult:
        """识别用户输入的意图"""
        text_lower = text.lower()

        # 检查是否是低碳相关话题（使用小写版本匹配）
        is_low_carbon_topic = any(kw in text_lower for kw in self.LOW_CARBON_KEYWORDS)

        # 识别意图（使用原始文本匹配，关键词本身支持中英文）
        intent, confidence = self._match_intent(text, text_lower)

        # 提取实体
        entities = self._extract_entities(text)

        # 构建上下文
        context = {
            "is_low_carbon_topic": is_low_carbon_topic,
            "text_length": len(text),
            "has_question_mark": "?" in text,
            "has_exclamation": "!" in text,
        }

        # 确定响应类型
        response_type = self._determine_response_type(intent, is_low_carbon_topic)

        return IntentResult(
            intent=intent,
            confidence=confidence,
            entities=entities,
            context=context,
            suggested_response_type=response_type,
        )

    def _match_intent(self, text: str, text_lower: str = None) -> Tuple[IntentType, float]:
        """匹配意图"""
        if text_lower is None:
            text_lower = text.lower()

        scores = {}

        for intent_type, patterns in self.INTENT_PATTERNS.items():
            score = 0
            for pattern in patterns:
                pattern_lower = pattern.lower()
                if pattern_lower in text_lower:
                    score += 1
            if score > 0:
                scores[intent_type] = score / len(patterns)

        # P6.S.3 + P6.S.12: 出行规划优先级提升
        # 单 STRONG_TRAVEL 命中即覆盖;WEAK_TRAVEL 需 ≥2 才覆盖
        # 避免"我应该怎么减少碳排放"被"碳排放"误识别为 travel
        strong_hits = sum(1 for kw in self.STRONG_TRAVEL if kw in text)
        weak_hits = sum(1 for kw in self.WEAK_TRAVEL if kw in text)
        if strong_hits > 0 or weak_hits >= 2:
            travel_hits = strong_hits + weak_hits
            scores[IntentType.TRAVEL_PLANNING] = (
                scores.get(IntentType.TRAVEL_PLANNING, 0) + 0.3 + travel_hits * 0.1
            )

        # P6.S.12: 建议请求优先级提升 — "建议/推荐/有什么好" 命中即覆盖
        # 避免"有什么低碳出行建议吗"被"什么/低碳/出行"散点命中 knowledge_query
        advice_signals = [
            "建议",
            "推荐",
            "有什么好",
            "怎么办",
            "如何做",
            "帮我",
            "帮忙",
            "怎么选",
            "想买",
            "想换",
        ]
        advice_hits = sum(1 for s in advice_signals if s in text)
        if advice_hits > 0:
            scores[IntentType.ADVICE_REQUEST] = (
                scores.get(IntentType.ADVICE_REQUEST, 0) + 0.3 + advice_hits * 0.1
            )

        # P6.S.23: LOCATION_QUERY 强优先 — 单命中即覆盖,避免被"什么/在"等散点稀释
        if scores.get(IntentType.LOCATION_QUERY, 0) > 0:
            scores[IntentType.LOCATION_QUERY] += 0.5

        if not scores:
            return IntentType.UNKNOWN, 0.5

        # 返回得分最高的意图
        best_intent = max(scores, key=scores.get)
        confidence = min(scores[best_intent] * 2, 1.0)  # 归一化置信度

        return best_intent, confidence

    def _extract_entities(self, text: str) -> List[str]:
        """提取实体"""
        entities = []

        for entity_type, keywords in self.ENTITY_PATTERNS.items():
            for keyword in keywords:
                if keyword in text:
                    entities.append(keyword)

        return list(set(entities))  # 去重

    def _determine_response_type(
        self, intent: IntentType, is_low_carbon_topic: bool = False
    ) -> str:
        """确定响应类型"""
        # 如果是低碳相关但意图不明确，尝试使用知识查询
        if is_low_carbon_topic and intent == IntentType.UNKNOWN:
            return "knowledge"

        type_mapping = {
            IntentType.KNOWLEDGE_QUERY: "knowledge",
            IntentType.ADVICE_REQUEST: "advice",
            IntentType.ACTION_REPORT: "encouragement",
            IntentType.FEEDBACK: "acknowledgment",
            IntentType.GREETING: "greeting",
            IntentType.SUGGESTION_ACCEPT: "positive",
            IntentType.SUGGESTION_REJECT: "alternative",
            IntentType.QUESTION: "knowledge",
            IntentType.TRAVEL_PLANNING: "tool_call",  # P6.S.3: 触发工具调用
            IntentType.UNKNOWN: "clarification",
        }

        return type_mapping.get(intent, "general")

    def analyze_sentiment(self, text: str) -> str:
        """简单情感分析"""
        positive_words = ["好", "棒", "喜欢", "赞", "不错", "感谢", "谢谢", "有用", "采纳"]
        negative_words = ["不好", "差", "讨厌", "没用", "麻烦", "难", "贵", "不适合", "不行"]

        positive_count = sum(1 for w in positive_words if w in text)
        negative_count = sum(1 for w in negative_words if w in text)

        if positive_count > negative_count:
            return "positive"
        elif negative_count > positive_count:
            return "negative"
        return "neutral"

    def get_intent_description(self, intent: IntentType) -> str:
        """获取意图描述"""
        descriptions = {
            IntentType.KNOWLEDGE_QUERY: "知识查询 - 用户想了解绿色低碳相关知识",
            IntentType.ADVICE_REQUEST: "建议请求 - 用户寻求低碳行动建议",
            IntentType.ACTION_REPORT: "行动报告 - 用户分享自己的低碳行动",
            IntentType.FEEDBACK: "反馈 - 用户对建议的反馈",
            IntentType.GREETING: "问候 - 用户打招呼",
            IntentType.SUGGESTION_ACCEPT: "建议采纳 - 用户接受了建议",
            IntentType.SUGGESTION_REJECT: "建议拒绝 - 用户拒绝了建议",
            IntentType.QUESTION: "问题 - 用户提出问题",
            IntentType.UNKNOWN: "未知 - 无法识别的意图",
        }
        return descriptions.get(intent, "未知意图")
