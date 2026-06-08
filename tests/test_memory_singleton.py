"""
验证 P0-2 修复:ShortTermMemory 单例

P0-2 之前:GreenAgent/LangGraphAgent/MemoryConsolidator 各自 new ShortTermMemory(),
导致写入与读取不在同一对象,记忆丢失。
P0-2 之后:get_short_term_memory() 返回同一实例。
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from memory.short_term import (
    ShortTermMemory,
    get_short_term_memory,
    reset_short_term_memory,
)


def test_singleton_basic():
    """基本单例性测试"""
    reset_short_term_memory()
    s1 = get_short_term_memory()
    s2 = get_short_term_memory()
    assert s1 is s2, f"期望同一实例,实际 s1={id(s1)} s2={id(s2)}"
    assert isinstance(s1, ShortTermMemory)
    print("✅ test_singleton_basic PASSED")


def test_singleton_concurrent():
    """并发 100 次访问,断言始终是同一实例"""
    reset_short_term_memory()
    instances = []

    def worker():
        instances.append(get_short_term_memory())

    threads = [threading.Thread(target=worker) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    first = instances[0]
    for inst in instances[1:]:
        assert inst is first, f"并发下应返回同一实例"
    print("✅ test_singleton_concurrent PASSED (100 threads, same instance)")


def test_data_shared_across_callers():
    """写入和读取共享"""
    reset_short_term_memory()
    a = get_short_term_memory()
    b = get_short_term_memory()
    a.add_message("conv-1", "user", "hello")
    history = b.get_conversation_history("conv-1")
    assert len(history) == 1
    assert history[0]["content"] == "hello"
    print("✅ test_data_shared_across_callers PASSED")


def test_reset():
    """reset 后能创建新实例"""
    s1 = get_short_term_memory()
    reset_short_term_memory()
    s2 = get_short_term_memory()
    assert s1 is not s2
    print("✅ test_reset PASSED")


if __name__ == "__main__":
    test_singleton_basic()
    test_singleton_concurrent()
    test_data_shared_across_callers()
    test_reset()
    print("\n🎉 all memory singleton tests passed")
