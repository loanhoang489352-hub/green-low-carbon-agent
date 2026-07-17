"""
Query Understanding 模块
将用户自然语言转化为结构化语义表示，减少歧义和误判
"""

import sys
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root / "src"))


class TimeUnit(Enum):
    """时间单位"""

    TODAY = "today"
    TOMORROW = "tomorrow"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    CUSTOM = "custom"


class LocationType(Enum):
    """位置类型"""

    POI = "poi"  # 兴趣点（商场、学校、医院等）
    ADDRESS = "address"  # 地址
    HOME = "home"  # 家
    WORK = "work"  # 公司/工作地点
    CITY = "city"  # 城市
    AREA = "area"  # 区域（如"京津冀"）
    UNKNOWN = "unknown"


class AmbiguityType(Enum):
    """歧义类型"""

    TIME_VAGUE = "time_vague"  # 时间模糊
    LOCATION_AMBIGUOUS = "location_ambiguous"  # 地点模糊
    INTENT_MULTIPLE = "intent_multiple"  # 多意图
    PRONOUN_REFERENCE = "pronoun_reference"  # 代词指代
    MANNER_UNCLEAR = "manner_unclear"  # 方式不明确
    SUBJECT_OMITTED = "subject_omitted"  # 主语省略


@dataclass
class TemporalInfo:
    """时间信息"""

    raw: str  # 原始文本 "今天"、"下周一"
    normalized: Optional[str] = None  # 标准化格式 "2026-05-18"
    time_type: str = "custom"  # 时间类型：today, tomorrow, week, month, custom
    confidence: float = 1.0
    start_of_day: Optional[str] = None  # 当天开始
    end_of_day: Optional[str] = None  # 当天结束

    def __post_init__(self):
        if self.normalized is None:
            self.normalized = self._parse_from_raw()

    def _parse_from_raw(self) -> Optional[str]:
        """从原始文本解析日期"""
        now = datetime.now()
        today = now.date()

        time_patterns = {
            r"今天": (today, today),
            r"明天": (today + timedelta(days=1), today + timedelta(days=1)),
            r"后天": (today + timedelta(days=2), today + timedelta(days=2)),
            r"大后天": (today + timedelta(days=3), today + timedelta(days=3)),
            r"昨天": (today - timedelta(days=1), today - timedelta(days=1)),
            r"前天": (today - timedelta(days=2), today - timedelta(days=2)),
            r"这周": (today, today + timedelta(days=6 - today.weekday())),
            r"下周": (today + timedelta(days=7), today + timedelta(days=13)),
            r"下周[一二三四五六日]": self._parse_next_weekday,
            r"本周[一二三四五六日]": self._parse_this_weekday,
            r"本月": (today.replace(day=1), today.replace(day=28)),
            r"下月": self._parse_next_month,
            r"\d+天[之之]?后": self._parse_days_later,
        }

        for pattern, handler in time_patterns.items():
            if re.search(pattern, self.raw):
                if callable(handler):
                    result = handler(self.raw)
                else:
                    result = handler
                if result:
                    self.start_of_day = result[0].isoformat()
                    self.end_of_day = result[1].isoformat()
                    return result[0].isoformat()
        return None

    def _parse_next_weekday(self, text: str) -> Tuple:
        """解析下周几"""
        weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
        match = re.search(r"下周([一二三四五六日天])", text)
        if match:
            target = weekday_map[match.group(1)]
            today = datetime.now().date()
            days_ahead = 7 + (target - today.weekday())
            return (today + timedelta(days=days_ahead),) * 2
        return (datetime.now().date(),) * 2

    def _parse_this_weekday(self, text: str) -> Tuple:
        """解析本周几"""
        weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
        match = re.search(r"本周([一二三四五六日天])", text)
        if match:
            target = weekday_map[match.group(1)]
            today = datetime.now().date()
            days_ahead = target - today.weekday()
            if days_ahead < 0:
                days_ahead += 7
            return (today + timedelta(days=days_ahead),) * 2
        return (datetime.now().date(),) * 2

    def _parse_next_month(self, text: str) -> Tuple:
        """解析下个月"""
        today = datetime.now().date()
        if today.month == 12:
            next_month = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_month = today.replace(month=today.month + 1, day=1)
        end_day = next_month.replace(day=28)  # 简化处理
        return (next_month, end_day)

    def _parse_days_later(self, text: str) -> Tuple:
        """解析N天后"""
        match = re.search(r"(\d+)天[之之]?后", text)
        if match:
            days = int(match.group(1))
            target = datetime.now().date() + timedelta(days=days)
            return (target, target)
        return (datetime.now().date(),) * 2


@dataclass
class LocationInfo:
    """位置信息"""

    raw: str  # 原始文本
    normalized: Optional[str] = None  # 标准化名称
    location_type: str = "unknown"  # 类型：poi, address, home, work, city, area
    city: Optional[str] = None  # 所属城市
    district: Optional[str] = None  # 所属区域
    category: Optional[str] = None  # POI类别（商场、学校、医院等）
    coordinates: Optional[Tuple[float, float]] = None  # 经纬度
    confidence: float = 1.0

    # 常见POI类型关键词
    POI_CATEGORIES = {
        "商场": ["商场", "购物中心", "大悦城", "万达", "银泰", "百货"],
        "写字楼": ["写字楼", "办公楼", "公司", "大厦"],
        "学校": ["学校", "大学", "学院", "中学", "小学", "幼儿园"],
        "医院": ["医院", "诊所", "卫生中心", "医务室"],
        "公园": ["公园", "广场", "景区", "景点"],
        "地铁站": ["地铁站", "地铁"],
        "火车站": ["火车站", "高铁站", "动车站"],
        "机场": ["机场", "航站楼"],
        "超市": ["超市", "便利店", "菜市场", "商场"],
        "餐厅": ["餐厅", "饭店", "餐馆", "食堂", "小吃"],
        "住宅": ["小区", "社区", "公寓", "家"],
    }

    HOME_WORDS = ["家", "家里", "回家", "回到家"]
    WORK_WORDS = ["公司", "单位", "上班", "公司"]

    def __post_init__(self):
        self._infer_type_and_category()

    def _infer_type_and_category(self):
        """推断位置类型和类别"""
        # 检查是否是"家"或"公司"
        if self.raw in self.HOME_WORDS:
            self.location_type = "home"
            self.normalized = "家"
            return
        if self.raw in self.WORK_WORDS:
            self.location_type = "work"
            self.normalized = "公司"
            return

        # 检查POI类别
        for category, keywords in self.POI_CATEGORIES.items():
            for kw in keywords:
                if kw in self.raw:
                    self.location_type = "poi"
                    self.category = category
                    self.normalized = self.raw
                    return

        # 推断城市(从 config/cities.yaml 加载)
        try:
            from config_loader import get_major_cities

            major_cities = get_major_cities()
        except Exception:
            major_cities = [
                "北京",
                "上海",
                "广州",
                "深圳",
                "杭州",
                "成都",
                "武汉",
                "南京",
                "西安",
                "重庆",
            ]
        for city in major_cities:
            if city in self.raw:
                self.city = city
                self.location_type = "city"
                break

        if self.normalized is None:
            self.normalized = self.raw


@dataclass
class TransportInfo:
    """出行方式信息"""

    raw: str  # 原始文本 "开车"、"地铁"
    transport_type: Optional[str] = None  # 类型：driving, transit, cycling, walking, taxi
    is_preferred: bool = True  # 是否是偏好方式 vs 实际行为

    TRANSPORT_MAP = {
        "开车": "driving",
        "驾车": "driving",
        "自驾": "driving",
        "骑车": "cycling",
        "骑行": "cycling",
        "骑": "cycling",
        "步行": "walking",
        "走路": "walking",
        "走": "walking",
        "公交": "transit",
        "公交车": "transit",
        "坐公交": "transit",
        "地铁": "transit",
        "乘地铁": "transit",
        "打车": "taxi",
        "出租车": "taxi",
        "拼车": "taxi",
        "电动车": "electric_vehicle",
        "电动": "electric_vehicle",
        "飞机": "airplane",
        "火车": "railway",
    }

    def __post_init__(self):
        self.transport_type = self.TRANSPORT_MAP.get(self.raw, None)


@dataclass
class ActivityInfo:
    """活动信息"""

    raw: str  # 原始文本
    activity_type: Optional[str] = None  # 类型：shopping, work, visit, exercise, dining, travel
    target: Optional[LocationInfo] = None  # 活动地点

    ACTIVITY_MAP = {
        "购物": "shopping",
        "逛街": "shopping",
        "买": "shopping",
        "逛": "shopping",
        "上班": "work",
        "工作": "work",
        "出差": "work",
        "开会": "work",
        "看病": "medical",
        "就医": "medical",
        "检查": "medical",
        "锻炼": "exercise",
        "运动": "exercise",
        "跑步": "exercise",
        "健身": "exercise",
        "吃饭": "dining",
        "就餐": "dining",
        "用餐": "dining",
        "旅游": "travel",
        "度假": "travel",
        "游玩": "travel",
        "探亲": "visit",
        "访友": "visit",
    }

    def __post_init__(self):
        self.activity_type = self.ACTIVITY_MAP.get(self.raw, None)


@dataclass
class SemanticComponents:
    """语义成分"""

    subject: str = "用户"  # 主语
    temporal: Optional[TemporalInfo] = None
    location: Optional[LocationInfo] = None
    transport: Optional[TransportInfo] = None
    activity: Optional[ActivityInfo] = None
    goal: Optional[str] = None  # 目的
    manner: Optional[str] = None  # 方式
    recipient: Optional[str] = None  # 接受者（如送给谁）


@dataclass
class ExtractedFact:
    """提取的事实"""

    fact_type: str  # time, location, transport, activity, quantity, etc.
    value: Any
    raw_text: str
    confidence: float = 1.0


@dataclass
class QueryUnderstanding:
    """Query理解结果"""

    original_query: str

    # 意图（复用 IntentType，由 IntentRecognizer 提供）
    intent: str
    intent_confidence: float

    # 语义成分
    semantic: SemanticComponents

    # 提取的事实列表
    facts: List[ExtractedFact] = field(default_factory=list)

    # 歧义标记
    ambiguities: List[Dict] = field(default_factory=list)

    # 领域信号
    domain_signals: List[str] = field(default_factory=list)

    # 下游需求信号
    needs_weather: bool = False
    needs_rag: bool = True
    needs_clarification: bool = False

    # 原始实体（供后续模块使用）
    raw_entities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """转换为字典（供日志/调试）"""
        return {
            "original_query": self.original_query,
            "intent": self.intent,
            "intent_confidence": self.intent_confidence,
            "semantic": {
                "subject": self.semantic.subject,
                "temporal": {
                    "raw": self.semantic.temporal.raw if self.semantic.temporal else None,
                    "normalized": self.semantic.temporal.normalized
                    if self.semantic.temporal
                    else None,
                    "type": self.semantic.temporal.time_type if self.semantic.temporal else None,
                }
                if self.semantic.temporal
                else None,
                "location": {
                    "raw": self.semantic.location.raw if self.semantic.location else None,
                    "normalized": self.semantic.location.normalized
                    if self.semantic.location
                    else None,
                    "type": self.semantic.location.location_type
                    if self.semantic.location
                    else None,
                    "city": self.semantic.location.city if self.semantic.location else None,
                    "category": self.semantic.location.category if self.semantic.location else None,
                }
                if self.semantic.location
                else None,
                "transport": {
                    "raw": self.semantic.transport.raw if self.semantic.transport else None,
                    "type": self.semantic.transport.transport_type
                    if self.semantic.transport
                    else None,
                }
                if self.semantic.transport
                else None,
                "activity": {
                    "raw": self.semantic.activity.raw if self.semantic.activity else None,
                    "type": self.semantic.activity.activity_type
                    if self.semantic.activity
                    else None,
                }
                if self.semantic.activity
                else None,
            },
            "facts": [
                {"type": f.fact_type, "value": f.value, "raw": f.raw_text} for f in self.facts
            ],
            "ambiguities": self.ambiguities,
            "domain_signals": self.domain_signals,
            "needs": {
                "weather": self.needs_weather,
                "rag": self.needs_rag,
                "clarification": self.needs_clarification,
            },
        }


class QueryUnderstandingEngine:
    """Query理解引擎"""

    # 领域关键词
    DOMAIN_KEYWORDS = {
        "出行": ["出行", "去", "到", "前往", "交通", "开车", "骑车", "步行", "公交", "地铁"],
        "购物": ["购物", "买", "逛街", "购物"],
        "饮食": ["吃", "吃饭", "餐厅", "外卖", "素食", "肉"],
        "能源": ["电", "用电", "省电", "节能", "空调", "暖气"],
        "环保": ["碳", "低碳", "环保", "减排", "分类", "回收"],
        "政策": ["补贴", "政策", "碳市场", "积分", "奖励"],
    }

    # 时间敏感关键词
    TIME_SENSITIVE_KEYWORDS = ["今天", "明天", "后天", "昨天", "前天", "这周", "下周"]

    # 地点敏感关键词
    LOCATION_SENSITIVE_KEYWORDS = [
        "去",
        "到",
        "回",
        "在",
        "西单",
        "大悦城",
        "家",
        "公司",
        "商场",
        "公园",
    ]

    # 出行方式关键词
    TRANSPORT_KEYWORDS = [
        "开车",
        "骑车",
        "骑行",
        "步行",
        "走路",
        "公交",
        "地铁",
        "打车",
        "出租",
        "拼车",
    ]

    def __init__(self):
        self._init_patterns()

    def _init_patterns(self):
        """初始化正则模式"""
        # 出行模式：主语 + 出行方式 + 目的地
        self.travel_patterns = [
            (r"(?:我|我们)?(开车|驾车|自驾)(?:去|到|往)(.+?)(?:出差|旅游|玩|办事|$)", "driving"),
            (r"(?:我|我们)?(骑车|骑行)(?:去|到|往)(.+?)(?:锻炼|健身|$)", "cycling"),
            (r"(?:我|我们)?(步行|走路)(?:去|到)(.+?)$", "walking"),
            (r"(?:我|我们)?(坐公交|乘公交|坐地铁|乘地铁)(?:去|到)(.+?)$", "transit"),
            (r"(?:我|我们)?(打车|坐出租)(?:去|到)(.+?)$", "taxi"),
            (r"去(.+?)(?:出差|旅游|玩|办事|购物|逛街|$)", None),
            (r"到(.+?)(?:出差|旅游|玩|办事|购物|逛街|$)", None),
            (r"(.+?)怎么去", None),
        ]

        # 行动计划模式
        self.action_plan_patterns = [
            (r"(?:我|我们)?打算(.+)", "plan"),
            (r"(?:我|我们)?计划(.+)", "plan"),
            (r"(?:我|我们)?准备(.+)", "plan"),
            (r"(?:我|我们)?想(.+)", "intention"),
            (r"(?:我|我们)?要(.+)", "intention"),
        ]

        # 行动报告模式
        self.action_report_patterns = [
            (
                r"(?:我|我们)?(今天|昨天|明天)?(开车|骑车|步行|坐公交|坐地铁)(?:去|到)(.+)",
                "completed",
            ),
            (r"(?:我|我们)?(买了|换了|安装了|开始|已经)(.+)", "completed"),
            (r"(?:我|我们)?刚(.+)", "just_completed"),
        ]

    def understand(
        self, query: str, existing_intent: str = None, existing_entities: List[str] = None
    ) -> QueryUnderstanding:
        """理解用户Query

        Args:
            query: 用户输入
            existing_intent: 已有的意图识别结果
            existing_entities: 已有的实体列表

        Returns:
            QueryUnderstanding 结构
        """
        query = query.strip()
        entities = existing_entities or []

        # 1. 提取语义成分
        semantic = self._extract_semantic_components(query)

        # 2. 提取事实
        facts = self._extract_facts(query, semantic)

        # 3. 检测歧义
        ambiguities = self._detect_ambiguities(query, semantic)

        # 4. 识别领域信号
        domain_signals = self._identify_domain_signals(query)

        # 5. 判断下游需求
        needs = self._determine_downstream_needs(query, semantic, existing_intent)

        return QueryUnderstanding(
            original_query=query,
            intent=existing_intent or "unknown",
            intent_confidence=0.5,
            semantic=semantic,
            facts=facts,
            ambiguities=ambiguities,
            domain_signals=domain_signals,
            needs_weather=needs["weather"],
            needs_rag=needs["rag"],
            needs_clarification=needs["clarification"],
            raw_entities=entities,
        )

    def _extract_semantic_components(self, query: str) -> SemanticComponents:
        """提取语义成分"""
        semantic = SemanticComponents()

        # 提取时间
        semantic.temporal = self._extract_temporal(query)

        # 提取地点
        semantic.location = self._extract_location(query)

        # 提取出行方式
        semantic.transport = self._extract_transport(query)

        # 提取活动
        semantic.activity = self._extract_activity(query)

        # 提取主语（简单处理）
        semantic.subject = self._extract_subject(query)

        return semantic

    def _extract_temporal(self, query: str) -> Optional[TemporalInfo]:
        """提取时间信息"""
        # 常见时间表达
        time_keywords = [
            "今天",
            "明天",
            "后天",
            "大后天",
            "昨天",
            "前天",
            "前天",
            "这周",
            "下周",
            "下周一",
            "下周二维",
            "下周些",
            "下周我",
            "下周天",
            "本周",
            "本月",
            "下月",
            "早上",
            "上午",
            "中午",
            "下午",
            "晚上",
            "傍晚",
            "现在",
            "稍后",
            "一会儿",
            "马上",
        ]

        for kw in time_keywords:
            if kw in query:
                return TemporalInfo(raw=kw)

        # 检查"X天后"模式
        match = re.search(r"(\d+)天后", query)
        if match:
            days = int(match.group(1))
            return TemporalInfo(raw=f"{days}天后")

        # 检查"下周一"等
        match = re.search(r"下周([一二三四五六日天])", query)
        if match:
            return TemporalInfo(raw=f"下周{match.group(1)}")

        return None

    def _extract_location(self, query: str) -> Optional[LocationInfo]:
        """提取位置信息"""
        # 排除的活动词（这些不应该被当作地点）
        activity_blacklist = [
            "开会",
            "工作",
            "上班",
            "吃饭",
            "运动",
            "锻炼",
            "健身",
            "旅游",
            "度假",
            "游玩",
            "出差",
            "办事",
            "购物",
            "逛街",
        ]

        # 目的地模式
        dest_patterns = [
            r"去(.+?)(?:出差|旅游|玩|办事|购物|逛街|$)",
            r"到(.+?)(?:出差|旅游|玩|办事|购物|逛街|$)",
            r"去(.+?)$",
            r"到(.+?)$",
            r"回(.+?)(?:家|公司|$)",
            r"在(.+?)(?:附近|旁边|$)",
        ]

        for pattern in dest_patterns:
            match = re.search(pattern, query)
            if match:
                dest = match.group(1).strip()
                # 排除黑名单中的活动词
                if len(dest) >= 2 and dest not in activity_blacklist:
                    return LocationInfo(raw=dest)

        # 检查是否包含家、公司等
        if any(w in query for w in ["回家", "到家", "在公司", "回公司"]):
            if "家" in query:
                return LocationInfo(raw="家", location_type="home")
            if "公司" in query:
                return LocationInfo(raw="公司", location_type="work")

        return None

    def _extract_transport(self, query: str) -> Optional[TransportInfo]:
        """提取出行方式"""
        for kw, transport_type in TransportInfo.TRANSPORT_MAP.items():
            if kw in query:
                # 判断是报告行为还是偏好
                is_preferred = any(p in query for p in ["想", "要", "喜欢", "偏好", "愿意"])
                return TransportInfo(
                    raw=kw, transport_type=transport_type, is_preferred=is_preferred
                )
        return None

    def _extract_activity(self, query: str) -> Optional[ActivityInfo]:
        """提取活动信息"""
        for kw, activity_type in ActivityInfo.ACTIVITY_MAP.items():
            if kw in query:
                return ActivityInfo(raw=kw, activity_type=activity_type)
        return None

    def _extract_subject(self, query: str) -> str:
        """提取主语"""
        if query.startswith("我"):
            return "用户"
        if query.startswith("我们"):
            return "用户群体"
        return "用户"

    def _extract_facts(self, query: str, semantic: SemanticComponents) -> List[ExtractedFact]:
        """提取事实"""
        facts = []

        if semantic.temporal:
            facts.append(
                ExtractedFact(
                    fact_type="time",
                    value=semantic.temporal.normalized or semantic.temporal.raw,
                    raw_text=semantic.temporal.raw,
                )
            )

        if semantic.location:
            facts.append(
                ExtractedFact(
                    fact_type="location",
                    value=semantic.location.normalized or semantic.location.raw,
                    raw_text=semantic.location.raw,
                )
            )

        if semantic.transport:
            facts.append(
                ExtractedFact(
                    fact_type="transport",
                    value=semantic.transport.transport_type,
                    raw_text=semantic.transport.raw,
                )
            )

        if semantic.activity:
            facts.append(
                ExtractedFact(
                    fact_type="activity",
                    value=semantic.activity.activity_type,
                    raw_text=semantic.activity.raw,
                )
            )

        return facts

    def _detect_ambiguities(self, query: str, semantic: SemanticComponents) -> List[Dict]:
        """检测歧义"""
        ambiguities = []

        # 时间模糊
        if semantic.temporal and semantic.temporal.time_type == "custom":
            ambiguities.append(
                {
                    "type": "time_vague",
                    "description": "时间表达较为模糊",
                    "raw": semantic.temporal.raw,
                }
            )

        # 地点模糊
        if semantic.location and semantic.location.location_type == "unknown":
            ambiguities.append(
                {
                    "type": "location_ambiguous",
                    "description": "地点类型不明确",
                    "raw": semantic.location.raw,
                }
            )

        # 代词指代（简单检测）
        pronouns = ["它", "这", "那", "这里", "那里"]
        if any(p in query for p in pronouns):
            ambiguities.append(
                {"type": "pronoun_reference", "description": "可能存在代词指代，需要上下文确认"}
            )

        # 方式不明确（用户说"去"但没有说明交通方式）
        if semantic.location and not semantic.transport:
            # 检查是否是模糊出行意图
            if any(kw in query for kw in ["去", "到", "前往"]):
                ambiguities.append({"type": "manner_unclear", "description": "出行方式未说明"})

        return ambiguities

    def _identify_domain_signals(self, query: str) -> List[str]:
        """识别领域信号"""
        signals = []
        query_lower = query.lower()

        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            if any(kw in query_lower for kw in keywords):
                signals.append(domain)

        return signals

    def _determine_downstream_needs(
        self, query: str, semantic: SemanticComponents, existing_intent: str = None
    ) -> Dict[str, bool]:
        """判断下游模块需求"""
        needs = {"weather": False, "rag": True, "clarification": False}

        # 天气需求判断
        weather_triggers = ["去", "到", "出行", "外面", "户外"]
        time_triggers = ["今天", "明天", "后天"]

        has_location = semantic.location is not None
        has_time = semantic.temporal is not None
        has_travel_intent = any(kw in query for kw in weather_triggers)

        # 意图为行动报告或建议请求，且涉及地点/时间
        if existing_intent in ["action_report", "advice_request", "unknown"]:
            if (has_location or has_time) and has_travel_intent:
                needs["weather"] = True

        # 知识查询需要 RAG
        if existing_intent == "knowledge_query":
            needs["rag"] = True

        # 歧义过多时需要澄清
        if (
            semantic.location
            and semantic.location.raw
            and semantic.location.location_type == "unknown"
        ):
            needs["clarification"] = False  # 暂时不主动询问

        return needs


def create_query_understanding(
    query: str, intent: str = None, entities: List[str] = None
) -> QueryUnderstanding:
    """便捷函数：创建Query理解"""
    engine = QueryUnderstandingEngine()
    return engine.understand(query, intent, entities)


# 单元测试
if __name__ == "__main__":
    print("=" * 60)
    print("Query Understanding Test")
    print("=" * 60)

    engine = QueryUnderstandingEngine()

    test_cases = [
        "我今天要去西单大悦城",
        "明天我想开车去北京",
        "下周打算坐地铁去开会",
        "这周哪天适合户外运动？",
        "我想买电动车还是燃油车？",
        "我刚安装了太阳能面板",
    ]

    for query in test_cases:
        print(f"\n[Query]: {query}")
        result = engine.understand(query)

        print(f"  Intent: {result.intent}")
        print(f"  Temporal: {result.semantic.temporal.raw if result.semantic.temporal else 'None'}")
        print(
            f"  Location: {result.semantic.location.raw if result.semantic.location else 'None'} ({result.semantic.location.location_type if result.semantic.location else 'None'})"
        )
        print(
            f"  Transport: {result.semantic.transport.raw if result.semantic.transport else 'None'}"
        )
        print(f"  Activity: {result.semantic.activity.raw if result.semantic.activity else 'None'}")
        print(f"  Needs Weather: {result.needs_weather}")
        print(f"  Ambiguities: {len(result.ambiguities)}")

        # 打印结构化JSON
        print(f"  [Structured]: {result.to_dict()}")

    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)
