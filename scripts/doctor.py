"""绿色低碳智能体 - 跨平台诊断工具

替代旧的 diagnose.bat。检查 Python 版本/.env 配置/核心依赖/外部 API 连通性。

用法:
    python scripts/doctor.py
    python scripts/doctor.py --skip-api  # 跳过外部 API 测试
"""

import sys
import os
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def header(title):
    print(f"\n{'=' * 50}\n {title}\n{'=' * 50}")


def check_python():
    header("[1/5] Python 版本")
    v = sys.version_info
    print(f"Python {v.major}.{v.minor}.{v.micro}")
    if v.minor < 12:
        print(f"  [WARN] 推荐 Python 3.12+,当前 3.{v.minor}")
        return False
    return True


def check_env():
    header("[2/5] .env 配置")
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        print(f"  [ERROR] .env 不存在(从 .env.example 复制并填写)")
        return False

    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except ImportError:
        print(f"  [WARN] 未安装 python-dotenv,手动 source .env")

    required = ["API_PROVIDER", "API_MODEL"]
    optional = {
        "MINIMAX_API_KEY": "MiniMax AI",
        "GAODE_API_KEY": "高德地图(出行规划)",
        "OPENAI_API_KEY": "OpenAI",
        "DEEPSEEK_API_KEY": "DeepSeek",
    }

    ok = True
    for k in required:
        v = os.environ.get(k, "")
        if not v or v.startswith("__"):
            print(f"  [ERROR] {k} 未配置")
            ok = False
        else:
            print(f"  [OK]    {k} = {v}")

    for k, label in optional.items():
        v = os.environ.get(k, "")
        if v and not v.startswith("__"):
            print(f"  [OK]    {k} ({label}) = {v[:20]}...")
        else:
            print(f"  [WARN]  {k} ({label}) 未配置")
    return ok


def check_deps():
    header("[3/5] 核心依赖")
    pkgs = [
        ("openai", "OpenAI 客户端"),
        ("langchain", "LangChain"),
        ("langgraph", "LangGraph 工作流"),
        ("chromadb", "向量数据库"),
        ("apscheduler", "调度器"),
        ("httpx", "HTTP 客户端(政策抓取)"),
        ("bs4", "BeautifulSoup(HTML 解析)"),
    ]
    ok = True
    for mod, label in pkgs:
        try:
            m = __import__(mod)
            v = getattr(m, "__version__", "?")
            print(f"  [OK]    {mod:14} {v:12} {label}")
        except ImportError:
            print(f"  [ERROR] {mod:14} 未安装   {label}")
            ok = False
    return ok


def check_llm():
    header("[4/5] LLM 连接")
    try:
        from llm.client import get_llm_client
        client = get_llm_client()
        resp = client.chat([{"role": "user", "content": "回复 OK 即可"}])
        # P5-A 后:client.chat() 返回 LLMResponse dataclass,统一用 .content
        if hasattr(resp, "content"):
            text = resp.content or ""
        elif isinstance(resp, str):
            text = resp
        else:
            text = str(resp)
        provider = getattr(client, "provider", getattr(client, "__class__", type("", (), {})).__name__)
        model = getattr(client, "model", "?")
        print(f"  [OK]    {provider}/{model}")
        print(f"  回复: {text[:80]}")
        return True
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")
        return False


def check_external_apis():
    header("[5/5] 外部 API(高德/天气)")
    ok = True

    if os.environ.get("GAODE_API_KEY"):
        try:
            from agent.tools.extended import TravelPlanningTool
            t = TravelPlanningTool()
            r = t.execute(origin="北京西站", destination="国贸")
            if r.success:
                rec = r.data.get("recommended", {})
                print(f"  [OK]    高德地图: {rec.get('type')} {rec.get('distance_km')}km")
            else:
                print(f"  [ERROR] 高德地图: {r.error}")
                ok = False
        except Exception as e:
            print(f"  [ERROR] 高德地图: {e}")
            ok = False
    else:
        print(f"  [SKIP]  高德地图(未配置 GAODE_API_KEY)")

    try:
        from utils.web_search import WebSearcher
        ws = WebSearcher()
        r = ws.fetch_weather_from_api("北京")
        if "获取天气信息失败" not in r:
            print(f"  [OK]    Open-Meteo 天气")
        else:
            print(f"  [ERROR] Open-Meteo: {r[:60]}")
            ok = False
    except Exception as e:
        print(f"  [ERROR] Open-Meteo: {e}")
        ok = False
    return ok


def main():
    parser = argparse.ArgumentParser(description="绿色低碳智能体诊断")
    parser.add_argument("--skip-api", action="store_true", help="跳过外部 API 测试")
    args = parser.parse_args()

    results = [
        ("Python", check_python()),
        (".env", check_env()),
        ("依赖", check_deps()),
        ("LLM", check_llm()),
    ]
    if not args.skip_api:
        results.append(("外部 API", check_external_apis()))

    header("总结")
    failed = [k for k, ok in results if not ok]
    if not failed:
        print("  [OK] 全部通过,可以启动 agent.bat")
        return 0
    print(f"  [FAIL] {len(failed)} 项失败: {', '.join(failed)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
