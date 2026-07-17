import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime


def get_project_root() -> Path:
    """获取项目根目录"""
    return Path(__file__).parent.parent.parent


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """加载配置文件"""
    if config_path is None:
        config_path = get_project_root() / "config" / "settings.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 处理环境变量替换
    config = _replace_env_vars(config)
    return config


def _replace_env_vars(config: Any) -> Any:
    """递归替换配置中的环境变量"""
    if isinstance(config, dict):
        return {k: _replace_env_vars(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [_replace_env_vars(item) for item in config]
    elif isinstance(config, str) and config.startswith("${") and config.endswith("}"):
        env_var = config[2:-1]
        return os.getenv(env_var, config)
    return config


def get_knowledge_base_path() -> Path:
    """获取知识库路径"""
    return get_project_root() / "knowledge_base"


def get_data_path() -> Path:
    """获取数据存储路径"""
    data_path = get_project_root() / "data"
    data_path.mkdir(parents=True, exist_ok=True)
    return data_path


def format_carbon_amount(kg: float) -> str:
    """格式化碳排放量为易读格式"""
    if kg >= 1000:
        return f"{kg / 1000:.2f} 吨 CO2"
    return f"{kg:.2f} 千克 CO2"


def calculate_carbon_saving(action: str, baseline: float) -> float:
    """计算碳减排量（简化版）"""
    # 简化的碳排放因子
    factors = {
        "步行": 0,
        "骑行": 0,
        "公交": 0.015,  # kg CO2/km
        "地铁": 0.01,
        "私家车": 0.15,
        "电动车": 0.05,
        "植物性饮食": 2.5,  # kg CO2/天
        "减少肉类": 1.5,
        "空调调高1度": 0.15,  # kg CO2/天
        "LED灯": 0.3,  # kg CO2/天
    }
    return factors.get(action, baseline)


def get_current_date() -> str:
    """获取当前日期字符串"""
    return datetime.now().strftime("%Y-%m-%d")


def get_current_datetime() -> str:
    """获取当前日期时间字符串"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_response_structure(
    message: str,
    intent: str = None,
    suggestions: list = None,
    knowledge_refs: list = None,
    memory_hints: list = None,
) -> Dict[str, Any]:
    """创建标准响应结构"""
    return {
        "message": message,
        "intent": intent,
        "suggestions": suggestions or [],
        "knowledge_refs": knowledge_refs or [],
        "memory_hints": memory_hints or [],
        "timestamp": get_current_datetime(),
    }


def extract_keywords(text: str) -> list:
    """提取文本关键词（简化版）"""
    # 简化的中文分词
    stop_words = {
        "的",
        "了",
        "是",
        "在",
        "我",
        "有",
        "和",
        "就",
        "不",
        "人",
        "都",
        "一",
        "一个",
        "上",
        "也",
        "很",
        "到",
        "说",
        "要",
        "去",
        "你",
        "会",
        "着",
        "没有",
        "看",
        "好",
        "自己",
        "这",
    }

    # 简单字符过滤
    chars = [c for c in text if c.isalnum() or c.isspace()]
    words = "".join(chars).split()

    return [w for w in words if w not in stop_words and len(w) > 1]
