"""
用户画像管理器
管理用户画像，包括环保认知水平、行为阶段、偏好等
支持完整的信息收集和动态更新
"""

import sqlite3
from db.connection import get_connection  # P6.P.2: 用池替裸 connect
import json
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime
import sys

project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


class UserProfileManager:
    """
    用户画像管理器 - 增强版

    画像维度:
    - basic_info: 基础信息 (年龄/性别/地域/收入等)
    - eco_profile: 环保画像 (知识水平/行为阶段/兴趣领域/行动历史)
    - behavior_profile: 行为画像 (出行偏好/饮食偏好/消费习惯等)
    - communication_style: 沟通风格 (专业/通俗/数据驱动)
    - preferences: 个性化偏好 (内容深度/响应长度/语气风格)
    - interaction_stats: 交互统计
    """

    KNOWLEDGE_LEVELS = ["入门", "了解", "精通"]
    BEHAVIOR_STAGES = ["无意向", "意向", "准备", "行动", "维持"]
    COMMUNICATION_STYLES = ["专业", "通俗", "数据驱动", "故事型"]
    ACTION_WILLINGNESS = ["高", "中", "低"]

    # 地域分类
    REGION_CATEGORIES = {
        "华北": ["北京", "天津", "河北", "山西", "内蒙古"],
        "东北": ["辽宁", "吉林", "黑龙江"],
        "华东": ["上海", "江苏", "浙江", "安徽", "福建", "江西", "山东"],
        "华中": ["河南", "湖北", "湖南"],
        "华南": ["广东", "广西", "海南"],
        "西南": ["重庆", "四川", "贵州", "云南", "西藏"],
        "西北": ["陕西", "甘肃", "青海", "宁夏", "新疆"],
        "港澳台": ["香港", "澳门", "台湾"]
    }

    # 年龄段分类
    AGE_GROUPS = {
        "18-25": {"label": "青年", "style_hint": "casual", "tone_hint": "friendly"},
        "26-35": {"label": "中青年", "style_hint": "balanced", "tone_hint": "professional"},
        "36-45": {"label": "中年", "style_hint": "detailed", "tone_hint": "patient"},
        "46-55": {"label": "中老年", "style_hint": "detailed", "tone_hint": "patient"},
        "56+": {"label": "老年", "style_hint": "detailed", "tone_hint": "gentle"}
    }

    # 收入水平分类
    INCOME_LEVELS = {
        "低收入": {"description": "月收入 5000 元以下", "action_cost_sensitivity": "高"},
        "中等收入": {"description": "月收入 5000-15000 元", "action_cost_sensitivity": "中"},
        "中高收入": {"description": "月收入 15000-30000 元", "action_cost_sensitivity": "低"},
        "高收入": {"description": "月收入 30000 元以上", "action_cost_sensitivity": "很低"}
    }

    # 家庭规模分类
    FAMILY_TYPES = {
        "1": {"label": "独居", "energy_focus": "个人", "recommendation_type": "简单实用"},
        "2": {"label": "两口之家", "energy_focus": "两人", "recommendation_type": "经济实惠"},
        "3-4": {"label": "三口/四口之家", "energy_focus": "家庭", "recommendation_type": "全面均衡"},
        "5+": {"label": "大家庭", "energy_focus": "集体", "recommendation_type": "系统化"}
    }

    # 环保关注领域
    ECO_INTERESTS = [
        {"id": "low_carbon_travel", "name": "低碳出行", "icon": "🚌", "keywords": ["骑车", "步行", "地铁", "公交", "电动车"]},
        {"id": "energy_saving", "name": "节能减排", "icon": "[TIP]", "keywords": ["空调", "用电", "暖气", "节能"]},
        {"id": "waste_classification", "name": "垃圾分类", "icon": "♻️", "keywords": ["垃圾", "分类", "回收", "废品"]},
        {"id": "green_consumption", "name": "绿色消费", "icon": "🛒", "keywords": ["购物", "环保产品", "有机", "一次性"]},
        {"id": "diet_eco", "name": "饮食环保", "icon": "🥗", "keywords": ["素食", "减少浪费", "光盘", "本地食材"]},
        {"id": "water_conservation", "name": "水资源保护", "icon": "💧", "keywords": ["节水", "用水", "水费"]},
        {"id": "renewable_energy", "name": "清洁能源", "icon": "☀️", "keywords": ["太阳能", "光伏", "新能源"]},
        {"id": "carbon_offset", "name": "碳补偿", "icon": "🌳", "keywords": ["植树", "碳汇", "碳中和"]}
    ]

    # 沟通风格配置
    COMMUNICATION_CONFIGS = {
        "专业": {
            "tone": "professional",
            "detail_level": "high",
            "use_terminology": True,
            "include_data": True
        },
        "通俗": {
            "tone": "friendly",
            "detail_level": "medium",
            "use_terminology": False,
            "include_data": False
        },
        "数据驱动": {
            "tone": "analytical",
            "detail_level": "high",
            "use_terminology": True,
            "include_data": True
        },
        "故事型": {
            "tone": "narrative",
            "detail_level": "medium",
            "use_terminology": False,
            "include_data": False
        }
    }

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = project_root / "data" / "user_profiles.db"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        self._profile_cache: Dict[str, Dict] = {}

        print("👤 用户画像系统初始化完成")

    def _init_database(self):
        """初始化数据库"""
        conn = get_connection(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                profile_data TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_interaction TEXT,
                conversation_count INTEGER DEFAULT 0
            )
        """)

        try:
            conn.commit()
        finally:
            pass  # conn 池 60s TTL 自动关

    def _get_default_profile(self, user_id: str) -> Dict[str, Any]:
        """获取默认画像"""
        return {
            "user_id": user_id,
            "registration_time": datetime.now().isoformat(),
            "basic_info": {
                "age_group": None,
                "gender": None,
                "region": None,
                "region_category": None,
                "income_level": None,
                "family_type": None,
                "occupation": None,
                "education": None
            },
            "eco_profile": {
                "knowledge_level": "intermediate",
                "behavior_stage": "意向",
                "awareness_level": "medium",
                "primary_interests": [],
                "action_history": [],
                "completed_actions": [],
                "rejected_actions": [],
                "engagement_history": []
            },
            "behavior_profile": {
                "travel_habits": {},
                "diet_habits": {},
                "consumption_habits": {},
                "home_energy_usage": {},
                "lifestyle_tags": []
            },
            "communication_style": "balanced",
            "preferences": {
                "content_depth": "balanced",
                "response_length": "medium",
                "tone": "encouraging",
                "format_preference": "text"
            },
            "preference_learning": {
                "confirmed_interests": [],
                "inferred_interests": [],
                "rejected_topics": [],
                "learning_confidence": {}
            },
            "statistics": {
                "total_conversations": 0,
                "total_messages": 0,
                "questions_asked": 0,
                "actions_reported": 0,
                "feedback_given": 0,
                "suggestions_accepted": 0,
                "suggestions_rejected": 0,
                "topic_interactions": {}
            },
            "onboarding_completed": False,
            "onboarding_step": 0
        }

    def create_profile(self, user_id: str, profile_data: Dict[str, Any] = None):
        """创建新用户画像"""
        conn = get_connection(str(self.db_path))
        # P6.P.2: 池已设 busy_timeout + WAL,无需再设
        cursor = conn.cursor()

        try:
            now = datetime.now().isoformat()
            profile = profile_data if profile_data else self._get_default_profile(user_id)
            profile["user_id"] = user_id
            profile["created_at"] = now
            profile["updated_at"] = now

            # P4-C.1: 默认 profile 含空图谱结构(由 get_profile 懒加载完整节点)
            if "graph" not in profile:
                from user_profile.profile_graph import UserProfileGraph
                profile["graph"] = UserProfileGraph(user_id).to_dict()

            cursor.execute("""
                INSERT OR REPLACE INTO user_profiles
                (user_id, profile_data, created_at, updated_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, json.dumps(profile, ensure_ascii=False), now, now))

            conn.commit()
        finally:
            pass  # conn 池 60s TTL 自动关

        if user_id in self._profile_cache:
            del self._profile_cache[user_id]

    def get_profile(self, user_id: str) -> Dict[str, Any]:
        """获取用户画像"""
        if user_id in self._profile_cache:
            return self._profile_cache[user_id]

        conn = get_connection(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT profile_data FROM user_profiles WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
        finally:
            pass  # conn 池 60s TTL 自动关

        if row is None:
            self.create_profile(user_id)
            return self.get_profile(user_id)

        profile = json.loads(row[0])

        # P4-C.1: 兜底 — 老数据可能没有 graph 字段
        if "graph" not in profile or not profile["graph"]:
            from user_profile.profile_graph import UserProfileGraph
            profile["graph"] = UserProfileGraph(user_id).to_dict()

        self._profile_cache[user_id] = profile
        return profile

    def update_profile(self, user_id: str, updates: Dict[str, Any]) -> bool:
        """更新用户画像"""
        profile = self.get_profile(user_id)

        for key, value in updates.items():
            if isinstance(value, dict) and key in profile:
                profile[key].update(value)
            else:
                profile[key] = value

        profile["updated_at"] = datetime.now().isoformat()

        conn = get_connection(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE user_profiles
            SET profile_data = ?, updated_at = ?
            WHERE user_id = ?
        """, (json.dumps(profile, ensure_ascii=False), profile["updated_at"], user_id))

        success = cursor.rowcount > 0
        try:
            conn.commit()
        finally:
            pass  # conn 池 60s TTL 自动关

        if user_id in self._profile_cache:
            del self._profile_cache[user_id]

        return success

    def update_basic_info(self, user_id: str, basic_info: Dict[str, Any]) -> bool:
        """更新基础信息并推断画像"""
        profile = self.get_profile(user_id)

        current_basic = profile.get("basic_info", {})
        current_basic.update(basic_info)

        inferred = self._infer_from_basic_info(current_basic)

        profile["basic_info"] = current_basic
        profile["communication_style"] = inferred.get("communication_style", profile.get("communication_style"))
        profile["preferences"].update(inferred.get("preferences", {}))

        profile["updated_at"] = datetime.now().isoformat()

        conn = get_connection(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE user_profiles
            SET profile_data = ?, updated_at = ?
            WHERE user_id = ?
        """, (json.dumps(profile, ensure_ascii=False), profile["updated_at"], user_id))

        success = cursor.rowcount > 0
        try:
            conn.commit()
        finally:
            pass  # conn 池 60s TTL 自动关

        if user_id in self._profile_cache:
            del self._profile_cache[user_id]

        return success

    def _infer_from_basic_info(self, basic_info: Dict) -> Dict[str, Any]:
        """根据基础信息推断画像"""
        inferred = {}

        age_group = basic_info.get("age_group")
        if age_group and age_group in self.AGE_GROUPS:
            group_info = self.AGE_GROUPS[age_group]
            inferred["communication_style"] = group_info.get("style_hint", "balanced")

        income = basic_info.get("income_level")
        if income and income in self.INCOME_LEVELS:
            cost_sens = self.INCOME_LEVELS[income].get("action_cost_sensitivity", "中")
            inferred["preferences"] = {
                "cost_sensitivity": cost_sens
            }

        return inferred

    def update_eco_profile(self, user_id: str, eco_updates: Dict[str, Any]) -> bool:
        """更新环保画像"""
        profile = self.get_profile(user_id)

        eco_profile = profile.get("eco_profile", {})
        eco_profile.update(eco_updates)

        profile["eco_profile"] = eco_profile
        profile["updated_at"] = datetime.now().isoformat()

        # P4-C.2: 同步到画像图谱
        profile["graph"] = self._sync_profile_to_graph(profile, eco_updates)

        conn = get_connection(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE user_profiles
            SET profile_data = ?, updated_at = ?
            WHERE user_id = ?
        """, (json.dumps(profile, ensure_ascii=False), profile["updated_at"], user_id))

        success = cursor.rowcount > 0
        try:
            conn.commit()
        finally:
            pass  # conn 池 60s TTL 自动关

        if user_id in self._profile_cache:
            del self._profile_cache[user_id]

        return success

    def _sync_profile_to_graph(self, profile: Dict[str, Any], eco_updates: Dict[str, Any]) -> Dict[str, Any]:
        """同步 profile 字段到 UserProfileGraph(P4-C.2)

        触发场景:
        - primary_interests 变化 → add_interest
        - behavior_stage 变化 → set_behavior_stage
        - action_history 追加 → add_action
        - completed_actions 追加 → add_action (positive)
        - rejected_actions 追加 → add_action (negative)
        """
        from user_profile.profile_graph import UserProfileGraph
        graph_data = profile.get("graph", {})
        if not graph_data:
            graph = UserProfileGraph(profile["user_id"])
        else:
            graph = UserProfileGraph.from_dict(graph_data)

        # interests
        for interest in eco_updates.get("primary_interests", []) or []:
            graph.add_interest(interest, confidence=0.7, source="profile_sync")

        # behavior stage
        new_stage = eco_updates.get("behavior_stage")
        if new_stage:
            graph.set_behavior_stage(new_stage)

        # action history(通常是新追加的列表)
        new_actions = eco_updates.get("action_history", []) or []
        for act in new_actions:
            if isinstance(act, dict):
                graph.add_action(
                    act.get("action", "未命名行为"),
                    sentiment=act.get("sentiment", "positive"),
                    context=act.get("context", ""),
                    carbon_saved=act.get("carbon_saved"),
                )
            elif isinstance(act, str):
                graph.add_action(act, sentiment="positive")

        return graph.to_dict()

    def update_behavior_profile(self, user_id: str, behavior_updates: Dict[str, Any]) -> bool:
        """更新行为画像"""
        profile = self.get_profile(user_id)

        behavior_profile = profile.get("behavior_profile", {})
        for key, value in behavior_updates.items():
            if isinstance(value, dict) and key in behavior_profile:
                behavior_profile[key].update(value)
            else:
                behavior_profile[key] = value

        profile["behavior_profile"] = behavior_profile
        profile["updated_at"] = datetime.now().isoformat()

        conn = get_connection(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE user_profiles
            SET profile_data = ?, updated_at = ?
            WHERE user_id = ?
        """, (json.dumps(profile, ensure_ascii=False), profile["updated_at"], user_id))

        success = cursor.rowcount > 0
        try:
            conn.commit()
        finally:
            pass  # conn 池 60s TTL 自动关

        if user_id in self._profile_cache:
            del self._profile_cache[user_id]

        return success

    def update_preference_learning(
        self,
        user_id: str,
        interest: str = None,
        action: str = None,
        accepted: bool = None,
        topic: str = None
    ) -> bool:
        """更新偏好学习数据"""
        profile = self.get_profile(user_id)

        pref_learning = profile.get("preference_learning", {
            "confirmed_interests": [],
            "inferred_interests": [],
            "rejected_topics": [],
            "learning_confidence": {}
        })

        if interest is not None:
            if accepted:
                if interest not in pref_learning["confirmed_interests"]:
                    pref_learning["confirmed_interests"].append(interest)
                if interest in pref_learning["inferred_interests"]:
                    pref_learning["inferred_interests"].remove(interest)
            else:
                if interest not in pref_learning["inferred_interests"]:
                    pref_learning["inferred_interests"].append(interest)

        if action is not None and accepted:
            eco_profile = profile.get("eco_profile", {})
            completed = eco_profile.get("completed_actions", [])
            if action not in completed:
                completed.append(action)
            eco_profile["completed_actions"] = completed
            profile["eco_profile"] = eco_profile

        if topic is not None and accepted is False:
            rejected = pref_learning.get("rejected_topics", [])
            if topic not in rejected:
                rejected.append(topic)
            pref_learning["rejected_topics"] = rejected

        profile["preference_learning"] = pref_learning
        profile["updated_at"] = datetime.now().isoformat()

        conn = get_connection(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE user_profiles
            SET profile_data = ?, updated_at = ?
            WHERE user_id = ?
        """, (json.dumps(profile, ensure_ascii=False), profile["updated_at"], user_id))

        success = cursor.rowcount > 0
        try:
            conn.commit()
        finally:
            pass  # conn 池 60s TTL 自动关

        if user_id in self._profile_cache:
            del self._profile_cache[user_id]

        return success

    def record_interaction(self, user_id: str, interaction_type: str, details: Dict = None) -> bool:
        """记录交互用于统计"""
        profile = self.get_profile(user_id)

        stats = profile.get("statistics", {
            "total_conversations": 0,
            "total_messages": 0,
            "questions_asked": 0,
            "actions_reported": 0,
            "feedback_given": 0,
            "suggestions_accepted": 0,
            "suggestions_rejected": 0,
            "topic_interactions": {}
        })

        stats["total_messages"] = stats.get("total_messages", 0) + 1

        if interaction_type == "question":
            stats["questions_asked"] = stats.get("questions_asked", 0) + 1
        elif interaction_type == "action":
            stats["actions_reported"] = stats.get("actions_reported", 0) + 1
        elif interaction_type == "feedback":
            stats["feedback_given"] = stats.get("feedback_given", 0) + 1
        elif interaction_type == "accept":
            stats["suggestions_accepted"] = stats.get("suggestions_accepted", 0) + 1
        elif interaction_type == "reject":
            stats["suggestions_rejected"] = stats.get("suggestions_rejected", 0) + 1

        if details and "topic" in details:
            topic = details["topic"]
            topic_stats = stats.get("topic_interactions", {})
            topic_stats[topic] = topic_stats.get(topic, 0) + 1
            stats["topic_interactions"] = topic_stats

        profile["statistics"] = stats
        profile["last_interaction"] = datetime.now().isoformat()
        profile["updated_at"] = datetime.now().isoformat()

        conn = get_connection(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE user_profiles
            SET profile_data = ?, updated_at = ?, last_interaction = ?
            WHERE user_id = ?
        """, (json.dumps(profile, ensure_ascii=False), profile["updated_at"], profile["last_interaction"], user_id))

        success = cursor.rowcount > 0
        try:
            conn.commit()
        finally:
            pass  # conn 池 60s TTL 自动关

        if user_id in self._profile_cache:
            del self._profile_cache[user_id]

        return success

    def update_conversation_count(self, user_id: str):
        """更新对话计数"""
        conn = get_connection(str(self.db_path))
        # P6.P.2: 池已设 busy_timeout + WAL,无需再设
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE user_profiles
                SET conversation_count = conversation_count + 1,
                    updated_at = ?
                WHERE user_id = ?
            """, (datetime.now().isoformat(), user_id))

            profile = self.get_profile(user_id)
            stats = profile.get("statistics", {})
            stats["total_conversations"] = stats.get("total_conversations", 0) + 1
            profile["statistics"] = stats

            cursor.execute("""
                UPDATE user_profiles
                SET profile_data = ?
                WHERE user_id = ?
            """, (json.dumps(profile, ensure_ascii=False), user_id))

            conn.commit()
        finally:
            pass  # conn 池 60s TTL 自动关

        if user_id in self._profile_cache:
            del self._profile_cache[user_id]

    def adjust_behavior_stage(self, user_id: str, direction: str = "up") -> Optional[str]:
        """调整行为阶段"""
        profile = self.get_profile(user_id)
        current = profile.get("eco_profile", {}).get("behavior_stage", "意向")

        stages = self.BEHAVIOR_STAGES
        idx = stages.index(current) if current in stages else 1

        if direction == "up" and idx < len(stages) - 1:
            idx += 1
        elif direction == "down" and idx > 0:
            idx -= 1

        new_stage = stages[idx]

        if new_stage != current:
            self.update_eco_profile(user_id, {"behavior_stage": new_stage})
            return new_stage

        return None

    def get_suggestion_strategy(self, user_id: str) -> Dict[str, Any]:
        """获取建议策略"""
        profile = self.get_profile(user_id)

        basic = profile.get("basic_info", {})
        eco = profile.get("eco_profile", {})
        prefs = profile.get("preferences", {})
        behavior = profile.get("behavior_profile", {})

        strategy = {
            "knowledge_level": eco.get("knowledge_level", "intermediate"),
            "behavior_stage": eco.get("behavior_stage", "意向"),
            "awareness_level": eco.get("awareness_level", "medium"),
            "communication_style": profile.get("communication_style", "balanced"),
            "cost_sensitivity": prefs.get("cost_sensitivity", "中"),
            "content_depth": prefs.get("content_depth", "balanced"),
            "response_length": prefs.get("response_length", "medium"),
            "primary_interests": eco.get("primary_interests", []),
            "confirmed_interests": profile.get("preference_learning", {}).get("confirmed_interests", []),
            "rejected_topics": profile.get("preference_learning", {}).get("rejected_topics", []),
            "family_type": basic.get("family_type"),
            "income_level": basic.get("income_level"),
        }

        stage = eco.get("behavior_stage", "意向")
        if stage == "无意向":
            strategy.update({
                "focus": "意识唤醒",
                "suggestion_intensity": "very_low",
                "action_complexity": "minimal",
                "tone": "gentle_encouragement",
                "example_focus": "easy_wins"
            })
        elif stage == "意向":
            strategy.update({
                "focus": "动机强化",
                "suggestion_intensity": "low",
                "action_complexity": "simple",
                "tone": "positive",
                "example_focus": "similar_people"
            })
        elif stage == "准备":
            strategy.update({
                "focus": "行动计划",
                "suggestion_intensity": "medium",
                "action_complexity": "moderate",
                "tone": "actionable",
                "example_focus": "step_by_step"
            })
        elif stage == "行动":
            strategy.update({
                "focus": "坚持支持",
                "suggestion_intensity": "medium",
                "action_complexity": "challenging",
                "tone": "supportive",
                "example_focus": "progress_tracking"
            })
        else:
            strategy.update({
                "focus": "深度拓展",
                "suggestion_intensity": "low",
                "action_complexity": "advanced",
                "tone": "expert",
                "example_focus": "innovation"
            })

        return strategy

    def get_personalization_context(self, user_id: str) -> Dict[str, Any]:
        """获取个性化上下文用于生成响应"""
        profile = self.get_profile(user_id)

        basic = profile.get("basic_info", {})
        eco = profile.get("eco_profile", {})
        behavior = profile.get("behavior_profile", {})
        prefs = profile.get("preferences", {})
        pref_learning = profile.get("preference_learning", {})

        comm_config = self.COMMUNICATION_CONFIGS.get(
            profile.get("communication_style", "balanced"),
            self.COMMUNICATION_CONFIGS["通俗"]
        )

        return {
            "user_id": user_id,
            "basic_info_summary": self._summarize_basic_info(basic),
            "knowledge_level": eco.get("knowledge_level", "intermediate"),
            "knowledge_level_chinese": self._get_knowledge_level_chinese(eco.get("knowledge_level")),
            "behavior_stage": eco.get("behavior_stage", "意向"),
            "behavior_stage_index": self.BEHAVIOR_STAGES.index(eco.get("behavior_stage", "意向")) if eco.get("behavior_stage", "意向") in self.BEHAVIOR_STAGES else 1,
            "primary_interests": eco.get("primary_interests", []),
            "interest_icons": self._get_interest_icons(eco.get("primary_interests", [])),
            "completed_actions": eco.get("completed_actions", []),
            "confirmed_interests": pref_learning.get("confirmed_interests", []),
            "rejected_topics": pref_learning.get("rejected_topics", []),
            "communication_config": comm_config,
            "communication_style": profile.get("communication_style", "balanced"),
            "preferences": prefs,
            "family_context": self._get_family_context(basic),
            "travel_habits": behavior.get("travel_habits", {}),
            "diet_habits": behavior.get("diet_habits", {}),
            "suggestion_acceptance_rate": self._calculate_acceptance_rate(profile),
            "onboarding_completed": profile.get("onboarding_completed", False),
            "conversation_count": profile.get("statistics", {}).get("total_conversations", 0),
            "last_interaction": profile.get("last_interaction")
        }

    def _summarize_basic_info(self, basic: Dict) -> str:
        """生成基础信息摘要"""
        parts = []
        if basic.get("age_group"):
            parts.append(f"{basic['age_group']}岁")
        if basic.get("region"):
            parts.append(f"{basic['region']}")
        if basic.get("family_type"):
            parts.append(f"{basic['family_type']}")
        return "，".join(parts) if parts else "新用户"

    def _get_knowledge_level_chinese(self, level: str) -> str:
        mapping = {
            "beginner": "入门",
            "intermediate": "了解",
            "advanced": "精通"
        }
        return mapping.get(level, "了解")

    def _get_interest_icons(self, interests: List[str]) -> str:
        icons = []
        for eco_interest in self.ECO_INTERESTS:
            if eco_interest["id"] in interests or eco_interest["name"] in interests:
                icons.append(eco_interest["icon"])
        return " ".join(icons) if icons else ""

    def _get_family_context(self, basic: Dict) -> str:
        family_type = basic.get("family_type", "")
        family_info = self.FAMILY_TYPES.get(family_type, {})
        return family_info.get("label", "")

    def _calculate_acceptance_rate(self, profile: Dict) -> float:
        stats = profile.get("statistics", {})
        accepted = stats.get("suggestions_accepted", 0)
        rejected = stats.get("suggestions_rejected", 0)
        total = accepted + rejected
        return accepted / total if total > 0 else 0.5

    def get_onboarding_questions(self) -> List[Dict[str, Any]]:
        """获取引导问题列表"""
        return [
            {
                "step": 1,
                "field": "age_group",
                "question": "你的年龄段是？",
                "type": "single_choice",
                "options": [
                    {"value": "18-25", "label": "18-25岁 (青年)"},
                    {"value": "26-35", "label": "26-35岁 (中青年)"},
                    {"value": "36-45", "label": "36-45岁 (中年)"},
                    {"value": "46-55", "label": "46-55岁 (中老年)"},
                    {"value": "56+", "label": "56岁以上 (老年)"}
                ]
            },
            {
                "step": 2,
                "field": "gender",
                "question": "你的性别是？",
                "type": "single_choice",
                "options": [
                    {"value": "male", "label": "男"},
                    {"value": "female", "label": "女"},
                    {"value": "other", "label": "其他/不愿透露"}
                ]
            },
            {
                "step": 3,
                "field": "region",
                "question": "你生活在哪个地区？",
                "type": "text_input",
                "placeholder": "例如：北京、上海、广东",
                "suggestions": list(set(sum(self.REGION_CATEGORIES.values(), [])))
            },
            {
                "step": 4,
                "field": "income_level",
                "question": "你的月收入水平大约是？",
                "type": "single_choice",
                "options": [
                    {"value": "低收入", "label": "5000元以下"},
                    {"value": "中等收入", "label": "5000-15000元"},
                    {"value": "中高收入", "label": "15000-30000元"},
                    {"value": "高收入", "label": "30000元以上"}
                ]
            },
            {
                "step": 5,
                "field": "family_type",
                "question": "你的家庭构成是怎样的？",
                "type": "single_choice",
                "options": [
                    {"value": "1", "label": "独居"},
                    {"value": "2", "label": "两口之家"},
                    {"value": "3-4", "label": "三口/四口之家"},
                    {"value": "5+", "label": "大家庭（5人及以上）"}
                ]
            },
            {
                "step": 6,
                "field": "primary_interests",
                "question": "你最关注哪些环保领域？（可多选）",
                "type": "multi_choice",
                "options": [
                    {"value": interest["id"], "label": f"{interest['icon']} {interest['name']}"}
                    for interest in self.ECO_INTERESTS
                ],
                "min_select": 1,
                "max_select": 4
            },
            {
                "step": 7,
                "field": "eco_knowledge",
                "question": "你对低碳环保的了解程度如何？",
                "type": "single_choice",
                "options": [
                    {"value": "low", "label": "刚了解，还不太清楚"},
                    {"value": "medium", "label": "知道一些，想学习更多"},
                    {"value": "high", "label": "比较了解，关注了很久"}
                ]
            },
            {
                "step": 8,
                "field": "behavior_stage",
                "question": "你在低碳生活方面目前处于哪个阶段？",
                "type": "single_choice",
                "options": [
                    {"value": "无意向", "label": "还没开始考虑"},
                    {"value": "意向", "label": "有想法，但还没行动"},
                    {"value": "准备", "label": "正在准备采取行动"},
                    {"value": "行动", "label": "已经在做低碳生活"},
                    {"value": "维持", "label": "已经成为习惯了"}
                ]
            }
        ]

    def complete_onboarding(self, user_id: str, answers: Dict[str, Any]) -> bool:
        """完成引导流程"""
        profile = self.get_profile(user_id)

        basic_info = {
            "age_group": answers.get("age_group"),
            "gender": answers.get("gender"),
            "region": answers.get("region"),
            "family_type": answers.get("family_type"),
            "income_level": answers.get("income_level")
        }

        region_category = None
        for cat_name, cities in self.REGION_CATEGORIES.items():
            if answers.get("region") in cities:
                region_category = cat_name
                break
        if region_category is None and answers.get("region"):
            region_category = "其他"
        basic_info["region_category"] = region_category

        eco_profile = {
            "knowledge_level": self._map_knowledge_level(answers.get("eco_knowledge")),
            "behavior_stage": answers.get("behavior_stage", "意向"),
            "primary_interests": answers.get("primary_interests", []),
            "awareness_level": answers.get("eco_knowledge", "medium")
        }

        inferred = self._infer_from_basic_info(basic_info)

        profile["basic_info"] = basic_info
        profile["eco_profile"] = {**profile.get("eco_profile", {}), **eco_profile}
        profile["communication_style"] = inferred.get("communication_style", "balanced")
        profile["preferences"] = {**profile.get("preferences", {}), **inferred.get("preferences", {})}
        profile["onboarding_completed"] = True
        profile["onboarding_step"] = 8
        profile["updated_at"] = datetime.now().isoformat()

        conn = get_connection(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE user_profiles
            SET profile_data = ?, updated_at = ?
            WHERE user_id = ?
        """, (json.dumps(profile, ensure_ascii=False), profile["updated_at"], user_id))

        success = cursor.rowcount > 0
        try:
            conn.commit()
        finally:
            pass  # conn 池 60s TTL 自动关

        if user_id in self._profile_cache:
            del self._profile_cache[user_id]

        return success

    def _map_knowledge_level(self, level: str) -> str:
        mapping = {"low": "beginner", "medium": "intermediate", "high": "advanced"}
        return mapping.get(level, "intermediate")

    def get_all_profiles(self) -> List[Dict]:
        """获取所有用户画像"""
        conn = get_connection(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT user_id FROM user_profiles")
            rows = cursor.fetchall()
        finally:
            pass  # conn 池 60s TTL 自动关

        return [self.get_profile(row[0]) for row in rows]

    def delete_profile(self, user_id: str) -> bool:
        """删除用户画像"""
        conn = get_connection(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("DELETE FROM user_profiles WHERE user_id = ?", (user_id,))

        success = cursor.rowcount > 0
        try:
            conn.commit()
        finally:
            pass  # conn 池 60s TTL 自动关

        if user_id in self._profile_cache:
            del self._profile_cache[user_id]

        return success

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        conn = get_connection(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT COUNT(*) FROM user_profiles")
            total_users = cursor.fetchone()[0]

            cursor.execute("SELECT SUM(conversation_count) FROM user_profiles")
            total_conversations = cursor.fetchone()[0] or 0
        finally:
            pass  # conn 池 60s TTL 自动关

        return {
            "total_users": total_users,
            "total_conversations": total_conversations,
            "avg_conversations_per_user": (
                total_conversations / total_users if total_users > 0 else 0
            )
        }
