"""
任务分解器
将用户复杂目标拆解为可执行的原子任务序列
"""

from typing import List, Dict, Any, Optional
import re

from .task import Task, TaskType, TaskStatus


class TaskDecomposer:
    """
    任务分解器

    根据意图类型和消息内容，将复杂目标分解为有序的任务列表
    """

    # 复合意图标记词
    MULTI_INTENT_MARKERS = [
        "而且", "还有", "并且", "另外", "顺便", "同时",
        "还有就是", "另外还有", "除此之外"
    ]

    # 疑问标记（多问题检测）
    QUESTION_MARKERS = ["？", "怎么", "如何", "为什么", "是什么", "哪里", "多少"]

    # 行动相关词
    ACTION_MARKERS = [
        "想", "要", "打算", "计划", "准备", "开始", "尝试",
        "做了", "做了", "完成了", "实现了"
    ]

    # 反馈相关词
    FEEDBACK_MARKERS = ["不错", "很好", "谢谢", "满意", "不想要", "不要", "拒绝"]

    def __init__(self):
        self._intent_task_map = {
            "knowledge_query": [TaskType.INTENT_RECOGNITION, TaskType.KNOWLEDGE_RETRIEVAL, TaskType.RESPONSE_GENERATE],
            "advice_request": [TaskType.INTENT_RECOGNITION, TaskType.KNOWLEDGE_QUERY, TaskType.ACTION_RECOMMEND, TaskType.RESPONSE_GENERATE],
            "action_report": [TaskType.INTENT_RECOGNITION, TaskType.PROFILE_UPDATE, TaskType.RESPONSE_GENERATE],
            "feedback": [TaskType.INTENT_RECOGNITION, TaskType.PROFILE_UPDATE, TaskType.RESPONSE_GENERATE],
            "greeting": [TaskType.INTENT_RECOGNITION, TaskType.RESPONSE_GENERATE],
            "other": [TaskType.INTENT_RECOGNITION, TaskType.RESPONSE_GENERATE],
        }

    def decompose(self, message: str, intent_type: str, context: Dict[str, Any] = None) -> List[Task]:
        """
        分解任务

        Args:
            message: 用户消息
            intent_type: 意图类型
            context: 上下文信息（可选）

        Returns:
            任务列表
        """
        context = context or {}

        # 评估复杂度
        complexity = self._assess_complexity(message, intent_type)

        if complexity == "simple":
            return self._decompose_simple(intent_type, context)
        elif complexity == "compound":
            return self._decompose_compound(message, intent_type, context)
        else:  # complex
            return self._decompose_complex(message, intent_type, context)

    def _assess_complexity(self, message: str, intent_type: str) -> str:
        """
        评估任务复杂度

        Returns:
            - "simple": 简单任务
            - "compound": 复合任务
            - "complex": 复杂多步骤任务
        """
        # 检测多意图标记
        has_multi = any(marker in message for marker in self.MULTI_INTENT_MARKERS)

        # 检测多问题
        question_count = sum(1 for q in self.QUESTION_MARKERS if q in message)
        has_multiple_questions = question_count > 1

        # 检测复杂意图
        complex_intents = ["advice_request", "knowledge_query"]
        is_complex_intent = intent_type in complex_intents and len(message) > 50

        if has_multi or has_multiple_questions or is_complex_intent:
            return "complex"
        elif intent_type in ["knowledge_query", "advice_request"]:
            return "compound"
        return "simple"

    def _decompose_simple(self, intent_type: str, context: Dict[str, Any]) -> List[Task]:
        """简单任务：直接映射到标准任务序列"""
        task_types = self._intent_task_map.get(intent_type, [TaskType.INTENT_RECOGNITION, TaskType.RESPONSE_GENERATE])

        tasks = []
        prev_task_id = None

        for i, task_type in enumerate(task_types):
            task = Task(
                task_type=task_type,
                description=self._get_task_description(task_type),
                parameters=context.copy(),
                priority=len(task_types) - i  # 前面的任务优先级更高
            )

            # 设置依赖
            if prev_task_id:
                task.dependencies.append(prev_task_id)

            tasks.append(task)
            prev_task_id = task.task_id

        return tasks

    def _decompose_compound(self, message: str, intent_type: str, context: Dict[str, Any]) -> List[Task]:
        """
        复合任务：包含多个子任务

        例如："什么是碳中和？如何实现？" -> 拆分为知识查询 + 行动推荐
        """
        tasks = []

        # 意图识别（始终第一个）
        intent_task = Task(
            task_type=TaskType.INTENT_RECOGNITION,
            description="识别用户意图",
            parameters={"message": message}
        )
        tasks.append(intent_task)

        # 分析是否有额外需求
        needs_retrieval = any(kw in message for kw in ["什么", "如何", "怎么", "为什么"])
        needs_recommendation = any(kw in message for kw in ["建议", "推荐", "方法", "做法", "行动"])

        if needs_retrieval:
            retrieval_task = Task(
                task_type=TaskType.KNOWLEDGE_RETRIEVAL,
                description="检索相关知识",
                parameters={"message": message},
                dependencies=[intent_task.task_id]
            )
            tasks.append(retrieval_task)

        if needs_recommendation:
            rec_task = Task(
                task_type=TaskType.ACTION_RECOMMEND,
                description="生成推荐建议",
                parameters={"message": message, "context": context},
                dependencies=[intent_task.task_id]
            )
            tasks.append(rec_task)

        # 响应生成（最后）
        response_task = Task(
            task_type=TaskType.RESPONSE_GENERATE,
            description="生成最终响应",
            parameters={"message": message},
            priority=0
        )
        # 设置依赖
        deps = [t.task_id for t in tasks]
        response_task.dependencies = deps

        tasks.append(response_task)

        return tasks

    def _decompose_complex(self, message: str, intent_type: str, context: Dict[str, Any]) -> List[Task]:
        """
        复杂任务：包含条件分支和错误处理

        例如："我想开始低碳生活，但不知道从哪开始" -> 需要先了解情况再推荐
        """
        tasks = []

        # 意图识别
        intent_task = Task(
            task_type=TaskType.INTENT_RECOGNITION,
            description="识别用户意图和需求",
            parameters={"message": message}
        )
        tasks.append(intent_task)

        # 知识查询（了解用户情况）
        if intent_type in ["advice_request", "knowledge_query"]:
            knowledge_task = Task(
                task_type=TaskType.KNOWLEDGE_QUERY,
                description="获取相关知识信息",
                parameters={"message": message},
                dependencies=[intent_task.task_id]
            )
            tasks.append(knowledge_task)

        # 画像更新（如果是新用户或需要了解更多）
        profile_task = Task(
            task_type=TaskType.PROFILE_UPDATE,
            description="更新用户画像",
            parameters={"message": message},
            dependencies=[intent_task.task_id]
        )
        tasks.append(profile_task)

        # 行动推荐
        rec_task = Task(
            task_type=TaskType.ACTION_RECOMMEND,
            description="生成个性化推荐",
            parameters={"message": message},
            dependencies=[profile_task.task_id]
        )
        tasks.append(rec_task)

        # 反思节点（评估推荐是否合适）
        reflection_task = Task(
            task_type=TaskType.REFLECTION,
            description="反思推荐结果",
            parameters={"recommendations": rec_task.result},
            dependencies=[rec_task.task_id]
        )
        tasks.append(reflection_task)

        # 响应生成
        response_task = Task(
            task_type=TaskType.RESPONSE_GENERATE,
            description="生成最终响应",
            parameters={"message": message},
            dependencies=[reflection_task.task_id]
        )
        tasks.append(response_task)

        return tasks

    def _get_task_description(self, task_type: TaskType) -> str:
        """获取任务类型描述"""
        descriptions = {
            TaskType.INTENT_RECOGNITION: "识别用户意图",
            TaskType.KNOWLEDGE_QUERY: "查询相关知识",
            TaskType.KNOWLEDGE_RETRIEVAL: "检索知识库",
            TaskType.ACTION_RECOMMEND: "生成行动建议",
            TaskType.PROFILE_UPDATE: "更新用户画像",
            TaskType.RESPONSE_GENERATE: "生成响应",
            TaskType.REFLECTION: "反思执行结果",
            TaskType.WEB_SEARCH: "执行网络搜索",
            TaskType.WEATHER_CHECK: "查询天气信息",
            TaskType.ERROR_HANDLING: "处理错误",
        }
        return descriptions.get(task_type, "执行任务")

    def decompose_multi_goal(self, message: str) -> List[List[Task]]:
        """
        分解多目标消息

        例如："我想了解碳中和，也想问问低碳出行" -> 拆分为两个子目标
        """
        # 按标点分割多目标
        segments = re.split(r'[。；!?\n]', message)
        segments = [s.strip() for s in segments if s.strip()]

        result = []
        for segment in segments:
            if len(segment) < 5:
                continue
            # 每个子目标单独分解
            task_list = self.decompose(segment, "other", {})
            if task_list:
                result.append(task_list)

        return result