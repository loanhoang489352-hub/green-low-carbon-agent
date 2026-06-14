"""
聊天路由 (P5-E: 改用 APIError 异常体系,异常不再泄栈)
"""
import json


def register_chat_routes(registry) -> None:
    """注册聊天相关路由"""

    from server.errors import APIError

    def chat(handler, data):
        user_id = data.get("user_id", "anonymous")
        message = data.get("message", "")
        conversation_id = data.get("conversation_id")

        if not message:
            raise APIError("BAD_REQUEST", "Message is required")

        response = handler.agent.chat(user_id, message, conversation_id)
        # P6.S.3: 完整序列化(含 tool_result 让前端可渲染地图/天气/路线)
        handler.send_json({
            "message": response.message,
            "conversation_id": response.conversation_id,
            "intent": response.intent if hasattr(response, "intent") else None,
            "suggestions": response.suggestions if hasattr(response, "suggestions") else [],
            "tool_result": response.tool_result if hasattr(response, "tool_result") else None,
        })

    def chat_enhanced(handler, data):
        user_id = data.get("user_id", "anonymous")
        message = data.get("message", "")
        conversation_id = data.get("conversation_id")

        if not message:
            raise APIError("BAD_REQUEST", "Message is required")

        response = handler.agent.chat_enhanced(user_id, message, conversation_id)
        handler.send_json({
            "message": response.message,
            "conversation_id": response.conversation_id,
            "intent": response.intent,
            "suggestions": response.suggestions,
            "knowledge_refs": response.knowledge_refs,
            "timestamp": response.timestamp,
            "personalization": response.personalization_info,
            "recommendations": response.recommendations,
            "profile_updates": response.profile_updates,
        })

    def conversation_reset(handler, data):
        conv_id = data.get("conversation_id")
        if conv_id:
            handler.agent.reset_conversation(conv_id)
        handler.send_json({"status": "success"})

    def conversation_history(handler, data):
        conv_id = data.get("conversation_id")
        if not conv_id:
            raise APIError("BAD_REQUEST", "conversation_id required")
        history = handler.agent.get_conversation_history(conv_id)
        handler.send_json({"history": history})

    def recommendations(handler, data):
        user_id = data.get("user_id", "anonymous")
        profile = handler.agent.get_user_profile(user_id)
        from user_profile.personalized_recommender import PersonalizedRecommendationEngine
        engine = PersonalizedRecommendationEngine()
        recs = engine.generate_recommendations(profile, count=3)
        handler.send_json({
            "recommendations": [
                {
                    "action": r.action,
                    "category": r.category,
                    "reason": r.reason,
                    "carbon_saving": r.estimated_carbon_saving,
                    "difficulty": r.difficulty,
                    "impact": r.impact,
                    "examples": r.examples,
                }
                for r in recs
            ]
        })

    def agent_react(handler, data):
        """P6.S.17: ReAct 测试端点 — 让 LLM 自主选 tool,跑多步循环"""
        message = data.get("message", "")
        if not message:
            raise APIError("BAD_REQUEST", "message required")
        tool_names = data.get("tool_names")
        max_steps = int(data.get("max_steps", 3))
        from agent.tool_dispatcher import run_react_loop
        from llm import get_llm_client
        from observability.trace import new_trace_id
        from agent.intent import IntentRecognizer
        from agent.response import ResponseContext
        import logging
        log = logging.getLogger(__name__)
        llm = get_llm_client()
        ir = IntentRecognizer()
        intent = ir.recognize(message).intent.value
        from llm import build_chat_prompt
        try:
            from user_profile.user_profile import UserProfileManager
            upm = UserProfileManager()
            profile = upm.get_profile(data.get("user_id", "anonymous"))
        except Exception:
            profile = {}
        try:
            ctx = ResponseContext(
                user_profile=profile, conversation_history=[],
                retrieved_knowledge=[], recent_memories=[],
                intent_type=intent,
            )
            from agent.response import ResponseGenerator
            rg = ResponseGenerator(use_llm=True)
            rg._get_llm_client()
            messages = rg._build_prompt(
                user_message=message, user_profile=profile, rag_context="",
                conversation_history=[],
            )
        except Exception as e:
            log.warning("[ReAct] prompt build fallback: %s", e)
            messages = [
                {"role": "system", "content": "你是绿宝,绿色低碳助手。"},
                {"role": "user", "content": message},
            ]
        messages.insert(0, {
            "role": "system",
            "content": (
                "你有一个工具调用系统。优先用工具查真实数据,基于工具结果回答。"
                "若没有合适工具,直接回答。"
            ),
        })
        result = run_react_loop(
            messages, llm, tool_names=tool_names,
            max_steps=max_steps, trace_id=new_trace_id(),
        )
        handler.send_json(result)

    def chat_stream_sse(handler, data):
        """P6.S.18: SSE 流式 chat 端点 — 实时推送 LLM 输出
        用 EventSource 消费,前端可边收边渲染
        """
        message = data.get("message", "")
        if not message:
            raise APIError("BAD_REQUEST", "message required")
        user_id = data.get("user_id", "anonymous")
        conversation_id = data.get("conversation_id")
        # 用 chunked transfer + SSE 格式
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("X-Accel-Buffering", "no")
        handler.end_headers()

        def emit(event: str, payload: str):
            """SSE 单条 event"""
            try:
                line = f"event: {event}\ndata: {payload}\n\n"
                handler.wfile.write(line.encode("utf-8"))
                handler.wfile.flush()
            except Exception:
                pass

        try:
            emit("start", json.dumps({"user_id": user_id}))
            # 用 LangGraphAgent.chat_stream 走 LangGraph 路径
            from agent.langgraph_agent import LangGraphAgent
            if not hasattr(handler, "_stream_agent"):
                from agent.langgraph_agent import LangGraphAgent as _LGA
                try:
                    handler._stream_agent = _LGA(use_langgraph=True, langgraph_mode="default")
                except Exception:
                    handler._stream_agent = None
            agent = handler._stream_agent
            if agent:
                for event in agent.chat_stream(user_id, message, conversation_id):
                    emit("progress", json.dumps(event, ensure_ascii=False, default=str))
            else:
                # 降级: 走普通 chat 然后一次性 emit
                from src.main import get_agent
                base_agent = get_agent()
                if base_agent.use_langgraph and base_agent.langgraph_agent:
                    for event in base_agent.langgraph_agent.chat_stream(
                        user_id, message, conversation_id
                    ):
                        emit("progress", json.dumps(event, ensure_ascii=False, default=str))
                else:
                    result = base_agent.chat_enhanced(user_id, message, conversation_id)
                    emit("done", json.dumps({
                        "content": result.message,
                        "intent": result.intent,
                        "knowledge_refs": result.knowledge_refs,
                    }, ensure_ascii=False, default=str))
                    emit("end", "{}")
                    return
            emit("end", "{}")
        except Exception as e:
            emit("error", json.dumps({"error": str(e)[:200]}))

    # P6.S.14: chat 端点对匿名 user_id 公开(避免浏览器无 token 时 401)
    #   - 用 user_id(在 body 里)做身份,不再强制 Bearer session_id
    #   - 浏览器 onboarding 后 / 匿名 user 都能直接聊天
    #   - 仍支持 Bearer token:有则用 login user,无则用 body user_id
    #   - 敏感端点(feedback/memory/profile)仍需 auth
    registry.add_route("POST", "/api/chat", chat, auth_required=False, description="基础聊天")
    registry.add_route("POST", "/api/chat/enhanced", chat_enhanced, auth_required=False, description="增强聊天(RAG+个性化)")
    registry.add_route("POST", "/api/conversation/reset", conversation_reset, auth_required=False, description="重置对话")
    registry.add_route("POST", "/api/conversation/history", conversation_history, auth_required=False, description="对话历史")
    registry.add_route("POST", "/api/recommendations", recommendations, auth_required=False, description="个性化推荐")
    registry.add_route("POST", "/api/agent/react", agent_react, auth_required=False, description="P6.S.17: ReAct 测试 — LLM 自主选 tool")
    registry.add_route("POST", "/api/chat/stream", chat_stream_sse, auth_required=False, description="P6.S.18: SSE 流式 chat")
