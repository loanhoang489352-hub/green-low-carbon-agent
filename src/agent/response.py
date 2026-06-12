"""
响应生成模块
根据用户意图、记忆和知识库生成个性化响应
支持LLM增强生成
"""

# Windows UTF-8 encoding setup - Only if not already wrapped (avoid duplicate wrapping)
import sys
if sys.platform == 'win32':
    import io
    if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import os
import random
from pathlib import Path

# 添加项目路径
script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
if str(project_root / 'src') not in sys.path:
    sys.path.insert(0, str(project_root / 'src'))


@dataclass
class ResponseContext:
    """响应上下文"""
    user_profile: Dict[str, Any]
    conversation_history: List[Dict]
    retrieved_knowledge: List[Dict]
    recent_memories: List[str]
    intent_type: str


class ResponseGenerator:
    """响应生成器"""

    # 预设的开场白
    GREETINGS = [
        "你好！我是绿色低碳助手，很高兴为你服务！",
        "嗨！有什么关于绿色低碳的问题想聊吗？",
        "欢迎来到绿色低碳助手！我们可以一起探讨低碳生活~"
    ]

    # 通用低碳知识库（知识为空时的后备内容）
    FALLBACK_KNOWLEDGE = {
        "碳": [
            "碳是指碳元素及其化合物。在低碳环保领域，'碳'通常指二氧化碳(CO2)等温室气体。",
            "碳足迹是指个人或组织在日常活动中直接或间接产生的二氧化碳总量。比如开车、用电都会产生碳足迹。",
            "碳中和是指通过节能减排和植树造林等方式，抵消自己产生的碳排放，达到'净零排放'。"
        ],
        "节能": [
            "节能减排是指通过提高能源利用效率来减少能源消耗和污染物排放。日常生活中的节能包括随手关灯、合理设置空调温度等。",
            "家庭节能可以从以下几个方面入手：1)选购节能电器；2)养成良好用电习惯；3)减少待机功耗；4)利用自然光和自然通风。"
        ],
        "出行": [
            "低碳出行是指采用对环境影响较小的交通方式，如步行、骑行、公交、地铁等。相比私家车，这些方式可以显著减少碳排放。",
            "电动车的碳排放通常只有燃油车的约三分之一。即使考虑发电侧的排放，电动车的全生命周期碳足迹也明显更低。"
        ],
        "分类": [
            "垃圾分类是指按照废弃物的一定标准将其分类投放、分类收集、分类运输、分类处理的行为。正确的分类是回收利用的前提。",
            "中国大部分城市实行'可回收物/厨余垃圾/有害垃圾/其他垃圾'四分类标准。各地具体规则可能略有不同。"
        ],
        "回收": [
            "废品回收可以减少资源开采和能源消耗。常见的可回收物包括废纸、塑料瓶、金属罐、旧衣物和电子垃圾等。",
            "二手交易是延长物品使用寿命、减少资源消耗的好方法。书籍、家具、电子产品等都适合二手交易。"
        ]
    }

    def _get_fallback_knowledge(self, message: str) -> str:
        """根据问题关键词返回后备知识"""
        message_lower = message.lower()
        for keyword, knowledge_list in self.FALLBACK_KNOWLEDGE.items():
            if keyword in message_lower:
                return random.choice(knowledge_list)
        # 默认回复
        return random.choice([
            "低碳生活是指在日常生活中通过选择环保产品、减少能源消耗、采用绿色出行方式等，降低个人对环境的影响。",
            "环境保护需要每个人的参与。从减少一次性用品、节约水电、选择公共交通等小事做起，就能为地球减碳。",
            "碳减排的核心是'开源节流'——一方面减少能源消耗，另一方面增加碳吸收（如植树造林）。"
        ])
    RESPONSE_TEMPLATES = {
        "knowledge": {
            "start": "关于这个问题，让我来为你解答：",
            "end": "希望这个回答对你有帮助！有什么其他问题吗？"
        },
        "advice": {
            "start": "好的，根据你的情况，我来给你一些建议：",
            "end": "从哪个开始行动比较合适呢？"
        },
        "encouragement": {
            "start": "太棒了！",
            "end": "继续保持！每一步都是在为地球做贡献~"
        },
        "acknowledgment": {
            "positive": "很高兴能帮到你！",
            "negative": "理解你的顾虑，我们可以换个方案。"
        },
        "greeting": {
            "start": "你好！我是绿色低碳助手，很高兴认识你！",
            "end": "今天想聊点什么？"
        },
        "clarification": {
            "start": "抱歉，我不太确定你具体想了解什么。不过：",
            "end": "还有其他想了解的吗？"
        }
    }

    # 行动建议列表
    ACTION_SUGGESTIONS = {
        "出行": [
            "尝试每周一天不开车，选择公共交通或骑行",
            "短距离出行试试步行或骑行，既健康又环保",
            "考虑购买电动车，长期来看更经济环保"
        ],
        "饮食": [
            "可以尝试每周一天素食，减少碳排放",
            "尽量减少外卖，选择自己做饭",
            "购买本地食材，减少运输碳排放"
        ],
        "家居": [
            "把家里灯泡换成LED，省电又耐用",
            "空调温度夏天调高1度，冬天调低1度",
            "外出时拔掉电器插头，减少待机功耗"
        ],
        "消费": [
            "购物时自带环保袋，拒绝一次性塑料",
            "选择有环保认证的产品",
            "考虑二手商品，延长物品使用寿命"
        ]
    }

    # 鼓励语
    ENCOURAGEMENTS = [
        "你的每一次低碳选择都很重要！",
        "小小的行动，大大的改变！",
        "坚持就是胜利，一起加油！",
        "你已经在为地球做贡献了！",
        "低碳生活，从点滴开始~"
    ]

    def __init__(self, use_llm: bool = True):
        self.conversation_count = {}  # 用户对话计数
        self._use_llm = use_llm
        self._llm_client = None

    def _get_llm_client(self):
        """获取LLM客户端（延迟初始化）"""
        if self._llm_client is None and self._use_llm:
            try:
                from llm import get_llm_client, build_chat_prompt
                self._llm_client = get_llm_client()
                self._build_prompt = build_chat_prompt
            except ImportError as e:
                print(f"LLM模块未安装，将使用模板生成: {e}")
                self._use_llm = False
            except Exception as e:
                print(f"LLM模块初始化失败: {e}")
                self._use_llm = False
        return self._llm_client

    def generate_with_llm(
        self,
        user_input: str,
        context: 'ResponseContext',
        rag_context: str = "",
        working_memory: str = "",
    ) -> str:
        """使用LLM生成响应（增强版,P4-H: 支持 working_memory 注入）

        P6.S.5: LLM_MOCK=true 时强制走 MockLLMClient(意图感知 mock),
        不调真实 API(避免 401 错误)
        """
        # P6.S.5: LLM_MOCK 强制路径(优先于工厂)
        if os.getenv("LLM_MOCK", "auto").strip().lower() in ("true", "1", "yes", "on"):
            from llm.client import MockLLMClient
            llm = MockLLMClient()
        else:
            llm = self._get_llm_client()

        if not llm:
                return self.generate_response(user_input, context)["message"]

        try:
            # P4-H: working_memory 注入
            kwargs = {
                "user_message": user_input,
                "user_profile": context.user_profile,
                "rag_context": rag_context,
                "conversation_history": context.conversation_history,
            }
            if working_memory:
                kwargs["working_memory"] = working_memory
            messages = self._build_prompt(**kwargs)
            response = llm.chat(messages)
            if hasattr(response, 'content'):
                return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            return self.generate_response(user_input, context)["message"]

    def generate_response(
        self,
        user_input: str,
        context: ResponseContext
    ) -> Dict[str, Any]:
        """生成完整响应"""

        response_parts = []
        suggestions = []
        knowledge_refs = []

        # 1. 根据意图类型生成主体响应
        response_type = self._determine_response_type(context)

        if response_type == "greeting":
            response_parts.append(self._generate_greeting(context))

        elif response_type == "knowledge":
            response_parts.append(self._generate_knowledge_response(context))

        elif response_type == "advice":
            response_parts.append(self._generate_advice_response(context))

        elif response_type == "encouragement":
            response_parts.append(self._generate_encouragement(context))

        elif response_type == "feedback":
            response_parts.append(self._generate_feedback_response(context))

        else:
            response_parts.append(self._generate_general_response(context))

        # 2. 添加个性化元素
        response_parts.append(self._add_personalized_element(context))

        # 3. 生成建议
        suggestions = self._generate_suggestions(context)

        # 4. 添加知识引用
        if context.retrieved_knowledge:
            knowledge_refs = [k.get("title", "") for k in context.retrieved_knowledge[:2]]

        return {
            "message": "\n\n".join(response_parts),
            "suggestions": suggestions,
            "knowledge_refs": knowledge_refs,
            "response_type": response_type
        }

    def _determine_response_type(self, context: ResponseContext) -> str:
        """根据上下文确定响应类型(委托给 response_mapper)"""
        from agent.response_mapper import map_intent_to_response_type
        return map_intent_to_response_type(getattr(context, "intent_type", None))

    def _generate_greeting(self, context: ResponseContext) -> str:
        """生成问候响应"""
        greeting = random.choice(self.GREETINGS)

        # 检查是否有记忆
        if context.recent_memories:
            return f"{greeting}\n\n我记得你之前关注过{context.recent_memories[0]}，有什么新进展吗？"

        return greeting

    def _generate_knowledge_response(self, context: ResponseContext) -> str:
        """生成知识类响应"""
        parts = []

        # 优先使用检索到的知识
        if context.retrieved_knowledge:
            for knowledge in context.retrieved_knowledge[:1]:
                title = knowledge.get("title", "")
                content = knowledge.get("content", "")[:500]
                parts.append(f"{title}\n\n{content}")
        else:
            # 没有检索到知识时，尝试根据消息内容提供后备知识
            # 提取消息中的关键词来提供相关内容
            fallback = self._get_fallback_for_intent(context)
            parts.append(fallback)

        # 添加互动引导
        parts.append("\n\n有其他想了解的吗？")

        return "\n".join(parts)

    def _get_fallback_for_intent(self, context: ResponseContext) -> str:
        """根据意图类型和用户画像返回后备知识"""
        # 根据意图类型选择对应的后备知识
        if context.intent_type in ["knowledge", "clarification"]:
            # 检查最近的对话内容
            if context.recent_memories:
                topic = context.recent_memories[0]
                if "碳" in topic:
                    return random.choice(self.FALLBACK_KNOWLEDGE["碳"])
                elif "节能" in topic:
                    return random.choice(self.FALLBACK_KNOWLEDGE["节能"])
                elif "出行" in topic or "交通" in topic:
                    return random.choice(self.FALLBACK_KNOWLEDGE["出行"])
                elif "分类" in topic or "垃圾" in topic:
                    return random.choice(self.FALLBACK_KNOWLEDGE["分类"])
                elif "回收" in topic:
                    return random.choice(self.FALLBACK_KNOWLEDGE["回收"])

            # 基于用户知识水平调整回答深度
            knowledge_level = context.user_profile.get("eco_knowledge_level", "入门")
            if knowledge_level == "入门":
                return ("低碳生活其实很简单！简单来说，就是从日常小事做起：\n"
                        "• 少开空调多通风\n"
                        "• 短距离出行选择步行或骑行\n"
                        "• 做好垃圾分类\n"
                        "• 随手关灯、拔掉电器插头\n"
                        "你有什么具体想了解的吗？")
            else:
                return random.choice([
                    "关于绿色低碳，我可以从碳排放计算、节能减排技巧、低碳出行等多个角度为你解答。你更关注哪个方面？",
                    "这个话题涉及多个维度。你想了解具体的减排方法、环境影响分析，还是实用的日常技巧？"
                ])
        elif context.intent_type == "advice":
            return self._generate_advice_response(context)
        else:
            return random.choice([
                "关于这个问题，让我分享一些实用的低碳知识...",
                "这是个很好的问题！让我从几个方面来解答..."
            ])

    def _generate_advice_response(self, context: ResponseContext) -> str:
        """生成建议类响应"""
        parts = []

        # 个性化开场
        knowledge_level = context.user_profile.get("eco_knowledge_level", "入门")

        if knowledge_level == "入门":
            parts.append("好的！让我用简单的方式给你一些建议~")
        else:
            parts.append("让我结合你的情况给出一些建议：")

        # 添加具体建议
        category = self._infer_suggestion_category(context)
        if category in self.ACTION_SUGGESTIONS:
            suggestions = random.sample(self.ACTION_SUGGESTIONS[category], min(2, len(self.ACTION_SUGGESTIONS[category])))
            for i, suggestion in enumerate(suggestions, 1):
                parts.append(f"\n{i}. {suggestion}")

        # 引导行动
        parts.append("\n\n你愿意从哪个开始尝试呢？")

        return "\n".join(parts)

    def _generate_encouragement(self, context: ResponseContext) -> str:
        """生成鼓励响应"""
        parts = [random.choice(self.ENCOURAGEMENTS)]

        # 计算减排效果（如果有相关信息）
        if context.recent_memories:
            parts.append(f"\n继续保持！你在{context.recent_memories[0]}方面做得很好。")

        # 添加下一个建议
        parts.append("\n要不要挑战一下更进一步的低碳行动？")

        return "\n".join(parts)

    def _generate_feedback_response(self, context: ResponseContext) -> str:
        """生成反馈响应"""
        return "感谢你的反馈！"

    def _generate_general_response(self, context: ResponseContext) -> str:
        """生成通用响应"""
        parts = []

        # 优先使用检索到的知识
        if context.retrieved_knowledge:
            parts.append("根据我的知识库，这是相关信息：")
            for knowledge in context.retrieved_knowledge[:1]:
                content = knowledge.get("content", "")
                title = knowledge.get("title", "")
                if title:
                    parts.append(f"【{title}】\n{content[:500]}")
                else:
                    parts.append(content[:500])
        else:
            # 没有检索到知识时的响应 - 提供真实回答而不是说"正在查找"
            fallback = self._get_fallback_for_intent(context)
            parts.append(fallback)
            parts.append("\n\n如果你有其他关于绿色低碳的问题，随时问我！")

        # 添加个性化元素
        parts.append(self._add_personalized_element(context))

        return "\n".join(parts)

    def _add_personalized_element(self, context: ResponseContext) -> str:
        """添加个性化元素"""
        elements = []

        # 基于用户画像添加个性化内容
        if context.recent_memories:
            elements.append(f"\n提示：之前你提到过关注{context.recent_memories[0]}，这个信息可能有帮助。")

        # 基于环保认知水平调整
        knowledge_level = context.user_profile.get("eco_knowledge_level", "入门")
        if knowledge_level == "入门":
            elements.append("\n如果你想了解更多基础知识，可以随时问我！")

        return "\n".join(elements) if elements else ""

    def _generate_suggestions(self, context: ResponseContext) -> List[str]:
        """生成建议列表"""
        suggestions = []

        # 根据上下文推断可能的建议
        for category, category_suggestions in self.ACTION_SUGGESTIONS.items():
            if any(cat in str(context.recent_memories) for cat in [category]):
                suggestions.extend(random.sample(category_suggestions, 1))

        # 如果没有匹配的，随机添加
        if not suggestions:
            for category in random.sample(list(self.ACTION_SUGGESTIONS.keys()), 2):
                suggestions.append(random.choice(self.ACTION_SUGGESTIONS[category]))

        return suggestions[:3]  # 最多返回3个

    def _infer_suggestion_category(self, context: ResponseContext) -> str:
        """推断建议类别"""
        # 基于最近的对话历史推断
        if context.conversation_history:
            last_msg = context.conversation_history[-1]
            # 兼容 dict 和 langchain HumanMessage/AIMessage 对象
            last_message = last_msg.get("content", "") if isinstance(last_msg, dict) else getattr(last_msg, "content", "")

            if any(kw in last_message for kw in ["开车", "出行", "交通", "车"]):
                return "出行"
            elif any(kw in last_message for kw in ["吃", "食物", "外卖", "肉", "素"]):
                return "饮食"
            elif any(kw in last_message for kw in ["空调", "灯", "电", "家", "住"]):
                return "家居"
            elif any(kw in last_message for kw in ["买", "购物", "消费"]):
                return "消费"

        return random.choice(list(self.ACTION_SUGGESTIONS.keys()))
