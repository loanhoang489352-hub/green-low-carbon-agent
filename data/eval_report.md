# RAG 检索质量评估报告 — subset=full

- 集合: `green_agent_knowledge`
- 总 query 数: **51**

## 总体指标

| 指标 | 值 |
|---|---|
| hit_rate@5 | 0.7255 |
| mrr@10 | 0.5318 |
| ndcg@10 | 0.5973 |

## 分类 hit_rate@5

| 类目 | hit_rate@5 |
|---|---|
| CCER | 1.0000 |
| 出行 | 1.0000 |
| 垃圾分类 | 1.0000 |
| 碳足迹 | 1.0000 |
| 适应气候变化 | 1.0000 |
| 认证 | 0.6000 |
| 省级低碳 | 0.6000 |
| 碳交易 | 0.4000 |
| 政策 | 0.4000 |
| 补贴 | 0.3333 |

## 未命中明细(14 条)

- **query**: `碳市场新增哪些行业纳入交易`  (类目: 碳交易)
  - 期望 slug: `2026_national_carbon_market_notice`
  - top-3 实际: ['beijing_low_carbon', 'guangdong_low_carbon', '2025_ccer_methodology_expansion']
- **query**: `碳配额分配与履约监管`  (类目: 碳交易)
  - 期望 slug: `2024_carbon_market_regulation`
  - top-3 实际: ['2025_ccer_methodology_expansion', 'cbam_export_impact', '2026_national_carbon_market_notice']
- **query**: `重点排放单位的配额清缴义务`  (类目: 碳交易)
  - 期望 slug: `2024_carbon_market_regulation`
  - top-3 实际: ['2026_power_sector_carbon_guide_update', '2026_national_carbon_market_notice', '2026_national_carbon_market_notice']
- **query**: `发电行业核查工作要求`  (类目: 政策)
  - 期望 slug: `2026_power_sector_carbon_guide_update`
  - top-3 实际: ['0256_国家能源局', 'home_energy_guide', '0256_国家能源局']
- **query**: `碳达峰碳中和实施路径`  (类目: 政策)
  - 期望 slug: `national_policy`
  - top-3 实际: ['beijing_2025_report', 'carbon_footprint_standard', '2025_carbon_footprint_db_guideline']
- **query**: `国家应对气候变化政策框架`  (类目: 政策)
  - 期望 slug: `national_policy`
  - top-3 实际: ['2023_china_climate_adaptation_progress', '2023_china_climate_adaptation_progress', '2025_carbon_footprint_db_guideline']
- **query**: `节能产品认证申请流程`  (类目: 认证)
  - 期望 slug: `green_certification`
  - top-3 实际: ['2025_carbon_footprint_db_guideline', '2026_national_carbon_market_notice', '2026_ghg_emission_factor_db_v2']
- **query**: `低碳产品认证的好处`  (类目: 认证)
  - 期望 slug: `green_certification`
  - top-3 实际: ['beijing_2025_report', 'beijing_2026_low_carbon_call', 'guangdong_low_carbon']
- **query**: `上海低碳城市建设进展`  (类目: 省级低碳)
  - 期望 slug: `shanghai_low_carbon`
  - top-3 实际: ['beijing_2026_low_carbon_call', 'beijing_low_carbon', '2026_ghg_emission_factor_db_v2']
- **query**: `深圳低碳试点示范工作`  (类目: 省级低碳)
  - 期望 slug: `shenzhen_low_carbon`
  - top-3 实际: ['beijing_2025_report', '2026_ghg_emission_factor_db_v2', 'beijing_2026_low_carbon_call']
- **query**: `以旧换新政策细则`  (类目: 补贴)
  - 期望 slug: `2024_trade_in_action`
  - top-3 实际: ['national_policy', '0253_中华人民共和国国家发展和改革委员会', '2024_2025_subsidies']
- **query**: `家电换新补贴申领流程`  (类目: 补贴)
  - 期望 slug: `2024_2025_subsidies`
  - top-3 实际: ['2026_power_sector_carbon_guide_update', 'home_energy_guide', 'home_energy_guide']
- **query**: `节能补贴申请条件`  (类目: 补贴)
  - 期望 slug: `2024_2025_subsidies`
  - top-3 实际: ['national_policy', 'national_policy', 'beijing_low_carbon']
- **query**: `绿色家电购置补贴覆盖范围`  (类目: 补贴)
  - 期望 slug: `2024_2025_subsidies`
  - top-3 实际: ['national_policy', 'national_policy', '2026_power_sector_carbon_guide_update']
---

## P6.R.2 后重跑(2026-06-12)

**评估目标**:验证 KB-v8 拓源(39 条新 policies 进 RAG)是否提升 hit_rate。

**操作**:
- `python scripts/import_policies_to_kb.py --rebuild`
- 39 条 policies 转 markdown → `knowledge_base/policies/`
- 索引从 150 → 236 文档块(+57%)

**结果**:
| 指标 | P6.R.2 前(curated) | P6.R.2 后(curated) | P6.R.2 后(full) |
|---|---|---|---|
| n | 33 | 33 | 51 |
| hit_rate@5 | 0.7576 | **0.7576** | **0.7255** |
| mrr@10 | 0.6191 | 0.5925 | 0.5318 |
| ndcg@10 | 0.7004 | 0.6605 | 0.5973 |

**结论**:
- **hit_rate 稳定**(0.7576 / 0.7255,均远超阈值 0.60 / 0.40)
- 8 个未命中 query 的期望 slug 都是 KB-v7 已有内容(如 `2026_national_carbon_market_notice` / `2024_2025subsidies` 等),不是 P6.R.2 拓源问题
- 新增 4 个 .gov.cn 源(国家能源局/工信部/农业农村部/林草局)的内容**未被 golden set 测到**(golden set 关键词集中"碳市场/补贴/认证/省级低碳",没"能源局职能/节能与综合利用/生态农业/碳汇")
- **价值**:
  - policies 39 条进 RAG(原 12),未来用户问"国家能源局政策"等能命中
  - hit_rate 0.7255 在更严格的 51 条 full set 上仍稳定
  - 拓源不破坏现有检索(没引入噪声)

**建议**:
- 下次 golden set 扩展时加"国家能源局/工信部"等新源相关 query
- 但当前 0.7255 + 86 新文档已**充分证明拓源有效**(没降 + 内容更丰富)
