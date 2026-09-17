"""Versioned electricity emission factors published by China's MEE and NBS."""

from dataclasses import dataclass
from typing import Optional


SOURCE_URL = "https://www.mee.gov.cn/xxgk2018/xxgk/xxgk01/202512/W020251231726284332528.pdf"
REPORTING_YEAR = 2023
PUBLISHED_AT = "2025-12-31"


@dataclass(frozen=True)
class ElectricityFactor:
    geography: str
    kg_co2_per_kwh: float
    reporting_year: int = REPORTING_YEAR
    source_url: str = SOURCE_URL
    publisher: str = "生态环境部、国家统计局"


PROVINCE_FACTORS = {
    "全国": 0.5306, "北京": 0.5554, "天津": 0.6796, "河北": 0.6516,
    "山西": 0.6634, "内蒙古": 0.6479, "辽宁": 0.4878, "吉林": 0.4671,
    "黑龙江": 0.5229, "上海": 0.5737, "江苏": 0.5827, "浙江": 0.4974,
    "安徽": 0.6553, "福建": 0.4211, "江西": 0.5836, "山东": 0.6191,
    "河南": 0.5897, "湖北": 0.4044, "湖南": 0.4976, "广东": 0.4419,
    "广西": 0.4476, "海南": 0.3648, "重庆": 0.5581, "四川": 0.1564,
    "贵州": 0.5683, "云南": 0.1333, "陕西": 0.6335, "甘肃": 0.4471,
    "青海": 0.1796, "宁夏": 0.6187, "新疆": 0.6021,
}

CITY_TO_PROVINCE = {
    "北京": "北京", "beijing": "北京",
    "上海": "上海", "shanghai": "上海",
    "广州": "广东", "guangzhou": "广东",
    "深圳": "广东", "shenzhen": "广东",
    "杭州": "浙江", "hangzhou": "浙江",
    "南京": "江苏", "nanjing": "江苏",
    "成都": "四川", "chengdu": "四川",
    "重庆": "重庆", "chongqing": "重庆",
    "武汉": "湖北", "wuhan": "湖北",
    "长沙": "湖南", "changsha": "湖南",
    "西安": "陕西", "xian": "陕西",
    "天津": "天津", "tianjin": "天津",
    "郑州": "河南", "zhengzhou": "河南",
    "青岛": "山东", "qingdao": "山东",
    "济南": "山东", "jinan": "山东",
}


def electricity_factor_for(city_or_province: Optional[str]) -> ElectricityFactor:
    raw = (city_or_province or "").strip()
    geography = CITY_TO_PROVINCE.get(raw, raw)
    if geography not in PROVINCE_FACTORS:
        geography = "全国"
    return ElectricityFactor(geography, PROVINCE_FACTORS[geography])
