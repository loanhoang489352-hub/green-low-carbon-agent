"""
profile模块 - 用户画像管理
"""

from .user_profile import UserProfileManager
from .dynamic_updater import DynamicProfileUpdater, get_profile_updater
from .personalized_recommender import PersonalizedRecommendationEngine, Recommendation
from .profile_graph import UserProfileGraph, ProfileNode, ProfileEdge

__all__ = [
    "UserProfileManager",
    "DynamicProfileUpdater",
    "get_profile_updater",
    "PersonalizedRecommendationEngine",
    "Recommendation",
    "UserProfileGraph",
    "ProfileNode",
    "ProfileEdge",
]
