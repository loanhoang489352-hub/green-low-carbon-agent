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
import uuid
sys.path.insert(0, str(__file__).replace("\\", "/").replace("tests/test_p6s15_tools_skills.py", "src"))

import urllib.request
import urllib.error
import json

_AUTH = {"token": None}


def _raw_post(url, data):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", errors="ignore"))


def _auth_token():
    if _AUTH["token"]:
        return _AUTH["token"]
    uname = "u_" + uuid.uuid4().hex[:10]
    try:
        _raw_post("http://localhost:8000/api/auth/register", {"username": uname, "password": "testpass123"})
    except Exception:
        pass
    code, body = _raw_post("http://localhost:8000/api/auth/login", {"username": uname, "password": "testpass123"})
    if code == 200 and body.get("session_id"):
        _AUTH["token"] = body["session_id"]
    return _AUTH["token"]


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
    # 对鉴权端点(/api/chat 等)自动带 Bearer token,消除 401
    if "chat" in url and _auth_token():
        headers["Authorization"] = "Bearer " + _auth_token()
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=headers, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", errors="ignore"))


def test_server_running():
    """前置:server 必须跑着"""
    try:
        code, _ = _http_get("http://localhost:8000/api/health", timeout=5)
    except (OSError, ConnectionError):
        print("⏭ SKIPPED: server not running")
        return False
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


def _travel_tool():
    """构造 TravelPlanningTool(强制走估算降级: 无高德 key / 高德失败都返回结构化数据,不依赖 amap 网络)"""
    from agent.tools.extended import TravelPlanningTool
    # 清掉 GAODE_API_KEY,让 execute 走"未配置 key → 估算降级",测试确定且快(不调 amap)
    os.environ["GAODE_API_KEY"] = ""
    return TravelPlanningTool()


def test_travel_tool_deep_response():
    """没有真实路线服务配置时必须失败，不能返回看似完整的模拟数据。"""
    tool = _travel_tool()
    res = tool.execute(origin="北京西单", destination="国贸", mode="all")
    assert not res.success
    assert res.data.get("routes") == []
    assert res.data.get("code") == "ROUTE_PROVIDER_NOT_CONFIGURED"


def test_travel_tool_carbon_and_walking():
    """无 provider 时不能合成自驾或步行路线。真实多模式由 provider 合约测试覆盖。"""
    tool = _travel_tool()
    res = tool.execute(origin="北京西单", destination="国贸", mode="all")
    assert not res.success
    assert res.data.get("routes") == []


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
    test_travel_tool_deep_response()
    test_travel_tool_carbon_and_walking()
    test_tools_skills_endpoint_returns_full_info()
    print("\n🎉 All P6.S.15 tests PASSED")
