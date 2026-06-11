# RAG 检索质量评估报告 — subset=curated

- 集合: `green_agent_knowledge`
- 总 query 数: **33**

## 总体指标

| 指标 | 值 |
|---|---|
| hit_rate@5 | 0.7576 |
| mrr@10 | 0.6191 |
| ndcg@10 | 0.7004 |

## 分类 hit_rate@5

| 类目 | hit_rate@5 |
|---|---|
| CCER | 1.0000 |
| 出行 | 1.0000 |
| 垃圾分类 | 1.0000 |
| 碳足迹 | 1.0000 |
| 适应气候变化 | 1.0000 |
| 碳交易 | 0.6667 |
| 政策 | 0.6667 |
| 认证 | 0.6667 |
| 省级低碳 | 0.6000 |
| 补贴 | 0.2500 |

## 未命中明细(8 条)

- **query**: `碳市场新增哪些行业纳入交易`  (类目: 碳交易)
  - 期望 slug: `2026_national_carbon_market_notice`
  - top-3 实际: ['beijing_low_carbon', 'guangdong_low_carbon', '2025_ccer_methodology_expansion']
- **query**: `发电行业核查工作要求`  (类目: 政策)
  - 期望 slug: `2026_power_sector_carbon_guide_update`
  - top-3 实际: ['home_energy_guide', 'beijing_2026_check', '2026_national_carbon_market_notice']
- **query**: `节能产品认证申请流程`  (类目: 认证)
  - 期望 slug: `green_certification`
  - top-3 实际: ['2025_carbon_footprint_db_guideline', '2026_national_carbon_market_notice', '2026_ghg_emission_factor_db_v2']
- **query**: `上海低碳城市建设进展`  (类目: 省级低碳)
  - 期望 slug: `shanghai_low_carbon`
  - top-3 实际: ['beijing_2026_low_carbon_call', 'beijing_low_carbon', '2026_ghg_emission_factor_db_v2']
- **query**: `深圳低碳试点示范工作`  (类目: 省级低碳)
  - 期望 slug: `shenzhen_low_carbon`
  - top-3 实际: ['beijing_2025_report', '2026_ghg_emission_factor_db_v2', 'beijing_2026_low_carbon_call']
- **query**: `以旧换新政策细则`  (类目: 补贴)
  - 期望 slug: `2024_trade_in_action`
  - top-3 实际: ['national_policy', '2024_2025_subsidies', '2023_china_climate_adaptation_progress']
- **query**: `家电换新补贴申领流程`  (类目: 补贴)
  - 期望 slug: `2024_2025_subsidies`
  - top-3 实际: ['2026_power_sector_carbon_guide_update', 'home_energy_guide', 'home_energy_guide']
- **query**: `节能补贴申请条件`  (类目: 补贴)
  - 期望 slug: `2024_2025_subsidies`
  - top-3 实际: ['national_policy', 'national_policy', 'beijing_low_carbon']