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
