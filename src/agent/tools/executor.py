"""
工具执行器
负责工具的实际调用、超时控制、错误处理、并行执行
参考 Build-Your-Own-Agent 指南的 ToolDispatcher 设计
"""

import atexit
import time
import asyncio
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from .base import BaseTool, ToolResult, ToolStatus


class ToolExecutor:
    """
    工具执行器

    功能：
    - 执行工具调用
    - 超时控制
    - 错误处理和重试
    - 执行结果格式化
    """

    def __init__(self, max_workers: int = 4, default_timeout: float = 30.0, max_retries: int = 2):
        self.max_workers = max_workers
        self.default_timeout = default_timeout
        self.max_retries = max_retries
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        # 注册进程退出时自动关闭线程池
        atexit.register(self.shutdown)

    def execute(
        self, tool: BaseTool, timeout: float = None, retry: bool = True, **kwargs
    ) -> ToolResult:
        """
        执行工具调用

        Args:
            tool: 工具实例
            timeout: 超时时间（秒）
            retry: 是否启用重试
            **kwargs: 工具参数

        Returns:
            ToolResult: 执行结果
        """
        if timeout is None:
            timeout = self.default_timeout

        tool._status = ToolStatus.RUNNING
        start_time = time.time()

        retries = self.max_retries if retry else 0
        last_error = None

        for attempt in range(retries + 1):
            try:
                result = self._execute_with_timeout(tool, timeout, **kwargs)
                tool._status = ToolStatus.SUCCESS
                result.execution_time = time.time() - start_time
                return result

            except Exception as e:
                last_error = str(e)
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))  # 指数退避

        tool._status = ToolStatus.FAILED
        return ToolResult(
            success=False,
            error=last_error or "执行失败",
            metadata={"attempts": retries + 1},
            execution_time=time.time() - start_time,
        )

    def _execute_with_timeout(self, tool: BaseTool, timeout: float, **kwargs) -> ToolResult:
        """使用超时的执行逻辑"""
        try:
            future = self._executor.submit(tool.execute, **kwargs)
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            tool._status = ToolStatus.TIMEOUT
            raise TimeoutError(f"工具执行超时（{timeout}秒）")

    def execute_sync(self, tool: BaseTool, **kwargs) -> ToolResult:
        """同步执行工具（无超时保护）"""
        tool._status = ToolStatus.RUNNING
        start_time = time.time()

        try:
            result = tool.execute(**kwargs)
            tool._status = ToolStatus.SUCCESS
            result.execution_time = time.time() - start_time
            return result
        except Exception as e:
            tool._status = ToolStatus.FAILED
            return ToolResult(success=False, error=str(e), execution_time=time.time() - start_time)

    def execute_batch(
        self, tool: BaseTool, batch_params: list[Dict[str, Any]], timeout: float = None
    ) -> list[ToolResult]:
        """
        批量执行工具

        Args:
            tool: 工具实例
            batch_params: 参数列表
            timeout: 每个执行的超时时间

        Returns:
            结果列表
        """
        results = []
        for params in batch_params:
            result = self.execute(tool, timeout=timeout, **params)
            results.append(result)
        return results

    def shutdown(self, wait: bool = True):
        """关闭执行器，释放线程资源"""
        if hasattr(self, "_executor") and self._executor is not None:
            self._executor.shutdown(wait=wait)
            self._executor = None


class ToolCallContext:
    """工具调用上下文"""

    def __init__(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ):
        self.tool_name = tool_name
        self.parameters = parameters
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.start_time = time.time()
        self.metadata: Dict[str, Any] = {}

    def add_metadata(self, key: str, value: Any):
        """添加元数据"""
        self.metadata[key] = value

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "elapsed": time.time() - self.start_time,
            "metadata": self.metadata,
        }


class RetryStrategy:
    """重试策略"""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 10.0,
        exponential: bool = True,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential = exponential

    def get_delay(self, attempt: int) -> float:
        """计算重试延迟"""
        if self.exponential:
            delay = self.base_delay * (2**attempt)
        else:
            delay = self.base_delay * (attempt + 1)
        return min(delay, self.max_delay)


# ========== 并行工具执行器（参考 Build-Your-Own-Agent 指南）==========


class ToolDispatcher:
    """
    工具分发器，支持并行执行路径独立的工具调用。

    关键设计：只有路径独立的工具才能并行执行。
    非安全工具（如涉及文件系统修改的操作）必须串行执行。
    """

    def __init__(self, registry=None, security_envelope=None):
        self.registry = registry
        self.security_envelope = security_envelope
        self._executor = ThreadPoolExecutor(max_workers=4)

    async def execute_all(self, tool_calls: List[Dict]) -> List[Dict]:
        """
        并行执行多个工具调用。
        只有路径独立的工具才能并行。

        Args:
            tool_calls: 工具调用列表，每项包含 name, args, id

        Returns:
            结果列表
        """
        if not tool_calls:
            return []

        # 分离可并行和需串行的工具调用
        parallel_tasks = []
        serial_queue = []

        for call in tool_calls:
            tool_def = self.registry.get(call["name"]) if self.registry else None
            is_concurrency_safe = tool_def.get("isConcurrencySafe", True) if tool_def else True

            if is_concurrency_safe:
                parallel_tasks.append(call)
            else:
                serial_queue.append(call)

        results = []

        # 执行并行任务
        if parallel_tasks:
            parallel_results = await self._execute_parallel(parallel_tasks)
            results.extend(parallel_results)

        # 串行执行非安全工具
        for call in serial_queue:
            result = await self._execute_single(call)
            results.append(result)

        return results

    async def _execute_parallel(self, tool_calls: List[Dict]) -> List[Dict]:
        """并行执行工具调用"""
        tasks = [self._execute_single(call) for call in tool_calls]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_single(self, call: Dict) -> Dict:
        """执行单个工具调用"""
        tool_name = call.get("name")
        args = call.get("args", {})
        call_id = call.get("id", call.get("tool_call_id", ""))

        try:
            # 安全检查
            if self.security_envelope:
                check_result = self.security_envelope.check(tool_name, args)
                if not check_result.allowed:
                    return {
                        "tool_call_id": call_id,
                        "success": False,
                        "error": f"安全检查失败: {check_result.reason}",
                    }
                if check_result.requires_approval:
                    return {
                        "tool_call_id": call_id,
                        "success": False,
                        "error": "需要用户审批",
                        "pending_approval": True,
                    }

            # 执行工具
            tool_def = self.registry.get(tool_name) if self.registry else None
            if not tool_def:
                return {
                    "tool_call_id": call_id,
                    "success": False,
                    "error": f"工具 {tool_name} 未找到",
                }

            handler = tool_def.get("handler")
            if not handler:
                return {
                    "tool_call_id": call_id,
                    "success": False,
                    "error": f"工具 {tool_name} 没有处理函数",
                }

            # 调用工具
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**args)
            else:
                result = await asyncio.to_thread(handler, **args)

            # 脱敏输出
            if self.security_envelope and isinstance(result, str):
                result = self.security_envelope.mask_output(result)

            return {"tool_call_id": call_id, "success": True, "output": result}

        except Exception as e:
            return {"tool_call_id": call_id, "success": False, "error": str(e)}

    def execute_sync(self, tool_calls: List[Dict]) -> List[Dict]:
        """同步版本的并行执行"""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.execute_all(tool_calls))
        finally:
            loop.close()

    def shutdown(self):
        """关闭执行器"""
        self._executor.shutdown(wait=True)
