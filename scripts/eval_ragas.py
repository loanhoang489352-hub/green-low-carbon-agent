#!/usr/bin/env python3
"""
任务5: RAGAS 检索质量评估脚本
基于现有 RAG 链路 + DeepSeek 作 LLM judge
输出 4 个核心指标: context_precision / context_recall / faithfulness / answer_relevancy

使用方法:
    set -a && source .env && set +a
    python scripts/eval_ragas.py --subset curated
    python scripts/eval_ragas.py --subset full --limit 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# 复用现有 golden set
GOLDEN_SET = PROJECT_ROOT / "tests" / "eval" / "golden_set.jsonl"
REPORT_PATH = PROJECT_ROOT / "data" / "ragas_report.md"


def load_golden(subset: str | None = None, limit: int | None = None) -> list:
    entries = []
    with open(GOLDEN_SET, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if subset and e.get("subset") != subset:
                continue
            entries.append(e)
            if limit and len(entries) >= limit:
                break
    return entries


def retrieve_context(engine, query: str, top_k: int = 5) -> tuple[str, list[str]]:
    """调 RAG 引擎返回 context 字符串 + slug 列表"""
    results = engine.retrieve(query, top_k=top_k)
    ctxs = []
    slugs = []
    for r in results:
        ctxs.append(r.content)
        meta = r.metadata or {}
        src = meta.get("source", "")
        slug = src.replace("\\", "/").split("/")[-1]
        if slug.endswith(".md"):
            slug = slug[:-3]
        slugs.append(slug)
    return "\n\n---\n\n".join(ctxs), slugs


def generate_answer(client, query: str, context: str) -> str:
    """用 LLM 生成答案(基于 RAG 召回的 context)"""
    prompt = f"""基于以下参考信息回答用户问题。如果参考信息不足,直接说"我不知道"。

参考信息:
{context[:3000]}

用户问题: {query}

回答:"""
    resp = client.chat([{"role": "user", "content": prompt}])
    return resp.content if not resp.error else f"[LLM_ERR]{resp.error}"


def slug_to_title(slug: str) -> str:
    """slug 转可读标题(给 RAGAS 用)"""
    return slug.replace("_", " ").replace("-", " ")


def main():
    parser = argparse.ArgumentParser(description="RAGAS 检索质量评估")
    parser.add_argument("--subset", choices=["curated", "full"], default="curated")
    parser.add_argument("--limit", type=int, default=None, help="限制 query 数量(快速验证)")
    parser.add_argument("--no-llm-judge", action="store_true", help="跳过 RAGAS LLM judge,只跑检索部分")
    args = parser.parse_args()

    # 1) 加载 RAG 引擎
    from rag.rag_engine import get_rag_engine, RAGConfig
    from paths import KNOWLEDGE_BASE_DIR
    from llm import create_llm_client
    import os

    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("API_KEY", "")
    if not api_key or api_key.startswith("__SET_ME__"):
        print("[ERR] DEEPSEEK_API_KEY 未配置")
        sys.exit(2)

    engine = get_rag_engine(RAGConfig(collection_name="green_agent_knowledge"))
    if not engine._initialized:
        engine.initialize(str(KNOWLEDGE_BASE_DIR))
    print(f"[ragas] RAG 引擎: {engine._vector_store.count()} chunks")

    # 2) 加载 LLM
    client = create_llm_client(
        provider="deepseek",
        api_key=api_key,
        model=os.environ.get("API_MODEL", "deepseek-chat"),
    )
    print(f"[ragas] LLM: {type(client).__name__} / {client.model}")

    # 3) 加载 golden set
    entries = load_golden(subset=args.subset, limit=args.limit)
    print(f"[ragas] subset={args.subset} → {len(entries)} queries")

    # 4) 构造 RAGAS 数据集
    questions, ground_truths, contexts, answers, retrieved_slugs_list = [], [], [], [], []
    t0 = time.time()
    for i, e in enumerate(entries, 1):
        q = e["query"]
        gt_slug = e["expected_source_slug"]
        gt_title = slug_to_title(gt_slug)

        ctx_str, slugs = retrieve_context(engine, q, top_k=5)
        ans = generate_answer(client, q, ctx_str)

        questions.append(q)
        # ground_truth 必须是答案文本(非 slug),RAGAS 用 LLM judge 对比
        ground_truths.append(f"参考文档: {gt_title}")
        contexts.append([ctx_str] if ctx_str else [""])
        answers.append(ans)
        retrieved_slugs_list.append(slugs)
        if i % 5 == 0:
            print(f"  [{i}/{len(entries)}] 已完成,累计 {time.time()-t0:.1f}s")

    print(f"[ragas] 全部 {len(entries)} 条已检索+生成答案,耗时 {time.time()-t0:.1f}s")

    # 5) RAGAS 评估(无参考指标)
    # 任务1 P1-2: 适配 DeepSeek(不支持 n>1)
    #  - 用 3 个单次生成指标(context_precision / context_recall / faithfulness)
    #  - 跳过 answer_relevancy(需 n>1)
    #  - 加 answer_relevancy_proxy(规则式 + 单次 LLM 评判,作为兜底)
    metrics = {}
    ragas_success = False
    if not args.no_llm_judge:
        try:
            from ragas import evaluate
            from ragas.metrics import (
                context_precision,
                context_recall,
                faithfulness,
            )
            from datasets import Dataset

            ds_dict = {
                "question": questions,
                "answer": answers,
                "contexts": contexts,
                "ground_truth": ground_truths,
            }
            ds = Dataset.from_dict(ds_dict)
            print("[ragas] 跑 RAGAS 3 个兼容 DeepSeek 指标...")

            from langchain_openai import ChatOpenAI

            judge_llm = ChatOpenAI(
                model=os.environ.get("API_MODEL", "deepseek-chat"),
                api_key=api_key,
                base_url="https://api.deepseek.com/v1",
                temperature=0,
                timeout=60,
            )

            result = evaluate(
                ds,
                metrics=[context_precision, context_recall, faithfulness],
                llm=judge_llm,
            )
            # RAGAS 0.4.3 返回 EvaluationResult:
            #   - result.scores = list of dict [{metric: float}, ...]
            #   - result.to_pandas() = DataFrame (含字符串列,无法 .mean())
            try:
                scores_list = getattr(result, "scores", None)
                if isinstance(scores_list, list) and scores_list:
                    # 聚合:每个 metric 取所有条目的平均
                    for col in ["context_precision", "context_recall", "faithfulness"]:
                        vals = [d.get(col) for d in scores_list if isinstance(d, dict) and d.get(col) is not None]
                        if vals:
                            metrics[col] = sum(vals) / len(vals)
                    ragas_success = True
                    print(f"[ragas] 解析成功,scores 长度 {len(scores_list)}")
            except Exception as parse_err:
                print(f"[WARN] scores 解析回退: {parse_err}")
        except Exception as e:
            print(f"[WARN] RAGAS 评估失败: {e}")
            import traceback

            traceback.print_exc()

    # 6) 兜底 + 增强指标(无 LLM judge 也可计算)
    hits = sum(1 for slugs, e in zip(retrieved_slugs_list, entries)
               if e["expected_source_slug"] in slugs)
    metrics.setdefault("retrieval_hit_rate@5", hits / max(len(entries), 1))
    diversity = (sum(len(set(slugs)) for slugs in retrieved_slugs_list) /
                 (5 * len(retrieved_slugs_list)) if retrieved_slugs_list else 0)
    metrics.setdefault("source_diversity@5", diversity)

    def kw_coverage(q, a):
        # 中文无空格,按 2-gram 切词;英文按词
        import re

        chinese = re.findall(r"[一-鿿]{2,}", q)
        english = re.findall(r"[a-zA-Z]{3,}", q)
        kws = chinese[:5] + english[:5]
        if not kws:
            return 0
        return sum(1 for k in kws if k in a) / len(kws)

    kw_cov = sum(kw_coverage(q, a) for q, a in zip(questions, answers)) / max(len(questions), 1)
    metrics.setdefault("answer_keyword_coverage", kw_cov)
    metrics.setdefault("ragas_llm_judge_ok", 1.0 if ragas_success else 0.0)

    # 任务1 P1-2: answer_relevancy_proxy — 单次 LLM 评判 + 规则式兜底
    #   跳过 n>1 的 answer_relevancy,用规则式 + 单次 LLM 评判模拟
    if not ragas_success and not args.no_llm_judge:
        try:
            from langchain_openai import ChatOpenAI
            proxy_llm = ChatOpenAI(
                model=os.environ.get("API_MODEL", "deepseek-chat"),
                api_key=api_key,
                base_url="https://api.deepseek.com/v1",
                temperature=0,
                timeout=60,
            )
            scores = []
            for q, a in zip(questions, answers):
                prompt = (
                    "评估下面答案与问题的相关性,0-1 分,只回数字。\n"
                    f"问题: {q}\n答案: {a[:500]}\n相关度:"
                )
                try:
                    r = proxy_llm.invoke(prompt)
                    txt = (r.content if hasattr(r, "content") else str(r)).strip()
                    import re as _re
                    m_score = _re.search(r"([0-9.]+)", txt)
                    scores.append(float(m_score.group(1)) if m_score else 0.0)
                except Exception:
                    scores.append(0.0)
            metrics["answer_relevancy_proxy"] = sum(scores) / max(len(scores), 1)
        except Exception as e:
            _logger.warning(f"[ragas] answer_relevancy_proxy 失败: {e}")
            metrics["answer_relevancy_proxy"] = 0.0

    # 6) 写报告
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# RAGAS 检索质量评估报告 — subset={args.subset}",
        "",
        f"- 评估时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 总 query 数: **{len(entries)}**",
        f"- ChromaDB 集合: green_agent_knowledge",
        f"- LLM judge: DeepSeek ({os.environ.get('API_MODEL', 'deepseek-chat')})",
        f"- Embedder: paraphrase-multilingual-MiniLM-L12-v2",
        "",
        "## 核心指标",
        "",
        "| 指标 | 值 | 说明 |",
        "|---|---|---|",
    ]
    desc_map = {
        "context_precision": "检索上下文的相关性(精准度)",
        "context_recall": "检索上下文的覆盖率",
        "faithfulness": "答案对上下文的忠实度(无幻觉)",
        "answer_relevancy_proxy": "答案相关性(单次 LLM 评判,替代 n>1 的 answer_relevancy)",
        "retrieval_hit_rate@5": "粗召回(降级模式)",
        "source_diversity@5": "top-5 来源多样性(0~1)",
        "answer_keyword_coverage": "答案关键词覆盖率(无 LLM)",
        "ragas_llm_judge_ok": "RAGAS LLM judge 成功(1/0)",
    }
    for k, v in metrics.items():
        if isinstance(v, (int, float)):
            desc = desc_map.get(k, k)
            lines.append(f"| {k} | {v:.4f} | {desc} |")
        else:
            lines.append(f"| {k} | {str(v)[:50]} | — |")

    # 每条 query 详细
    lines.extend(["", "## 明细", ""])
    for i, (q, slugs, ans) in enumerate(zip(questions, retrieved_slugs_list, answers), 1):
        lines.append(f"### Q{i}: {q}")
        lines.append(f"- 检索 top-5: {slugs}")
        lines.append(f"- 答案(前 100 字): {ans[:100]}")
        lines.append("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] 报告写入: {REPORT_PATH}")
    print()
    print("=== 指标 ===")
    for k, v in metrics.items():
        if isinstance(v, (int, float)):
            print(f"  {k}: {v:.4f}")


if __name__ == "__main__":
    main()
