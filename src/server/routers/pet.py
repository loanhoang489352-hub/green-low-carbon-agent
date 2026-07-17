"""
宠物 HTTP 路由 — 18 个端点
挂载在 server/app.py,与 chat/policy 平级
"""
import json
import logging
from datetime import date
from typing import Optional

logger = logging.getLogger("router.pet")


def register_pet_routes(registry) -> None:
    """注册宠物相关路由"""

    # ===== 任务3 基础端点(原 8 任务) =====

    def pet_state(handler, data):
        """GET /api/pet/state — 查精灵状态"""
        from pet import get_pet_engine
        user_id = data.get("user_id") or "anonymous"
        e = get_pet_engine()
        s = e.get_state(user_id)
        handler.send_json({"status": "success", "state": s.to_dict()})

    def pet_pat(handler, data):
        """POST /api/pet/pat — 抚摸"""
        from pet import get_pet_engine
        user_id = data.get("user_id") or "anonymous"
        e = get_pet_engine()
        r = e.pat(user_id)
        handler.send_json({"status": "success", **r})

    def pet_feed(handler, data):
        """POST /api/pet/feed — 投喂"""
        from pet import get_pet_engine
        user_id = data.get("user_id") or "anonymous"
        item_id = data.get("item_id", "led_bulb")
        e = get_pet_engine()
        r = e.feed(user_id, item_id)
        handler.send_json({"status": "success" if r.get("ok") else "error", **r})

    def pet_apply(handler, data):
        """POST /api/pet/apply — 录入低碳行为(任务2 主入口)"""
        from pet import get_pet_engine
        user_id = data.get("user_id") or "anonymous"
        behavior = data.get("behavior_type", "bus")
        amount = float(data.get("amount", 0))
        e = get_pet_engine()
        r = e.apply_behavior_rewards(user_id, behavior, amount)
        handler.send_json({"status": "success", "result": r.to_dict()})

    def pet_inventory(handler, data):
        """GET /api/pet/inventory — 道具栏"""
        from pet import get_pet_engine
        from pet.pet_engine import ITEMS
        user_id = data.get("user_id") or "anonymous"
        e = get_pet_engine()
        state = e.get_state(user_id)
        handler.send_json({
            "status": "success",
            "coins": state.coins,
            "items": [
                {"id": k, "name": v["name"], "cost": v["cost"]}
                for k, v in ITEMS.items()
            ],
        })

    def pet_skills(handler, data):
        """GET /api/pet/skills — 技能列表 + 解锁状态"""
        from pet import get_pet_engine
        user_id = data.get("user_id") or "anonymous"
        e = get_pet_engine()
        skills = e.get_skills(user_id)
        handler.send_json({"status": "success", "skills": skills})

    def pet_skill_today(handler, data):
        """GET /api/pet/skill/today — 今日复盘"""
        from pet import get_pet_engine
        user_id = data.get("user_id") or "anonymous"
        e = get_pet_engine()
        s = e.get_state(user_id)
        handler.send_json({
            "status": "success",
            "today": {
                "level": s.level,
                "title": s.title(),
                "total_co2_saved_kg": round(s.total_co2_saved, 2),
                "consecutive_days": s.consecutive_days,
                "appearance": s.appearance,
                "habitat": s.habitat,
                "status": s.status(),
                "coins": s.coins,
            }
        })

    def pet_skill_lifetime(handler, data):
        """GET /api/pet/skill/lifetime — 长期累计"""
        from pet import get_pet_engine
        user_id = data.get("user_id") or "anonymous"
        e = get_pet_engine()
        s = e.get_state(user_id)
        trees = s.total_co2_saved / 60.0  # 1 棵树年吸 60kg
        handler.send_json({
            "status": "success",
            "lifetime": {
                "total_co2_kg": round(s.total_co2_saved, 2),
                "equivalent_trees": round(trees, 2),
                "level": s.level,
                "appearance": s.appearance,
                "consecutive_days": s.consecutive_days,
            }
        })

    # ===== M1-T1 多品种端点 =====

    def pet_species_list(handler, data):
        """GET /api/pet/species — 5 大生态系"""
        from pet.species import SPECIES_LIBRARY
        handler.send_json({
            "status": "success",
            "species": [
                {"id": sid, **sp} for sid, sp in SPECIES_LIBRARY.items()
            ]
        })

    def pet_gacha(handler, data):
        """POST /api/pet/gacha — 抽卡"""
        from pet.species import get_species_registry
        user_id = data.get("user_id") or "anonymous"
        n = int(data.get("n", 1))
        reg = get_species_registry()
        pets = reg.gacha(user_id, n=n)
        handler.send_json({
            "status": "success" if pets else "error",
            "got": [p.to_dict() for p in pets],
            "count": len(pets),
        })

    def pet_list_my(handler, data):
        """GET /api/pet/my — 我的宠物列表"""
        from pet.species import get_species_registry
        user_id = data.get("user_id") or "anonymous"
        reg = get_species_registry()
        pets = reg.list_user_pets(user_id)
        handler.send_json({
            "status": "success",
            "pets": [p.to_dict() for p in pets],
        })

    def pet_set_active(handler, data):
        """POST /api/pet/set-active — 切换出战"""
        from pet.species import get_species_registry
        user_id = data.get("user_id") or "anonymous"
        pet_id = int(data.get("pet_id", 0))
        reg = get_species_registry()
        ok = reg.set_active_pet(user_id, pet_id)
        handler.send_json({"status": "success" if ok else "error"})

    def pet_codex(handler, data):
        """GET /api/pet/codex — 我的图鉴"""
        from pet.species import get_species_registry
        user_id = data.get("user_id") or "anonymous"
        reg = get_species_registry()
        codex = reg.list_user_codex(user_id)
        handler.send_json({"status": "success", "codex": codex, "count": len(codex)})

    # ===== M1-T2 季节端点 =====

    def pet_season_info(handler, data):
        """GET /api/pet/season — 当前季节活动信息"""
        from pet.seasonal import get_seasonal_manager
        sm = get_seasonal_manager()
        info = sm.get_current_season_info()
        handler.send_json({"status": "success", "season": info})

    def pet_season_status(handler, data):
        """GET /api/pet/season/status — 用户的季节进度"""
        from pet.seasonal import get_seasonal_manager
        user_id = data.get("user_id") or "anonymous"
        sm = get_seasonal_manager()
        status = sm.get_user_season_status(user_id)
        handler.send_json({"status": "success", **status})

    def pet_season_claim(handler, data):
        """POST /api/pet/season/claim — 领取季节奖励"""
        from pet.seasonal import get_seasonal_manager
        from datetime import date as _date
        user_id = data.get("user_id") or "anonymous"
        task_id = data.get("task_id", "")
        season = data.get("season", "summer")
        year = int(data.get("year", _date.today().year))
        sm = get_seasonal_manager()
        reward = sm.claim_reward(user_id, task_id, season, year)
        handler.send_json({"status": "success" if reward else "error", "reward": reward})

    # ===== M1-T3 PK 端点 =====

    def pet_ranking(handler, data):
        """GET /api/pet/ranking — 排行榜"""
        from pet.ranking import get_ranking_system
        period = data.get("period", "all")
        top = int(data.get("top", 20))
        rs = get_ranking_system()
        handler.send_json({
            "status": "success",
            "period": period,
            "ranking": rs.get_leaderboard(period=period, top=top),
        })

    def pet_pk_battle(handler, data):
        """POST /api/pet/pk — PK 对战"""
        from pet.ranking import get_ranking_system
        challenger = data.get("challenger_id") or "anonymous"
        opponent = data.get("opponent_id", "")
        if not opponent:
            handler.send_json({"status": "error", "msg": "需 opponent_id"}, status=400)
            return
        rs = get_ranking_system()
        result = rs.pk_battle(challenger, opponent)
        handler.send_json({"status": "success", "result": result})

    def pet_friends(handler, data):
        """GET/POST /api/pet/friends — 好友列表/加好友"""
        from pet.ranking import get_ranking_system
        user_id = data.get("user_id") or "anonymous"
        action = data.get("action", "list")
        rs = get_ranking_system()
        if action == "add":
            friend_id = data.get("friend_id", "")
            ok = rs.add_friend(user_id, friend_id) if friend_id else False
            handler.send_json({"status": "success" if ok else "error"})
        else:
            handler.send_json({
                "status": "success",
                "friends": rs.list_friends(user_id)
            })

    # ===== 路由注册(auth_required=False 保持老 e2e 兼容) =====

    registry.add_route("GET", "/api/pet/state", pet_state, auth_required=False, description="宠物状态")
    registry.add_route("POST", "/api/pet/pat", pet_pat, auth_required=False, description="抚摸")
    registry.add_route("POST", "/api/pet/feed", pet_feed, auth_required=False, description="投喂")
    registry.add_route("POST", "/api/pet/apply", pet_apply, auth_required=False, description="录入低碳行为")
    registry.add_route("GET", "/api/pet/inventory", pet_inventory, auth_required=False, description="道具栏")
    registry.add_route("GET", "/api/pet/skills", pet_skills, auth_required=False, description="技能列表")
    registry.add_route("GET", "/api/pet/skill/today", pet_skill_today, auth_required=False, description="今日复盘")
    registry.add_route("GET", "/api/pet/skill/lifetime", pet_skill_lifetime, auth_required=False, description="长期累计")
    # M1-T1
    registry.add_route("GET", "/api/pet/species", pet_species_list, auth_required=False, description="5 大生态系")
    registry.add_route("POST", "/api/pet/gacha", pet_gacha, auth_required=False, description="抽卡")
    registry.add_route("GET", "/api/pet/my", pet_list_my, auth_required=False, description="我的宠物")
    registry.add_route("POST", "/api/pet/set-active", pet_set_active, auth_required=False, description="切换出战")
    registry.add_route("GET", "/api/pet/codex", pet_codex, auth_required=False, description="图鉴")
    # M1-T2
    registry.add_route("GET", "/api/pet/season", pet_season_info, auth_required=False, description="季节活动")
    registry.add_route("GET", "/api/pet/season/status", pet_season_status, auth_required=False, description="季节进度")
    registry.add_route("POST", "/api/pet/season/claim", pet_season_claim, auth_required=False, description="领季节奖")
    # M1-T3
    registry.add_route("GET", "/api/pet/ranking", pet_ranking, auth_required=False, description="PK 排行榜")
    registry.add_route("POST", "/api/pet/pk", pet_pk_battle, auth_required=False, description="PK 对战")
    registry.add_route("GET", "/api/pet/friends", pet_friends, auth_required=False, description="好友列表")
