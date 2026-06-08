"""
任务数据类定义
定义任务的原子单位、结构和管理
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
import uuid


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"       # 等待执行
    RUNNING = "running"       # 执行中
    COMPLETED = "completed"   # 已完成
    FAILED = "failed"         # 执行失败
    SKIPPED = "skipped"       # 已跳过
    WAITING = "waiting"       # 等待依赖完成


class TaskType(Enum):
    """任务类型枚举"""
    # 核心任务类型
    INTENT_RECOGNITION = "intent_recognition"      # 意图识别
    KNOWLEDGE_QUERY = "knowledge_query"            # 知识查询
    ACTION_RECOMMEND = "action_recommend"           # 行动推荐
    PROFILE_UPDATE = "profile_update"              # 画像更新
    RESPONSE_GENERATE = "response_generate"        # 响应生成
    REFLECTION = "reflection"                       # 反思

    # 外部工具调用
    WEB_SEARCH = "web_search"                       # 网络搜索
    WEATHER_CHECK = "weather_check"                 # 天气查询
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval"     # 知识检索

    # 特殊任务
    CONDITIONAL_BRANCH = "conditional_branch"       # 条件分支
    LOOP = "loop"                                   # 循环
    ERROR_HANDLING = "error_handling"               # 错误处理


@dataclass
class Task:
    """
    原子任务单元

    属性：
    - task_id: 唯一标识
    - task_type: 任务类型
    - description: 任务描述
    - parameters: 任务参数
    - dependencies: 依赖的任务ID列表
    - status: 当前状态
    - result: 执行结果
    - error: 错误信息
    - priority: 优先级（数字越大优先级越高）
    """

    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    task_type: TaskType = TaskType.INTENT_RECOGNITION
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    priority: int = 0

    def can_execute(self, completed_tasks: List[str]) -> bool:
        """检查是否满足执行条件（所有依赖都已完成）"""
        if self.status != TaskStatus.PENDING:
            return False
        return all(dep in completed_tasks for dep in self.dependencies)

    def mark_running(self):
        """标记为执行中"""
        self.status = TaskStatus.RUNNING

    def mark_completed(self, result: Any = None):
        """标记为已完成"""
        self.status = TaskStatus.COMPLETED
        self.result = result

    def mark_failed(self, error: str):
        """标记为失败"""
        self.status = TaskStatus.FAILED
        self.error = error

    def mark_skipped(self, reason: str = ""):
        """标记为跳过"""
        self.status = TaskStatus.SKIPPED
        self.error = reason or self.error

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type.value,
            "description": self.description,
            "parameters": self.parameters,
            "dependencies": self.dependencies,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "priority": self.priority
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """从字典创建任务"""
        task_type = TaskType(data.get("task_type", "intent_recognition"))
        status = TaskStatus(data.get("status", "pending"))
        return cls(
            task_id=data.get("task_id", str(uuid.uuid4())[:8]),
            task_type=task_type,
            description=data.get("description", ""),
            parameters=data.get("parameters", {}),
            dependencies=data.get("dependencies", []),
            status=status,
            result=data.get("result"),
            error=data.get("error"),
            priority=data.get("priority", 0)
        )


@dataclass
class TaskGraph:
    """
    任务图管理器

    管理一组任务及其依赖关系
    """

    tasks: List[Task] = field(default_factory=list)
    task_map: Dict[str, Task] = field(default_factory=dict)

    def add_task(self, task: Task) -> str:
        """添加任务"""
        self.tasks.append(task)
        self.task_map[task.task_id] = task
        return task.task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self.task_map.get(task_id)

    def get_ready_tasks(self, completed_task_ids: List[str]) -> List[Task]:
        """获取可以执行的任务（依赖都已满足）"""
        ready = []
        for task in self.tasks:
            if task.can_execute(completed_task_ids):
                ready.append(task)
        # 按优先级排序
        ready.sort(key=lambda t: t.priority, reverse=True)
        return ready

    def mark_completed(self, task_id: str, result: Any = None):
        """标记任务完成"""
        task = self.task_map.get(task_id)
        if task:
            task.mark_completed(result)

    def mark_failed(self, task_id: str, error: str):
        """标记任务失败"""
        task = self.task_map.get(task_id)
        if task:
            task.mark_failed(error)

    def is_all_completed(self) -> bool:
        """检查是否所有任务都完成"""
        return all(t.status == TaskStatus.COMPLETED for t in self.tasks)

    def get_failed_tasks(self) -> List[Task]:
        """获取失败的任务"""
        return [t for t in self.tasks if t.status == TaskStatus.FAILED]

    def reset(self):
        """重置所有任务状态"""
        for task in self.tasks:
            task.status = TaskStatus.PENDING
            task.result = None
            task.error = None