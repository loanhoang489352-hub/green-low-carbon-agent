"""
动态画像更新模块
在对话过程中自动学习用户偏好，动态更新画像
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from collections import Counter


class DynamicProfileUpdater:
    """
    动态画像更新器

    功能:
    - 从对话中自动提取用户偏好
    - 分析用户行为模式
    - 渐进式更新用户画像
    - 学习用户反馈
    """

    # 兴趣关键词映射
    INTEREST_KEYWORDS = {
        "low_carbon_travel": {
            "keywords": [
                "开车",
                "骑车",
                "骑行",
                "步行",
                "公交",
                "地铁",
                "打车",
                "电动车",
                "自行车",
                "飞机",
                "火车",
                "通勤",
                "出行",
                "交通",
            ],
            "weight": 1.0,
        },
        "energy_saving": {
            "keywords": [
                "空调",
                "暖气",
                "电费",
                "用电",
                "节能",
                "省电",
                "灯",
                "LED",
                "热水器",
                "洗衣机",
                "冰箱",
                "功耗",
            ],
            "weight": 1.0,
        },
        "waste_classification": {
            "keywords": [
                "垃圾",
                "分类",
                "回收",
                "废品",
                "可回收",
                "有害",
                "厨余",
                "干垃圾",
                "湿垃圾",
            ],
            "weight": 1.0,
        },
        "green_consumption": {
            "keywords": [
                "购物",
                "购买",
                "环保产品",
                "有机",
                "一次性",
                "塑料袋",
                "包装",
                "快递",
                "网购",
            ],
            "weight": 1.0,
        },
        "diet_eco": {
            "keywords": [
                "饮食",
                "素食",
                "减少浪费",
                "光盘",
                "肉",
                "蔬菜",
                "外卖",
                "本地食材",
                "食物",
                "吃",
            ],
            "weight": 0.8,
        },
        "water_conservation": {
            "keywords": ["水", "节水", "用水", "水费", "洗澡", "淋浴", "水资源"],
            "weight": 0.8,
        },
        "renewable_energy": {
            "keywords": ["太阳能", "光伏", "新能源", "风电", "清洁能源", "充电桩", "充电"],
            "weight": 1.0,
        },
        "carbon_offset": {
            "keywords": ["植树", "碳汇", "碳中和", "碳补偿", "碳足迹", "碳排放", "减排"],
            "weight": 1.0,
        },
    }

    # 行为阶段关键词
    BEHAVIOR_STAGE_KEYWORDS = {
        "无意向": {
            "indicators": ["不了解", "没想过", "不想", "没必要", "太麻烦", "没时间"],
            "opposite": ["想", "考虑", "了解"],
        },
        "意向": {
            "indicators": ["想", "考虑", "了解一下", "可能", "有兴趣", "打算", "计划"],
            "opposite": ["已经", "开始", "做了", "完成"],
        },
        "准备": {
            "indicators": ["准备", "正在准备", "打算", "计划", "要开始", "准备开始", "第一步"],
            "opposite": ["已经", "完成", "习惯了"],
        },
        "行动": {
            "indicators": ["开始", "正在", "已经", "做了", "执行", "尝试", "进行中", "实施"],
            "opposite": ["想", "考虑", "打算"],
        },
        "维持": {
            "indicators": ["坚持", "持续", "保持", "习惯", "已经习惯", "一直", "每天"],
            "opposite": ["不想", "算了", "放弃"],
        },
    }

    # 行动类型
    ACTION_TYPES = {
        "travel_change": {
            "positive": [
                "骑行了",
                "骑自行车",
                "步行了",
                "走路去",
                "坐地铁",
                "坐公交",
                "换了电动车",
                "买了自行车",
                "少开了车",
            ],
            "negative": ["开了车", "打车了", "坐飞机了"],
        },
        "energy_saving": {
            "positive": ["关了灯", "关了空调", "调高了温度", "拔了插头", "换了LED", "用了节能模式"],
            "negative": ["开了空调", "开了暖气", "忘了关灯"],
        },
        "consumption_change": {
            "positive": ["买了环保袋", "拒绝了塑料", "买了有机", "自带杯子", "自带餐具"],
            "negative": ["点了外卖", "买了塑料瓶"],
        },
        "waste_action": {
            "positive": ["分类了", "回收了", "卖了废品", "做了垃圾分类"],
            "negative": ["乱扔了", "没分类"],
        },
    }

    # 知识水平信号
    KNOWLEDGE_LEVEL_SIGNALS = {
        "beginner": {
            "questions": [
                "什么是",
                "为什么",
                "碳足迹是什么",
                "怎么算",
                "什么意思",
                "不太懂",
                "不清楚",
            ],
            "terminology_lack": True,
        },
        "advanced": {
            "questions": ["计算方法", "原理", "机制", "标准", "数据", "研究", "分析", "碳汇计算"],
            "terminology_use": ["碳足迹", "碳中和", "碳达峰", "温室气体", "生命周期", "LCA"],
        },
    }

    def __init__(self):
        self._interest_scores: Dict[str, Dict[str, float]] = {}
        self._action_history: Dict[str, List[Dict]] = {}
        self._feedback_history: Dict[str, List[Dict]] = {}

    def analyze_message(
        self, user_id: str, message: str, intent_type: str, entities: List[str] = None
    ) -> Dict[str, Any]:
        """
        分析用户消息，提取偏好信息

        Args:
            user_id: 用户ID
            message: 用户消息
            intent_type: 意图类型
            entities: 识别的实体列表

        Returns:
            分析结果字典
        """
        results = {
            "detected_interests": [],
            "behavior_indicators": [],
            "knowledge_signals": [],
            "action_reports": [],
            "confidence_scores": {},
        }

        message_lower = message.lower()

        interests = self._detect_interests(message_lower)
        results["detected_interests"] = interests

        for interest_id, score in interests:
            self._update_interest_score(user_id, interest_id, score)

        stage_indicator = self._detect_behavior_stage(message)
        if stage_indicator:
            results["behavior_indicators"].append(stage_indicator)

        knowledge_level = self._detect_knowledge_level(message, intent_type)
        if knowledge_level:
            results["knowledge_signals"].append(knowledge_level)

        actions = self._extract_action_reports(message)
        results["action_reports"] = actions

        for action in actions:
            self._record_action(user_id, action)

        return results

    def _detect_interests(self, message: str) -> List[Tuple[str, float]]:
        """检测用户兴趣"""
        interests = []

        for interest_id, config in self.INTEREST_KEYWORDS.items():
            matches = 0
            for keyword in config["keywords"]:
                if keyword in message:
                    matches += 1

            if matches > 0:
                score = min(matches * config["weight"] * 0.3, 1.0)
                interests.append((interest_id, score))

        interests.sort(key=lambda x: x[1], reverse=True)
        return interests[:3]

    def _update_interest_score(self, user_id: str, interest_id: str, score: float):
        """更新兴趣分数"""
        if user_id not in self._interest_scores:
            self._interest_scores[user_id] = {}

        current = self._interest_scores[user_id].get(interest_id, 0)
        self._interest_scores[user_id][interest_id] = min(current + score * 0.5, 1.0)

    def _detect_behavior_stage(self, message: str) -> Optional[Dict]:
        """检测行为阶段"""
        for stage, config in self.BEHAVIOR_STAGE_KEYWORDS.items():
            positive_count = sum(1 for kw in config["indicators"] if kw in message)
            if positive_count > 0:
                return {
                    "stage": stage,
                    "confidence": min(positive_count * 0.3, 1.0),
                    "matched_keywords": [kw for kw in config["indicators"] if kw in message],
                }
        return None

    def _detect_knowledge_level(self, message: str, intent_type: str) -> Optional[Dict]:
        """检测知识水平"""
        beginner_signals = self.KNOWLEDGE_LEVEL_SIGNALS["beginner"]
        advanced_signals = self.KNOWLEDGE_LEVEL_SIGNALS["advanced"]

        beginner_count = sum(1 for q in beginner_signals["questions"] if q in message)

        advanced_count = sum(1 for term in advanced_signals["terminology_use"] if term in message)
        advanced_count += sum(1 for q in advanced_signals["questions"] if q in message)

        if beginner_count > advanced_count and beginner_count >= 2:
            return {"level": "beginner", "confidence": min(beginner_count * 0.2, 0.8)}
        elif advanced_count > beginner_count and advanced_count >= 2:
            return {"level": "advanced", "confidence": min(advanced_count * 0.2, 0.8)}

        return None

    def _extract_action_reports(self, message: str) -> List[Dict]:
        """提取行动报告"""
        actions = []

        for action_type, configs in self.ACTION_TYPES.items():
            for action in configs.get("positive", []):
                if action in message:
                    actions.append(
                        {
                            "type": action_type,
                            "sentiment": "positive",
                            "action": action,
                            "original_text": message,
                        }
                    )
                    break

            for action in configs.get("negative", []):
                if action in message:
                    actions.append(
                        {
                            "type": action_type,
                            "sentiment": "negative",
                            "action": action,
                            "original_text": message,
                        }
                    )
                    break

        return actions

    def _record_action(self, user_id: str, action: Dict):
        """记录用户行动"""
        if user_id not in self._action_history:
            self._action_history[user_id] = []

        action_record = {**action, "timestamp": datetime.now().isoformat()}

        self._action_history[user_id].append(action_record)

        if len(self._action_history[user_id]) > 100:
            self._action_history[user_id] = self._action_history[user_id][-100:]

    def analyze_feedback(
        self, user_id: str, feedback_type: str, feedback_content: str, suggestion: str = None
    ) -> Dict[str, Any]:
        """
        分析用户反馈

        Args:
            user_id: 用户ID
            feedback_type: 反馈类型 (accept/reject/partial)
            feedback_content: 反馈内容
            suggestion: 原始建议内容

        Returns:
            分析结果
        """
        results = {"feedback_type": feedback_type, "reasons": [], "inferred_preferences": {}}

        feedback_lower = feedback_content.lower()

        if feedback_type == "accept":
            results["reasons"].append("用户接受了建议")
            if suggestion:
                interests = self._detect_interests(suggestion.lower())
                for interest_id, _ in interests:
                    self._update_interest_score(user_id, interest_id, 0.3)

        elif feedback_type == "reject":
            reasons = []

            if any(word in feedback_lower for word in ["太贵", "价格", "费用", "成本", "花钱"]):
                reasons.append("cost_concern")
                results["inferred_preferences"]["cost_sensitivity"] = "high"

            if any(word in feedback_lower for word in ["麻烦", "复杂", "不方便", "没时间", "太忙"]):
                reasons.append("convenience_concern")
                results["inferred_preferences"]["convenience_priority"] = "high"

            if any(word in feedback_lower for word in ["不适合", "不适用", "我家", "情况"]):
                reasons.append("context_mismatch")
                results["inferred_preferences"]["needs_personalization"] = True

            if any(word in feedback_lower for word in ["听不懂", "太专业", "不懂"]):
                reasons.append("complexity_issue")
                results["inferred_preferences"]["preferred_complexity"] = "simple"

            results["reasons"] = reasons

            if suggestion:
                self._infer_rejected_topics(user_id, suggestion)

        self._record_feedback(user_id, feedback_type, feedback_content, results)

        return results

    def _infer_rejected_topics(self, user_id: str, suggestion: str):
        """推断被拒绝的话题"""
        interests = self._detect_interests(suggestion.lower())

        if user_id not in self._interest_scores:
            self._interest_scores[user_id] = {}

        for interest_id, _ in interests:
            current = self._interest_scores[user_id].get(interest_id, 0)
            self._interest_scores[user_id][interest_id] = max(current - 0.2, 0)

    def _record_feedback(self, user_id: str, feedback_type: str, content: str, analysis: Dict):
        """记录反馈"""
        if user_id not in self._feedback_history:
            self._feedback_history[user_id] = []

        record = {
            "type": feedback_type,
            "content": content,
            "analysis": analysis,
            "timestamp": datetime.now().isoformat(),
        }

        self._feedback_history[user_id].append(record)

        if len(self._feedback_history[user_id]) > 100:
            self._feedback_history[user_id] = self._feedback_history[user_id][-100:]

    def get_learned_interests(self, user_id: str, top_n: int = 5) -> List[Tuple[str, float]]:
        """获取学习到的兴趣排序"""
        if user_id not in self._interest_scores:
            return []

        scores = self._interest_scores[user_id]
        sorted_interests = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_interests[:top_n]

    def get_action_summary(self, user_id: str, recent_days: int = 7) -> Dict[str, Any]:
        """获取行动总结"""
        if user_id not in self._action_history:
            return {"total_actions": 0, "positive_ratio": 0, "action_types": {}}

        actions = self._action_history[user_id]

        cutoff = datetime.now().timestamp() - (recent_days * 24 * 3600)
        recent_actions = [
            a for a in actions if datetime.fromisoformat(a["timestamp"]).timestamp() > cutoff
        ]

        positive = sum(1 for a in recent_actions if a.get("sentiment") == "positive")
        negative = sum(1 for a in recent_actions if a.get("sentiment") == "negative")
        total = len(recent_actions)

        action_types = Counter(a.get("type") for a in recent_actions)

        return {
            "total_actions": total,
            "positive_count": positive,
            "negative_count": negative,
            "positive_ratio": positive / total if total > 0 else 0,
            "action_types": dict(action_types),
            "most_common_type": action_types.most_common(1)[0][0] if action_types else None,
        }

    def get_profile_updates(self, user_id: str) -> Dict[str, Any]:
        """生成画像更新建议"""
        updates = {}

        if user_id in self._interest_scores and self._interest_scores[user_id]:
            top_interests = self.get_learned_interests(user_id, top_n=5)
            interest_list = [i[0] for i in top_interests if i[1] > 0.3]
            if interest_list:
                updates["primary_interests"] = interest_list

        if user_id in self._action_history:
            action_summary = self.get_action_summary(user_id, recent_days=30)
            if action_summary["total_actions"] >= 3:
                most_common = action_summary.get("most_common_type")
                if most_common:
                    action_to_interest = {
                        "travel_change": "low_carbon_travel",
                        "energy_saving": "energy_saving",
                        "consumption_change": "green_consumption",
                        "waste_action": "waste_classification",
                    }
                    if most_common in action_to_interest:
                        if "primary_interests" not in updates:
                            updates["primary_interests"] = []
                        if action_to_interest[most_common] not in updates["primary_interests"]:
                            updates["primary_interests"].append(action_to_interest[most_common])

        return updates

    def clear_user_data(self, user_id: str):
        """清除用户数据"""
        if user_id in self._interest_scores:
            del self._interest_scores[user_id]
        if user_id in self._action_history:
            del self._action_history[user_id]
        if user_id in self._feedback_history:
            del self._feedback_history[user_id]


# 全局实例
_profile_updater = None


def get_profile_updater() -> DynamicProfileUpdater:
    """获取动态画像更新器实例"""
    global _profile_updater
    if _profile_updater is None:
        _profile_updater = DynamicProfileUpdater()
    return _profile_updater
