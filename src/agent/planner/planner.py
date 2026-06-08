"""
Planner主类
负责任务规划、执行调度和结果汇总
"""

from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
import logging

from .task import Task, TaskStatus, TaskType, TaskGraph
from .task_decomposer import TaskDecomposer

logger = logging.getLogger(__name__)


@dataclass
class PlanningResult:
    """规划结果"""
    tasks: List[Task]
    task_graph: TaskGraph
    success: bool
    error: Optional[str] = None
    execution_summary: Dict[str, Any] = field(default_factory=dict)
    failed_tasks: List[Dict[str, Any]] = field(default_factory=list)


class Planner:
    """
    任务规划器

    功能：
    - 接收用户消息和意图
    - 分解任务为可执行单元
    - 管理任务依赖关系
    - 调度任务执行
    - 汇总执行结果
    """

    def __init__(self):
        self.decomposer = TaskDecomposer()
        self._current_graph: Optional[TaskGraph] = None
        self._execution_callbacks: Dict[TaskType, Callable] = {}

    def register_executor(self, task_type: TaskType, executor: Callable):
        """
        注册任务执行器

        Args:
            task_type: 任务类型
            executor: 执行函数，签名为 func(task: Task) -> Any
        """
        self._execution_callbacks[task_type] = executor

    def plan(self, message: str, intent_type: str, context: Dict[str, Any] = None) -> PlanningResult:
        """
        执行规划

        Args:
            message: 用户消息
            intent_type: 意图类型
            context: 上下文信息

        Returns:
            PlanningResult: 规划结果
        """
        try:
            # 分解任务
            tasks = self.decomposer.decompose(message, intent_type, context)

            # 构建任务图
            task_graph = TaskGraph(tasks=tasks)
            for task in tasks:
                task_graph.task_map[task.task_id] = task

            self._current_graph = task_graph

            return PlanningResult(
                tasks=tasks,
                task_graph=task_graph,
                success=True
            )

        except Exception as e:
            return PlanningResult(
                tasks=[],
                task_graph=TaskGraph(),
                success=False,
                error=str(e)
            )

    def execute_next(self) -> Optional[Task]:
        """
        执行下一个可执行的任务

        Returns:
            执行完成的任务，如果没有可执行任务返回None
        """
        if not self._current_graph:
            return None

        completed_ids = [
            t.task_id for t in self._current_graph.tasks
            if t.status == TaskStatus.COMPLETED
        ]

        ready_tasks = self._current_graph.get_ready_tasks(completed_ids)
        if not ready_tasks:
            return None

        task = ready_tasks[0]
        task.mark_running()

        # 执行任务
        executor = self._execution_callbacks.get(task.task_type)
        if executor:
            try:
                result = executor(task)
                task.mark_completed(result)
            except Exception as e:
                task.mark_failed(str(e))
                logger.exception(
                    "[Planner] 任务执行失败: task_id=%s type=%s error=%s",
                    task.task_id, task.task_type, e,
                )
        else:
            # 没有注册执行器 — 显式记录而不是默默跳过
            logger.warning(
                "[Planner] 任务无执行器,标记为 SKIPPED: task_id=%s type=%s",
                task.task_id, task.task_type,
            )
            task.mark_skipped(reason="no_executor_registered")

        return task

    def execute_all(self) -> PlanningResult:
        """
        执行所有任务（同步）

        Returns:
            PlanningResult: 包含执行结果
        """
        if not self._current_graph:
            return PlanningResult(
                tasks=[],
                task_graph=TaskGraph(),
                success=False,
                error="No plan available"
            )

        max_iterations = 100  # 防止无限循环
        iterations = 0

        while iterations < max_iterations:
            iterations += 1

            task = self.execute_next()
            if task is None:
                break

        # 构建执行摘要
        completed = [t for t in self._current_graph.tasks if t.status == TaskStatus.COMPLETED]
        failed = [t for t in self._current_graph.tasks if t.status == TaskStatus.FAILED]
        skipped = [t for t in self._current_graph.tasks if t.status == TaskStatus.SKIPPED]

        execution_summary = {
            "total": len(self._current_graph.tasks),
            "completed": len(completed),
            "failed": len(failed),
            "skipped": len(skipped),
            "task_results": {
                t.task_id: {
                    "type": t.task_type.value,
                    "status": t.status.value,
                    "result": t.result,
                    "error": t.error
                }
                for t in self._current_graph.tasks
            }
        }

        failed_tasks = [
            {
                "task_id": t.task_id,
                "type": t.task_type.value,
                "error": t.error or "unknown",
                "retryable": True,
            }
            for t in failed
        ]
        if failed_tasks:
            logger.warning(
                "[Planner] %d 个任务失败: %s",
                len(failed_tasks),
                [ft["task_id"] for ft in failed_tasks],
            )

        return PlanningResult(
            tasks=self._current_graph.tasks,
            task_graph=self._current_graph,
            success=len(failed) == 0,
            execution_summary=execution_summary,
            failed_tasks=failed_tasks,
        )

    def get_task_result(self, task_id: str) -> Any:
        """获取任务结果"""
        if not self._current_graph:
            return None
        task = self._current_graph.get_task(task_id)
        return task.result if task else None

    def get_response_task_result(self) -> Optional[str]:
        """获取响应生成任务的结果（用于返回给用户）"""
        if not self._current_graph:
            return None

        for task in reversed(self._current_graph.tasks):
            if task.task_type == TaskType.RESPONSE_GENERATE and task.status == TaskStatus.COMPLETED:
                return task.result

        return None

    def reset(self):
        """重置规划器"""
        if self._current_graph:
            self._current_graph.reset()
        self._current_graph = None


class ReActPlanner(Planner):
    """
    ReAct模式规划器

    支持观察-行动-反思闭环的规划器
    """

    def __init__(self):
        super().__init__()
        self._observation_history: List[Dict[str, Any]] = []

    def plan_with_react(
        self,
        message: str,
        intent_type: str,
        context: Dict[str, Any] = None
    ) -> PlanningResult:
        """
        使用ReAct模式规划

        在标准规划流程上增加反思节点
        """
        result = self.plan(message, intent_type, context)

        if not result.success:
            return result

        # 为复杂任务添加反思节点
        if len(result.tasks) > 3:
            reflection_task = Task(
                task_type=TaskType.REFLECTION,
                description="执行整体反思",
                parameters={"tasks": result.tasks}
            )

            # 依赖于所有之前的任务
            reflection_task.dependencies = [t.task_id for t in result.tasks]

            result.tasks.append(reflection_task)
            result.task_graph.add_task(reflection_task)

        return result

    def add_observation(self, action: str, result: Any, success: bool):
        """添加观察结果"""
        self._observation_history.append({
            "action": action,
            "result": result,
            "success": success
        })

    def should_replan(self) -> bool:
        """判断是否需要重新规划"""
        if not self._observation_history:
            return False

        # 如果最近3次行动都失败了，考虑重新规划
        recent = self._observation_history[-3:]
        if len(recent) >= 3 and not any(o["success"] for o in recent):
            return True

        return False

    def clear_history(self):
        """清除观察历史"""
        self._observation_history = []