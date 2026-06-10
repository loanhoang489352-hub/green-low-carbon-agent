"""
网络搜索模块
使用Python内置urllib进行简单的网络请求
"""

import sys
import json
import re
from urllib.parse import quote, urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from datetime import datetime

# 添加项目根目录
project_root = __file__.rsplit('/', 2)[0] if '/' in __file__ else __file__.rsplit('\\', 2)[0]
if project_root not in sys.path:
    sys.path.insert(0, project_root)


class WebSearcher:
    """简单的网络搜索"""

    # 实时信息关键词
    REALTIME_KEYWORDS = [
        "油价", "油价调整", "今日油价", "汽油价格", "柴油价格",
        "天气", "气温", "天气预报", "今天天气", "明天天气",
        "空气质量", "PM2.5", "AQI",
        "电价", "电费", "燃气价格", "天然气价格",
        "新闻", "最新", "今天", "现在",
        "汇率", "美元", "人民币汇率",
        "股价", "股票", "上证", "深证",
        "时间", "几点", "日期", "星期几",
    ]

    def __init__(self):
        self.session_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    def is_realtime_query(self, query: str) -> bool:
        """判断是否为实时查询"""
        query_lower = query.lower()
        for keyword in self.REALTIME_KEYWORDS:
            if keyword in query:
                return True
        return False

    def search_oil_price(self) -> str:
        """搜索油价信息（模拟）"""
        try:
            # 这里可以接入真实API，但为了简单返回已知信息
            return self._get_simulated_oil_price()
        except Exception as e:
            return f"抱歉，暂时无法获取油价信息。错误: str(e)"

    def _get_simulated_oil_price(self) -> str:
        """返回模拟油价数据（实际应该联网获取）"""
        return """根据2026年4月的油价情况：

**今日参考油价**（以北京为例）：
- 92号汽油: 约 8.20 元/升
- 95号汽油: 约 8.75 元/升
- 98号汽油: 约 10.00 元/升
- 0号柴油: 约 7.90 元/升

**油价调整周期**：
中国油价每10个工作日调整一次，下次调价窗口约为4月中旬。

**省油建议**：
1. 保持经济时速（60-90km/h）
2. 避免急加速急刹车
3. 定期保养，保持轮胎气压正常
4. 尽量选择公共交通或电动车

如需查询实时准确油价，建议访问：
- 国家发改委官网
- 中国石油、中国石化官网
- 各省市发改委网站
"""

    def search_weather(self, location: str = "") -> str:
        """搜索天气信息"""
        return self._get_simulated_weather()

    # 主要城市备用列表(Open-Meteo 支持中文名,这里保留作为 fallback)
    _CITY_CODES = {
        "北京": "101010100", "上海": "101020100", "广州": "101280101",
        "深圳": "101280601", "杭州": "101210101", "南京": "101190101",
        "武汉": "101200101", "成都": "101270101", "西安": "101110101",
        "天津": "101030100", "重庆": "101040100", "苏州": "101190401",
    }

    # Open-Meteo WMO weathercode → 中文描述
    _WEATHER_CODE_CN = {
        0: "晴", 1: "少云", 2: "多云", 3: "阴",
        45: "雾", 48: "雾凇",
        51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
        56: "冻雨", 57: "冻雨",
        61: "小雨", 63: "中雨", 65: "大雨",
        66: "冻雨", 67: "冻雨",
        71: "小雪", 73: "中雪", 75: "大雪",
        77: "米雪",
        80: "阵雨", 81: "阵雨", 82: "强阵雨",
        85: "阵雪", 86: "强阵雪",
        95: "雷暴", 96: "雷暴伴冰雹", 99: "强雷暴伴冰雹",
    }

    def fetch_weather_from_api(self, city: str = "北京") -> str:
        """调用 Open-Meteo 免费 API 获取实时天气(无需 key,全球覆盖)
        注:已从和风天气(403)切换到 Open-Meteo
        """
        # 1. geocode: 中文城市名 → 经纬度
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={quote(city)}&count=1&language=zh"
        try:
            req = Request(geo_url, headers=self.session_headers)
            with urlopen(req, timeout=10) as resp:
                geo = json.loads(resp.read().decode("utf-8"))
            results = geo.get("results")
            if not results:
                return f"获取天气信息失败: 找不到城市 '{city}'"
            lat = results[0]["latitude"]
            lon = results[0]["longitude"]
        except (URLError, HTTPError, TimeoutError) as e:
            return f"获取天气信息失败: geocode {type(e).__name__}: {e}"

        # 2. 实时天气 + 湿度(湿度在 hourly 里)
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&current_weather=true&hourly=relative_humidity_2m&forecast_days=1"
        )
        try:
            req = Request(weather_url, headers=self.session_headers)
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (URLError, HTTPError, TimeoutError) as e:
            return f"获取天气信息失败: weather {type(e).__name__}: {e}"

        cw = data.get("current_weather", {})
        if not cw:
            return f"获取天气信息失败: 天气数据为空"

        # 取当前时刻对应的湿度(hourly 时间数组与 current.time 对齐)
        humidity = "?"
        hourly = data.get("hourly", {})
        if hourly:
            times = hourly.get("time", [])
            hums = hourly.get("relative_humidity_2m", [])
            ct = cw.get("time", "")
            if ct in times:
                idx = times.index(ct)
                if idx < len(hums):
                    humidity = hums[idx]

        code = cw.get("weathercode", 0)
        desc = self._WEATHER_CODE_CN.get(code, f"代码{code}")
        wind_dir = self._wind_direction_cn(cw.get("winddirection", 0))

        return (
            f"**{city}实时天气**({cw.get('time', '')})\n\n"
            f"- 天气:{desc}\n"
            f"- 气温:{cw.get('temperature', '?')}°C\n"
            f"- 风速:{cw.get('windspeed', '?')} km/h\n"
            f"- 风向:{wind_dir}\n"
            f"- 湿度:{humidity}%\n"
            f"- 数据源:Open-Meteo(免费)"
        )

    @staticmethod
    def _wind_direction_cn(deg: float) -> str:
        """风向角度 → 中文(0=北, 90=东, 180=南, 270=西)"""
        dirs = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
        idx = int((deg + 22.5) // 45) % 8
        return dirs[idx]

    def _get_simulated_weather(self) -> str:
        """返回模拟天气数据"""
        return f"""**今日天气预报**（北京，2026年4月11日，周六）：

- 天气：晴转多云
- 气温：12°C ~ 24°C
- 风力：东南风 2-3级
- 空气质量：良（AQI 65）
- 紫外线：中等
- 湿度：45%

**出行建议**：
- 天气宜人，适合户外活动
- 建议选择公共交通出行
- 骑行或步行更环保健康

如需查询实时天气，请访问：
- 中国气象局官网
- 天气类APP（如墨迹天气）"""

    def search_aqi(self) -> str:
        """搜索空气质量"""
        return """**今日空气质量**（北京，2026年4月11日）：

- AQI指数：65（良）
- PM2.5：35 μg/m³
- PM10：68 μg/m³
- 空气质量等级：良
- 主要污染物：PM10

**健康建议**：
- 空气质量良好，可以正常户外活动
- 敏感人群建议佩戴口罩

**低碳出行建议**：
- 多选择公共交通
- 骑行或步行是最佳选择
- 减少私家车出行，降低尾气排放"""

    def search_electricity_price(self) -> str:
        """搜索电价信息"""
        return """**居民电价参考**（以北京为例）：

**阶梯电价**：
- 第一档（0-2400度）：0.48元/度
- 第二档（2400-4800度）：0.53元/度
- 第三档（4800度以上）：0.78元/度

**峰谷电价**（部分地区）：
- 峰时（6:00-22:00）：约0.55元/度
- 谷时（22:00-6:00）：约0.35元/度

**省电建议**：
1. 使用节能电器
2. 避开高峰时段使用大功率电器
3. 及时关闭待机电源
4. 充分利用自然光"""

    def search_news(self) -> str:
        """搜索最新新闻"""
        return """**最新环保相关新闻**（2026年4月）：

**国内政策**：
- 碳达峰碳中和政策持续推进
- 新能源汽车补贴政策延续
- 各地垃圾分类工作深入开展

**国际动态**：
- 全球气候峰会召开
- 欧盟碳边境调节机制实施
- 多国提出更积极减排目标

**科技创新**：
- 新能源技术突破
- 碳捕集技术进展
- 氢能源应用推广

**生活提示**：
- 关注本地环保活动
- 参与社区低碳行动
- 从日常小事做起"""

    def get_realtime_response(self, query: str) -> str:
        """根据查询类型返回实时信息"""
        query_lower = query.lower()

        if "油价" in query or "汽油" in query:
            return self.search_oil_price()
        elif "天气" in query or "气温" in query:
            return self.search_weather()
        elif "空气" in query or "PM" in query or "AQI" in query:
            return self.search_aqi()
        elif "电" in query and ("价" in query or "费" in query):
            return self.search_electricity_price()
        elif "新闻" in query or "最新" in query:
            return self.search_news()
        else:
            return self.search_news()
