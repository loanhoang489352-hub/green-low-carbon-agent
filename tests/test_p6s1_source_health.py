"""P6.S.1: 源健康 backoff 机制测试

阶梯:
- 1 次失败 → 不 backoff
- 2 次失败 → 1h backoff
- 3 次失败 → 6h backoff
- 4+ 次失败 → 24h backoff
- 1 次成功 → 重置(consecutive_failures=0, next_retry_at=NULL)
"""
import io
import contextlib
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT / "src"))

from policy.updater import PolicyUpdater


@pytest.fixture
def pu():
    """用临时 DB,屏蔽 __init__ 里的 emoji print(Windows GBK 控制台会爆)"""
    tmp_db = tempfile.mktemp(suffix=".db")
    with contextlib.redirect_stdout(io.StringIO()):
        p = PolicyUpdater(db_path=tmp_db)
    yield p, tmp_db
    if os.path.exists(tmp_db):
        os.unlink(tmp_db)


def _get_health(pu, tmp_db, source_name):
    conn = sqlite3.connect(tmp_db)
    c = conn.cursor()
    c.execute("SELECT consecutive_failures, next_retry_at, last_success FROM source_health WHERE source_name=?", (source_name,))
    row = c.fetchone()
    conn.close()
    return row


def test_1_failure_no_backoff(pu):
    """1 次失败不应 backoff,允许立即重试(只记错误,不断网源)"""
    p, tmp_db = pu
    p._record_source_health("mee.gov.cn", success=False, error="ConnectError")
    assert not p._is_source_in_backoff("mee.gov.cn")


def test_2_failures_1h_backoff(pu):
    """2 次连续失败 → 1h backoff"""
    p, tmp_db = pu
    p._record_source_health("mee.gov.cn", success=False, error="err1")
    p._record_source_health("mee.gov.cn", success=False, error="err2")
    assert p._is_source_in_backoff("mee.gov.cn")
    failures, next_retry, _ = _get_health(p, tmp_db, "mee.gov.cn")
    delta_min = (datetime.fromisoformat(next_retry) - datetime.now()).total_seconds() / 60
    assert failures == 2
    assert 55 < delta_min < 65, f"backoff 应 ~60 分钟,实际 {delta_min:.1f}"


def test_3_failures_6h_backoff(pu):
    """3 次连续失败 → 6h backoff"""
    p, tmp_db = pu
    p._record_source_health("s1", success=False, error="e1")
    p._record_source_health("s1", success=False, error="e2")
    # 模拟 1h 已过(过期) → 第 3 次失败
    conn = sqlite3.connect(tmp_db)
    conn.execute("UPDATE source_health SET next_retry_at=?", ((datetime.now() - timedelta(minutes=1)).isoformat(),))
    conn.commit()
    conn.close()
    p._record_source_health("s1", success=False, error="e3")
    failures, next_retry, _ = _get_health(p, tmp_db, "s1")
    assert failures == 3
    delta_h = (datetime.fromisoformat(next_retry) - datetime.now()).total_seconds() / 3600
    assert 5.5 < delta_h < 6.5, f"backoff 应 ~6h,实际 {delta_h:.2f}h"


def test_4_failures_24h_backoff(pu):
    """4+ 次连续失败 → 24h backoff(指数封顶)"""
    p, tmp_db = pu
    for i in range(3):
        # 先把上次的 next_retry_at 设到过去(模拟过期),再 record
        conn = sqlite3.connect(tmp_db)
        conn.execute("UPDATE source_health SET next_retry_at=?", ((datetime.now() - timedelta(minutes=1)).isoformat(),))
        conn.commit()
        conn.close()
        p._record_source_health("s2", success=False, error=f"e{i}")
    # 第 4 次失败(不覆盖,验证其自身设的 24h)
    p._record_source_health("s2", success=False, error="e3")
    failures, next_retry, _ = _get_health(p, tmp_db, "s2")
    assert failures == 4
    delta_h = (datetime.fromisoformat(next_retry) - datetime.now()).total_seconds() / 3600
    assert 23.5 < delta_h < 24.5, f"backoff 应 ~24h,实际 {delta_h:.2f}h"


def test_success_resets(pu):
    """成功后清零 consecutive_failures + next_retry_at"""
    p, tmp_db = pu
    p._record_source_health("s3", success=False, error="e1")
    p._record_source_health("s3", success=False, error="e2")
    assert p._is_source_in_backoff("s3")
    p._record_source_health("s3", success=True)
    failures, next_retry, last_success = _get_health(p, tmp_db, "s3")
    assert failures == 0
    assert next_retry is None
    assert last_success is not None
    assert not p._is_source_in_backoff("s3")


def test_different_sources_independent(pu):
    """各源 backoff 独立"""
    p, tmp_db = pu
    p._record_source_health("src_a", success=False, error="e")
    p._record_source_health("src_a", success=False, error="e")
    assert p._is_source_in_backoff("src_a")
    # src_b 还没失败,不应 backoff
    assert not p._is_source_in_backoff("src_b")
