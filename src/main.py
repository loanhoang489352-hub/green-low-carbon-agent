"""
绿色低碳智能体 - 主入口
使用Python内置http.server，纯Python实现
支持 RAG、个性化推荐和用户引导
"""

import os
import sys
from pathlib import Path

# Windows UTF-8 encoding setup - BEFORE any imports
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 设置UTF-8编码环境
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONWARNINGS"] = "ignore"

print("[DEBUG] main.py started", flush=True)

print("[DEBUG] main.py started", flush=True)

# 加载 .env 配置文件
script_path_for_env = Path(__file__).resolve()
project_root_for_env = script_path_for_env.parent.parent
env_file = project_root_for_env / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file)
        print("[环境] 已加载 .env 文件", flush=True)
    except ImportError:
        # 手动解析 .env 文件
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()
        print("[环境] 已手动加载 .env 文件", flush=True)
else:
    print(f"[环境] .env 文件不存在: {env_file}", flush=True)

print("[DEBUG] Encoding setup done", flush=True)

import uuid
from http.server import ThreadingHTTPServer

# 常量
MAX_BODY_SIZE = 2_000_000  # 单次请求 body 最大 2MB(P5-D: RoutedRequestHandler 用)
DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000"

print("[DEBUG] Imports done", flush=True)

script_path = Path(__file__).resolve()
print(f"[DEBUG] script_path: {script_path}", flush=True)

project_root = script_path.parent.parent
src_path = script_path.parent

print(f"[DEBUG] project_root: {project_root}", flush=True)
print(f"[DEBUG] src_path: {src_path}", flush=True)

if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
    print("[DEBUG] Added src to sys.path", flush=True)

os.chdir(str(src_path))
print(f"[DEBUG] Changed directory to: {os.getcwd()}", flush=True)

# 延迟导入，避免启动时就卡住
agent_instance = None


def get_agent():
    """延迟加载 Agent 实例"""
    global agent_instance
    if agent_instance is None:
        print("[启动] 正在初始化智能体...", flush=True)
        try:
            print("[DEBUG] Importing agent.core...", flush=True)
            from agent.core import GreenAgent

            print("[DEBUG] GreenAgent imported", flush=True)
            print("[启动] 正在创建 GreenAgent 实例...", flush=True)

            use_langgraph = os.environ.get("USE_LANGGRAPH", "false").lower() == "true"
            use_react = os.environ.get("LANGGRAPH_MODE", "") == "react"

            agent_instance = GreenAgent(
                knowledge_base_path=str(project_root / "knowledge_base"),
                enable_rag=True,
                use_llm=True,
            )

            if use_langgraph and agent_instance.langgraph_agent:
                agent_instance.langgraph_agent.use_react = use_react
                agent_instance.langgraph_agent._init_graph()
                print(f"[启动] LangGraph 引擎已初始化 (ReAct: {use_react})")

            print("[启动] 智能体初始化完成", flush=True)
        except Exception as e:
            print(f"[启动] 智能体初始化失败: {e}", flush=True)
            import traceback

            traceback.print_exc()
            raise
    return agent_instance


_policy_updater_instance = None
_feedback_manager_instance = None
_account_manager_instance = None


def get_policy_updater():
    """延迟加载 PolicyUpdater 实例"""
    global _policy_updater_instance
    if _policy_updater_instance is None:
        from policy.updater import PolicyUpdater

        _policy_updater_instance = PolicyUpdater()
        _policy_updater_instance.add_sample_policies()
    return _policy_updater_instance


def get_feedback_manager():
    """延迟加载 FeedbackManager 实例"""
    global _feedback_manager_instance
    if _feedback_manager_instance is None:
        from feedback.feedback_manager import FeedbackManager

        _feedback_manager_instance = FeedbackManager()
    return _feedback_manager_instance


def get_account_manager():
    """延迟加载 AccountManager 实例"""
    global _account_manager_instance
    if _account_manager_instance is None:
        from auth.account_manager import AccountManager

        _account_manager_instance = AccountManager()
    return _account_manager_instance


def run_server(host="0.0.0.0", port=8000):
    """运行服务器(P5-D: 使用 RoutedRequestHandler 走 RouterRegistry)"""
    print("\n[AGENT] 绿色低碳智能体正在启动...", flush=True)
    print("[提示] 服务器将立即启动，收到请求时再加载模型", flush=True)

    # P5-B: 启动时初始化结构化日志
    from observability import setup_logging

    log_file_path = None
    try:
        from paths import DATA_DIR

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log_file_path = str(DATA_DIR / "logs" / "app.log")
    except Exception:
        pass
    setup_logging(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        log_file=log_file_path,
        also_stdout=True,
    )
    if log_file_path:
        print(f"[P5-B] 结构化日志已启用 -> {log_file_path}", flush=True)

    # P5-D: 初始化路由 + 订阅 + 调度
    from server.app import init_app

    HandlerClass = init_app()
    print("[P5-D] RoutedRequestHandler 初始化完成,所有路由已注册", flush=True)

    print("[DEBUG] Creating HTTPServer...", flush=True)
    server = ThreadingHTTPServer((host, port), HandlerClass)
    print(f"[DEBUG] HTTPServer created on {(host, port)}", flush=True)

    print("\n" + "=" * 50, flush=True)
    print("[AGENT] 绿色低碳智能体 v2.0 启动成功！", flush=True)
    print("=" * 50, flush=True)
    print(f"   服务地址: http://localhost:{port}", flush=True)
    print("   按 Ctrl+C 停止服务", flush=True)
    print("=" * 50 + "\n", flush=True)

    try:
        # P5-J: 注册 SIGTERM / SIGINT 优雅退出(委托给 lifecycle 模块)
        # SIGTERM = K8s / docker stop / systemctl stop
        # SIGINT  = Ctrl+C / docker-compose down
        import threading
        from server.lifecycle import install_signal_handlers

        shutdown_event = threading.Event()

        # 注册 SIGTERM / SIGINT / SIGBREAK(幂等)
        installed = install_signal_handlers(server=server, timeout_s=10.0)
        if installed:
            import logging

            logging.getLogger(__name__).info(
                "[Server] P5-J 优雅退出已启用 (SIGTERM/SIGINT → 等 inflight ≤10s → 关闭 server/scheduler/DB)"
            )

        # serve_forever() 阻塞,直到 server.shutdown() 被调用
        server.serve_forever()
        # 等待信号 handler 走完(确保日志落盘)
        shutdown_event.wait(timeout=2.0)
    except KeyboardInterrupt:
        # 兜底:Windows 某些场景 signal 不能完全注册,走 KeyboardInterrupt
        print("\n\n服务已停止")
        try:
            from server.lifecycle import graceful_shutdown

            graceful_shutdown(server=server, timeout_s=5.0)
        except Exception:
            try:
                server.shutdown()
            except Exception:
                pass


def run_cli():
    """运行命令行界面"""
    print("\n[AGENT] 绿色低碳智能体 (命令行模式)")
    print("=" * 50)
    print("输入 'quit' 或 'exit' 退出程序")
    print("输入 'profile' 查看用户画像")
    print("输入 'stats' 查看统计信息")
    print("输入 'onboarding' 开始引导流程")
    print("=" * 50)

    agent = get_agent()

    policy_updater = get_policy_updater()
    policy_updater.add_sample_policies()

    user_id = str(uuid.uuid4())[:8]
    conversation_id = None

    while True:
        try:
            user_input = input("\n你: ").strip()

            if user_input.lower() in ["quit", "exit", "退出"]:
                print("\n感谢使用！再见！")
                break

            if user_input.lower() == "profile":
                profile = agent.get_user_profile(user_id)
                print("\n[STAT] 你的用户画像:")
                eco = profile.get("eco_profile", {})
                print(f"   - 环保认知水平: {eco.get('knowledge_level')}")
                print(f"   - 行为阶段: {eco.get('behavior_stage')}")
                print(f"   - 关注领域: {', '.join(eco.get('primary_interests', []))}")
                continue

            if user_input.lower() == "stats":
                kb_stats = agent.get_knowledge_stats()
                print("\n[KB] 知识库统计:")
                print(f"   - 文档总数: {kb_stats.get('total_documents')}")
                continue

            if user_input.lower() == "onboarding":
                status = agent.start_onboarding(user_id)
                print(f"\n引导状态: {status}")
                continue

            if not user_input:
                continue

            response = agent.chat_enhanced(user_id, user_input, conversation_id)
            conversation_id = response.conversation_id

            print("\n🤖 助手:")
            print(response.message)

            if response.personalization_info:
                ctx = response.personalization_info
                print(
                    f"\n📌 个性化信息: {ctx.get('knowledge_level')} | {ctx.get('behavior_stage')}阶段"
                )

            if response.recommendations:
                print("\n[TIP] 为你推荐:")
                for i, rec in enumerate(response.recommendations[:2], 1):
                    print(f"   {i}. {rec['action']}")

            if response.suggestions:
                print("\n🔄 你可以尝试:")
                for i, suggestion in enumerate(response.suggestions[:3], 1):
                    print(f"   {i}. {suggestion}")

        except KeyboardInterrupt:
            print("\n\n程序被用户中断，再见！")
            break
        except Exception as e:
            print(f"\n发生错误: {e}")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="绿色低碳智能体")
    parser.add_argument("--host", default="0.0.0.0", help="服务器地址")
    parser.add_argument("--port", type=int, default=8000, help="服务器端口")
    parser.add_argument("--cli", action="store_true", help="使用命令行模式")
    parser.add_argument("--use-langgraph", action="store_true", help="使用 LangGraph 架构")
    parser.add_argument("--no-langgraph", action="store_true", help="强制关闭 LangGraph(覆盖 .env)")
    parser.add_argument("--use-react", action="store_true", help="使用 ReAct 模式的 LangGraph")

    args = parser.parse_args()

    if args.no_langgraph:
        os.environ["USE_LANGGRAPH"] = "false"
        os.environ["LANGGRAPH_MODE"] = ""
    elif args.use_langgraph or args.use_react:
        os.environ["USE_LANGGRAPH"] = "true"
        if args.use_react:
            os.environ["LANGGRAPH_MODE"] = "react"
    print(
        f"[启动] LangGraph 模式: USE_LANGGRAPH={os.environ.get('USE_LANGGRAPH', 'false')}, MODE={os.environ.get('LANGGRAPH_MODE', '')}"
    )

    if args.cli:
        run_cli()
    else:
        run_server(host=args.host, port=args.port)
