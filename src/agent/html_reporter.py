"""
P14 HTML Reporter — 高级 HTML 报告渲染引擎

设计:
  · 单文件 HTML(内嵌 Tailwind/Alpine/Chart.js CDN)— 直接浏览器打开
  · Jinja2 模板 + Python 上下文
  · 多 variant 切换(少折腾/省钱/减碳)— Alpine.js 响应式
  · 字段溯源可视化(每个字段从哪读到的)
  · 待办清单(可勾选,localStorage 持久化)
  · Chart.js 节省饼图 + 月度趋势
  · LLM 反问可点击回复
  · Obsidian 同步状态展示

输出:可直接用浏览器打开的 HTML 字符串
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

_log = logging.getLogger(__name__)

# 模板目录
_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

# 本地化前端库缓存(替代 CDN,离线/国内网络可用)
_STATIC_CACHE: Dict[str, str] = {}


def _load_static_js() -> Dict[str, str]:
    """读取本地化的前端库,缓存后返回(避免每次渲染都读磁盘)。"""
    if not _STATIC_CACHE:
        for name in ("tailwind.js", "alpine.min.js", "chart.umd.min.js"):
            p = _TEMPLATE_DIR / "static" / name
            _STATIC_CACHE[name] = p.read_text(encoding="utf-8") if p.exists() else ""
    return _STATIC_CACHE


# ============ 数据准备 ============

def build_variants(plan_dict: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """从单一 plan 生成 3 个排序 variant

    Returns:
        {
          "easy":  按 difficulty 升序(默认,少折腾)
          "money": 按 estimated_saving_cny 降序(省钱)
          "carbon":按 estimated_saving_co2_kg 降序(减碳)
        }
    """
    actions = plan_dict.get("actions", [])
    by_easy = sorted(actions, key=lambda a: (a.get("difficulty", 3), a.get("id", "")))
    by_money = sorted(actions, key=lambda a: (-(a.get("estimated_saving_cny") or 0), a.get("id", "")))
    by_carbon = sorted(actions, key=lambda a: (-(a.get("estimated_saving_co2_kg") or 0), a.get("id", "")))
    return {
        "easy": by_easy,
        "money": by_money,
        "carbon": by_carbon,
    }


def build_chart_data(variants: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Chart.js 饼图:当前 variant 按 category(电/水/气)聚合节省"""
    by_category: Dict[str, float] = {"electricity": 0.0, "water": 0.0, "gas": 0.0}
    for a in variants.get("easy", []):
        cat = a.get("category", "electricity")
        cny = a.get("estimated_saving_cny") or 0.0
        if cat in by_category:
            by_category[cat] += cny
    return {
        "labels": ["电", "水", "气"],
        "datasets": [{
            "label": "年度节省(元)",
            "data": [
                round(by_category["electricity"], 2),
                round(by_category["water"], 2),
                round(by_category["gas"], 2),
            ],
            "backgroundColor": ["#10b981", "#3b82f6", "#f59e0b"],
            "borderWidth": 2,
            "borderColor": "#ffffff",
        }],
    }


def build_field_cards(profile: Dict[str, Any], sources: Dict[str, str]) -> List[Dict[str, Any]]:
    """把画像字段序列化成卡片数据

    Returns:
        [{"name": "family_size", "label": "家庭人数", "value": 5, "source": "家庭画像记录",
          "icon": "👨‍👩‍👧", "category": "household"}, ...]
    """
    cards: List[Dict[str, Any]] = []
    field_meta = [
        ("family_size", "家庭人数", "👨‍👩‍👧", "household"),
        ("home_size_sqm", "住房面积", "🏠", "household"),
        ("city", "所在城市", "🌆", "household"),
        ("monthly_electricity_bill", "月电费(元)", "⚡", "bill"),
        ("monthly_water_bill", "月水费(元)", "💧", "bill"),
        ("monthly_gas_bill", "月燃气费(元)", "🔥", "bill"),
        ("appliances", "家电清单", "🛋️", "appliance"),
        ("ac_temp_setting", "空调设定温度(°C)", "❄️", "habit"),
        ("priority", "优先级", "🎯", "preference"),
    ]
    for fname, label, icon, cat in field_meta:
        val = profile.get(fname)
        if val is None or val == "" or val == []:
            continue
        if isinstance(val, list) and not val:
            continue
        cards.append({
            "name": fname,
            "label": label,
            "value": val,
            "source": sources.get(fname, "未确认"),
            "icon": icon,
            "category": cat,
        })
    return cards


def build_today_card_display(card_dict: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """今日行动卡序列化"""
    if not card_dict:
        return []
    return card_dict.get("actions", [])


# ============ 引擎 ============

class HTMLReporter:
    """HTML 报告渲染器 — 单文件输出,可直接浏览器打开"""

    def __init__(self, template_dir: Optional[Path] = None) -> None:
        self.template_dir = Path(template_dir) if template_dir else _TEMPLATE_DIR
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(["html"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        # 注册 filter
        self.env.filters["tojson_pretty"] = lambda x: json.dumps(x, ensure_ascii=False, indent=2)
        self.env.filters["truncate_text"] = lambda s, n=120: (s[:n] + "...") if isinstance(s, str) and len(s) > n else s

    def render_energy_plan(self,
                           *,
                           user_id: str,
                           profile: Dict[str, Any],
                           profile_sources: Dict[str, str],
                           plan: Dict[str, Any],
                           today_card: Optional[Dict[str, Any]] = None,
                           llm_explanation: str = "",
                           llm_follow_up: Optional[List[str]] = None,
                           llm_meta: Optional[Dict[str, Any]] = None,
                           obsidian_writes: Optional[List[str]] = None,
                           violations: Optional[List[str]] = None,
                           anti_hallu_passed: bool = True,
                           profile_field_count: int = 0) -> str:
        """渲染节能方案 HTML 报告"""
        variants = build_variants(plan)
        chart_data = build_chart_data(variants)
        field_cards = build_field_cards(profile, profile_sources)
        today_card_actions = build_today_card_display(today_card)

        # 计算节省合计(各 variant)
        total_savings = {
            "easy": sum(a.get("estimated_saving_cny") or 0 for a in variants["easy"]),
            "money": sum(a.get("estimated_saving_cny") or 0 for a in variants["money"]),
            "carbon": sum(a.get("estimated_saving_cny") or 0 for a in variants["carbon"]),
        }
        total_co2 = {
            "easy": sum(a.get("estimated_saving_co2_kg") or 0 for a in variants["easy"]),
            "money": sum(a.get("estimated_saving_co2_kg") or 0 for a in variants["money"]),
            "carbon": sum(a.get("estimated_saving_co2_kg") or 0 for a in variants["carbon"]),
        }

        # 待办(合并全部 variant 的 action_id)
        all_action_ids = sorted({a["id"] for a in plan.get("actions", []) if a.get("id")})

        ctx = {
            "title": f"节能方案 · {profile.get('city', '用户')}",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "user_id": user_id,
            "user_alias": user_id[:8] if user_id else "guest",
            # 画像
            "profile": profile,
            "profile_field_count": profile_field_count or len(profile_sources),
            "field_cards": field_cards,
            "profile_sources": profile_sources,
            # Plan
            "plan": plan,
            "plan_id": plan.get("id", "?"),
            "today_card_actions": today_card_actions,
            # variants
            "variants": variants,
            "variant_easy": variants["easy"],
            "variant_money": variants["money"],
            "variant_carbon": variants["carbon"],
            "total_savings": total_savings,
            "total_co2": total_co2,
            "total_actions": len(plan.get("actions", [])),
            # chart
            "chart_data_json": json.dumps(chart_data, ensure_ascii=False),
            # LLM
            "llm_explanation": llm_explanation or "(未启用 LLM 推理 / 已回退到模板)",
            "llm_follow_up": llm_follow_up or [],
            "llm_meta": llm_meta or {},
            # Obsidian
            "obsidian_writes": obsidian_writes or [],
            # 护栏
            "anti_hallu_passed": anti_hallu_passed,
            "violations": violations or [],
            # 待办
            "all_action_ids_json": json.dumps(all_action_ids, ensure_ascii=False),
            # 前端库(内联,单文件离线可开)
            "tailwind_js": _load_static_js().get("tailwind.js", ""),
            "alpine_js": _load_static_js().get("alpine.min.js", ""),
            "chart_js": _load_static_js().get("chart.umd.min.js", ""),
        }

        template = self.env.get_template("energy_plan_report.html")
        return template.render(**ctx)

    def render_error(self, message: str, user_id: str = "guest") -> str:
        """渲染错误页(模板不可用时的兜底)"""
        return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>渲染失败</title>
<style>
body{{font-family:system-ui;padding:40px;background:#fef2f2;color:#7f1d1d}}
.err{{max-width:600px;margin:auto;background:#fff;padding:24px;border-radius:12px;
border:1px solid #fca5a5;box-shadow:0 4px 12px rgba(0,0,0,0.05)}}
h1{{margin-top:0}}
</style></head><body>
<div class="err">
<h1>⚠️ 报告渲染失败</h1>
<p>用户: {user_id}</p>
<p>错误: {message}</p>
<p style="color:#9ca3af">请检查 HTML 模板或联系开发者。</p>
</div>
</body></html>"""


__all__ = ["HTMLReporter"]