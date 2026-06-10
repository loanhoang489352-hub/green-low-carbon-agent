"""
绿色低碳智能体 - 主入口
使用Python内置http.server，纯Python实现
支持 RAG、个性化推荐和用户引导
"""

import os
import sys
from pathlib import Path

# Windows UTF-8 encoding setup - BEFORE any imports
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

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
        print(f"[环境] 已加载 .env 文件", flush=True)
    except ImportError:
        # 手动解析 .env 文件
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()
        print(f"[环境] 已手动加载 .env 文件", flush=True)
else:
    print(f"[环境] .env 文件不存在: {env_file}", flush=True)

print("[DEBUG] Encoding setup done", flush=True)

import json
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# 常量
MAX_BODY_SIZE = 2_000_000  # 单次请求 body 最大 2MB
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
                use_llm=True
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


print("[DEBUG] Defining RequestHandler class...", flush=True)


class RequestHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器"""

    @property
    def agent(self):
        """延迟获取 agent"""
        return get_agent()

    @property
    def policy_updater(self):
        """延迟获取 policy_updater"""
        return get_policy_updater()

    def do_GET(self):
        """处理GET请求"""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.serve_html()
        elif path == "/api/knowledge/stats":
            self.send_json(self.agent.get_knowledge_stats())
        elif path == "/api/rag/stats":
            rag_stats = self.agent.get_rag_stats()
            self.send_json(rag_stats)
        elif path == "/api/policy/latest":
            limit = int(parse_qs(parsed.query).get('limit', [10])[0])
            self.send_json(self.policy_updater.get_latest_policies(limit=limit))
        elif path == "/api/policy/summary":
            self.send_json({"summary": self.policy_updater.generate_policy_summary()})
        elif path == "/api/health":
            self.send_json({
                "status": "healthy",
                "version": "2.0.0",
                "rag_enabled": self.agent.rag_enabled,
                "features": {
                    "personalization": True,
                    "onboarding": True,
                    "dynamic_updates": True
                }
            })
        elif path.startswith("/api/profile/"):
            user_id = path.split("/")[-1]
            profile = self.agent.get_user_profile(user_id)
            self.send_json({"user_id": user_id, "profile": profile})
        elif path.startswith("/api/personalization/"):
            user_id = path.split("/")[-1]
            ctx = self.agent.get_personalization_context(user_id)
            self.send_json({"user_id": user_id, "context": ctx})
        elif path.startswith("/api/stats/"):
            user_id = path.split("/")[-1]
            stats = self.agent.get_user_stats(user_id)
            self.send_json({"user_id": user_id, "stats": stats})
        elif path.startswith("/api/conversation/"):
            conv_id = path.split("/")[-1]
            history = self.agent.get_conversation_history(conv_id)
            self.send_json({"history": history})
        elif path == "/api/onboarding/questions":
            questions = self.agent.profile_manager.get_onboarding_questions()
            self.send_json({"questions": questions})
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        """处理POST请求"""
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > MAX_BODY_SIZE:
            self.send_error(413, f"Request body too large (max {MAX_BODY_SIZE} bytes)")
            return
        if content_length < 0:
            self.send_error(400, "Invalid Content-Length")
            return
        body = self.rfile.read(content_length).decode('utf-8')

        try:
            data = json.loads(body)
        except Exception as e:
            print(f"[错误] JSON解析失败: {e}, body: {body[:100] if body else 'empty'}")
            self.send_error(400, "Invalid JSON")
            return

        # 用户注册
        if path == "/api/user/register":
            user_info = data.get("user_info", {})
            try:
                user_id = self.agent.register_user(user_info)
                self.send_json({
                    "user_id": user_id,
                    "status": "registered"
                })
            except Exception as e:
                print(f"[错误] 注册失败: {e}")
                self.send_error(500, f"注册失败: {str(e)}")

        # 获取/更新引导状态
        elif path == "/api/onboarding/status":
            user_id = data.get("user_id")
            if not user_id:
                self.send_error(400, "user_id required")
                return
            status = self.agent.get_onboarding_status(user_id)
            self.send_json(status)

        # 开始引导
        elif path == "/api/onboarding/start":
            user_id = data.get("user_id")
            if not user_id:
                self.send_error(400, "user_id required")
                return
            result = self.agent.start_onboarding(user_id)
            self.send_json(result)

        # 回答引导问题 - 兼容临时用户
        elif path == "/api/onboarding/answer":
            user_id = data.get("user_id")
            step = data.get("step")
            answer = data.get("answer")

            if not user_id or user_id.startswith("temp_"):
                # 临时用户，创建一个真正的用户ID
                user_id = str(uuid.uuid4())[:12]
                print(f"[Onboarding] 创建新用户ID: {user_id}")

            if step is None:
                self.send_error(400, "step required")
                return

            result = self.agent.process_onboarding_answer(user_id, step, answer)
            self.send_json({"user_id": user_id, **result})

        # 更新用户画像
        elif path == "/api/user/update":
            user_id = data.get("user_id")
            profile_data = data.get("profile", {})
            if user_id:
                self.agent.profile_manager.update_profile(user_id, profile_data)
                self.send_json({"status": "updated"})
            else:
                self.send_error(400, "user_id required")

        # 基础聊天
        elif path == "/api/chat":
            user_id = data.get("user_id", "anonymous")
            message = data.get("message", "")
            conversation_id = data.get("conversation_id")

            if not message:
                self.send_error(400, "Message is required")
                return

            try:
                print(f"[Chat] 收到请求: user_id={user_id}, message={message[:50]}...")
                response = self.agent.chat(user_id, message, conversation_id)
                print(f"[Chat] 回复已生成: {len(response.message)} 字符")
                self.send_json({
                    "message": response.message,
                    "conversation_id": response.conversation_id,
                    "intent": response.intent,
                    "suggestions": response.suggestions,
                    "knowledge_refs": response.knowledge_refs,
                    "timestamp": response.timestamp
                })
            except Exception as e:
                import traceback
                print(f"[错误] agent.chat失败: {e}")
                traceback.print_exc()
                self.send_error(500, f"Internal error: {str(e)}")

        # 增强版聊天（RAG + 个性化）
        elif path == "/api/chat/enhanced":
            user_id = data.get("user_id", "anonymous")
            message = data.get("message", "")
            conversation_id = data.get("conversation_id")

            if not message:
                self.send_error(400, "Message is required")
                return

            try:
                response = self.agent.chat_enhanced(user_id, message, conversation_id)
                self.send_json({
                    "message": response.message,
                    "conversation_id": response.conversation_id,
                    "intent": response.intent,
                    "suggestions": response.suggestions,
                    "knowledge_refs": response.knowledge_refs,
                    "timestamp": response.timestamp,
                    "personalization": response.personalization_info,
                    "recommendations": response.recommendations,
                    "profile_updates": response.profile_updates
                })
            except Exception as e:
                import traceback
                print(f"[错误] agent.chat_enhanced失败: {e}")
                traceback.print_exc()
                self.send_error(500, f"Internal error: {str(e)}")

        # 重置对话
        elif path == "/api/conversation/reset":
            conv_id = data.get("conversation_id")
            if conv_id:
                self.agent.reset_conversation(conv_id)
            self.send_json({"status": "success"})

        # 政策更新检查
        elif path == "/api/policy/check-updates":
            result = self.policy_updater.check_updates()
            self.send_json(result)

        # 获取用户个性化上下文
        elif path == "/api/personalization/context":
            user_id = data.get("user_id")
            if not user_id:
                self.send_error(400, "user_id required")
                return
            ctx = self.agent.get_personalization_context(user_id)
            self.send_json({"context": ctx})

        # 获取推荐
        elif path == "/api/recommendations":
            user_id = data.get("user_id", "anonymous")
            profile = self.agent.get_user_profile(user_id)
            from user_profile.personalized_recommender import PersonalizedRecommendationEngine
            engine = PersonalizedRecommendationEngine()
            recs = engine.generate_recommendations(profile, count=3)
            self.send_json({
                "recommendations": [
                    {
                        "action": r.action,
                        "category": r.category,
                        "reason": r.reason,
                        "carbon_saving": r.estimated_carbon_saving,
                        "difficulty": r.difficulty,
                        "impact": r.impact,
                        "examples": r.examples
                    }
                    for r in recs
                ]
            })

        # 保存 API Key / 模型设置
        elif path == "/api/settings/api-key":
            import os
            api_key = data.get("api_key")
            provider = data.get("provider", "openai")
            model = data.get("model")

            if api_key:
                os.environ["API_PROVIDER"] = provider
                # 根据不同的提供商设置正确的环境变量
                provider_key_map = {
                    "openai": "OPENAI_API_KEY",
                    "minimax": "MINIMAX_API_KEY",
                    "zhipu": "ZHIPU_API_KEY",
                    "baidu": "BAIDU_API_KEY",
                    "ali": "ALI_API_KEY",
                    "deepseek": "DEEPSEEK_API_KEY"
                }
                key_name = provider_key_map.get(provider, "OPENAI_API_KEY")
                os.environ[key_name] = api_key

                if model:
                    os.environ["API_MODEL"] = model
                else:
                    # 设置默认模型
                    default_models = {
                        "openai": "gpt-4o-mini",
                        "minimax": "abab6.5s",
                        "zhipu": "glm-4-flash",
                        "baidu": "ernie-4.0-8k",
                        "ali": "qwen-plus",
                        "deepseek": "deepseek-chat"
                    }
                    os.environ["API_MODEL"] = default_models.get(provider, "gpt-4o-mini")

                # 将设置写入 .env 文件
                env_path = project_root / ".env"
                try:
                    with open(env_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()

                    # 更新对应的行
                    updated_lines = []
                    for line in lines:
                        stripped = line.strip()
                        if stripped.startswith("API_PROVIDER="):
                            updated_lines.append(f"API_PROVIDER={provider}\n")
                        elif stripped.startswith("API_MODEL="):
                            updated_lines.append(f"API_MODEL={os.environ.get('API_MODEL')}\n")
                        elif stripped.startswith(f"{key_name}="):
                            updated_lines.append(f"{key_name}={api_key}\n")
                        else:
                            updated_lines.append(line)

                    with open(env_path, "w", encoding="utf-8") as f:
                        f.writelines(updated_lines)

                    print(f"[Settings] 配置已保存到 .env 文件")
                except Exception as e:
                    print(f"[Settings] 保存到 .env 文件失败: {e}")

                # 重置 LLM 客户端以应用新设置
                from llm import reset_llm_client
                reset_llm_client()

                print(f"[Settings] 提供商: {provider}, 模型: {os.environ.get('API_MODEL')}, Key: {key_name}")
                self.send_json({"status": "saved", "message": "设置已保存到 .env 文件", "model": os.environ.get("API_MODEL")})
            else:
                self.send_error(400, "api_key required")

        # 提交反馈
        elif path == "/api/feedback":
            message_id = data.get("message_id")
            feedback_type = data.get("type")
            reason = data.get("reason")
            comment = data.get("comment")

            if not message_id or not feedback_type:
                self.send_error(400, "message_id and type are required")
                return

            feedback_mgr = get_feedback_manager()
            result = feedback_mgr.add_feedback(
                message_id=message_id,
                user_id=data.get("user_id", "anonymous"),
                conversation_id=data.get("conversation_id"),
                feedback_type=feedback_type,
                reason=reason,
                comment=comment
            )

            if result.get("success"):
                self.send_json({"status": "success", "action": result.get("action")})
            else:
                self.send_error(400, result.get("error", "Feedback failed"))

        # 获取消息反馈统计
        elif path == "/api/feedback/message":
            message_id = data.get("message_id")
            if not message_id:
                self.send_error(400, "message_id is required")
                return

            feedback_mgr = get_feedback_manager()
            stats = feedback_mgr.get_message_feedback(message_id)
            user_status = feedback_mgr.check_user_feedback(message_id, data.get("user_id", "anonymous"))
            stats["user_status"] = user_status
            self.send_json(stats)

        # 注册账号
        elif path == "/api/auth/register":
            username = data.get("username")
            password = data.get("password")

            if not username or not password:
                self.send_error(400, "用户名和密码必填")
                return

            account_mgr = get_account_manager()
            result = account_mgr.register(username, password)

            if result.get("success"):
                self.send_json({
                    "status": "success",
                    "account_id": result.get("account_id"),
                    "username": result.get("username")
                })
            else:
                self.send_error(400, result.get("error", "注册失败"))

        # 登录
        elif path == "/api/auth/login":
            username = data.get("username")
            password = data.get("password")

            if not username or not password:
                self.send_error(400, "用户名和密码必填")
                return

            account_mgr = get_account_manager()
            result = account_mgr.login(username, password)

            if result.get("success"):
                account_id = result.get("account_id")

                # 检查是否已有关联的用户画像
                user_id = account_mgr.get_user_id_by_account(account_id)
                if not user_id:
                    # 自动创建用户画像
                    agent = get_agent()
                    user_id = agent.register_user(account_id=account_id)

                self.send_json({
                    "status": "success",
                    "session_id": result.get("session_id"),
                    "account_id": account_id,
                    "username": result.get("username"),
                    "user_id": user_id,
                    "expires_at": result.get("expires_at")
                })
            else:
                self.send_error(401, result.get("error", "登录失败"))

        # 登出
        elif path == "/api/auth/logout":
            session_id = data.get("session_id")
            if session_id:
                get_account_manager().logout(session_id)
            self.send_json({"status": "success"})

        # 验证会话
        elif path == "/api/auth/check":
            session_id = data.get("session_id")
            if not session_id:
                self.send_json({"valid": False, "error": "session_id required"})
                return

            account_mgr = get_account_manager()
            account_id = account_mgr.validate_session(session_id)

            if account_id:
                info = account_mgr.get_account_info(account_id)
                if info:
                    self.send_json({
                        "valid": True,
                        "account_id": account_id,
                        "username": info.get("username")
                    })
                else:
                    self.send_json({"valid": False})
            else:
                self.send_json({"valid": False})

        # 获取会话信息
        elif path == "/api/auth/session":
            session_id = data.get("session_id")
            if not session_id:
                self.send_error(400, "session_id required")
                return

            account_mgr = get_account_manager()
            session_info = account_mgr.get_session_info(session_id)

            if session_info:
                self.send_json({"status": "success", "session": session_info})
            else:
                self.send_json({"status": "success", "session": None})

        # 获取反馈统计汇总
        elif path == "/api/feedback/stats":
            days = int(parse_qs(parsed.query).get('days', [7])[0])
            feedback_mgr = get_feedback_manager()
            self.send_json(feedback_mgr.get_feedback_stats(days))

        # 获取用户反馈历史
        elif path == "/api/feedback/history":
            user_id = path.split("/")[-1]
            if user_id == "history":
                user_id = data.get("user_id", "anonymous")
            limit = int(parse_qs(parsed.query).get('limit', [50])[0])
            feedback_mgr = get_feedback_manager()
            self.send_json({"history": feedback_mgr.get_user_feedback_history(user_id, limit)})

        # 获取最近的负面反馈
        elif path == "/api/feedback/negative":
            limit = int(parse_qs(parsed.query).get('limit', [20])[0])
            feedback_mgr = get_feedback_manager()
            self.send_json({"negative_feedback": feedback_mgr.get_recent_negative_feedback(limit)})

        else:
            self.send_error(404, "Not Found")

    def serve_html(self):
        """返回HTML页面"""
        html_path = project_root / "web" / "index.html"

        if html_path.exists():
            with open(html_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
        else:
            self.send_error(404, "HTML file not found")

    def send_json(self, data):
        """发送JSON响应"""
        json_str = json.dumps(data, ensure_ascii=False)

        self.send_response(200)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json_str.encode("utf-8"))

    @staticmethod
    def _cors_origin() -> str:
        """根据环境变量决定 CORS 来源,未配置时仅允许本地"""
        allowed = os.environ.get("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
        origins = [o.strip() for o in allowed.split(",") if o.strip()]
        if not origins:
            return "http://127.0.0.1:8000"
        return ",".join(origins)

    def do_OPTIONS(self):
        """处理CORS预检请求"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        """自定义日志格式"""
        print(f"[HTTP] {args[0]}")


def run_server(host="0.0.0.0", port=8000):
    """运行服务器"""
    print(f"\n[AGENT] 绿色低碳智能体正在启动...", flush=True)
    print(f"[提示] 服务器将立即启动，收到请求时再加载模型", flush=True)

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

    # 注意：这里不调用 get_agent()，让服务器立即启动
    # Agent 会在第一次请求时才初始化

    print("[DEBUG] Creating HTTPServer...", flush=True)
    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"[DEBUG] HTTPServer created on {(host, port)}", flush=True)

    print(f"\n" + "=" * 50, flush=True)
    print(f"[AGENT] 绿色低碳智能体 v2.0 启动成功！", flush=True)
    print(f"=" * 50, flush=True)
    print(f"   服务地址: http://localhost:{port}", flush=True)
    print(f"   按 Ctrl+C 停止服务", flush=True)
    print(f"=" * 50 + "\n", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n服务已停止")
        server.shutdown()


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
                print(f"\n[STAT] 你的用户画像:")
                eco = profile.get("eco_profile", {})
                print(f"   - 环保认知水平: {eco.get('knowledge_level')}")
                print(f"   - 行为阶段: {eco.get('behavior_stage')}")
                print(f"   - 关注领域: {', '.join(eco.get('primary_interests', []))}")
                continue

            if user_input.lower() == "stats":
                kb_stats = agent.get_knowledge_stats()
                print(f"\n[KB] 知识库统计:")
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

            print(f"\n🤖 助手:")
            print(response.message)

            if response.personalization_info:
                ctx = response.personalization_info
                print(f"\n📌 个性化信息: {ctx.get('knowledge_level')} | {ctx.get('behavior_stage')}阶段")

            if response.recommendations:
                print(f"\n[TIP] 为你推荐:")
                for i, rec in enumerate(response.recommendations[:2], 1):
                    print(f"   {i}. {rec['action']}")

            if response.suggestions:
                print(f"\n🔄 你可以尝试:")
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
    print(f"[启动] LangGraph 模式: USE_LANGGRAPH={os.environ.get('USE_LANGGRAPH', 'false')}, MODE={os.environ.get('LANGGRAPH_MODE', '')}")

    if args.cli:
        run_cli()
    else:
        run_server(host=args.host, port=args.port)
