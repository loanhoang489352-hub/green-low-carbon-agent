"""
任务6: 宠物养成 - 模块入口
"""

from .pet_engine import PetEngine, PetState, PetStateChangeResult, get_pet_engine
from .constants import init_pet_schema
from .skills import register_pet_skills

__all__ = [
    "PetEngine",
    "PetState",
    "PetStateChangeResult",
    "get_pet_engine",
    "init_pet_schema",
    "register_pet_skills",
]
