# RAG 检索质量评估报告 — subset=curated

- 集合: `green_agent_knowledge`
- 总 query 数: **33**

## 总体指标

| 指标 | 值 |
|---|---|
| hit_rate@5 | 0.7273 |
| mrr@10 | 0.5591 |
| ndcg@10 | 0.6484 |

## 分类 hit_rate@5

| 类目 | hit_rate@5 |
|---|---|
| 碳交易 | 1.0000 |
| 出行 | 1.0000 |
| 认证 | 1.0000 |
| 适应气候变化 | 1.0000 |
| CCER | 0.6667 |
| 政策 | 0.6667 |
| 垃圾分类 | 0.6667 |
| 省级低碳 | 0.6000 |
| 补贴 | 0.5000 |
| 碳足迹 | 0.3333 |

## 未命中明细(9 条)

- **query**: `国家核证自愿减排量新方法学`  (类目: CCER)
  - 期望 slug: `2025_ccer_methodology_expansion`
  - top-3 实际: ['0253_中华人民共和国国家发展和改革委员会', '中国碳排放交易网_更新_20260614_180502', '中国碳排放交易网_更新_20260614_180502']
- **query**: `发电行业核查工作要求`  (类目: 政策)
  - 期望 slug: `2026_power_sector_carbon_guide_update`
  - top-3 实际: ['0256_国家能源局', '0224_经济·科技--人民网', '0222_中国能源网-中国能源报社官网']
- **query**: `厨余垃圾处理方法`  (类目: 垃圾分类)
  - 期望 slug: `daily_living`
  - top-3 实际: ['2025_ccer_methodology_expansion', '0224_经济·科技--人民网', 'guangdong_low_carbon']
- **query**: `碳足迹数据库管理指引`  (类目: 碳足迹)
  - 期望 slug: `2025_carbon_footprint_db_guideline`
  - top-3 实际: ['2026_national_carbon_market_notice', 'national_policy', 'carbon_footprint_standard']
- **query**: `温室气体排放因子数据库 v2`  (类目: 碳足迹)
  - 期望 slug: `2026_ghg_emission_factor_db_v2`
  - top-3 实际: ['green_certification', '0233_应对气候变化_中华人民共和国生态环境部', 'beijing_low_carbon']
- **query**: `北京市低碳行动方案`  (类目: 省级低碳)
  - 期望 slug: `beijing_low_carbon`
  - top-3 实际: ['beijing_2026_low_carbon_call', 'guangdong_low_carbon', 'shenzhen_low_carbon']
- **query**: `广东省低碳发展规划`  (类目: 省级低碳)
  - 期望 slug: `guangdong_low_carbon`
  - top-3 实际: ['beijing_2026_low_carbon_call', '中国碳排放交易网_更新_20260614_180502', '2024_2025_subsidies']
- **query**: `家电换新补贴申领流程`  (类目: 补贴)
  - 期望 slug: `2024_2025_subsidies`
  - top-3 实际: ['beijing_low_carbon', 'national_policy', 'shanghai_low_carbon']
- **query**: `节能补贴申请条件`  (类目: 补贴)
  - 期望 slug: `2024_2025_subsidies`
  - top-3 实际: ['beijing_low_carbon', 'national_policy', 'shanghai_low_carbon']