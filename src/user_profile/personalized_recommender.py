"""
个性化推荐引擎
基于用户画像和上下文生成个性化建议
"""

import random
from typing import Dict, List, Any
from dataclasses import dataclass


@dataclass
class Recommendation:
    """推荐结果"""

    action: str
    category: str
    reason: str
    personalization_context: str
    difficulty: str
    impact: str
    estimated_carbon_saving: str
    examples: List[str]
    rejected_reasons: List[str] = None


class PersonalizedRecommendationEngine:
    """
    个性化推荐引擎

    根据用户画像、行为阶段、偏好等生成个性化低碳建议
    """

    # 建议库 - 按类别和难度组织
    ACTION_LIBRARY = {
        "出行": {
            "easy": [
                {
                    "action": "短距离出行选择步行或骑行",
                    "difficulty": "easy",
                    "impact": "low",
                    "carbon_saving": "每次约0.5-2kg CO2",
                    "reason_templates": [
                        "短距离骑行不仅环保，还能锻炼身体",
                        "步行是最环保的出行方式，还省钱",
                    ],
                    "examples": ["3公里以内可以步行或骑共享单车", "小区周边购物步行即可"],
                    "personalization_hints": ["通勤距离", "交通工具"],
                },
                {
                    "action": "每周选择一天公共交通出行",
                    "difficulty": "easy",
                    "impact": "medium",
                    "carbon_saving": "每周约5-10kg CO2",
                    "reason_templates": [
                        "公共交通可以显著减少个人碳排放",
                        "减少开车还能省油费停车费",
                    ],
                    "examples": ["周三不开车，坐地铁或公交上班", "周末逛商场坐公交去"],
                    "personalization_hints": ["通勤方式", "停车便利性"],
                },
                {
                    "action": "搭载同事或朋友拼车出行",
                    "difficulty": "easy",
                    "impact": "medium",
                    "carbon_saving": "每次约2-5kg CO2/人",
                    "reason_templates": [
                        "拼车可以大幅减少道路车辆数量",
                        "和朋友一起通勤还能聊天解闷",
                    ],
                    "examples": ["和邻居拼车上下班", "顺路接送孩子时约其他家长"],
                    "personalization_hints": ["通勤路线", "家庭成员"],
                },
            ],
            "medium": [
                {
                    "action": "考虑购买新能源汽车",
                    "difficulty": "medium",
                    "impact": "high",
                    "carbon_saving": "每年约2-4吨 CO2",
                    "reason_templates": [
                        "电动车虽然充电有碳排放，但整体比燃油车少60%以上",
                        "长期使用成本更低，保养更简单",
                    ],
                    "examples": ["比亚迪、蔚来、特斯拉等都是不错的选择", "看看是否有购车补贴政策"],
                    "personalization_hints": ["收入水平", "家庭用车需求"],
                },
                {
                    "action": "优化通勤路线，减少开车频率",
                    "difficulty": "medium",
                    "impact": "medium",
                    "carbon_saving": "每月约30-60kg CO2",
                    "reason_templates": [
                        "合理规划路线可以减少无效里程",
                        "减少开车还能缓解交通压力",
                    ],
                    "examples": ["住得近的同事可以轮流开车", "在地铁站附近停车换乘"],
                    "personalization_hints": ["通勤距离", "工作地点交通"],
                },
            ],
            "hard": [
                {
                    "action": "申请安装家庭充电桩",
                    "difficulty": "hard",
                    "impact": "high",
                    "carbon_saving": "配合电动车使用效果更佳",
                    "reason_templates": [
                        "在家充电更方便，还能利用低谷电价",
                        "配合太阳能发电系统效果更好",
                    ],
                    "examples": ["咨询物业和电力公司申请流程", "了解当地的补贴政策"],
                    "personalization_hints": ["住房类型", "收入水平"],
                }
            ],
        },
        "家居": {
            "easy": [
                {
                    "action": "离开房间时随手关灯",
                    "difficulty": "easy",
                    "impact": "low",
                    "carbon_saving": "每月约5-15kg CO2",
                    "reason_templates": ["随手关灯是最简单的节能方式", "养成习惯后完全不费力"],
                    "examples": ["离开客厅就关灯", "白天充分利用自然光"],
                    "personalization_hints": ["家庭成员"],
                },
                {
                    "action": "空调温度夏天调高1度，冬天调低1度",
                    "difficulty": "easy",
                    "impact": "medium",
                    "carbon_saving": "每年约200-500kg CO2",
                    "reason_templates": [
                        "1度的温差人体几乎感觉不到，但能省不少电",
                        "空调是家庭耗电大户，温度调整效果明显",
                    ],
                    "examples": ["夏天设置26度，冬天设置20度", "睡觉时再调低/高1-2度"],
                    "personalization_hints": ["家庭用电习惯", "空调使用频率"],
                },
                {
                    "action": "拔掉不用的电器插头",
                    "difficulty": "easy",
                    "impact": "low",
                    "carbon_saving": "每月约10-20kg CO2",
                    "reason_templates": [
                        "电器待机也会耗电，叫'吸血鬼电力'",
                        "集中在一个插排上方便开关",
                    ],
                    "examples": ["电视、机顶盒、充电器等不用时拔掉", "使用带开关的插排"],
                    "personalization_hints": ["家电数量"],
                },
            ],
            "medium": [
                {
                    "action": "更换LED节能灯泡",
                    "difficulty": "medium",
                    "impact": "medium",
                    "carbon_saving": "每年约100-200kg CO2",
                    "reason_templates": [
                        "LED灯比白炽灯节能80%以上",
                        "虽然单价高一些，但寿命长8-10倍",
                    ],
                    "examples": ["先换家里最常用的几个灯", "购买时选择正规品牌"],
                    "personalization_hints": ["住房情况", "收入水平"],
                },
                {
                    "action": "使用智能插座或定时器控制电器",
                    "difficulty": "medium",
                    "impact": "medium",
                    "carbon_saving": "每月约10-30kg CO2",
                    "reason_templates": ["智能控制可以避免忘记关闭电器", "定时开关更方便"],
                    "examples": ["电热水器设定时开关", "路由器设置夜间关闭"],
                    "personalization_hints": ["科技接受度", "家电类型"],
                },
            ],
            "hard": [
                {
                    "action": "安装智能家居系统优化用电",
                    "difficulty": "hard",
                    "impact": "high",
                    "carbon_saving": "每年约500-1000kg CO2",
                    "reason_templates": [
                        "智能家居可以精细化管理用电",
                        "虽然投入较大，但长期收益明显",
                    ],
                    "examples": ["米家、绿米等智能家居生态", "从简单的智能插座开始逐步升级"],
                    "personalization_hints": ["收入水平", "科技接受度", "住房情况"],
                },
                {
                    "action": "安装太阳能光伏发电系统",
                    "difficulty": "hard",
                    "impact": "very_high",
                    "carbon_saving": "每年约1-3吨 CO2",
                    "reason_templates": ["太阳能是真正的清洁能源", "多余电力可以卖给电网"],
                    "examples": ["咨询当地的光伏安装公司", "了解安装条件和补贴政策"],
                    "personalization_hints": ["住房类型", "地区光照", "收入水平"],
                },
            ],
        },
        "消费": {
            "easy": [
                {
                    "action": "购物时自带环保袋",
                    "difficulty": "easy",
                    "impact": "low",
                    "carbon_saving": "每月约5-10kg CO2",
                    "reason_templates": ["塑料袋难降解，污染环境", "环保袋结实耐用，长期更省钱"],
                    "examples": ["买菜、逛超市都带上环保袋", "车里、包里各放一个备用"],
                    "personalization_hints": ["购物习惯"],
                },
                {
                    "action": "减少一次性塑料制品使用",
                    "difficulty": "easy",
                    "impact": "low",
                    "carbon_saving": "每月约3-8kg CO2",
                    "reason_templates": [
                        "一次性塑料是最大的污染源之一",
                        "使用可重复使用的物品更环保",
                    ],
                    "examples": ["自带水杯、餐具、吸管", "拒绝一次性餐具"],
                    "personalization_hints": ["饮食习惯", "工作环境"],
                },
                {
                    "action": "购买本地食材，减少食品运输碳排放",
                    "difficulty": "easy",
                    "impact": "medium",
                    "carbon_saving": "每月约20-50kg CO2",
                    "reason_templates": ["食品运输是碳排放的重要来源", "本地食材更新鲜"],
                    "examples": ["去菜市场或农场直销点买菜", "关注食材产地标签"],
                    "personalization_hints": ["饮食习惯", "购物习惯"],
                },
            ],
            "medium": [
                {
                    "action": "选择有环保认证的产品",
                    "difficulty": "medium",
                    "impact": "medium",
                    "carbon_saving": "累计效果显著",
                    "reason_templates": [
                        "环保认证产品通常更耐用、更环保",
                        "虽然可能贵一点，但品质更有保障",
                    ],
                    "examples": ["选购有绿色食品标志的食品", "选择有能效标识的家电"],
                    "personalization_hints": ["收入水平", "消费习惯"],
                },
                {
                    "action": "减少冲动消费，只买需要的东西",
                    "difficulty": "medium",
                    "impact": "high",
                    "carbon_saving": "视消费额而定",
                    "reason_templates": ["减少消费是最有效的减排方式", "理性消费还能省钱"],
                    "examples": ["购物前列清单", "等几天再决定是否购买"],
                    "personalization_hints": ["消费习惯", "收入水平"],
                },
            ],
            "hard": [
                {
                    "action": "转向可持续品牌和二手交易",
                    "difficulty": "hard",
                    "impact": "high",
                    "carbon_saving": "显著减少碳足迹",
                    "reason_templates": ["可持续品牌注重环保和公平", "二手交易可以延长物品寿命"],
                    "examples": ["购买二手书籍、家具", "选择承诺可持续发展的品牌"],
                    "personalization_hints": ["消费观念", "收入水平"],
                }
            ],
        },
        "饮食": {
            "easy": [
                {
                    "action": "减少食物浪费，光盘行动",
                    "difficulty": "easy",
                    "impact": "medium",
                    "carbon_saving": "每月约30-80kg CO2",
                    "reason_templates": [
                        "食物浪费不仅是浪费钱，还浪费了生产它时的碳排放",
                        "按需购买、合理储存可以大大减少浪费",
                    ],
                    "examples": ["少做一点，按食量做饭", "吃不完的下一顿继续吃"],
                    "personalization_hints": ["家庭规模", "饮食习惯"],
                },
                {
                    "action": "每周尝试一天素食",
                    "difficulty": "easy",
                    "impact": "medium",
                    "carbon_saving": "每周约15-30kg CO2",
                    "reason_templates": [
                        "肉类生产碳排放很高，减少吃肉就是减排",
                        "素食也很有营养，还有助于健康",
                    ],
                    "examples": ["周一设为'无肉日'", "尝试一些素食食谱"],
                    "personalization_hints": ["饮食习惯", "家庭成员"],
                },
                {
                    "action": "减少外卖订餐",
                    "difficulty": "easy",
                    "impact": "medium",
                    "carbon_saving": "每次约1-3kg CO2",
                    "reason_templates": ["外卖包装和配送都会产生碳排放", "自己做饭更健康、更省钱"],
                    "examples": ["中午带饭上班", "周末在家做饭"],
                    "personalization_hints": ["工作环境", "饮食习惯"],
                },
            ],
            "medium": [
                {
                    "action": "选择当季本地蔬菜",
                    "difficulty": "medium",
                    "impact": "low",
                    "carbon_saving": "每月约10-20kg CO2",
                    "reason_templates": ["当季蔬菜不需要大棚加热", "本地蔬菜减少运输碳排放"],
                    "examples": ["夏天多吃瓜果，冬天多吃萝卜白菜", "去菜市场买当天的菜"],
                    "personalization_hints": ["饮食习惯", "购物习惯"],
                }
            ],
            "hard": [
                {
                    "action": "计算并追踪个人碳足迹",
                    "difficulty": "hard",
                    "impact": "high",
                    "carbon_saving": "通过了解带动行动",
                    "reason_templates": ["了解自己的碳排放才能更好地减排", "数据化管理更科学"],
                    "examples": ["使用碳足迹计算器", "记录每月的用电量、开车里程等"],
                    "personalization_hints": ["知识水平", "科技接受度"],
                }
            ],
        },
        "垃圾分类": {
            "easy": [
                {
                    "action": "在家设置分类垃圾桶",
                    "difficulty": "easy",
                    "impact": "medium",
                    "carbon_saving": "提高回收率",
                    "reason_templates": ["分类是回收的前提", "在家就分好，投放更方便"],
                    "examples": ["设置可回收/不可回收两个桶", "厨余垃圾单独存放"],
                    "personalization_hints": ["住房情况", "家庭成员"],
                },
                {
                    "action": "了解当地垃圾分类规则",
                    "difficulty": "easy",
                    "impact": "medium",
                    "carbon_saving": "正确分类才能有效回收",
                    "reason_templates": ["不同城市分类标准可能不同", "正确分类是环保的基础"],
                    "examples": ["查询当地垃圾分类指南", "记住常见物品的分类"],
                    "personalization_hints": ["地区"],
                },
            ],
            "medium": [
                {
                    "action": "将可回收物送去回收点",
                    "difficulty": "medium",
                    "impact": "medium",
                    "carbon_saving": "每吨可回收物减排约1.5吨 CO2",
                    "reason_templates": ["回收利用可以大大减少原材料开采", "很多物品都可以回收"],
                    "examples": ["收集废纸、塑料瓶送回收站", "电子垃圾送专业回收点"],
                    "personalization_hints": ["居住环境"],
                }
            ],
            "hard": [
                {
                    "action": "参与社区环保活动",
                    "difficulty": "hard",
                    "impact": "high",
                    "carbon_saving": "影响更多人",
                    "reason_templates": [
                        "一个人的力量有限，集体行动影响更大",
                        "参与活动还能结识志同道合的朋友",
                    ],
                    "examples": ["参加社区垃圾分类志愿活动", "组织邻居一起环保"],
                    "personalization_hints": ["社交意愿", "时间精力"],
                }
            ],
        },
    }

    # 行为阶段推荐策略
    STAGE_STRATEGIES = {
        "无意向": {
            "difficulty_filter": ["easy"],
            "suggestion_count": 1,
            "focus": "意识唤醒",
            "tone": "鼓励性",
            "highlight": "简单易行的小行动",
        },
        "意向": {
            "difficulty_filter": ["easy", "medium"],
            "suggestion_count": 2,
            "focus": "动机强化",
            "tone": "积极正面",
            "highlight": "行动的好处和意义",
        },
        "准备": {
            "difficulty_filter": ["easy", "medium"],
            "suggestion_count": 2,
            "focus": "行动计划",
            "tone": "务实指导",
            "highlight": "具体步骤和注意事项",
        },
        "行动": {
            "difficulty_filter": ["medium", "hard"],
            "suggestion_count": 2,
            "focus": "坚持支持",
            "tone": "支持鼓励",
            "highlight": "成功案例和进步追踪",
        },
        "维持": {
            "difficulty_filter": ["hard"],
            "suggestion_count": 2,
            "focus": "深度拓展",
            "tone": "专业深入",
            "highlight": "进阶技巧和创新方法",
        },
    }

    # 收入水平建议调整
    INCOME_ADJUSTMENTS = {
        "低收入": {
            "prefer_easy": True,
            "avoid_hard": True,
            "highlight_benefit": "省钱",
            "cost_emphasis": True,
        },
        "中等收入": {
            "prefer_easy": True,
            "avoid_hard": False,
            "highlight_benefit": "性价比",
            "cost_emphasis": True,
        },
        "中高收入": {
            "prefer_easy": False,
            "avoid_hard": False,
            "highlight_benefit": "品质生活",
            "cost_emphasis": False,
        },
        "高收入": {
            "prefer_easy": False,
            "avoid_hard": False,
            "highlight_benefit": "社会责任",
            "cost_emphasis": False,
        },
    }

    # 家庭规模建议调整
    FAMILY_ADJUSTMENTS = {
        "1": {"scale_down": ["全家行动", "家庭合作"], "scale_up": ["个人实践"]},
        "2": {"scale_down": [], "scale_up": []},
        "3-4": {"scale_down": [], "scale_up": ["孩子带动全家"]},
        "5+": {"scale_down": ["全家参与"], "scale_up": ["分头行动"]},
    }

    def __init__(self):
        self._recommendation_history: Dict[str, List[str]] = {}

    # 任务1 P1-1: 地域化 + 兴趣偏好 + 行为频次的差异化加权
    # 修复:之前 3 角色返回完全相同(同质化),根因是缺这些加权
    REGION_AFFINITY = {
        "beijing": {
            "出行": 1.3,
            "家居": 1.1,
            "消费": 1.0,
            "饮食": 1.0,
            "垃圾分类": 1.4,
        },  # 京津冀公交发达 + 严垃圾分类
        "shanghai": {
            "出行": 1.3,
            "家居": 1.1,
            "消费": 1.1,
            "饮食": 1.0,
            "垃圾分类": 1.4,
        },  # 上海垃圾分类
        "guangzhou": {
            "出行": 1.0,
            "家居": 1.0,
            "消费": 1.2,
            "饮食": 1.3,
            "垃圾分类": 1.1,
        },  # 粤菜多
        "shenzhen": {"出行": 1.1, "家居": 1.0, "消费": 1.2, "饮食": 1.2, "垃圾分类": 1.1},
        "hangzhou": {
            "出行": 1.1,
            "家居": 1.2,
            "消费": 1.1,
            "饮食": 1.0,
            "垃圾分类": 1.3,
        },  # 互联网+绿色城市
    }
    INTEREST_TO_CATEGORY = {
        "travel": "出行",
        "low_carbon_travel": "出行",
        "home_energy": "家居",
        "energy_saving": "家居",
        "low_carbon_purchase": "消费",
        "green_consumption": "消费",
        "diet_eco": "饮食",
        "low_carbon_diet": "饮食",
        "recycle": "垃圾分类",
        "waste_classification": "垃圾分类",
        "plastic_reduction": "消费",
        "campus": "饮食",
        "business": "消费",
    }

    def _compute_category_weight(
        self,
        category: str,
        region: str,
        interests: list,
        recent_behaviors: list,
    ) -> float:
        """任务1 P1-1: 类别加权综合 — 地域 + 兴趣 + 行为频次

        Returns:
            权重(>=0.1,越大越优先)
        """
        weight = 1.0
        # 1) 地域加成
        reg = (region or "").lower()
        weight *= self.REGION_AFFINITY.get(reg, {}).get(category, 1.0)
        # 2) 兴趣加成(任一兴趣命中, +50%)
        for it in interests or []:
            if self.INTEREST_TO_CATEGORY.get(it) == category:
                weight *= 1.5
                break
        # 3) 最近行为频次加成(最近 7 天同一类行为,降权避免重复推荐同类;反向,如从未做过,则提权)
        behavior_types_to_cat = {
            "bus": "出行",
            "walk": "出行",
            "bike": "出行",
            "electricity": "家居",
            "water": "家居",
            "purchase": "消费",
            "recycle": "垃圾分类",
            "plastic": "垃圾分类",
            "recycle_sort": "垃圾分类",
        }
        recent_cat_count = sum(
            1
            for b in (recent_behaviors or [])
            if behavior_types_to_cat.get(b.get("type", "")) == category
        )
        if recent_cat_count >= 5:
            weight *= 0.4  # 已大量做该类,降权
        elif recent_cat_count == 0:
            weight *= 1.3  # 从未做过,提权(引导新行为)
        return max(0.1, weight)

    def generate_recommendations(
        self, user_profile: Dict[str, Any], context: Dict[str, Any] = None, count: int = 3
    ) -> List[Recommendation]:
        """
        生成个性化建议

        Args:
            user_profile: 用户画像
            context: 额外上下文（如对话内容、recent_behaviors、region）
            count: 建议数量

        Returns:
            推荐列表
        """
        recommendations = []

        eco = user_profile.get("eco_profile", {})
        basic = user_profile.get("basic_info", {})
        prefs = user_profile.get("preferences", {})
        pref_learning = user_profile.get("preference_learning", {})

        # 任务1 P1-1: 多源提取 region/interests/recent_behaviors
        region = basic.get("region") or basic.get("city") or user_profile.get("region", "")
        interests = (
            confirmed_interests
            if (
                confirmed_interests := pref_learning.get("confirmed_interests", [])
                or prefs.get("interests", [])
                or user_profile.get("interests", [])
            )
            else []
        )
        recent_behaviors = (
            (context or {}).get("recent_behaviors") or user_profile.get("recent_behaviors") or []
        )

        behavior_stage = eco.get("behavior_stage", "意向")
        strategy = self.STAGE_STRATEGIES.get(behavior_stage, self.STAGE_STRATEGIES["意向"])

        income_level = basic.get("income_level", "中等收入")
        income_adj = self.INCOME_ADJUSTMENTS.get(income_level, self.INCOME_ADJUSTMENTS["中等收入"])

        family_type = basic.get("family_type", "3-4")
        family_adj = self.FAMILY_ADJUSTMENTS.get(family_type, self.FAMILY_ADJUSTMENTS["3-4"])

        confirmed_interests_pref = pref_learning.get("confirmed_interests", [])
        rejected_topics = pref_learning.get("rejected_topics", [])

        difficulty_filter = strategy.get("difficulty_filter", ["easy", "medium"])

        categories = list(self.ACTION_LIBRARY.keys())
        # 任务1 P1-1: 用 _compute_category_weight 综合排序,不再固定顺序
        weighted_categories = sorted(
            categories,
            key=lambda c: self._compute_category_weight(c, region, interests, recent_behaviors),
            reverse=True,
        )

        suggested_actions = []
        for category in weighted_categories:
            if len(suggested_actions) >= count:
                break

            if category not in self.ACTION_LIBRARY:
                continue

            if category in rejected_topics:
                continue

            for difficulty in difficulty_filter:
                if len(suggested_actions) >= count:
                    break

                if difficulty not in self.ACTION_LIBRARY[category]:
                    continue

                for action_data in self.ACTION_LIBRARY[category][difficulty]:
                    if len(suggested_actions) >= count:
                        break

                    action_text = action_data["action"]

                    if self._was_recently_suggested(user_profile.get("user_id", ""), action_text):
                        continue

                    if not self._check_personalization_fit(action_data, user_profile):
                        continue

                    reason = self._generate_personalized_reason(
                        action_data, user_profile, strategy, income_adj
                    )
        recommendations = []

        eco = user_profile.get("eco_profile", {})
        basic = user_profile.get("basic_info", {})
        prefs = user_profile.get("preferences", {})
        pref_learning = user_profile.get("preference_learning", {})

        behavior_stage = eco.get("behavior_stage", "意向")
        strategy = self.STAGE_STRATEGIES.get(behavior_stage, self.STAGE_STRATEGIES["意向"])

        income_level = basic.get("income_level", "中等收入")
        income_adj = self.INCOME_ADJUSTMENTS.get(income_level, self.INCOME_ADJUSTMENTS["中等收入"])

        family_type = basic.get("family_type", "3-4")
        family_adj = self.FAMILY_ADJUSTMENTS.get(family_type, self.FAMILY_ADJUSTMENTS["3-4"])

        confirmed_interests = pref_learning.get("confirmed_interests", [])
        rejected_topics = pref_learning.get("rejected_topics", [])

        difficulty_filter = strategy.get("difficulty_filter", ["easy", "medium"])

        categories = list(self.ACTION_LIBRARY.keys())
        if confirmed_interests:
            interest_to_category = {
                "low_carbon_travel": "出行",
                "energy_saving": "家居",
                "green_consumption": "消费",
                "diet_eco": "饮食",
                "waste_classification": "垃圾分类",
            }
            priority_categories = [
                interest_to_category.get(i, "家居")
                for i in confirmed_interests
                if i in interest_to_category
            ]
            other_categories = [c for c in categories if c not in priority_categories]
            ordered_categories = priority_categories + other_categories
        else:
            ordered_categories = categories

        suggested_actions = []
        for category in ordered_categories:
            if len(suggested_actions) >= count:
                break

            if category not in self.ACTION_LIBRARY:
                continue

            if category in rejected_topics:
                continue

            for difficulty in difficulty_filter:
                if len(suggested_actions) >= count:
                    break

                if difficulty not in self.ACTION_LIBRARY[category]:
                    continue

                for action_data in self.ACTION_LIBRARY[category][difficulty]:
                    if len(suggested_actions) >= count:
                        break

                    action_text = action_data["action"]

                    if self._was_recently_suggested(user_profile.get("user_id", ""), action_text):
                        continue

                    if not self._check_personalization_fit(action_data, user_profile):
                        continue

                    reason = self._generate_personalized_reason(
                        action_data, user_profile, strategy, income_adj
                    )

                    rec = Recommendation(
                        action=action_text,
                        category=category,
                        reason=reason,
                        personalization_context=self._generate_personalization_context(
                            action_data, user_profile
                        ),
                        difficulty=difficulty,
                        impact=action_data.get("impact", "medium"),
                        estimated_carbon_saving=action_data.get("carbon_saving", ""),
                        examples=action_data.get("examples", []),
                        rejected_reasons=self._generate_rejection_reasons(action_data),
                    )

                    suggested_actions.append(rec)

        return suggested_actions[:count]

    def _was_recently_suggested(self, user_id: str, action: str) -> bool:
        """检查是否最近推荐过"""
        if user_id not in self._recommendation_history:
            return False

        history = self._recommendation_history[user_id]
        return action in history[-10:]

    def _check_personalization_fit(self, action_data: Dict, user_profile: Dict) -> bool:
        """检查建议是否适合用户"""
        hints = action_data.get("personalization_hints", [])
        basic = user_profile.get("basic_info", {})

        for hint in hints:
            if hint == "收入水平":
                if not basic.get("income_level"):
                    return False
            elif hint == "住房情况":
                if not basic.get("family_type"):
                    return False
            elif hint == "地区":
                if not basic.get("region"):
                    return False

        return True

    def _generate_personalized_reason(
        self, action_data: Dict, user_profile: Dict[str, Any], strategy: Dict, income_adj: Dict
    ) -> str:
        """生成个性化理由"""
        templates = action_data.get("reason_templates", ["这是一个不错的低碳行动"])

        template = random.choice(templates)

        knowledge_level = user_profile.get("eco_profile", {}).get("knowledge_level", "intermediate")

        if income_adj.get("highlight_benefit"):
            benefit = income_adj["highlight_benefit"]
            if "省钱" in benefit and "benefit" not in template.lower():
                template = template.replace("。", f"，而且能{benefit}。")

        return template

    def _generate_personalization_context(self, action_data: Dict, user_profile: Dict) -> str:
        """生成个性化上下文"""
        parts = []

        basic = user_profile.get("basic_info", {})
        eco = user_profile.get("eco_profile", {})

        age_group = basic.get("age_group")
        if age_group:
            parts.append(f"{age_group}岁人群")

        region = basic.get("region")
        if region:
            parts.append(f"{region}地区")

        family_type = basic.get("family_type")
        if family_type:
            family_info = {"1": "独居", "2": "两人世界", "3-4": "三口/四口之家", "5+": "大家庭"}
            parts.append(f"{family_info.get(family_type, '')}")

        return "，".join(parts) if parts else "根据您的情况"

    def _generate_rejection_reasons(self, action_data: Dict) -> List[str]:
        """生成可能的拒绝理由"""
        reasons = []

        difficulty = action_data.get("difficulty", "easy")
        if difficulty == "easy":
            reasons.append("太简单了，想要更有挑战的")
        elif difficulty == "hard":
            reasons.append("感觉太复杂了")

        impact = action_data.get("impact", "medium")
        if impact == "low":
            reasons.append("感觉效果不明显")

        return reasons

    def record_recommendation_feedback(self, user_id: str, action: str, feedback_type: str):
        """记录推荐反馈"""
        if user_id not in self._recommendation_history:
            self._recommendation_history[user_id] = []

        if feedback_type == "shown":
            self._recommendation_history[user_id].append(action)

        if len(self._recommendation_history[user_id]) > 50:
            self._recommendation_history[user_id] = self._recommendation_history[user_id][-50:]

    def get_category_suggestions(
        self, category: str, user_profile: Dict[str, Any], difficulty: str = "easy"
    ) -> List[Dict]:
        """获取特定类别的建议"""
        if category not in self.ACTION_LIBRARY:
            return []

        actions = self.ACTION_LIBRARY[category].get(difficulty, [])

        filtered = []
        for action_data in actions:
            if self._check_personalization_fit(action_data, user_profile):
                filtered.append(action_data)

        return filtered

    def augment_with_rag(
        self,
        static_recommendations: List[Recommendation],
        user_profile: Dict[str, Any],
        rag_results: List[Dict[str, Any]] = None,
        max_rag_suggestions: int = 1,
    ) -> List[Recommendation]:
        """P4-F.3: 用 RAG 检索结果补充推荐

        当 rag_results 非空时,挑出与用户兴趣最相关的 1-2 条,
        转换为 Recommendation(source='rag'),附加到列表头部。

        兜底:rag_results 为空或异常时,直接返回 static 列表。
        """
        if not rag_results:
            return static_recommendations

        try:
            eco = user_profile.get("eco_profile", {}) or {}
            interests = list(eco.get("primary_interests") or [])
            basic = user_profile.get("basic_info", {}) or {}
            region = basic.get("region") or "全国"

            # 简单相关度:包含兴趣或地区关键词的优先
            def _relevance(item: Dict[str, Any]) -> int:
                text = (item.get("content", "") or "").lower()
                score = 0
                for it in interests:
                    if it and it.lower() in text:
                        score += 2
                if region and region != "全国" and region.lower() in text:
                    score += 1
                return score

            ranked = sorted(rag_results, key=_relevance, reverse=True)
            added = 0
            rag_recs: List[Recommendation] = []
            for item in ranked[:max_rag_suggestions]:
                content = (item.get("content") or "").strip()
                if not content:
                    continue
                source = item.get("source") or "知识库"
                # 用内容前 60 字做 action 文本,后跟参考来源
                snippet = content[:60].replace("\n", " ").strip()
                rec = Recommendation(
                    action=f"参考{region}本地政策:{snippet}…",
                    category="policy",
                    reason=f"基于知识库{source}的本地化建议",
                    personalization_context={"source": "rag", "doc_source": source},
                    difficulty="easy",
                    impact="medium",
                    estimated_carbon_saving="",
                    examples=[],
                    rejected_reasons=[],
                )
                rag_recs.append(rec)
                added += 1

            if rag_recs:
                return rag_recs + list(static_recommendations)
        except Exception:
            pass
        return list(static_recommendations)

    def calculate_carbon_impact(self, recommendations: List[Recommendation]) -> Dict[str, Any]:
        """计算建议的碳排放影响"""
        total_impact = 0
        impact_details = []

        for rec in recommendations:
            impact_map = {"very_low": 0.5, "low": 1, "medium": 3, "high": 5, "very_high": 10}
            impact = impact_map.get(rec.impact, 1)
            total_impact += impact
            impact_details.append(
                {"action": rec.action, "impact": rec.impact, "estimated_value": impact}
            )

        return {
            "total_impact_score": total_impact,
            "details": impact_details,
            "impact_level": ("高" if total_impact > 8 else "中" if total_impact > 4 else "低"),
        }
