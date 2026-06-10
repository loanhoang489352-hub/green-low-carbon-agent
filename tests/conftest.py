"""
Pytest 配置和共享 fixtures
"""

import sys
import os
from pathlib import Path

# 添加 src 到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# 设置 UTF-8 环境
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"

import pytest


@pytest.fixture
def project_path():
    """项目根目录"""
    return project_root


@pytest.fixture
def knowledge_base_path(project_path):
    """知识库路径"""
    return project_path / "knowledge_base"


@pytest.fixture
def test_user_id():
    """测试用户ID"""
    return "test_user_001"


@pytest.fixture
def sample_message():
    """测试消息"""
    return "什么是碳排放?"
