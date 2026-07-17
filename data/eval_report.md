# RAG 检索质量评估报告 — subset=full

- 集合: `green_agent_knowledge`
- 总 query 数: **51**

## 总体指标

| 指标 | 值 |
|---|---|
| hit_rate@5 | 0.6471 |
| mrr@10 | 0.5497 |
| ndcg@10 | 0.6057 |

## 分类 hit_rate@5

| 类目 | hit_rate@5 |
|---|---|
| 出行 | 1.0000 |
| 碳交易 | 0.8000 |
| 认证 | 0.8000 |
| 适应气候变化 | 0.8000 |
| CCER | 0.6000 |
| 政策 | 0.6000 |
| 碳足迹 | 0.6000 |
| 省级低碳 | 0.6000 |
| 补贴 | 0.5000 |
| 垃圾分类 | 0.2000 |

## 未命中明细(18 条)

- **query**: `碳配额分配与履约监管`  (类目: 碳交易)
  - 期望 slug: `2024_carbon_market_regulation`
  - top-3 实际: ['carbon_footprint_standard', '2026_national_carbon_market_notice', '2026_power_sector_carbon_guide_update']
- **query**: `国家核证自愿减排量新方法学`  (类目: CCER)
  - 期望 slug: `2025_ccer_methodology_expansion`
  - top-3 实际: ['0253_中华人民共和国国家发展和改革委员会', '0222_中国能源网-中国能源报社官网', '2026_national_carbon_market_notice']
- **query**: `自愿减排市场重启进展`  (类目: CCER)
  - 期望 slug: `2025_ccer_methodology_expansion`
  - top-3 实际: ['0250_经济参考网_-_新华社《经济参考报》官方网站', '0243_界面新闻-只服务于独立思考的人群-Jiemian.com', '0254_国家统计局']
- **query**: `发电行业核查工作要求`  (类目: 政策)
  - 期望 slug: `2026_power_sector_carbon_guide_update`
  - top-3 实际: ['0256_国家能源局', '0224_经济·科技--人民网', '0222_中国能源网-中国能源报社官网']
- **query**: `国家应对气候变化政策框架`  (类目: 政策)
  - 期望 slug: `national_policy`
  - top-3 实际: ['2023_china_climate_adaptation_progress', '0233_应对气候变化_中华人民共和国生态环境部', '2023_china_climate_adaptation_progress']
- **query**: `生活垃圾如何分类`  (类目: 垃圾分类)
  - 期望 slug: `daily_living`
  - top-3 实际: ['guangdong_low_carbon', 'shanghai_low_carbon', '2025_ccer_methodology_expansion']
- **query**: `厨余垃圾处理方法`  (类目: 垃圾分类)
  - 期望 slug: `daily_living`
  - top-3 实际: ['2025_ccer_methodology_expansion', '0224_经济·科技--人民网', 'guangdong_low_carbon']
- **query**: `可回收物分类指引`  (类目: 垃圾分类)
  - 期望 slug: `daily_living`
  - top-3 实际: ['guangdong_low_carbon', '2025_ccer_methodology_expansion', '2024_2025_subsidies']
- **query**: `有害垃圾投放注意事项`  (类目: 垃圾分类)
  - 期望 slug: `daily_living`
  - top-3 实际: ['beijing_low_carbon', 'shenzhen_low_carbon', 'guangdong_low_carbon']
- **query**: `碳足迹数据库管理指引`  (类目: 碳足迹)
  - 期望 slug: `2025_carbon_footprint_db_guideline`
  - top-3 实际: ['2026_national_carbon_market_notice', 'national_policy', 'carbon_footprint_standard']
- **query**: `温室气体排放因子数据库 v2`  (类目: 碳足迹)
  - 期望 slug: `2026_ghg_emission_factor_db_v2`
  - top-3 实际: ['green_certification', '0233_应对气候变化_中华人民共和国生态环境部', 'beijing_low_carbon']
- **query**: `低碳产品认证的好处`  (类目: 认证)
  - 期望 slug: `green_certification`
  - top-3 实际: ['beijing_2026_low_carbon_call', 'beijing_2026_low_carbon_call', 'beijing_2026_low_carbon_call']
- **query**: `北京市低碳行动方案`  (类目: 省级低碳)
  - 期望 slug: `beijing_low_carbon`
  - top-3 实际: ['beijing_2026_low_carbon_call', 'guangdong_low_carbon', 'shenzhen_low_carbon']
- **query**: `广东省低碳发展规划`  (类目: 省级低碳)
  - 期望 slug: `guangdong_low_carbon`
  - top-3 实际: ['beijing_2026_low_carbon_call', '2024_2025_subsidies', '0248_首页']
- **query**: `气候风险评估方法`  (类目: 适应气候变化)
  - 期望 slug: `2023_china_climate_adaptation_progress`
  - top-3 实际: ['2025_carbon_footprint_db_guideline', '0226_Reports_—_IPCC', '2025_carbon_footprint_db_guideline']
- **query**: `家电换新补贴申领流程`  (类目: 补贴)
  - 期望 slug: `2024_2025_subsidies`
  - top-3 实际: ['beijing_low_carbon', 'national_policy', 'shanghai_low_carbon']
- **query**: `节能补贴申请条件`  (类目: 补贴)
  - 期望 slug: `2024_2025_subsidies`
  - top-3 实际: ['beijing_low_carbon', 'national_policy', 'shanghai_low_carbon']
- **query**: `绿色家电购置补贴覆盖范围`  (类目: 补贴)
  - 期望 slug: `2024_2025_subsidies`
  - top-3 实际: ['national_policy', 'guangdong_low_carbon', 'shanghai_low_carbon']