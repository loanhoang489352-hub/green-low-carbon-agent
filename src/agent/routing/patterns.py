"""路由相关的领域关键词正则(状态机与路由器共用)。"""
import re

ENERGY = r'家庭节能|节能方案|节能规划|节水|节电|省电|电费|水费|燃气费|家里.*节能'
TRAVEL = r'路线|导航|怎么走|如何去|怎么去|从.+到|通勤|出行规划'
EXPLAIN = r'什么是|是什么|为什么|为何|原理|含义|怎么算|如何计算|怎么计算|有什么区别'
NEGATIVE_PLAN = r'(?:不需要|不要|不用|不想)(?:再|给我)?(?:做|制定|生成)?(?:家庭)?(?:节能|出行)?(?:方案|规划|计划)'
PLAN = r'制定|帮我|规划|计划|怎么省|如何省|怎么节|如何节|建议|降低|减少|省点|太高|太贵'


def domain_of(text):
    if re.search(ENERGY, text):
        return 'energy'
    if re.search(TRAVEL, text):
        return 'travel'
    return 'general'


def planning_intent(domain):
    return 'energy_planning' if domain == 'energy' else 'travel_planning'
