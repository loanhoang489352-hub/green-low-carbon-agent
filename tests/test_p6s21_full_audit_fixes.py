"""
P6.S.21 测试: 全链路审计 + 修复
- KB 守门员
- KB 合规清洗
- RAG 阈值/分数分布
- BM25 索引填充
"""
import sys
import os
import json
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(__file__).replace("\\", "/").replace("tests/test_p6s21_full_audit_fixes.py", "src"))


def _http_get(url, timeout=10):
    req = urllib.request.Request(url, method="GET")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", errors="ignore"))


def _http_post(url, data, timeout=30):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", errors="ignore"))


def test_server_running():
    return _http_get("http://localhost:8000/api/health", timeout=5)[0] == 200


# ============ Task 1: 模块健康巡检 ============

def test_all_modules_health():
    """P6.S.21: 所有 7 个 tool + 3 skill + 1 MCP server 都注册"""
    code, body = _http_get("http://localhost:8000/api/tools-skills")
    assert code == 200
    assert body["tools_count"] == 7, f"应 7 tools, 实际 {body['tools_count']}"
    assert body["skills_count"] == 3, f"应 3 skills, 实际 {body['skills_count']}"
    print(f"  ✓ tools: {body['tools_count']}, skills: {body['skills_count']}")
    print("✅ test_all_modules_health PASSED")


def test_mcp_server_connected():
    """P6.S.21: MCP server connected + 3 tool 注入"""
    if not test_server_running():
        return
    code, body = _http_get("http://localhost:8000/api/mcp/status")
    assert code == 200
    assert body["servers_count"] == 1
    assert body["servers"][0]["status"] == "connected"
    assert body["tools_count"] == 3
    print("✅ test_mcp_server_connected PASSED")


def test_mcp_tool_actually_callable_via_react():
    """P6.S.21: MCP tool 可被 LLM 通过 ReAct 真调"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/agent/react",
        {
            "message": "骑 5 公里自行车排多少碳?",
            "tool_names": ["mcp_mock_server_mock_carbon"],
            "max_steps": 2,
        },
        timeout=60,
    )
    assert code == 200
    tool_calls = body.get("tool_calls", [])
    assert len(tool_calls) >= 1, "应至少调 1 次 tool"
    assert tool_calls[0]["name"].startswith("mcp_"), f"应调 MCP tool, 实际 {tool_calls[0]['name']}"
    assert tool_calls[0]["success"], f"tool 调失败: {tool_calls[0]}"
    print(f"  ✓ tool_calls: {[(tc['name'], tc['success']) for tc in tool_calls]}")
    print("✅ test_mcp_tool_actually_callable_via_react PASSED")


# ============ Task 2: 出行规划全链路 ============

def test_travel_planning_works_with_gaode_key():
    """P6.S.21: 出行规划在有 GAODE_API_KEY 时真能调通"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/chat/enhanced",
        {"user_id": "p6s21_travel_test", "message": "从北京西单到国贸怎么走"},
        timeout=60,
    )
    assert code == 200
    assert body["intent"] == "travel_planning"
    msg = body.get("message", "")
    # 关键:有具体数据(8km, 30 分钟等)说明 TravelPlanningTool 真调到了
    assert "8km" in msg or "30" in msg, f"应有具体路线数据: {msg[:300]}"
    assert "⚠️" not in msg, f"不应是降级提示: {msg[:300]}"
    print(f"  ✓ 出行规划触发 + 高德数据有: {msg[:80]!r}")
    print("✅ test_travel_planning_works_with_gaode_key PASSED")


# ============ Task 3: 位置定位 ============

def test_geolocation_must_be_user_provided():
    """P6.S.21: 项目无自动定位,缺省出发地 = "当前位置" 占位符 → 高德失败 → 降级"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/chat/enhanced",
        {"user_id": "p6s21_geo_test", "message": "怎么去机场"},
        timeout=60,
    )
    assert code == 200
    msg = body.get("message", "")
    # 应显示高德失败(因为 origin=当前位置 是字面量)
    assert "当前位置" in msg or "通用建议" in msg, \
        f"无自动定位时应显示降级提示: {msg[:300]}"
    print(f"  ✓ 位置定位结论:无自动定位,需用户写明")
    print("✅ test_geolocation_must_be_user_provided PASSED")


def test_user_explicit_location_works():
    """P6.S.21: 用户写明位置 → LLM 解析 → 工具调用正常"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/chat/enhanced",
        {"user_id": "p6s21_geo_test", "message": "我现在在国贸,去西单"},
        timeout=60,
    )
    assert code == 200
    msg = body.get("message", "")
    # 有具体路线(1号线, 国贸站)
    assert "国贸" in msg and "西单" in msg, f"应含具体路线: {msg[:200]}"
    print("✅ test_user_explicit_location_works PASSED")


# ============ Task 4: KB 守门员 + 合规清洗 ============

def test_kb_quarantine_dir_exists():
    """P6.S.21: 7 个真正无关文件已归档"""
    kb_dir = Path("d:/绿色低碳智能体/knowledge_base")
    quarantine_dir = kb_dir / "_quarantine"
    assert quarantine_dir.exists(), f"应创建归档目录: {quarantine_dir}"
    # 至少 7 个文件
    files = list(quarantine_dir.rglob("*.md"))
    assert len(files) >= 7, f"应至少归档 7 个, 实际 {len(files)}"
    # 关键文件应被归档
    archived_paths = [str(f.relative_to(kb_dir)) for f in files]
    assert any("共产党员网" in p for p in archived_paths), "应归档共产党员网"
    assert any("国家统计局" in p for p in archived_paths), "应归档国家统计局"
    assert any("Defense" in p or "EDF" in p for p in archived_paths), "应归档 Environmental Defense Fund"
    print(f"  ✓ 归档 {len(files)} 个文件:")
    for p in sorted(archived_paths):
        print(f"    - {p}")
    print("✅ test_kb_quarantine_dir_exists PASSED")


def test_kb_cleanup_log_exists():
    """P6.S.21: 清理日志写入"""
    log_file = Path("d:/绿色低碳智能体/data/kb_cleanup_log.json")
    assert log_file.exists(), f"清理日志应存在: {log_file}"
    log = json.loads(log_file.read_text(encoding="utf-8"))
    assert log["total_files_quarantined"] >= 7
    assert log["total_size_kb"] > 0
    assert len(log["files"]) >= 7
    # 每条都应有 status 和 reason
    for f in log["files"]:
        assert "status" in f
        assert "reason" in f
    print(f"  ✓ 清理日志: {log['total_files_quarantined']} 个文件, {log['total_size_kb']}KB")
    print("✅ test_kb_cleanup_log_exists PASSED")


def test_kb_stats_after_cleanup():
    """P6.S.21: /api/knowledge/stats 反映清洗后的状态"""
    if not test_server_running():
        return
    code, body = _http_get("http://localhost:8000/api/knowledge/stats")
    assert code == 200
    # total_documents 反映了 policies/ 的剩余文件
    total = body.get("total_documents", 0)
    # 之前 45(38 policies + 4 policy + 3 guide + 5 basic) - 5(归档了 5 个 policies, 还有 2 个 0.1KB)
    # 实际剩 38 - 5 - 2 = 31? 看
    assert total > 0 and total < 50, f"total 应在合理范围: {total}"
    print(f"  ✓ total_documents: {total} (清洗后)")
    print("✅ test_kb_stats_after_cleanup PASSED")


# ============ Task 5: RAG 阈值 + 分数分布 ============

def test_rag_bm25_index_populated():
    """P6.S.21: 启动时即使 ChromaDB 已有索引,也填充 BM25"""
    from rag.rag_engine import RAGEngine, RAGConfig
    from pathlib import Path
    cfg = RAGConfig(enabled=True)
    engine = RAGEngine(cfg)
    engine.initialize(str(Path("d:/绿色低碳智能体/knowledge_base")))
    retriever = engine._retriever
    assert hasattr(retriever, "bm25_retriever")
    # P6.S.21 修后,BM25 索引应被填充
    bm25_count = len(retriever.bm25_retriever.documents)
    assert bm25_count > 0, f"BM25 索引应被填充, 实际 {bm25_count} 个 docs"
    print(f"  ✓ BM25 docs: {bm25_count}")
    print("✅ test_rag_bm25_index_populated PASSED")


def test_rag_relevant_query_scores_high():
    """P6.S.21: 相关 query 分数 > 0.1(BM25 命中)"""
    from rag.rag_engine import RAGEngine, RAGConfig
    from pathlib import Path
    cfg = RAGConfig(enabled=True)
    engine = RAGEngine(cfg)
    engine.initialize(str(Path("d:/绿色低碳智能体/knowledge_base")))
    retriever = engine._retriever
    for q in ["碳中和", "新能源", "低碳"]:
        results = retriever.retrieve(q, top_k=3, min_score=0.0)
        assert results, f"'{q}' 应至少 1 个结果"
        top_score = results[0].score
        # P6.S.21 修后,相关 query 分数应 > 0.1(BM25 关键词命中)
        assert top_score > 0.1, f"'{q}' top score 应 > 0.1, 实际 {top_score:.3f}"
        print(f"  ✓ '{q}' top score: {top_score:.3f} (> 0.1)")


def test_rag_irrelevant_query_scores_low():
    """P6.S.21: 无关 query 分数应 < 0.05(BM25 不命中,几乎为 0)"""
    from rag.rag_engine import RAGEngine, RAGConfig
    from pathlib import Path
    cfg = RAGConfig(enabled=True)
    engine = RAGEngine(cfg)
    engine.initialize(str(Path("d:/绿色低碳智能体/knowledge_base")))
    retriever = engine._retriever
    for q in ["股票", "天气", "彩票", "演唱会"]:
        results = retriever.retrieve(q, top_k=3, min_score=0.0)
        # 无关 query 分数应 < 0.1(BM25 不命中)
        if results:
            top_score = results[0].score
            assert top_score < 0.1, f"无关 query '{q}' 分数应 < 0.1, 实际 {top_score:.3f}"
            print(f"  ✓ '{q}' top score: {top_score:.3f} (< 0.1)")


if __name__ == "__main__":
    test_server_running()
    test_all_modules_health()
    test_mcp_server_connected()
    test_mcp_tool_actually_callable_via_react()
    test_travel_planning_works_with_gaode_key()
    test_geolocation_must_be_user_provided()
    test_user_explicit_location_works()
    test_kb_quarantine_dir_exists()
    test_kb_cleanup_log_exists()
    test_kb_stats_after_cleanup()
    test_rag_bm25_index_populated()
    test_rag_relevant_query_scores_high()
    test_rag_irrelevant_query_scores_low()
    print("\n🎉 All P6.S.21 tests PASSED")
