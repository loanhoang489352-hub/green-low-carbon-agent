"""
P11.C 测试: ${ENV_VAR} 占位符展开 + 真实 MCP server 配置解析

覆盖:
1. _expand_env_in_string 单元测试(命中 / 未命中 / 多次 / 嵌套)
2. _expand_env_in_mapping 单元测试
3. expand_mcp_yaml_placeholders 递归展开(dict / list / string)
4. MCPRegistry.load_config 加载含 ${GITHUB_TOKEN} 占位符的 yaml
5. MCPRegistry 加载含 OAuth 字段(notion 模板)的 yaml
6. StreamableHTTPClientConfig 的 headers / oauth_token 已被展开
7. yaml 中 disabled server 不会触发网络请求(只是配置解析,不应 raise)

不依赖真实 GITHUB_TOKEN / NOTION_TOKEN — 测试通过 monkeypatch.environ 注入临时变量
"""
import os
import sys
import tempfile
import textwrap
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


# ============ 单元测试:env 占位符展开 ============

def test_expand_simple_var():
    """单个 ${VAR} 展开"""
    from mcp.streamable_client import _expand_env_in_string

    with mock.patch.dict(os.environ, {"FOO_TEST_VAR": "bar_value"}):
        assert _expand_env_in_string("hello ${FOO_TEST_VAR}") == "hello bar_value"
    print("✅ test_expand_simple_var PASSED")


def test_expand_multiple_vars():
    """多个 ${VAR} 一次展开"""
    from mcp.streamable_client import _expand_env_in_string

    with mock.patch.dict(os.environ, {"VAR_A": "AAA", "VAR_B": "BBB"}):
        s = "${VAR_A} - ${VAR_B} - ${VAR_A}"
        expanded = _expand_env_in_string(s)
        assert expanded == "AAA - BBB - AAA"
    print("✅ test_expand_multiple_vars PASSED")


def test_expand_missing_var_preserves_placeholder():
    """env 不存在时保留原占位符(便于 debug)"""
    from mcp.streamable_client import _expand_env_in_string

    with mock.patch.dict(os.environ, {}, clear=True):
        # 清空 env 后,${SOMETHING_DEFINITELY_NOT_SET_xxx} 应保留
        result = _expand_env_in_string("Bearer ${SOMETHING_DEFINITELY_NOT_SET_xxx}")
        assert result == "Bearer ${SOMETHING_DEFINITELY_NOT_SET_xxx}"
    print("✅ test_expand_missing_var_preserves_placeholder PASSED")


def test_expand_passthrough_non_string():
    """非 string 类型直接返回"""
    from mcp.streamable_client import _expand_env_in_string

    assert _expand_env_in_string(None) is None
    assert _expand_env_in_string(123) == 123
    assert _expand_env_in_string(["${VAR}"]) == ["${VAR}"]  # list 不递归
    assert _expand_env_in_string({"k": "v"}) == {"k": "v"}
    print("✅ test_expand_passthrough_non_string PASSED")


def test_expand_no_placeholder():
    """无占位符字符串原样返回"""
    from mcp.streamable_client import _expand_env_in_string

    assert _expand_env_in_string("just plain text") == "just plain text"
    assert _expand_env_in_string("") == ""
    print("✅ test_expand_no_placeholder PASSED")


def test_expand_mapping():
    """dict 形式展开(用于 headers)"""
    from mcp.streamable_client import _expand_env_in_mapping

    with mock.patch.dict(os.environ, {"MY_TOKEN": "ghp_xxx", "OTHER": "y"}):
        result = _expand_env_in_mapping(
            {
                "Authorization": "Bearer ${MY_TOKEN}",
                "X-Other": "${OTHER}",
                "Plain": "no-var",
            }
        )
        assert result == {
            "Authorization": "Bearer ghp_xxx",
            "X-Other": "y",
            "Plain": "no-var",
        }
    print("✅ test_expand_mapping PASSED")


def test_recursive_expand_yaml_dict():
    """递归展开 dict / list / string 嵌套结构"""
    from mcp.streamable_client import expand_mcp_yaml_placeholders

    with mock.patch.dict(os.environ, {"X_TOKEN": "tok123", "Y_URL": "https://api.example.com"}):
        yaml_like = {
            "name": "test",
            "url": "${Y_URL}/mcp",
            "headers": {
                "Authorization": "Bearer ${X_TOKEN}",
                "X-Custom": "literal",
            },
            "oauth_client_id": "${X_TOKEN}",
            "tags": ["${Y_URL}", "static"],
            "timeout": 30,  # 数字不动
        }
        result = expand_mcp_yaml_placeholders(yaml_like)
        assert result["url"] == "https://api.example.com/mcp"
        assert result["headers"]["Authorization"] == "Bearer tok123"
        assert result["headers"]["X-Custom"] == "literal"
        assert result["oauth_client_id"] == "tok123"
        assert result["tags"][0] == "https://api.example.com"
        assert result["tags"][1] == "static"
        assert result["timeout"] == 30  # 数字原样
        assert result["name"] == "test"
    print("✅ test_recursive_expand_yaml_dict PASSED")


# ============ MCPRegistry.load_config 集成测试 ============

def test_registry_loads_github_mcp_config():
    """MCPRegistry 能解析含 ${GITHUB_TOKEN} 的 GitHub MCP 配置"""
    from mcp import MCPRegistry
    from mcp.streamable_client import StreamableHTTPClientConfig

    yaml_text = textwrap.dedent("""
        mcp_servers:
          - name: github
            transport: streamable-http
            url: https://api.githubcopilot.com/mcp/
            headers:
              Authorization: Bearer ${GITHUB_TOKEN}
            enabled: false
    """).strip()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_text)
        path = f.name
    try:
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_test123abc"}):
            reg = MCPRegistry()
            configs = reg.load_config(path)
        assert len(configs) == 1
        cfg = configs[0]
        assert isinstance(cfg, StreamableHTTPClientConfig)
        assert cfg.name == "github"
        assert cfg.url == "https://api.githubcopilot.com/mcp/"
        assert cfg.headers["Authorization"] == "Bearer ghp_test123abc", \
            f"token 应被展开, 实际: {cfg.headers}"
        assert cfg.enabled is False
        assert cfg.transport == "streamable-http"
    finally:
        os.unlink(path)
    print("✅ test_registry_loads_github_mcp_config PASSED")


def test_registry_loads_notion_mcp_template():
    """MCPRegistry 能解析含 OAuth 字段的 Notion MCP 模板"""
    from mcp import MCPRegistry
    from mcp.streamable_client import StreamableHTTPClientConfig

    yaml_text = textwrap.dedent("""
        mcp_servers:
          - name: notion
            transport: streamable-http
            url: https://mcp.notion.com/mcp
            oauth_token: ${NOTION_TOKEN}
            oauth_client_id: ${NOTION_CLIENT_ID}
            oauth_client_secret: ${NOTION_CLIENT_SECRET}
            enabled: false
    """).strip()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_text)
        path = f.name
    try:
        with mock.patch.dict(
            os.environ,
            {
                "NOTION_TOKEN": "secret_abc",
                "NOTION_CLIENT_ID": "client_xyz",
                "NOTION_CLIENT_SECRET": "secret_xyz",
            },
        ):
            reg = MCPRegistry()
            configs = reg.load_config(path)
        assert len(configs) == 1
        cfg = configs[0]
        assert isinstance(cfg, StreamableHTTPClientConfig)
        assert cfg.oauth_token == "secret_abc"
        assert cfg.oauth_client_id == "client_xyz"
        assert cfg.oauth_client_secret == "secret_xyz"
        assert cfg.enabled is False
    finally:
        os.unlink(path)
    print("✅ test_registry_loads_notion_mcp_template PASSED")


def test_registry_github_token_missing_keeps_placeholder():
    """env 没设时,${GITHUB_TOKEN} 保留原样(便于用户发现漏配)"""
    from mcp import MCPRegistry
    from mcp.streamable_client import StreamableHTTPClientConfig

    yaml_text = textwrap.dedent("""
        mcp_servers:
          - name: github
            transport: streamable-http
            url: https://api.githubcopilot.com/mcp/
            headers:
              Authorization: Bearer ${GITHUB_TOKEN}
            enabled: false
    """).strip()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_text)
        path = f.name
    try:
        # 确保 GITHUB_TOKEN 未设
        env_backup = os.environ.pop("GITHUB_TOKEN", None)
        try:
            reg = MCPRegistry()
            configs = reg.load_config(path)
            cfg = configs[0]
            assert cfg.headers["Authorization"] == "Bearer ${GITHUB_TOKEN}", \
                "未设 env 时应保留占位符"
        finally:
            if env_backup is not None:
                os.environ["GITHUB_TOKEN"] = env_backup
    finally:
        os.unlink(path)
    print("✅ test_registry_github_token_missing_keeps_placeholder PASSED")


def test_registry_loads_real_mcp_yaml_file():
    """生产 yaml 文件 config/mcp_servers.yaml 应能正确加载(github + notion disabled)"""
    from mcp import MCPRegistry

    real_yaml = ROOT / "config" / "mcp_servers.yaml"
    assert real_yaml.exists(), f"生产 yaml 不存在: {real_yaml}"
    # 不依赖真实 token — 即使没设,disabled server 也能正确加载
    reg = MCPRegistry()
    configs = reg.load_config(str(real_yaml))
    names = {c.name for c in configs}
    # mock_server (stdio) + mock_http_server (disabled http) + github (disabled) + notion (disabled)
    assert "mock_server" in names
    assert "mock_http_server" in names
    assert "github" in names
    assert "notion" in names
    # github / notion 默认 enabled=false
    by_name = {c.name: c for c in configs}
    assert by_name["github"].enabled is False
    assert by_name["notion"].enabled is False
    assert by_name["github"].transport == "streamable-http"
    assert by_name["notion"].transport == "streamable-http"
    print("✅ test_registry_loads_real_mcp_yaml_file PASSED")


def test_registry_github_url_and_origin_correct():
    """github MCP 配置的 url / origin 应符合预期"""
    from mcp import MCPRegistry

    real_yaml = ROOT / "config" / "mcp_servers.yaml"
    reg = MCPRegistry()
    configs = reg.load_config(str(real_yaml))
    github_cfg = next(c for c in configs if c.name == "github")
    assert github_cfg.url.startswith("https://api.githubcopilot.com")
    assert github_cfg.origin == "https://green-low-carbon-agent.local"
    assert github_cfg.verify_ssl is True
    # notion
    notion_cfg = next(c for c in configs if c.name == "notion")
    assert notion_cfg.url == "https://mcp.notion.com/mcp"
    print("✅ test_registry_github_url_and_origin_correct PASSED")


if __name__ == "__main__":
    test_expand_simple_var()
    test_expand_multiple_vars()
    test_expand_missing_var_preserves_placeholder()
    test_expand_passthrough_non_string()
    test_expand_no_placeholder()
    test_expand_mapping()
    test_recursive_expand_yaml_dict()
    test_registry_loads_github_mcp_config()
    test_registry_loads_notion_mcp_template()
    test_registry_github_token_missing_keeps_placeholder()
    test_registry_loads_real_mcp_yaml_file()
    test_registry_github_url_and_origin_correct()
    print("\n🎉 All P11.C real MCP config tests PASSED")