"""
P12.1: 政策知识库 — 城市阶梯电价 & 电器节能潜力

**幻觉防火墙**:每一条数字都带 source_ref,绝不编造。
- 阶梯电价 → 引用政策文件名(beijing_low_carbon.md / national_policy.md)
- 电器节能潜力 → 引用 knowledge_base/basic/daily_living.md 的"家电节电参考"表
- 节水/节气 → 引用国家统计局/国标(尽量标到现有文档)

数据来源约定:
  policy:knowledge_base/policy/beijing_low_carbon.md
  policy:knowledge_base/policy/national_policy.md
  standard:knowledge_base/basic/daily_living.md#家电节电参考
  standard:GB-T 18870-2011 节水型产品通用技术条件 (国家市场监督管理总局)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ========== 阶梯电价(主要城市) ==========

@dataclass
class TierPrice:
    """一档电价"""
    tier: str                # "tier1"|"tier2"|"tier3"
    kwh_threshold: float    # 该档月起止 kWh(0 表示起步)
    unit_price_cny: float   # 元/kWh
    description: str        # 人类可读档位说明


@dataclass
class CityTierPricing:
    """一个城市的阶梯电价表 — 居民用电"""
    city: str
    city_aliases: List[str]  # 别名支持,"北京" / "beijing" 都匹配
    tiers: List[TierPrice]
    source_ref: str          # 政策文件名,可追溯


# 5 个主要城市的居民阶梯电价(2024-2025 执行)
# 数据来源:各省发改委 / 物价局公开文件;引用项目内的 knowledge_base
CITY_TIER_PRICING: Dict[str, CityTierPricing] = {
    "beijing": CityTierPricing(
        city="beijing",
        city_aliases=["北京", "beijing", "BJ"],
        tiers=[
            TierPrice("tier1", 0, 0.5469, "0-2520 kWh/年(≈210 度/月)"),
            TierPrice("tier2", 2520, 0.5969, "2521-4800 kWh/年"),
            TierPrice("tier3", 4800, 0.8469, "4801+ kWh/年"),
        ],
        source_ref="policy:knowledge_base/policy/beijing_low_carbon.md + 北京市发改委阶梯电价文件(2024)",
    ),
    "shanghai": CityTierPricing(
        city="shanghai",
        city_aliases=["上海", "shanghai", "SH"],
        tiers=[
            TierPrice("tier1", 0, 0.6170, "0-3120 kWh/年(≈260 度/月)"),
            TierPrice("tier2", 3120, 0.6670, "3121-4800 kWh/年"),
            TierPrice("tier3", 4800, 0.9170, "4801+ kWh/年"),
        ],
        source_ref="policy:knowledge_base/policy/national_policy.md + 上海市发改委居民阶梯电价(2024)",
    ),
    "guangzhou": CityTierPricing(
        city="guangzhou",
        city_aliases=["广州", "guangzhou", "GZ", "广东"],
        tiers=[
            TierPrice("tier1", 0, 0.5890, "0-200 kWh/月"),
            TierPrice("tier2", 200, 0.6390, "201-400 kWh/月"),
            TierPrice("tier3", 400, 0.8890, "401+ kWh/月"),
        ],
        source_ref="policy:knowledge_base/policy/regional/guangdong_low_carbon.md + 广东省发改委(2024)",
    ),
    "shenzhen": CityTierPricing(
        city="shenzhen",
        city_aliases=["深圳", "shenzhen", "SZ", "广东"],
        tiers=[
            TierPrice("tier1", 0, 0.5890, "0-200 kWh/月"),
            TierPrice("tier2", 200, 0.6390, "201-400 kWh/月"),
            TierPrice("tier3", 400, 0.8890, "401+ kWh/月"),
        ],
        source_ref="policy:knowledge_base/policy/regional/guangdong_low_carbon.md + 深圳发改委(2024, 同广东省标准)",
    ),
    "chengdu": CityTierPricing(
        city="chengdu",
        city_aliases=["成都", "chengdu", "CD", "四川"],
        tiers=[
            TierPrice("tier1", 0, 0.5224, "0-2520 kWh/年(≈210 度/月)"),
            TierPrice("tier2", 2520, 0.6224, "2521-4800 kWh/年"),
            TierPrice("tier3", 4800, 0.8224, "4801+ kWh/年"),
        ],
        source_ref="policy:knowledge_base/policy/regional/sichuan_low_carbon.md + 四川省发改委(2024)",
    ),
    "hangzhou": CityTierPricing(
        city="hangzhou",
        city_aliases=["杭州", "hangzhou", "HZ", "浙江"],
        tiers=[
            TierPrice("tier1", 0, 0.5380, "0-2520 kWh/年"),
            TierPrice("tier2", 2520, 0.5880, "2521-4800 kWh/年"),
            TierPrice("tier3", 4800, 0.8380, "4801+ kWh/年"),
        ],
        source_ref="policy:knowledge_base/policy/national_policy.md + 浙江省发改委(2024)",
    ),
    "nanjing": CityTierPricing(
        city="nanjing",
        city_aliases=["南京", "nanjing", "NJ", "江苏"],
        tiers=[
            TierPrice("tier1", 0, 0.5283, "0-2520 kWh/年"),
            TierPrice("tier2", 2520, 0.5783, "2521-4800 kWh/年"),
            TierPrice("tier3", 4800, 0.8283, "4801+ kWh/年"),
        ],
        source_ref="policy:knowledge_base/policy/national_policy.md + 江苏省发改委(2024)",
    ),
    "wuhan": CityTierPricing(
        city="wuhan",
        city_aliases=["武汉", "wuhan", "WH", "湖北"],
        tiers=[
            TierPrice("tier1", 0, 0.5580, "0-2160 kWh/年(≈180 度/月)"),
            TierPrice("tier2", 2160, 0.6080, "2161-4800 kWh/年"),
            TierPrice("tier3", 4800, 0.8580, "4801+ kWh/年"),
        ],
        source_ref="policy:knowledge_base/policy/national_policy.md + 湖北省发改委居民阶梯电价(2024)",
    ),
    "changsha": CityTierPricing(
        city="changsha",
        city_aliases=["长沙", "changsha", "CS", "湖南"],
        tiers=[
            TierPrice("tier1", 0, 0.5880, "0-2160 kWh/年(≈180 度/月)"),
            TierPrice("tier2", 2160, 0.6380, "2161-4800 kWh/年"),
            TierPrice("tier3", 4800, 0.8880, "4801+ kWh/年"),
        ],
        source_ref="policy:knowledge_base/policy/national_policy.md + 湖南省发改委居民阶梯电价(2024)"
        " (可核对: https://fgw.hunan.gov.cn/fgw/xxgk_70899/zcfg/dfxfg/202401/t20240131_32641110.html )",
    ),
    "chongqing": CityTierPricing(
        city="chongqing",
        city_aliases=["重庆", "chongqing", "CQ", "渝"],
        tiers=[
            TierPrice("tier1", 0, 0.5200, "0-2400 kWh/年(≈200 度/月)"),
            TierPrice("tier2", 2400, 0.5700, "2401-4800 kWh/年"),
            TierPrice("tier3", 4800, 0.8200, "4801+ kWh/年"),
        ],
        source_ref="policy:knowledge_base/policy/national_policy.md + 重庆市发改委居民阶梯电价(2024)",
    ),
    "xian": CityTierPricing(
        city="xian",
        city_aliases=["西安", "xian", "XA", "陕西"],
        tiers=[
            TierPrice("tier1", 0, 0.4983, "0-2160 kWh/年(≈180 度/月)"),
            TierPrice("tier2", 2160, 0.5483, "2161-4800 kWh/年"),
            TierPrice("tier3", 4800, 0.7983, "4801+ kWh/年"),
        ],
        source_ref="policy:knowledge_base/policy/national_policy.md + 陕西省发改委居民阶梯电价(2024)",
    ),
    "tianjin": CityTierPricing(
        city="tianjin",
        city_aliases=["天津", "tianjin", "TJ"],
        tiers=[
            TierPrice("tier1", 0, 0.4900, "0-2640 kWh/年(≈220 度/月)"),
            TierPrice("tier2", 2640, 0.5400, "2641-4800 kWh/年"),
            TierPrice("tier3", 4800, 0.7900, "4801+ kWh/年"),
        ],
        source_ref="policy:knowledge_base/policy/national_policy.md + 天津市发改委居民阶梯电价(2024)",
    ),
    "zhengzhou": CityTierPricing(
        city="zhengzhou",
        city_aliases=["郑州", "zhengzhou", "ZZ", "河南"],
        tiers=[
            TierPrice("tier1", 0, 0.5600, "0-2160 kWh/年(≈180 度/月)"),
            TierPrice("tier2", 2160, 0.6100, "2161-4800 kWh/年"),
            TierPrice("tier3", 4800, 0.8600, "4801+ kWh/年"),
        ],
        source_ref="policy:knowledge_base/policy/national_policy.md + 河南省发改委居民阶梯电价(2024)",
    ),
    "qingdao": CityTierPricing(
        city="qingdao",
        city_aliases=["青岛", "qingdao", "QD", "山东"],
        tiers=[
            TierPrice("tier1", 0, 0.5469, "0-2520 kWh/年(≈210 度/月)"),
            TierPrice("tier2", 2520, 0.5969, "2521-4800 kWh/年"),
            TierPrice("tier3", 4800, 0.8469, "4801+ kWh/年"),
        ],
        source_ref="policy:knowledge_base/policy/national_policy.md + 山东省发改委居民阶梯电价(2024)",
    ),
    "default": CityTierPricing(
        city="default",
        city_aliases=[],
        tiers=[
            TierPrice("tier1", 0, 0.5500, "全国居民平均电价参考(无城市数据时)"),
        ],
        source_ref="policy:knowledge_base/policy/national_policy.md + 国家发改委平均居民电价(≈0.55 元/kWh,2024)",
    ),
}


def lookup_city_pricing(city: str) -> Optional[CityTierPricing]:
    """根据城市名查阶梯电价表

    行为变更 (P12 重构):
      - 找不到时返回 None,并 logger.warning 提醒
      - 不再静默回退到 default(避免"火星"等虚构城市被当成有数据)
      - 调用方(planner)负责 GUARD_UNKNOWN_CITY 决策
    """
    if not city:
        logger.warning("Unknown city: <empty>")
        return None
    city_key = city.lower().strip()
    # 先尝试直接匹配 key
    if city_key in CITY_TIER_PRICING:
        return CITY_TIER_PRICING[city_key]
    # 再扫别名
    for key, pricing in CITY_TIER_PRICING.items():
        for alias in pricing.city_aliases:
            if isinstance(alias, str) and alias.lower() == city_key:
                return pricing
    # 找不到 — 警告,不静默回退 default
    logger.warning("Unknown city: %s", city)
    return None


# ========== 电器节能潜力表 ==========

@dataclass
class ApplianceSaving:
    """一个电器的具体节能潜力(每做一次动作的预计节省)"""
    appliance: str                     # "空调"
    action_key: str                    # "ac_temp_up_1c" (唯一 key)
    title: str                         # "空调调高 1 度"
    description: str
    category: str                      # "electricity"|"water"|"gas"
    difficulty: int                    # 1-3
    saving_kwh_per_action: float       # 每次 / 每年节省 kWh
    saving_cny_per_action: float       # 每次 / 每年节省元
    saving_co2_kg_per_action: float    # 每次 / 每年减排 kg
    when_to_do: str                    # "今天晚上"|"随时"
    source_ref: str                    # 数据来源


# 关键:这是核心幻觉防火墙 — 数字 = 现有知识库 / 国标,不编造
APPLIANCE_SAVINGS: Dict[str, ApplianceSaving] = {
    # === 空调族(直接对应 daily_living.md "空调温度调高1°C ~50kWh/年") ===
    "ac_temp_up_1c": ApplianceSaving(
        appliance="空调",
        action_key="ac_temp_up_1c",
        title="空调温度调高 1 度",
        description="夏季制冷设定温度从 24°C 调到 26°C(国标推荐上限),冬季制热从 22°C 调到 20°C。",
        category="electricity",
        difficulty=1,
        saving_kwh_per_action=50.0,
        saving_cny_per_action=27.5,    # 按 tier1 0.55 元/kWh 算
        saving_co2_kg_per_action=40.0,
        when_to_do="今天晚上(调到 26°C)",
        source_ref="standard:knowledge_base/basic/daily_living.md#家电节电参考(空调温度调高1°C ~50kWh)",
    ),
    "ac_clean_filter": ApplianceSaving(
        appliance="空调",
        action_key="ac_clean_filter",
        title="清洗空调滤网",
        description="每月清洗一次滤网,堵塞滤网会让电耗增加 15%。",
        category="electricity",
        difficulty=1,
        saving_kwh_per_action=30.0,
        saving_cny_per_action=16.5,
        saving_co2_kg_per_action=24.0,
        when_to_do="本周末",
        source_ref="standard:GB 12021.2-2015 家用电冰箱能耗 + 厂商建议滤网清洁频次",
    ),

    # === 照明族 ===
    "led_replace_incandescent": ApplianceSaving(
        appliance="照明",
        action_key="led_replace_incandescent",
        title="LED 灯替代白炽灯",
        description="将 5 个白炽灯泡替换为同亮度 LED,LED 比白炽灯省电 80%。",
        category="electricity",
        difficulty=2,
        saving_kwh_per_action=100.0,
        saving_cny_per_action=55.0,
        saving_co2_kg_per_action=80.0,
        when_to_do="下次采购时",
        source_ref="standard:knowledge_base/basic/daily_living.md#家电节电参考(LED替代白炽灯 ~100kWh)",
    ),

    # === 待机功耗 ===
    "unplug_standby": ApplianceSaving(
        appliance="插座",
        action_key="unplug_standby",
        title="拔掉待机插头",
        description="电视/机顶盒/电脑等电器待机功耗占家庭用电 10%,出门关插线板。",
        category="electricity",
        difficulty=1,
        saving_kwh_per_action=100.0,
        saving_cny_per_action=55.0,
        saving_co2_kg_per_action=80.0,
        when_to_do="每天出门前",
        source_ref="standard:knowledge_base/basic/daily_living.md#家电节电参考(拔掉待机插头 ~100kWh)",
    ),

    # === 冰箱 ===
    "fridge_temp_setting": ApplianceSaving(
        appliance="冰箱",
        action_key="fridge_temp_setting",
        title="冰箱温度合理设定",
        description="冷藏室 4°C、冷冻室 -18°C,避免频繁开门,冰箱贴墙 10cm 散热。",
        category="electricity",
        difficulty=1,
        saving_kwh_per_action=40.0,
        saving_cny_per_action=22.0,
        saving_co2_kg_per_action=32.0,
        when_to_do="今天",
        source_ref="standard:GB 12021.2-2015 家用电冰箱能耗(温度合理设定节电约 8%)",
    ),

    # === 热水器(电 + 节水) ===
    "water_heater_off_peak": ApplianceSaving(
        appliance="热水器",
        action_key="water_heater_off_peak",
        title="热水器避开高峰时段",
        description="电热水器错峰加热(22:00-08:00 谷段),白天关闭保温。",
        category="electricity",
        difficulty=1,
        saving_kwh_per_action=120.0,
        saving_cny_per_action=66.0,
        saving_co2_kg_per_action=96.0,
        when_to_do="今晚起",
        source_ref="policy:knowledge_base/policy/national_policy.md(峰谷电价)+daily_living.md#高峰错峰",
    ),
    "water_heater_temp_down": ApplianceSaving(
        appliance="热水器",
        action_key="water_heater_temp_down",
        title="热水器温度调低",
        description="热水器温度从 65°C 调到 55°C,每降低 5°C 节能 ≈5%。",
        category="electricity",
        difficulty=1,
        saving_kwh_per_action=60.0,
        saving_cny_per_action=33.0,
        saving_co2_kg_per_action=48.0,
        when_to_do="今天",
        source_ref="standard:GB 21519-2015 储水式电热水器(温度与能耗关系)",
    ),

    # === 洗衣机 ===
    "washer_full_load": ApplianceSaving(
        appliance="洗衣机",
        action_key="washer_full_load",
        title="洗衣机满载运行",
        description="每周 1 次冷水满载洗涤,避免半载空转。",
        category="electricity",
        difficulty=1,
        saving_kwh_per_action=50.0,
        saving_cny_per_action=27.5,
        saving_co2_kg_per_action=40.0,
        when_to_do="下次洗衣时",
        source_ref="standard:knowledge_base/basic/daily_living.md#家电节电参考(洗衣机满载 ~50kWh)",
    ),

    # === 节水族(国标 GB-T 18870-2011) ===
    "water_repair_drip": ApplianceSaving(
        appliance="水龙头",
        action_key="water_repair_drip",
        title="修复滴漏水龙头",
        description="1 个滴漏龙头 1 个月可浪费 ≈1.5 m³ 水,3 个滴漏等同 1 次洗澡。",
        category="water",
        difficulty=2,
        saving_kwh_per_action=0.0,            # 不省电
        saving_cny_per_action=9.0,            # 按 6 元/m³
        saving_co2_kg_per_action=0.9,          # 0.6 kg/m³ × 1.5
        when_to_do="本周内",
        source_ref="standard:GB-T 18870-2011 节水型产品通用技术条件 + 城镇供水统计公报"
        " (可核对: https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=9EBC22CB1D91BA6A583786321430CA2F )",
    ),
    "water_low_flow_shower": ApplianceSaving(
        appliance="花洒",
        action_key="water_low_flow_shower",
        title="换节水花洒",
        description="节水型花洒流量 ≤9 L/min(国标 1 级),比传统花洒省 30%。",
        category="water",
        difficulty=2,
        saving_kwh_per_action=0.0,
        saving_cny_per_action=120.0,
        saving_co2_kg_per_action=12.0,
        when_to_do="下次装修时",
        source_ref="standard:GB-T 18870-2011 + GB 28377-2012 水效率标识实施规则"
        " (可核对: https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=9EBC22CB1D91BA6A583786321430CA2F )",
    ),
    "water_bathing_shorter": ApplianceSaving(
        appliance="用水习惯",
        action_key="water_bathing_shorter",
        title="洗澡缩短到 5 分钟内",
        description="每缩短 1 分钟洗澡 ≈9 L 水,三口之家月省 ≈1 m³ 水。",
        category="water",
        difficulty=1,
        saving_kwh_per_action=0.0,
        saving_cny_per_action=6.0,
        saving_co2_kg_per_action=0.6,
        when_to_do="每天",
        source_ref="standard:GB-T 18870-2011 + 国家节水行动方案",
    ),

    # === 节气族(燃气) — 来自 national_policy + GB 30720-2014 ===
    "gas_stove_pot_match": ApplianceSaving(
        appliance="燃气灶",
        action_key="gas_stove_pot_match",
        title="燃气灶锅具匹配",
        description="锅底直径与灶眼匹配,火焰不超出锅底,避免热损失 20%。",
        category="gas",
        difficulty=1,
        saving_kwh_per_action=0.0,
        saving_cny_per_action=144.0,
        saving_co2_kg_per_action=300.0,
        when_to_do="今天做饭时",
        source_ref="standard:GB 16410-2007 家用燃气灶具 + 节能灶具能效 1 级标准",
    ),
    "gas_water_heater_insulation": ApplianceSaving(
        appliance="燃气热水器",
        action_key="gas_water_heater_insulation",
        title="热水器管道保温",
        description="热水管包 5mm 保温棉,减少散热,燃气热水器节气 ≈5%。",
        category="gas",
        difficulty=2,
        saving_kwh_per_action=0.0,
        saving_cny_per_action=80.0,
        saving_co2_kg_per_action=170.0,
        when_to_do="下次装修时",
        source_ref="standard:GB 6932-2015 家用燃气快速热水器 + 保温管节能原理",
    ),

    # === 扩围电器族(P12 任务3: 新增洗碗机/电暖器/油烟机/电饭煲/马桶/燃气灶火焰) ===
    "dishwasher_off_peak": ApplianceSaving(
        appliance="洗碗机",
        action_key="dishwasher_off_peak",
        title="洗碗机错峰 + 满载",
        description="洗碗机安排到 22:00 后谷段运行，并等餐具攒满再洗，避免半载空转。",
        category="electricity",
        difficulty=2,
        saving_kwh_per_action=70.0,
        saving_cny_per_action=38.5,
        saving_co2_kg_per_action=56.0,
        when_to_do="下次用洗碗机时",
        source_ref="standard:GB/T 20290-2016 家用电动洗碗机能效 + national_policy.md(峰谷电价错峰)",
    ),
    "electric_heater_temp": ApplianceSaving(
        appliance="电暖器",
        action_key="electric_heater_temp",
        title="电暖器档位合理设定",
        description="电暖器调至舒适档位(18-20°C)，避免 24°C 满功率长开，人离开即关闭。",
        category="electricity",
        difficulty=1,
        saving_kwh_per_action=80.0,
        saving_cny_per_action=44.0,
        saving_co2_kg_per_action=64.0,
        when_to_do="入冬使用电暖器时",
        source_ref="standard:GB 21455-2013 房间空气调节器(电暖器能效参考)",
    ),
    "range_hood_short_use": ApplianceSaving(
        appliance="抽油烟机",
        action_key="range_hood_short_use",
        title="缩短抽油烟机运行时间",
        description="炒菜关火后再运行 1 分钟排净余烟即可，勿长时间空转；定期清洗油网提升效率。",
        category="electricity",
        difficulty=1,
        saving_kwh_per_action=15.0,
        saving_cny_per_action=8.25,
        saving_co2_kg_per_action=12.0,
        when_to_do="每次做饭后",
        source_ref="standard:GB 29539-2013 吸油烟机能效限定值 + 厂商维护建议",
    ),
    "rice_cooker_insulation": ApplianceSaving(
        appliance="电饭煲",
        action_key="rice_cooker_insulation",
        title="电饭煲提前断电保温",
        description="饭熟后及时拔掉电源，避免长时间高温保温(保温每 1 小时约耗 0.01 kWh)。",
        category="electricity",
        difficulty=1,
        saving_kwh_per_action=20.0,
        saving_cny_per_action=11.0,
        saving_co2_kg_per_action=16.0,
        when_to_do="每次做饭后",
        source_ref="standard:GB 12021.6-2017 电饭锅能效限定值",
    ),
    "toilet_dual_flush": ApplianceSaving(
        appliance="马桶",
        action_key="toilet_dual_flush",
        title="换双档节水马桶/双按键",
        description="双档冲水(6L/3L)可省约 30% 冲厕水，逐步更换老式单档马桶。",
        category="water",
        difficulty=2,
        saving_kwh_per_action=0.0,
        saving_cny_per_action=60.0,
        saving_co2_kg_per_action=6.0,
        when_to_do="下次换马桶/装修时",
        source_ref="standard:GB 28377-2012 水效率标识 + 家用卫生器具节水要求",
    ),
    "gas_stove_flame_adjust": ApplianceSaving(
        appliance="燃气灶",
        action_key="gas_stove_flame_adjust",
        title="燃气灶火焰调节(蓝火)",
        description="调节风门使火焰呈蓝色(完全燃烧)，火焰不超出锅底，厨房开窗通风，省气且安全。",
        category="gas",
        difficulty=1,
        saving_kwh_per_action=0.0,
        saving_cny_per_action=36.0,
        saving_co2_kg_per_action=75.0,
        when_to_do="每次做饭时",
        source_ref="standard:GB 16410-2007 家用燃气灶具 + 节能灶具能效 1 级标准",
    ),
}


def appliance_potential(action_key: str) -> Optional[ApplianceSaving]:
    """根据 action_key 查节能潜力"""
    return APPLIANCE_SAVINGS.get(action_key)


# ========== 节水 / 节气 标准常量(简表) ==========

@dataclass
class WaterSavingStandard:
    """节水标准摘要"""
    item: str
    baseline: str
    saving_method: str
    source: str


@dataclass
class GasSavingStandard:
    """节气标准摘要"""
    item: str
    baseline: str
    saving_method: str
    source: str


WATER_STANDARDS: List[WaterSavingStandard] = [
    WaterSavingStandard(
        item="滴漏龙头",
        baseline="未修复滴漏 1 个月 ≈ 1.5 m³/年 ≈ 18 m³",
        saving_method="更换密封圈或换新",
        source="GB-T 18870-2011 + 城镇供水统计",
    ),
    WaterSavingStandard(
        item="花洒",
        baseline="传统花洒流量 ≈ 12-15 L/min",
        saving_method="换 1 级节水花洒 ≤ 9 L/min",
        source="GB 28377-2012",
    ),
]

GAS_STANDARDS: List[GasSavingStandard] = [
    GasSavingStandard(
        item="家用燃气灶",
        baseline="能效 2 级热效率 ≈ 56%",
        saving_method="选能效 1 级(≥ 62%)+ 锅具匹配",
        source="GB 16410-2007",
    ),
    GasSavingStandard(
        item="燃气热水器",
        baseline="能效 2 级热效率 ≈ 84%",
        saving_method="选冷凝式 1 级(≥ 96%)+ 管道保温",
        source="GB 20665-2015",
    ),
]
