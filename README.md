# 绿色低碳智能体

基于消费者偏好建模的绿色智能体设计与实现

## 项目概述

这是一个可投入使用的绿色低碳智能体，具备以下核心功能：

- **垂类知识库**：接入绿色低碳专业知识，支持实时检索
- **长短期记忆**：记住用户风格和偏好，提供个性化建议
- **用户画像**：基于环保认知水平、行为阶段等维度构建用户画像
- **政策更新**：定时更新低碳政策，确保信息时效性
- **个性化推荐**：根据用户特点提供定制化的低碳行动建议

## 系统架构

```
用户交互层
    ↓
智能体核心引擎 (意图理解 → 对话策略 → 响应生成)
    ↓
┌─────────────┬──────────────┬──────────────┐
│  知识库系统  │   记忆系统    │  用户画像    │
│ (向量检索)  │ (长短期)     │  (个性化)    │
└─────────────┴──────────────┴──────────────┘
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行智能体

**Web界面模式（推荐）**：
```bash
cd src
python main.py
```
然后在浏览器打开 http://localhost:8000

**命令行模式**：
```bash
cd src
python main.py --cli
```

### 3. 运行测试

```bash
cd tests
python test_agent.py
```

## 目录结构

```
绿色低碳智能体/
├── SPEC.md              # 系统设计规范
├── README.md            # 项目说明
├── requirements.txt     # Python依赖
├── config/
│   └── settings.yaml    # 配置文件
├── src/
│   ├── main.py          # 应用入口
│   ├── agent/           # 智能体核心
│   │   ├── core.py      # 核心引擎
│   │   ├── intent.py    # 意图识别
│   │   └── response.py  # 响应生成
│   ├── knowledge/       # 知识库
│   │   └── manager.py
│   ├── memory/          # 记忆系统
│   │   ├── short_term.py
│   │   └── long_term.py
│   ├── profile/         # 用户画像
│   │   └── user_profile.py
│   └── policy/          # 政策更新
│       └── updater.py
├── knowledge_base/      # 知识库文件
│   ├── basic/          # 基础知识
│   ├── policy/         # 政策知识
│   └── guide/          # 实操指南
├── web/
│   └── index.html      # Web界面
└── tests/
    └── test_agent.py   # 测试脚本
```

## 核心模块说明

### 1. 意图识别 (`agent/intent.py`)

基于规则的轻量级意图识别：
- 知识查询
- 建议请求
- 行动报告
- 反馈
- 问候

### 2. 知识库 (`knowledge/`)

支持Markdown格式的知识文档存储和检索：
- 自动加载 `knowledge_base/` 目录下的文档
- 基于关键词匹配的检索
- 分类管理（basic/policy/guide）

### 3. 记忆系统 (`memory/`)

**短期记忆**：
- 会话级对话历史
- 工作记忆（最近N轮）
- 自动过期清理

**长期记忆**：
- SQLite持久化存储
- 用户偏好持久化
- 记忆检索

### 4. 用户画像 (`profile/`)

画像维度：
- 环保认知水平（入门/了解/精通）
- 行为阶段（无意向→意向→准备→行动→维持）
- 沟通风格（专业/通俗/数据驱动）
- 行动意愿（高/中/低）

### 5. 政策更新 (`policy/`)

- 政策数据库管理
- 示例政策数据
- 定时更新机制（可扩展）

## API接口

服务启动后可访问 http://localhost:8000/docs 查看完整API文档

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/chat` | POST | 发送对话消息 |
| `/api/profile/{user_id}` | GET | 获取用户画像 |
| `/api/knowledge/stats` | GET | 获取知识库统计 |
| `/api/policy/latest` | GET | 获取最新政策 |
| `/api/policy/summary` | GET | 获取政策摘要 |

## 扩展建议

### 接入大语言模型

修改 `config/settings.yaml` 中的LLM配置：

```yaml
llm:
  provider: "openai"  # 或 "local"
  model: "gpt-3.5-turbo"
  api_key: "${OPENAI_API_KEY}"
```

### 接入向量数据库

```bash
pip install chromadb sentence-transformers
```

修改配置启用向量检索。

### 添加更多知识

在 `knowledge_base/` 对应目录下添加Markdown文件即可。

## 毕设相关

本项目是为本科毕业设计"基于消费者偏好建模的绿色智能体设计与实现"开发的初版原型。

### 设计要点

1. **轻量级实现**：不依赖复杂的机器学习模型，采用规则+反馈驱动
2. **行为改变导向**：每次对话引导用户采取具体行动
3. **渐进式个性化**：随对话深入逐渐了解用户，提供更精准建议
4. **实时性保障**：预留政策更新机制

### 可改进方向

1. 接入LLM提升对话质量
2. 使用向量数据库实现语义检索
3. 增加用户行为追踪和分析
4. 完善政策爬虫和更新机制
5. 添加更多交互形式（微信小程序等）

## 许可证

MIT License
