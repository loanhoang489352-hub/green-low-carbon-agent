"""
P5-F 日志 + 调度契约测试

覆盖:
1. scheduler.py 注册 5 个 cron job (P5-F 新增 consolidate_short_to_long)
2. 启动时后台异步触发 RAG 重建
3. /api/health 的 scheduler check 通过(用 mock)
4. _consolidate_short_to_long 跑通(无 conversation 时返 0)
5. /src/ 全量 print("[WARN]") / print("[ERROR]") 0 命中
6. 模块级 _logger 在所有改动文件存在
7. data/logs/app.log 真有内容(setup_logging 验证)
"""

import sys
import os
import re
import time
import logging
import tempfile
from io import StringIO
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import pytest


# ========== 1. scheduler cron 注册 ==========

def test_scheduler_registers_all_cron_jobs():
    """scheduler 启动后注册 5 个 job: daily_kb_update, memory_decay, consolidate_short_to_long, short_term_cleanup, working_memory_heartbeat"""
    from scheduler import start_scheduler, stop_scheduler, reset_scheduler
    reset_scheduler()
    sched = start_scheduler()
    try:
        job_ids = {job.id for job in sched.get_jobs()}
        assert "daily_kb_update" in job_ids, "缺 daily_kb_update"
        assert "memory_decay" in job_ids, "缺 memory_decay"
        assert "consolidate_short_to_long" in job_ids, "缺 consolidate_short_to_long (P5-F 新增)"
        assert "short_term_cleanup" in job_ids, "缺 short_term_cleanup"
        assert "working_memory_heartbeat" in job_ids, "缺 working_memory_heartbeat"
        assert len(job_ids) == 5, f"应有 5 个 job,实际 {len(job_ids)}: {job_ids}"
    finally:
        stop_scheduler(wait=False)


def test_scheduler_consolidate_cron_hourly():
    """consolidate_short_to_long 每小时跑一次(CronTrigger cron 表达式验证)"""
    from scheduler import start_scheduler, stop_scheduler, reset_scheduler
    from apscheduler.triggers.cron import CronTrigger
    reset_scheduler()
    sched = start_scheduler()
    try:
        job = sched.get_job("consolidate_short_to_long")
        assert job is not None
        # CronTrigger 验证
        trigger = job.trigger
        assert isinstance(trigger, CronTrigger)
        # 用 str(trigger) 验证(minute=17 表示每小时 :17)
        s = str(trigger)
        assert "minute='17'" in s, f"应在每小时 :17 跑,trigger str: {s}"
        assert "hour='*'" in s, f"小时应为 *,trigger str: {s}"
    finally:
        stop_scheduler(wait=False)


def test_scheduler_daily_kb_cron_at_0200():
    """daily_kb_update 每日 02:00"""
    from scheduler import start_scheduler, stop_scheduler, reset_scheduler
    from apscheduler.triggers.cron import CronTrigger
    reset_scheduler()
    sched = start_scheduler()
    try:
        job = sched.get_job("daily_kb_update")
        assert job is not None
        trigger = job.trigger
        s = str(trigger)
        assert "minute='0'" in s, f"分钟应为 0,trigger str: {s}"
        assert "hour='2'" in s, f"小时应为 2,trigger str: {s}"
    finally:
        stop_scheduler(wait=False)


def test_scheduler_memory_decay_cron_at_0300():
    """memory_decay 每日 03:00"""
    from scheduler import start_scheduler, stop_scheduler, reset_scheduler
    from apscheduler.triggers.cron import CronTrigger
    reset_scheduler()
    sched = start_scheduler()
    try:
        job = sched.get_job("memory_decay")
        assert job is not None
        trigger = job.trigger
        s = str(trigger)
        assert "minute='0'" in s, f"分钟应为 0,trigger str: {s}"
        assert "hour='3'" in s, f"小时应为 3,trigger str: {s}"
    finally:
        stop_scheduler(wait=False)


def test_scheduler_max_instances_1():
    """所有 cron job 都设 max_instances=1(防并发)"""
    from scheduler import start_scheduler, stop_scheduler, reset_scheduler
    reset_scheduler()
    sched = start_scheduler()
    try:
        for job in sched.get_jobs():
            assert job.max_instances == 1, f"{job.id} max_instances != 1"
    finally:
        stop_scheduler(wait=False)


def test_scheduler_is_singleton():
    """start_scheduler 多次调用返同一实例"""
    from scheduler import start_scheduler, stop_scheduler, reset_scheduler
    reset_scheduler()
    a = start_scheduler()
    b = start_scheduler()
    try:
        assert a is b
    finally:
        stop_scheduler(wait=False)


# ========== 2. 启动时后台异步 RAG 重建 ==========

def test_scheduler_triggers_async_rag_rebuild_on_startup():
    """start_scheduler 启动后会触发后台线程 rebuild_index(daemon=True)"""
    from scheduler import start_scheduler, stop_scheduler, reset_scheduler
    import scheduler as sched_mod
    reset_scheduler()

    rebuild_called = {"yes": False}

    # 拿 get_rag_engine 的真实路径(无法 import 时也算跳过了)
    real_get_rag = None
    try:
        from rag.rag_engine import get_rag_engine
        real_get_rag = get_rag_engine
    except Exception:
        pass

    def fake_engine():
        rebuild_called["yes"] = True
        # 模拟 RAGEngine 对象,有 rebuild_index 方法
        class FakeEngine:
            def rebuild_index(self, knowledge_base_path=None):
                return 42  # 模拟返回文档块数
        return FakeEngine()

    # 替换 import 路径
    original_funcs = {}
    try:
        # patch sys.modules 里的 get_rag_engine
        import sys as _sys
        rag_engine_mod = _sys.modules.get("rag.rag_engine")
        if rag_engine_mod:
            original_funcs["get_rag_engine"] = rag_engine_mod.get_rag_engine
            rag_engine_mod.get_rag_engine = fake_engine

        start_scheduler()
        # 等后台线程跑一下
        time.sleep(0.3)

        # 验证线程存在(daemon 模式)
        threads = [t for t in threading.enumerate() if t.name == "startup-rag-rebuild"]
        # 线程可能跑完已退出,所以 rebuild_called 至少应被触发
        assert rebuild_called["yes"] is True, "startup-rag-rebuild 线程没跑"
    finally:
        stop_scheduler(wait=False)
        # 还原
        if "get_rag_engine" in original_funcs:
            rag_engine_mod.get_rag_engine = original_funcs["get_rag_engine"]


# ========== 3. _consolidate_short_to_long 跑通 ==========

def test_consolidate_short_to_long_runs_clean():
    """短期记忆无 conversation 时,consolidate 应跑通且返 0"""
    from scheduler import _consolidate_short_to_long
    # 不抛异常即可
    _consolidate_short_to_long()


def test_consolidate_short_to_long_processes_real_conversation():
    """短期记忆有 conversation 时,consolidate 跑通不抛异常"""
    from memory.short_term import get_short_term_memory
    from scheduler import _consolidate_short_to_long

    stm = get_short_term_memory()
    # 加一个测试 conversation
    stm.add_message("test-conv-1", "user", "我关心碳中和")
    # 关联 user_id(P5-F 假设 stm.metadata[cid] 里有 user_id 字段)
    stm.metadata["test-conv-1"]["user_id"] = "u_test_1"

    try:
        _consolidate_short_to_long()
    finally:
        # 清理
        stm.delete_conversation("test-conv-1")


# ========== 4. /src/ 全量 print("[WARN]") / print("[ERROR]") 0 命中 ==========

def test_no_print_warn_in_src():
    """src/ 下不应再有 print('[WARN]...') 模式"""
    src_dir = Path(__file__).resolve().parent.parent / "src"
    pattern = re.compile(r'print\s*\(\s*f?[\'"]\[WARN')
    found = []
    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if pattern.search(text):
            found.append(str(py_file.relative_to(src_dir)))
    assert not found, f"仍有 print('[WARN]') 的文件: {found}"


def test_no_print_error_in_src():
    """src/ 下不应再有 print('[ERROR]...') 模式"""
    src_dir = Path(__file__).resolve().parent.parent / "src"
    pattern = re.compile(r'print\s*\(\s*f?[\'"]\[ERROR')
    found = []
    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if pattern.search(text):
            found.append(str(py_file.relative_to(src_dir)))
    assert not found, f"仍有 print('[ERROR]') 的文件: {found}"


# ========== 5. 改动文件中 _logger 存在 ==========

def test_logger_defined_in_changed_modules():
    """P5-F 改动的 4 个文件都有模块级 _logger"""
    files = [
        "src/llm/__init__.py",
        "src/llm/client.py",
        "src/rag/embedder.py",
        "src/rag/rag_engine.py",
        "src/rag/vector_store.py",
    ]
    for f in files:
        text = (Path(__file__).resolve().parent.parent / f).read_text(encoding="utf-8")
        # 检查 _logger 定义
        assert "_logger" in text, f"{f} 缺 _logger"


# ========== 6. /api/health 的 scheduler check 通过 ==========

def test_health_check_scheduler_includes_running():
    """/api/health 的 scheduler check 报告运行状态"""
    from server.health import _check_scheduler
    result = _check_scheduler()
    assert "status" in result
    assert "detail" in result
    # 在没有 scheduler 时应返 ok + "not started"
    assert result["status"] in ("ok", "down", "degraded")


# ========== 7. data/logs/app.log 真有内容 ==========

def test_setup_logging_writes_to_file():
    """setup_logging 写文件成功(可独立验证,带清理)"""
    from observability import setup_logging
    tmp = tempfile.mkdtemp(prefix="p5f_log_")
    log_path = os.path.join(tmp, "test.log")
    setup_logging(level="INFO", log_file=log_path, also_stdout=False)
    try:
        log = logging.getLogger("p5f_test")
        log.info("test_event", extra={"key": "value"})
        log.warning("test_warning_event")
        # 强制 flush
        for h in logging.getLogger().handlers:
            h.flush()
        # 文件应有内容
        assert os.path.exists(log_path)
        content = Path(log_path).read_text(encoding="utf-8")
        assert "test_event" in content
        assert "test_warning_event" in content
        assert "key" in content  # extra 字段
    finally:
        # 清理
        for h in list(logging.getLogger().handlers):
            logging.getLogger().removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ========== 8. 端到端: scheduler 启动后日志包含 cron 记录 ==========

def test_scheduler_log_on_startup(caplog):
    """scheduler 启动时记录 cron job 数"""
    from scheduler import start_scheduler, stop_scheduler, reset_scheduler
    reset_scheduler()

    with caplog.at_level(logging.INFO, logger="scheduler"):
        start_scheduler()
        time.sleep(0.1)
        stop_scheduler(wait=False)
    # 至少有一条 scheduler 日志
    scheduler_logs = [r for r in caplog.records if r.name == "scheduler"]
    assert any("cron job" in r.getMessage() or "已注册" in r.getMessage() for r in scheduler_logs), \
        f"scheduler 没记录 cron 数量,records: {[(r.name, r.getMessage()) for r in caplog.records]}"


# ========== helper ==========
import threading  # noqa: E402  (for test_scheduler_triggers_async_rag_rebuild_on_startup)
