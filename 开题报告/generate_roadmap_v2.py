# 绿色低碳智能体 - 开题报告技术路线图

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
import numpy as np

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'WenQuanYi Micro Hei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def create_proper_roadmap():
    fig, ax = plt.subplots(1, 1, figsize=(18, 14))
    ax.set_xlim(0, 18)
    ax.set_ylim(0, 14)
    ax.axis('off')
    ax.set_aspect('equal')

    # 颜色定义
    colors = {
        'phase1': '#3498DB',  # 需求分析 - 蓝色
        'phase2': '#2ECC71',  # 知识库构建 - 绿色
        'phase3': '#9B59B6',  # 智能体设计 - 紫色
        'phase4': '#E74C3C',  # 核心技术 - 红色
        'phase5': '#F39C12',  # 系统实现 - 橙色
        'arrow': '#34495E',   # 箭头颜色
        'bg': '#ECF0F1',      # 背景
        'white': '#FFFFFF',
    }

    # 标题
    ax.text(9, 13.5, '技术路线图', fontsize=24, fontweight='bold', ha='center', va='center', color='#2C3E50')
    ax.text(9, 12.9, 'Technical Roadmap - 基于消费者偏好建模的绿色智能体设计与实现', fontsize=11, ha='center', va='center', style='italic', color='#7F8C8D')

    # ===== 第一阶段：需求分析 =====
    phase1_y = 11.8
    phase1_width = 16
    ax.add_patch(FancyBboxPatch((1, phase1_y-0.6), phase1_width, 1.2,
                                boxstyle="round,pad=0.03,rounding_size=0.15",
                                facecolor=colors['phase1'], edgecolor='#2471A3', linewidth=2.5, alpha=0.9))
    ax.text(2.5, phase1_y, '一、需求分析', fontsize=14, fontweight='bold', ha='left', va='center', color='white')

    # 第一阶段子模块
    phase1_items = [
        ('用户调研', 4.5), ('场景分析', 6.8), ('功能需求', 9.1),
        ('非功能需求', 11.4), ('可行性分析', 13.7)
    ]
    for name, x in phase1_items:
        ax.add_patch(FancyBboxPatch((x-0.7, phase1_y-0.8), 1.4, 0.5,
                                    boxstyle="round,pad=0.02",
                                    facecolor='white', edgecolor='#2471A3', linewidth=1))
        ax.text(x, phase1_y-1.05, name, fontsize=8, ha='center', va='center', color='#2C3E50')

    # ===== 第二阶段：知识库构建 =====
    phase2_y = 10.0
    ax.add_patch(FancyBboxPatch((1, phase2_y-0.6), phase1_width, 1.2,
                                boxstyle="round,pad=0.03,rounding_size=0.15",
                                facecolor=colors['phase2'], edgecolor='#239B56', linewidth=2.5, alpha=0.9))
    ax.text(2.5, phase2_y, '二、知识库构建', fontsize=14, fontweight='bold', ha='left', va='center', color='white')

    # 知识库分类
    kb_items = [
        ('基础知识库\n碳足迹/碳中和\n温室气体概念', 3.5),
        ('专业知识库\n绿色产品认证\n碳交易市场', 6.8),
        ('政策知识库\n国家政策/地方政策\n补贴激励', 10.1),
        ('实操指南库\n家庭节能/绿色出行\n企业减碳', 13.4)
    ]
    for name, x in kb_items:
        ax.add_patch(FancyBboxPatch((x-1.1, phase2_y-1.4), 2.2, 1.0,
                                    boxstyle="round,pad=0.02",
                                    facecolor='white', edgecolor='#239B56', linewidth=1))
        ax.text(x, phase2_y-0.9, name, fontsize=7, ha='center', va='center', color='#2C3E50')

    # ===== 第三阶段：智能体设计 =====
    phase3_y = 7.8
    ax.add_patch(FancyBboxPatch((1, phase3_y-0.6), phase1_width, 1.2,
                                boxstyle="round,pad=0.03,rounding_size=0.15",
                                facecolor=colors['phase3'], edgecolor='#7D3C98', linewidth=2.5, alpha=0.9))
    ax.text(2.5, phase3_y, '三、智能体设计', fontsize=14, fontweight='bold', ha='left', va='center', color='white')

    # 智能体设计模块
    agent_items = [
        ('用户意图理解\n查询/建议/行动/反馈\n实体/情感/紧急度', 3.5),
        ('对话策略管理\nPrompt动态调整\n行为推动策略', 7.0),
        ('响应生成器\n多源信息融合\n风格适配', 10.5),
        ('动作执行\n知识检索\n推荐生成', 14.0)
    ]
    for name, x in agent_items:
        ax.add_patch(FancyBboxPatch((x-1.2, phase3_y-1.4), 2.4, 1.0,
                                    boxstyle="round,pad=0.02",
                                    facecolor='white', edgecolor='#7D3C98', linewidth=1))
        ax.text(x, phase3_y-0.9, name, fontsize=7, ha='center', va='center', color='#2C3E50')

    # ===== 第四阶段：核心技术 =====
    phase4_y = 5.6
    ax.add_patch(FancyBboxPatch((1, phase4_y-0.6), phase1_width, 1.2,
                                boxstyle="round,pad=0.03,rounding_size=0.15",
                                facecolor=colors['phase4'], edgecolor='#C0392B', linewidth=2.5, alpha=0.9))
    ax.text(2.5, phase4_y, '四、核心技术', fontsize=14, fontweight='bold', ha='left', va='center', color='white')

    # 核心技术模块
    tech_items = [
        ('RAG检索增强\n向量数据库\n混合检索', 3.0),
        ('用户画像建模\n环保认知/行为阶段\n偏好学习', 6.3),
        ('个性化推荐\n行为阶段策略\n收入水平调整', 9.6),
        ('长短期记忆\nMemGPT思想\n工作记忆', 12.9)
    ]
    for name, x in tech_items:
        ax.add_patch(FancyBboxPatch((x-1.1, phase4_y-1.4), 2.2, 1.0,
                                    boxstyle="round,pad=0.02",
                                    facecolor='white', edgecolor='#C0392B', linewidth=1))
        ax.text(x, phase4_y-0.9, name, fontsize=7, ha='center', va='center', color='#2C3E50')

    # ===== 第五阶段：系统实现 =====
    phase5_y = 3.4
    ax.add_patch(FancyBboxPatch((1, phase5_y-0.6), phase1_width, 1.2,
                                boxstyle="round,pad=0.03,rounding_size=0.15",
                                facecolor=colors['phase5'], edgecolor='#D68910', linewidth=2.5, alpha=0.9))
    ax.text(2.5, phase5_y, '五、系统实现', fontsize=14, fontweight='bold', ha='left', va='center', color='white')

    # 系统实现模块
    impl_items = [
        ('前端开发\nWeb界面\n用户引导', 3.5),
        ('后端服务\nFastAPI\nHTTP服务', 6.5),
        ('数据库\nSQLite/ChromaDB\n向量存储', 9.5),
        ('API接口\n对话/画像/推荐\n政策更新', 12.5)
    ]
    for name, x in impl_items:
        ax.add_patch(FancyBboxPatch((x-1.0, phase5_y-1.4), 2.0, 1.0,
                                    boxstyle="round,pad=0.02",
                                    facecolor='white', edgecolor='#D68910', linewidth=1))
        ax.text(x, phase5_y-0.9, name, fontsize=7, ha='center', va='center', color='#2C3E50')

    # ===== 底层技术栈 =====
    tech_stack_y = 1.6
    ax.add_patch(FancyBboxPatch((1, tech_stack_y-0.5), phase1_width, 0.9,
                                boxstyle="round,pad=0.03,rounding_size=0.1",
                                facecolor='#D5DBDB', edgecolor='#717D7E', linewidth=2))
    ax.text(2.5, tech_stack_y, '技术栈', fontsize=12, fontweight='bold', ha='left', va='center', color='#2C3E50')

    tech_stack = [
        ('Python 3.10+', 3.5), ('FastAPI', 5.5), ('SQLite', 7.5),
        ('ChromaDB', 9.5), ('sentence-transformers', 12.5), ('OpenAI API兼容', 15.5)
    ]
    for name, x in tech_stack:
        ax.add_patch(Rectangle((x-0.8, tech_stack_y-0.6), 1.6, 0.35,
                               facecolor='white', edgecolor='#717D7E', linewidth=0.5))
        ax.text(x, tech_stack_y-0.42, name, fontsize=7, ha='center', va='center', color='#2C3E50')

    # ===== 箭头连接 - 阶段间连接 =====
    arrow_y_positions = [phase1_y - 0.6, phase2_y - 0.6, phase3_y - 0.6, phase4_y - 0.6, phase5_y - 0.6]
    for i in range(len(arrow_y_positions) - 1):
        start_y = arrow_y_positions[i]
        end_y = arrow_y_positions[i + 1]
        # 画连接箭头
        for x in [5, 9, 13]:
            ax.annotate('', xy=(x, end_y), xytext=(x, start_y),
                       arrowprops=dict(arrowstyle='->', color=colors['arrow'], lw=1.5))

    # ===== 阶段间水平连接线 =====
    for y_pos in arrow_y_positions[1:4]:
        for x in [3.5, 6.5, 9.5, 12.5]:
            ax.plot([x, x], [y_pos - 0.8, y_pos - 0.6], color=colors['arrow'], lw=1, alpha=0.5)

    # ===== 箭头标注 =====
    ax.annotate('', xy=(16.5, arrow_y_positions[0]-0.6), xytext=(16.5, arrow_y_positions[1]-0.6),
               arrowprops=dict(arrowstyle='->', color=colors['arrow'], lw=2))
    ax.text(17.0, (arrow_y_positions[0] + arrow_y_positions[1])/2 - 0.3, '进行中',
           fontsize=8, ha='left', va='center', color='#7F8C8D')

    # ===== 图例 =====
    legend_y = 0.7
    legend_items = [
        (colors['phase1'], '需求分析'),
        (colors['phase2'], '知识库构建'),
        (colors['phase3'], '智能体设计'),
        (colors['phase4'], '核心技术'),
        (colors['phase5'], '系统实现'),
    ]
    for i, (color, label) in enumerate(legend_items):
        x_pos = 2 + i * 3.2
        ax.add_patch(Rectangle((x_pos, legend_y-0.15), 0.4, 0.25, facecolor=color, edgecolor='#555'))
        ax.text(x_pos + 0.5, legend_y-0.02, label, fontsize=9, va='center', color='#2C3E50')

    plt.tight_layout()
    return fig

if __name__ == "__main__":
    print("正在生成技术路线图...")
    fig = create_proper_roadmap()
    output_path = r"d:\绿色低碳智能体\开题报告\技术路线图_v2.png"
    fig.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white', edgecolor='none')
    print(f"技术路线图已保存至: {output_path}")
    plt.close()
