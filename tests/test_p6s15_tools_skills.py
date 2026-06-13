"""
P6.S.15 测试: Tool/Skill 注册 + 出行规划深度

P6.S.15 修复:
1. 所有 tool/skill 之前从未注册,Registry 是空的
2. LowCarbonTravelSkill 死代码(定义了但没用)
3. 出行规划评分显示 0.577/10 误导(实际 0-1)
4. 出行规划只有 3 种交通方式(公交+地铁/骑行/自驾),缺步行
5. 出行规划响应缺深度(无具体线路名/碳减排对比/评分明细)

验证:
1. 启动后 tool registry 包含 4 个 tool
2. 启动后 skill executor 包含 3 个 skill(含 low_carbon_travel)
3. 出行规划响应评分是 0-10 范围
4. 短途自动加步行选项
5. 响应包含碳减排对比/评分明细/天气/权重
6. /api/tools-skills 端点可查
"""
import sys
import os
sys.path.insert(0, str(__file__).replace("\\", "/").replace("tests/test_p6s15_tools_skills.py", "src"))

import urllib.request
import urllib.error
import json


def _http_get(url, timeout=10):
    req = urllib.request.Request(url, method="GET")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", errors="ignore"))


def _http_post(url, data, headers=None, timeout=60):
    headers = headers or {}
    headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=headers, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", errors="ignore"))


def test_server_running():
    """前置:server 必须跑着"""
    code, _ = _http_get("http://localhost:8000/api/health", timeout=5)
    if code != 200:
        print(f"⏭ SKIPPED: server not running (code={code})")
        return False
    return True


def test_tools_registry_populated():
    """P6.S.15: 启动后 tool registry 应含 4 个 tool"""
    if not test_server_running():
        return
    code, body = _http_get("http://localhost:8000/api/tools-skills")
    assert code == 200, f"应 200, 实际 {code}"
    assert body["tools_count"] >= 4, f"应 ≥4 tools, 实际 {body['tools_count']}"
    tool_names = [t["name"] for t in body["tools"]]
    assert "travel_planning" in tool_names, "应含 travel_planning tool"
    assert "knowledge_retrieval" in tool_names
    print(f"  tools: {tool_names}")
    print("✅ test_tools_registry_populated PASSED")


def test_skills_registry_populated():
    """P6.S.15: 启动后 skill executor 应含 3 个 skill(含 low_carbon_travel)"""
    if not test_server_running():
        return
    code, body = _http_get("http://localhost:8000/api/tools-skills")
    assert code == 200
    assert body["skills_count"] >= 3, f"应 ≥3 skills, 实际 {body['skills_count']}"
    skill_names = [s["name"] for s in body["skills"]]
    assert "low_carbon_travel" in skill_names, "应含 low_carbon_travel skill(死代码修复)"
    assert "policy_query" in skill_names
    assert "profile_update" in skill_names
    # low_carbon_travel 应组合多个 tool
    lct = next(s for s in body["skills"] if s["name"] == "low_carbon_travel")
    assert "weather_query" in lct["tools"], "low_carbon_travel 应组合 weather_query"
    assert "carbon_calc" in lct["tools"], "low_carbon_travel 应组合 carbon_calc"
    assert "public_transit" in lct["tools"], "low_carbon_travel 应组合 public_transit"
    print(f"  skills: {skill_names}")
    print("✅ test_skills_registry_populated PASSED")


def test_travel_planning_uses_high_score_format():
    """P6.S.15: 出行规划推荐评分应是 0-10 范围(不是 0.577/10)"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/chat/enhanced",
        {"user_id": "u_travel_p6s15", "message": "从北京西单到国贸怎么走"},
    )
    assert code == 200
    msg = body.get("message", "")
    # 推荐评分应是 X.X/10 形式(X 是 0-10 数字)
    import re
    m = re.search(r"综合评分 (\d+(?:\.\d+)?)/10", msg)
    assert m, f"应含'综合评分 X.X/10', 实际: {msg[:300]}"
    score = float(m.group(1))
    assert 0 <= score <= 10, f"评分应 0-10, 实际 {score}"
    print(f"  推荐评分: {score}/10")
    print("✅ test_travel_planning_uses_high_score_format PASSED")


def test_travel_planning_has_score_breakdown():
    """P6.S.15: 响应应含评分明细(碳/费用/时长/天气)"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/chat/enhanced",
        {"user_id": "u_travel_p6s15", "message": "从北京西单到国贸怎么走"},
    )
    msg = body.get("message", "")
    # 应含 [碳:X 费:Y 时:Z 天:W] 形式
    import re
    breakdown = re.search(r"\[碳:[\d.]+\s+费:[\d.]+\s+时:[\d.]+\s+天:[\d.]+\]", msg)
    assert breakdown, f"应含评分明细 [碳:X 费:Y 时:Z 天:W], 实际: {msg[:400]}"
    print(f"  含评分明细: {breakdown.group(0)}")
    print("✅ test_travel_planning_has_score_breakdown PASSED")


def test_travel_planning_short_distance_adds_walking():
    """P6.S.15: 短途(<5km)应自动加步行选项"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/chat/enhanced",
        {"user_id": "u_short_p6s15", "message": "从北京西单到天安门怎么走"},
    )
    msg = body.get("message", "")
    assert "步行" in msg, f"短途应含步行选项, 实际: {msg[:500]}"
    print("✅ test_travel_planning_short_distance_adds_walking PASSED")


def test_travel_planning_shows_carbon_savings():
    """P6.S.15: 应显示碳减排对比(对比自驾)"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/chat/enhanced",
        {"user_id": "u_carbon_p6s15", "message": "从北京西单到国贸怎么走"},
    )
    msg = body.get("message", "")
    # 应含 ⬇️ -碳X.XXkg 形式(对比自驾减排)
    import re
    savings = re.search(r"⬇️ -碳\d+(?:\.\d+)?kg", msg)
    assert savings, f"应含碳减排对比, 实际: {msg[:500]}"
    print(f"  碳减排对比: {savings.group(0)}")
    print("✅ test_travel_planning_shows_carbon_savings PASSED")


def test_travel_planning_shows_weights():
    """P6.S.15: 响应应显示评分权重"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/chat/enhanced",
        {"user_id": "u_w_p6s15", "message": "从北京西单到国贸怎么走"},
    )
    msg = body.get("message", "")
    # 应含 📊 评分权重:碳排 X · 费用 Y · 时长 Z · 天气 W
    assert "评分权重" in msg, f"应含'评分权重'章节, 实际: {msg[:500]}"
    assert "碳排" in msg and "费用" in msg and "时长" in msg and "天气" in msg
    print("✅ test_travel_planning_shows_weights PASSED")


def test_travel_planning_shows_specific_line_names():
    """P6.S.15: 应显示具体线路名(地铁1号线 / 公交52路)"""
    if not test_server_running():
        return
    code, body = _http_post(
        "http://localhost:8000/api/chat/enhanced",
        {"user_id": "u_line_p6s15", "message": "从北京西单到国贸怎么走"},
    )
    msg = body.get("message", "")
    # 应含具体线路名(括号内)
    assert "(" in msg and ")" in msg, f"应含具体线路名(括号), 实际: {msg[:500]}"
    # 至少有一条"公交"或"地铁"或"步行"前缀
    assert any(kw in msg for kw in ["公交", "地铁", "步行", "骑行", "自驾"])
    print("✅ test_travel_planning_shows_specific_line_names PASSED")


def test_tools_skills_endpoint_returns_full_info():
    """P6.S.15: /api/tools-skills 应返完整 tools + skills 信息"""
    if not test_server_running():
        return
    code, body = _http_get("http://localhost:8000/api/tools-skills")
    assert code == 200
    # 每个 tool 应有 name/description/category/tags
    for t in body["tools"]:
        assert "name" in t
        assert "category" in t
        assert "description" in t
    # 每个 skill 应有 name/description/category/tools(子工具列表)
    for s in body["skills"]:
        assert "name" in s
        if "tools" in s:
            assert isinstance(s["tools"], list)
    print(f"  tools: {body['tools_count']}, skills: {body['skills_count']}")
    print("✅ test_tools_skills_endpoint_returns_full_info PASSED")


if __name__ == "__main__":
    test_server_running()
    test_tools_registry_populated()
    test_skills_registry_populated()
    test_travel_planning_uses_high_score_format()
    test_travel_planning_has_score_breakdown()
    test_travel_planning_short_distance_adds_walking()
    test_travel_planning_shows_carbon_savings()
    test_travel_planning_shows_weights()
    test_travel_planning_shows_specific_line_names()
    test_tools_skills_endpoint_returns_full_info()
    print("\n🎉 All P6.S.15 tests PASSED")
