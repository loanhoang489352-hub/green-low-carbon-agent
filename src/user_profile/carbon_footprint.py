"""
碳足迹计算器
基于用户行为计算CO2排放量
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json


@dataclass
class CarbonEmission:
    """碳排放记录"""
    category: str      # 出行/用电/饮食/消费/其他
    action: str        # 具体行为
    amount: float      # 排放量(kg CO2)
    unit: str         # 单位
    date: str          # 日期
    details: Dict[str, Any]  # 额外信息


class CarbonFootprintCalculator:
    """
    碳足迹计算器
    
    基于日常生活行为计算碳排放量
    支持：出行、用电、饮食、消费四大类别
    """
    
    # 碳排放因子 (单位：kg CO2)
    EMISSION_FACTORS = {
        # 出行 - 按公里
        "出行": {
            "私家车(汽油)": 0.21,      # kg CO2/km
            "私家车(柴油)": 0.17,
            "私家车(电动车)": 0.12,    # 含发电碳排放
            "出租车": 0.27,
            "网约车": 0.25,
            "摩托车": 0.14,
            "公交车": 0.08,           # 人均
            "地铁": 0.04,             # 人均
            "高铁": 0.04,             # 人均
            "飞机(国内)": 0.18,       # 人均/km
            "飞机(国际)": 0.15,
            "步行": 0.0,
            "骑行": 0.0,
        },
        # 用电 - 按度数
        "用电": {
            "照明": 0.6,              # kg CO2/kWh (中国平均)
            "空调": 0.6,
            "电视": 0.6,
            "冰箱": 0.6,
            "洗衣机": 0.6,
            "厨房电器": 0.6,
            "其他": 0.6,
        },
        # 饮食 - 按重量
        "饮食": {
            "牛肉": 27.0,             # kg CO2/kg
            "羊肉": 13.0,
            "猪肉": 7.0,
            "禽肉": 4.0,
            "鱼类": 3.0,
            "蛋类": 2.5,
            "奶制品": 3.2,
            "大米": 2.7,
            "面粉": 1.8,
            "蔬菜": 0.4,
            "水果": 0.5,
            "坚果": 1.0,
        },
        # 消费 - 按价格
        "消费": {
            "服装": 0.01,              # kg CO2/元
            "电子产品": 0.02,
            "日用品": 0.005,
            "书籍": 0.008,
            "家具": 0.015,
        },
    }
    
    # 替代行为碳减排量
    REDUCTION_ACTIONS = {
        "公共交通": {
            "替代": "私家车",
            "减排因子": 0.19,          # kg CO2/km
        },
        "步行/骑行": {
            "替代": "私家车", 
            "减排因子": 0.21,
        },
        "拼车": {
            "替代": "单独开车",
            "减排因子": 0.105,          # 50%减排
        },
        "素食一天": {
            "替代": "肉食",
            "减排因子": 2.0,           # 一天素食减排约2kg
        },
        "空调调低1度": {
            "替代": "高温度",
            "减排因子": 0.15,          # kg CO2/天
        },
        "随手关灯": {
            "替代": "忘记关灯",
            "减排因子": 0.3,           # kg CO2/天
        },
        "自带水杯": {
            "替代": "瓶装水",
            "减排因子": 0.05,           # kg CO2/天
        },
        "自带购物袋": {
            "替代": "塑料袋",
            "减排因子": 0.01,          # kg CO2/次
        },
        "双面打印": {
            "替代": "单面",
            "减排因子": 0.005,         # kg CO2/张
        },
    }
    
    def __init__(self):
        self.records: List[CarbonEmission] = []
        self.reduction_records: List[Dict] = []
    
    def calculate_travel_emission(self, distance: float, vehicle_type: str) -> float:
        """计算出行碳排放"""
        factors = self.EMISSION_FACTORS["出行"]
        factor = factors.get(vehicle_type, 0.2)
        return distance * factor
    
    def calculate_electricity_emission(self, kwh: float) -> float:
        """计算用电碳排放"""
        return kwh * 0.6  # 中国电网排放因子
    
    def calculate_diet_emission(self, food_type: str, weight: float) -> float:
        """计算饮食碳排放"""
        factors = self.EMISSION_FACTORS["饮食"]
        factor = factors.get(food_type, 1.0)
        return weight * factor
    
    def calculate_consumption_emission(self, category: str, cost: float) -> float:
        """计算消费碳排放"""
        factors = self.EMISSION_FACTORS["消费"]
        factor = factors.get(category, 0.01)
        return cost * factor
    
    def record_action(self, category: str, action: str, value: float, 
                 unit: str = "次", details: Dict = None) -> CarbonEmission:
        """记录行为并计算碳排放"""
        date = datetime.now().strftime("%Y-%m-%d")
        
        if category == "出行":
            emission = self.calculate_travel_emission(value, action)
        elif category == "用电":
            emission = self.calculate_electricity_emission(value)
        elif category == "饮食":
            emission = self.calculate_diet_emission(action, value)
        elif category == "消费":
            emission = self.calculate_consumption_emission(action, value)
        else:
            emission = 0.0
        
        record = CarbonEmission(
            category=category,
            action=action,
            amount=emission,
            unit=unit,
            date=date,
            details=details or {}
        )
        self.records.append(record)
        return record
    
    def record_reduction(self, action: str, value: float = 1.0) -> Dict:
        """记录低碳行为（减排量）"""
        reduction_info = self.REDUCTION_ACTIONS.get(action, {})
        减排量 = value * reduction_info.get("减排因子", 0)
        
        record = {
            "action": action,
            "value": value,
            "减排量": 减排量,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "替代行为": reduction_info.get("替代", "")
        }
        self.reduction_records.append(record)
        return record
    
    def get_total_emission(self, days: int = 30) -> float:
        """获取近N天总排放量"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        total = sum(r.amount for r in self.records if r.date >= cutoff)
        return total
    
    def get_total_reduction(self, days: int = 30) -> float:
        """获取近N天总减排量"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        total = sum(r.get("减排量", 0) for r in self.reduction_records if r["date"] >= cutoff)
        return total
    
    def get_category_breakdown(self, days: int = 30) -> Dict[str, float]:
        """获取分类排放统计"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        breakdown = {}
        for r in self.records:
            if r.date >= cutoff:
                breakdown[r.category] = breakdown.get(r.category, 0) + r.amount
        return breakdown
    
    def get_monthly_report(self) -> Dict[str, Any]:
        """月度碳足迹报告"""
        total = self.get_total_emission(30)
        reduction = self.get_total_reduction(30)
        breakdown = self.get_category_breakdown(30)
        
        # 计算全国人均对比
        # 中国人均月排放约60kg CO2
        national_avg = 60.0
        comparison = (total - national_avg) / national_avg * 100
        
        return {
            "period": "近30天",
            "总排放_kg_CO2": round(total, 2),
            "总减排_kg_CO2": round(reduction, 2),
            "净排放_kg_CO2": round(total - reduction, 2),
            "分类排放": breakdown,
            "对比全国平均": f"{comparison:+.1f}%" if comparison != 0 else "持平",
            "评级": self._get_grade(total - reduction)
        }
    
    def _get_grade(self, net_emission: float) -> str:
        """碳足迹评级"""
        if net_emission < 30:
            return "A+ 优秀"
        elif net_emission < 45:
            return "A 良好"
        elif net_emission < 60:
            return "B 一般"
        elif net_emission < 80:
            return "C 需改进"
        else:
            return "D 需关注"
    
    def get_suggestions(self) -> List[Dict[str, str]]:
        """根据当前排放情况生成改进建议"""
        breakdown = self.get_category_breakdown(30)
        suggestions = []
        
        # 基于高排放类别推荐
        if breakdown.get("出行", 0) > 20:
            suggestions.append({
                "category": "出行",
                "action": "每周1天公共交通",
                "减排潜力": "~5kg CO2/周",
                "difficulty": "easy"
            })
        if breakdown.get("饮食", 0) > 15:
            suggestions.append({
                "category": "饮食", 
                "action": "每周1天素食",
                "减排潜力": "~8kg CO2/周",
                "difficulty": "medium"
            })
        if breakdown.get("用电", 0) > 10:
            suggestions.append({
                "category": "用电",
                "action": "空调调低1度+随手关灯",
                "减排潜力": "~3kg CO2/周",
                "difficulty": "easy"
            })
            
        return suggestions
    
    @classmethod
    def get_available_actions(cls) -> Dict[str, List[str]]:
        """获取可记录的行为类型"""
        return {
            category: list(actions.keys()) 
            for category, actions in cls.EMISSION_FACTORS.items()
        }
    
    @classmethod
    def get_reduction_actions(cls) -> Dict[str, str]:
        """获取可记录的低碳行为"""
        return {k: v["替代"] for k, v in cls.REDUCTION_ACTIONS.items()}