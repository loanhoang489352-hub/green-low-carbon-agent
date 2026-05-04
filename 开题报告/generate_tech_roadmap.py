# 绿色低碳智能体技术路线图生成脚本

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'WenQuanYi Micro Hei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def create_tech_roadmap():
    fig, ax = plt.subplots(1, 1, figsize=(20, 14))
    ax.set_xlim(0, 20)
    ax.set_ylim(0, 14)
    ax.axis('off')
    ax.set_aspect('equal')

    # 颜色定义
    colors = {
        'user': '#4ECDC4',       # 用户层 - 青色
        'interface': '#45B7D1', # 接口层 - 天蓝
        'core': '#96CEB4',       # 核心层 - 浅绿
        'personalization': '#FFEAA7',  # 个性化 - 浅黄
        'rag': '#DDA0DD',        # RAG层 - 紫色
        'memory': '#98D8C8',     # 记忆层 - 薄荷
        'llm': '#F7DC6F',        # LLM层 - 金色
        'data': '#BB8FCE',       # 数据层 - 薰衣草
        'arrow': '#555555'       # 箭头
    }

    # 标题
    ax.text(10, 13.5, '绿色低碳智能体技术路线图', fontsize=22, fontweight='bold',
            ha='center', va='center', color='#2C3E50')
    ax.text(10, 12.9, 'Green Low-Carbon Agent Technical Roadmap', fontsize=12,
            ha='center', va='center', style='italic', color='#7F8C8D')

    # ===== 第一层：用户交互层 =====
    layer1_y = 11.5
    ax.add_patch(FancyBboxPatch((0.5, layer1_y-0.4), 19, 0.8,
                                boxstyle="round,pad=0.05,rounding_size=0.1",
                                facecolor=colors['user'], edgecolor='#27AE60', linewidth=2, alpha=0.9))
    ax.text(10, layer1_y, '用户交互层 (User Interface)', fontsize=14, fontweight='bold',
            ha='center', va='center', color='white')

    # 子模块
    sub_modules1 = [
        ('Web前端', 2.5), ('HTTP API', 5.5), ('移动端', 8.5), ('命令行', 11.5), ('微信小程序', 14.5), ('钉钉/飞书', 17.5)
    ]
    for name, x in sub_modules1:
        ax.add_patch(FancyBboxPatch((x-0.8, layer1_y-0.9), 1.6, 0.5,
                                    boxstyle="round,pad=0.02",
                                    facecolor='white', edgecolor='#27AE60', linewidth=1))
        ax.text(x, layer1_y-0.65, name, fontsize=9, ha='center', va='center', color='#2C3E50')

    # ===== 第二层：接口适配层 =====
    layer2_y = 9.5
    ax.add_patch(FancyBboxPatch((0.5, layer2_y-0.4), 19, 0.8,
                                boxstyle="round,pad=0.05,rounding_size=0.1",
                                facecolor=colors['interface'], edgecolor='#2980B9', linewidth=2, alpha=0.9))
    ax.text(10, layer2_y, '接口适配层 (Interface Adapter)', fontsize=14, fontweight='bold',
            ha='center', va='center', color='white')

    sub_modules2 = [
        ('请求路由', 3.5), ('参数校验', 7), ('会话管理', 10.5), ('限流熔断', 14), ('日志记录', 17.5)
    ]
    for name, x in sub_modules2:
        ax.add_patch(FancyBboxPatch((x-0.8, layer2_y-0.9), 1.6, 0.5,
                                    boxstyle="round,pad=0.02",
                                    facecolor='white', edgecolor='#2980B9', linewidth=1))
        ax.text(x, layer2_y-0.65, name, fontsize=9, ha='center', va='center', color='#2C3E50')

    # ===== 第三层：核心智能体引擎 =====
    layer3_y = 7.5
    ax.add_patch(FancyBboxPatch((2, layer3_y-0.5), 16, 1,
                                boxstyle="round,pad=0.05,rounding_size=0.15",
                                facecolor=colors['core'], edgecolor='#27AE60', linewidth=3, alpha=0.95))
    ax.text(10, layer3_y+0.2, '核心智能体引擎 (Core Agent Engine)', fontsize=15, fontweight='bold',
            ha='center', va='center', color='#1E8449')

    # 核心子模块 - 意图识别
    core_modules = [
        ('意图识别\nIntent Recognition', 3.5, ['关键词匹配', '模式识别', '置信度计算']),
        ('对话管理\nDialogue Management', 7.5, ['多轮对话', '上下文跟踪', '状态维护']),
        ('响应生成\nResponse Generation', 11.5, ['模板生成', 'LLM增强', '知识注入']),
        ('动作执行\nAction Execution', 15.5, ['知识检索', '推荐生成', '数据更新'])
    ]
    for name, x, details in core_modules:
        ax.add_patch(FancyBboxPatch((x-1.2, layer3_y-1.5), 2.4, 1.0,
                                    boxstyle="round,pad=0.02",
                                    facecolor='white', edgecolor='#1E8449', linewidth=1.5))
        ax.text(x, layer3_y-1.0, name, fontsize=9, ha='center', va='center', color='#2C3E50', fontweight='bold')

    # ===== 第四层：个性化系统 =====
    layer4_y = 4.5
    ax.add_patch(FancyBboxPatch((1, layer4_y-0.5), 18, 1,
                                boxstyle="round,pad=0.05,rounding_size=0.15",
                                facecolor=colors['personalization'], edgecolor='#F39C12', linewidth=3, alpha=0.95))
    ax.text(10, layer4_y+0.2, '个性化系统 (Personalization System)', fontsize=14, fontweight='bold',
            ha='center', va='center', color='#9A7D0A')

    # 个性化子模块
    perso_modules = [
        ('用户画像\nUser Profile', 3, ['基础信息', '环保认知', '行为阶段', '兴趣偏好']),
        ('画像更新\nDynamic Updater', 7, ['实时分析', '兴趣挖掘', '阶段识别']),
        ('推荐引擎\nRecommendation', 11, ['行为推荐', '碳排放估算', '难易评估']),
        ('引导系统\nOnboarding', 15, ['初始采集', '偏好确认', '画像完善'])
    ]
    for name, x, features in perso_modules:
        ax.add_patch(FancyBboxPatch((x-1.3, layer4_y-1.5), 2.6, 1.0,
                                    boxstyle="round,pad=0.02",
                                    facecolor='white', edgecolor='#F39C12', linewidth=1.5))
        ax.text(x, layer4_y-1.0, name, fontsize=8, ha='center', va='center', color='#2C3E50', fontweight='bold')

    # ===== 第五层：RAG系统 =====
    layer5_y = 2.5
    ax.add_patch(FancyBboxPatch((1.5, layer5_y-0.5), 17, 1,
                                boxstyle="round,pad=0.05,rounding_size=0.15",
                                facecolor=colors['rag'], edgecolor='#8E44AD', linewidth=3, alpha=0.95))
    ax.text(10, layer5_y+0.2, 'RAG增强系统 (Retrieval-Augmented Generation)', fontsize=14, fontweight='bold',
            ha='center', va='center', color='#6C3483')

    # RAG子模块
    rag_modules = [
        ('知识库管理\nKnowledge Manager', 3.5, ['文档解析', '分类存储', '版本管理']),
        ('向量化\nEmbedder', 7.5, ['多语言模型', '语义编码', '维度统一']),
        ('向量存储\nVector Store', 11.5, ['ChromaDB', '相似度检索', '高效索引']),
        ('混合检索\nHybrid Retriever', 15.5, ['语义检索', 'BM25', '重排序'])
    ]
    for name, x, features in rag_modules:
        ax.add_patch(FancyBboxPatch((x-1.2, layer5_y-1.5), 2.4, 1.0,
                                    boxstyle="round,pad=0.02",
                                    facecolor='white', edgecolor='#8E44AD', linewidth=1.5))
        ax.text(x, layer5_y-1.0, name, fontsize=8, ha='center', va='center', color='#2C3E50', fontweight='bold')

    # ===== 底层：记忆系统 & LLM调用 =====
    bottom_y = 0.8

    # 记忆系统
    ax.add_patch(FancyBboxPatch((0.5, bottom_y-0.3), 6, 0.6,
                                boxstyle="round,pad=0.03,rounding_size=0.1",
                                facecolor=colors['memory'], edgecolor='#16A085', linewidth=2))
    ax.text(3.5, bottom_y, '记忆系统 Memory', fontsize=11, fontweight='bold',
            ha='center', va='center', color='white')
    ax.text(1.5, bottom_y-0.7, '短期记忆\nSQLite', fontsize=8, ha='center', va='center')
    ax.text(5.5, bottom_y-0.7, '长期记忆\n偏好学习', fontsize=8, ha='center', va='center')

    # LLM调用
    ax.add_patch(FancyBboxPatch((7.5, bottom_y-0.3), 12, 0.6,
                                boxstyle="round,pad=0.03,rounding_size=0.1",
                                facecolor=colors['llm'], edgecolor='#D4AC0D', linewidth=2))
    ax.text(13.5, bottom_y, 'LLM大模型调用层 LLM Integration', fontsize=11, fontweight='bold',
            ha='center', va='center', color='#7D6608')
    llm_providers = ['OpenAI', '智谱GLM', '文心一言', '通义千问', 'MiniMax', 'DeepSeek']
    llm_x = [9, 10.5, 12, 13.5, 15, 16.5]
    for name, x in zip(llm_providers, llm_x):
        ax.text(x, bottom_y-0.7, name, fontsize=7, ha='center', va='center', color='#2C3E50')

    # ===== 箭头连接 =====
    # 第一层到第二层
    for x in [2.5, 5.5, 8.5, 11.5, 14.5, 17.5]:
        ax.annotate('', xy=(x, layer2_y-0.4), xytext=(x, layer1_y-0.4),
                   arrowprops=dict(arrowstyle='->', color=colors['arrow'], lw=1.5))

    # 第二层到第三层
    for x in [3.5, 7, 10.5, 14, 17.5]:
        ax.annotate('', xy=(x, layer3_y-0.5), xytext=(x, layer2_y-0.4),
                   arrowprops=dict(arrowstyle='->', color=colors['arrow'], lw=1.5))

    # 第三层到第四层
    for x in [3.5, 7.5, 11.5, 15.5]:
        ax.annotate('', xy=(x, layer4_y-0.5), xytext=(x, layer3_y-1.5),
                   arrowprops=dict(arrowstyle='->', color=colors['arrow'], lw=1.5))

    # 第四层到第五层
    for x in [3, 7, 11, 15]:
        ax.annotate('', xy=(x+0.5, layer5_y-0.5), xytext=(x, layer4_y-1.5),
                   arrowprops=dict(arrowstyle='->', color=colors['arrow'], lw=1.5))

    # 第四层到记忆
    ax.annotate('', xy=(3.5, bottom_y+0.3), xytext=(3.5, layer4_y-1.5),
               arrowprops=dict(arrowstyle='->', color=colors['arrow'], lw=1, ls='--'))

    # 第三层到LLM
    ax.annotate('', xy=(13.5, bottom_y+0.3), xytext=(11.5, layer3_y-1.5),
               arrowprops=dict(arrowstyle='->', color=colors['arrow'], lw=1, ls='--'))

    # ===== 数据流向标注 =====
    ax.text(19.5, 8, '数据\n流向', fontsize=9, ha='center', va='center',
            bbox=dict(boxstyle='round', facecolor='#ECF0F1', edgecolor='#BDC3C7'))
    ax.annotate('', xy=(19.5, 9.3), xytext=(19.5, 6.7),
               arrowprops=dict(arrowstyle='->', color='#E74C3C', lw=2))

    # ===== 图例 =====
    legend_y = 0.1
    ax.text(0.5, legend_y, '图例 Legend:', fontsize=9, fontweight='bold', color='#2C3E50')

    legend_items = [
        (colors['user'], '用户交互'),
        (colors['interface'], '接口适配'),
        (colors['core'], '核心引擎'),
        (colors['personalization'], '个性化'),
        (colors['rag'], 'RAG系统'),
        (colors['memory'], '记忆系统'),
        (colors['llm'], 'LLM调用'),
    ]
    for i, (color, label) in enumerate(legend_items):
        x_pos = 3 + i * 2.4
        ax.add_patch(plt.Rectangle((x_pos, legend_y-0.15), 0.3, 0.2,
                                   facecolor=color, edgecolor='#555', linewidth=0.5))
        ax.text(x_pos + 0.4, legend_y-0.05, label, fontsize=8, va='center', color='#2C3E50')

    # ===== 技术栈标注 =====
    tech_stack = "技术栈 | Tech Stack: Python 3.10+ | Flask/FastAPI | SQLite | sentence-transformers | ChromaDB | TensorFlow/PyTorch | OpenAI API兼容"
    ax.text(10, -0.3, tech_stack, fontsize=8, ha='center', va='center',
            style='italic', color='#7F8C8D')

    plt.tight_layout()
    return fig

if __name__ == "__main__":
    print("正在生成技术路线图...")
    fig = create_tech_roadmap()
    output_path = r"d:\绿色低碳智能体\开题报告\技术路线图.png"
    fig.savefig(output_path, dpi=300, bbox_inches='tight',
                facecolor='white', edgecolor='none')
    print(f"技术路线图已保存至: {output_path}")
    plt.close()
