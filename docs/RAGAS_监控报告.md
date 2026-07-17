# 任务 5: RAGAS 监控体系落地 — 报告

**部署时间**: 2026-06-14
**工具**: RAGAS 0.x + DeepSeek-v4-flash LLM judge
**脚本**: `scripts/eval_ragas.py`

## 一、监控指标体系

| 指标 | 类别 | 计算方式 | 范围 |
|---|---|---|---|
| **retrieval_hit_rate@5** | 召回质量 | top-5 是否含期望 slug | 0~1 |
| **source_diversity@5** | 检索多样性 | top-5 不同文档数 / 5 | 0~1 |
| **answer_keyword_coverage** | 答案质量 | 答案含 query 关键词比例 | 0~1 |
| **context_precision** | RAG 检索精准 | RAGAS LLM judge | 0~1 |
| **context_recall** | RAG 检索覆盖 | RAGAS LLM judge | 0~1 |
| **faithfulness** | 答案忠实度 | RAGAS LLM judge | 0~1 |
| **answer_relevancy** | 答案相关性 | RAGAS LLM judge | 0~1 |
| **ragas_llm_judge_ok** | 健康检查 | RAGAS 是否跑通 | 0/1 |

## 二、最新评估结果(10 条 curated)

| 指标 | 值 | 状态 |
|---|---|---|
| retrieval_hit_rate@5 | **0.8000** | ✅ 高 |
| source_diversity@5 | **0.8200** | ✅ 高 |
| answer_keyword_coverage | 0.2500 | ⚠️ 偏低 |
| context_precision | N/A | DeepSeek n=1 限制 |
| context_recall | N/A | DeepSeek n=1 限制 |
| faithfulness | N/A | DeepSeek n=1 限制 |
| answer_relevancy | N/A | DeepSeek n=1 限制 |
| ragas_llm_judge_ok | 0.0 | ⚠️ DeepSeek 不支持 n>1 |

## 三、RAGAS 已知限制

**DeepSeek API 仅支持 `n=1`**(单次生成),但 RAGAS `answer_relevancy` 等指标内部需要 `n>1` 多次生成对比。导致 LLM judge 维度不可用。

### 解法选项
1. **换用 OpenAI/Claude/Anthropic 作 judge**(支持 n>1)
2. **降级到 ragas `context_precision_without_groundtruth` 系列**(单次生成)
3. **使用自建忠实度检测**(规则式,不依赖 LLM)
4. **用 LLM-judge 离线批量评估,定期跑(任务5 已实现脚本,等换 LLM)**

## 四、落地物

- `scripts/eval_ragas.py` — 完整评估脚本(可入 CI)
- `data/ragas_report.md` — 每次评估自动生成报表
- 4 个核心 RAGAS 指标 + 4 个无 LLM 兜底指标

## 五、CI/CD 接入建议

```bash
# 每周一次跑全量,日报跑抽样
set -a && source .env && set +a
python scripts/eval_ragas.py --subset curated --limit 30
```

## 六、闭环

✅ RAGAS 监控脚本落地
✅ 4 个 RAGAS 标准指标 + 4 个无 LLM 兜底指标
✅ 报表自动写入 `data/ragas_report.md`
✅ 限制已记录(DeepSeek n=1)
⚠️ 完整 LLM judge 维度需换 OpenAI/Claude 作 judge
