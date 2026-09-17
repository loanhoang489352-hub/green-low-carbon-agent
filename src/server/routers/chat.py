"""
聊天路由 (P5-E: 改用 APIError 异常体系,异常不再泄栈)
"""

import json


def register_chat_routes(registry) -> None:
    """注册聊天相关路由"""

    from server.errors import APIError
    from agent.conversation_store import ConversationOwnershipError

    def _require_owner_conversation(handler, conv_id) -> None:
        """P0: 校验 conversation_id 属于当前登录用户(防水平越权)"""
        current = getattr(handler, "current_user", None) or {}
        if not current.get("user_id"):
            raise APIError("UNAUTHORIZED", "需要登录")
        try:
            store = handler.agent.conversation_store
            if hasattr(store, "assert_owner"):
                store.assert_owner(conv_id, current["user_id"])
        except ConversationOwnershipError:
            raise APIError("FORBIDDEN", "无权访问该对话")
        except APIError:
            raise
        except Exception:
            # 会话不在 store 中(如重启后仅存在于 SQLite):允许通过,由业务层兜底
            pass

    def chat(handler, data):
        # 已登录用户强制用其账号 user_id(防止 body 冒充他人);匿名走 anonymous/temp_*
        current = getattr(handler, "current_user", None) or {}
        user_id = data.get("user_id", "anonymous")
        if current.get("user_id"):
            user_id = current["user_id"]
        elif not user_id or not (user_id == "anonymous" or user_id.startswith("temp_")):
            raise APIError("UNAUTHORIZED", "匿名对话需使用 anonymous 或 temp_ 前缀 user_id")
        message = data.get("message", "")
        conversation_id = data.get("conversation_id")

        if not message:
            raise APIError("BAD_REQUEST", "Message is required")

        try:
            response = handler.agent.chat(user_id, message, conversation_id)
        except ConversationOwnershipError:
            raise APIError("FORBIDDEN", "无权访问该对话")
        # P6.S.3: 完整序列化(含 tool_result 让前端可渲染地图/天气/路线)
        handler.send_json(
            {
                "message": response.message,
                "conversation_id": response.conversation_id,
                "intent": response.intent if hasattr(response, "intent") else None,
                "suggestions": response.suggestions if hasattr(response, "suggestions") else [],
                "tool_result": response.tool_result if hasattr(response, "tool_result") else None,
            }
        )

    def chat_enhanced(handler, data):
        # P0: 已鉴权端点,强制用登录身份,禁止 body 冒充他人 user_id
        # identity 统一走 server.identity.resolve_user_id(与节能端共用同一策略)
        from server.identity import resolve_user_id

        user_id = resolve_user_id(handler, data)
        message = data.get("message", "")
        conversation_id = data.get("conversation_id")

        if not message:
            raise APIError("BAD_REQUEST", "Message is required")

        # P6.S.22: 浏览器传入的 location(前端 navigator.geolocation) → handler._browser_location
        loc = data.get("location")
        if loc and isinstance(loc, dict) and loc.get("lat") and loc.get("lng"):
            try:
                handler._browser_location = {
                    "lat": float(loc["lat"]),
                    "lng": float(loc["lng"]),
                    "city": loc.get("city", "") or "",
                    "region": loc.get("region", "") or "",
                    "country": loc.get("country", "中国"),
                }
            except Exception:
                pass

        # 解析用户真实定位(浏览器精确坐标/IP/画像) → 传给 chat_enhanced,供出行规划消歧/起点
        try:
            from utils.geolocate import best_location

            geo = best_location(handler=handler, user_id=user_id)
            location_info = geo.to_dict()
        except Exception:
            location_info = {}

        try:
            response = handler.agent.chat_enhanced(
                user_id, message, conversation_id, user_location=location_info
            )
        except ConversationOwnershipError:
            raise APIError("FORBIDDEN", "无权访问该对话")
        handler.send_json(
            {
                "message": response.message,
                "conversation_id": response.conversation_id,
                "intent": response.intent,
                "suggestions": response.suggestions,
                "knowledge_refs": response.knowledge_refs,
                "timestamp": response.timestamp,
                "personalization": response.personalization_info,
                "recommendations": response.recommendations,
                "profile_updates": response.profile_updates,
                "location": location_info,  # P6.S.22: 返定位来源供前端展示
                "tool_result": response.tool_result if hasattr(response, "tool_result") else None,  # P6.S.23
                "trace": getattr(response, "trace", []),  # 节点透明度:执行轨迹(意图/RAG/记忆/LLM/工具)
            }
        )

    def conversation_reset(handler, data):
        # P0: 需鉴权 + owner 校验(只能重置自己的对话)
        conv_id = data.get("conversation_id")
        if not conv_id:
            raise APIError("BAD_REQUEST", "conversation_id required")
        _require_owner_conversation(handler, conv_id)
        handler.agent.reset_conversation(conv_id)
        handler.send_json({"status": "success"})

    def conversation_history(handler, data):
        # P0: 需鉴权 + owner 校验(只能读自己的对话历史)
        conv_id = data.get("conversation_id")
        if not conv_id:
            raise APIError("BAD_REQUEST", "conversation_id required")
        _require_owner_conversation(handler, conv_id)
        history = handler.agent.get_conversation_history(conv_id)
        handler.send_json({"history": history})

    def recommendations(handler, data):
        from server.identity import resolve_user_id
        user_id = resolve_user_id(handler, data)
        profile = handler.agent.get_user_profile(user_id)
        from user_profile.personalized_recommender import PersonalizedRecommendationEngine

        engine = PersonalizedRecommendationEngine()
        recs = engine.generate_recommendations(profile, count=3)
        handler.send_json(
            {
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
            }
        )

    def agent_react(handler, data):
        """P6.S.17: ReAct 测试端点 — 让 LLM 自主选 tool,跑多步循环"""
        message = data.get("message", "")
        if not message:
            raise APIError("BAD_REQUEST", "message required")
        tool_names = data.get("tool_names")
        if not tool_names:
            # 默认暴露所有已注册工具(含节能 3 个),让 LLM 自主选择;失败则 None(退化到无工具单步)
            try:
                from agent.tools import get_registry as get_tool_registry

                tool_names = get_tool_registry().list_all()
            except Exception:
                tool_names = None
        try:
            max_steps = int(data.get("max_steps", 3))
        except (TypeError, ValueError):
            max_steps = 3
        # P0: 限制单次请求最大步数,防止无限循环烧 LLM 额度
        max_steps = max(1, min(max_steps, 8))
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
        try:
            from user_profile.user_profile import UserProfileManager

            upm = UserProfileManager()
            profile = upm.get_profile(data.get("user_id", "anonymous"))
        except Exception:
            profile = {}
        try:
            ctx = ResponseContext(
                user_profile=profile,
                conversation_history=[],
                retrieved_knowledge=[],
                recent_memories=[],
                intent_type=intent,
            )
            from agent.response import ResponseGenerator

            rg = ResponseGenerator(use_llm=True)
            rg._get_llm_client()
            messages = rg._build_prompt(
                user_message=message,
                user_profile=profile,
                rag_context="",
                conversation_history=[],
            )
        except Exception as e:
            log.warning("[ReAct] prompt build fallback: %s", e)
            messages = [
                {"role": "system", "content": "你是绿宝,绿色低碳助手。"},
                {"role": "user", "content": message},
            ]
        messages.insert(
            0,
            {
                "role": "system",
                "content": (
                    "你有一个工具调用系统。优先用工具查真实数据,基于工具结果回答。"
                    "若没有合适工具,直接回答。"
                ),
            },
        )
        result = run_react_loop(
            messages,
            llm,
            tool_names=tool_names,
            max_steps=max_steps,
            trace_id=new_trace_id(),
        )
        handler.send_json(result)

    def chat_stream_sse(handler, data):
        """P6.S.18: SSE 流式 chat 端点 — 实时推送 LLM 输出
        用 EventSource 消费,前端可边收边渲染
        """
        message = data.get("message", "")
        if not message:
            raise APIError("BAD_REQUEST", "message required")
        from server.identity import resolve_user_id
        user_id = resolve_user_id(handler, data)
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
                    emit(
                        "done",
                        json.dumps(
                            {
                                "content": result.message,
                                "intent": result.intent,
                                "knowledge_refs": result.knowledge_refs,
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                    )
                    emit("end", "{}")
                    return
            emit("end", "{}")
        except Exception as e:
            emit("error", json.dumps({"error": str(e)[:200]}))

    def chat_trace_stream(handler, data):
        """P6.S.x: SSE 实时执行轨迹 — 后端逐步 push trace 事件,前端边收边渲染"思考过程"。
        复用 chat_enhanced(trace=实时trace),每 add/start/finish 一步就推一条 event:trace。
        """
        import json as _json
        from agent.trace import Trace

        from server.identity import resolve_user_id
        user_id = resolve_user_id(handler, data)
        message = data.get("message", "")
        conversation_id = data.get("conversation_id")

        # P6.S.22: 读 body 的 browser location 并存到 handler._browser_location,
        # 否则 best_location 拿不到浏览器精确坐标 → 会落到默认北京。与 /api/chat/enhanced 一致。
        try:
            loc = data.get("location")
            if loc and isinstance(loc, dict) and loc.get("lat") and loc.get("lng"):
                handler._browser_location = {
                    "lat": float(loc["lat"]),
                    "lng": float(loc["lng"]),
                    "city": loc.get("city", "") or "",
                    "region": loc.get("region", "") or "",
                    "country": loc.get("country", "中国"),
                }
        except Exception:
            pass

        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("X-Accel-Buffering", "no")
        handler.end_headers()

        def emit(event: str, payload: str):
            try:
                line = f"event: {event}\ndata: {payload}\n\n"
                handler.wfile.write(line.encode("utf-8"))
                handler.wfile.flush()
            except Exception:
                pass

        def on_step(entry):
            # 每记录一步,实时推给前端
            emit("trace", _json.dumps(entry, ensure_ascii=False, default=str))

        live_trace = Trace(on_step=on_step)
        emit("start", _json.dumps({"user_id": user_id, "status": "thinking", "message": message}, ensure_ascii=False))
        # 解析用户真实定位(浏览器精确坐标/IP/画像) → 传给 chat_enhanced 供出行规划消歧/起点
        try:
            from utils.geolocate import best_location

            user_location = best_location(handler=handler, user_id=user_id).to_dict()
        except Exception:
            user_location = {}
        try:
            resp = handler.agent.chat_enhanced(
                user_id, message, conversation_id, trace=live_trace, user_location=user_location
            )
            emit(
                "done",
                _json.dumps(
                    {
                        "message": getattr(resp, "message", ""),
                        "conversation_id": getattr(resp, "conversation_id", conversation_id),
                        "intent": getattr(resp, "intent", "react"),
                        "suggestions": getattr(resp, "suggestions", []),
                        "knowledge_refs": getattr(resp, "knowledge_refs", []),
                        "recommendations": getattr(resp, "recommendations", []),
                        "tool_result": getattr(resp, "tool_result", None),
                        "location": getattr(resp, "personalization_info", {}).get("location"),
                        "personalization": getattr(resp, "personalization_info", {}),
                        "profile_updates": getattr(resp, "profile_updates", {}),
                        "trace": getattr(resp, "trace", []),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            )
        except Exception as e:
            emit("error", _json.dumps({"error": str(e)[:200]}))
        emit("end", "{}")

    # P5-D 鉴权强制落地:
    #   - /api/chat 保持公开(浏览器匿名对话兜底,body 带 user_id)
    #   - /api/chat/enhanced 需鉴权(走 RAG + 个性化,涉及 user 隐私数据)
    #   - /api/recommendations 需鉴权(画像驱动,user 隐私)
    #   - /api/conversation/{id} 已在 profile.py 中注册为 True
    registry.add_route("POST", "/api/chat", chat, auth_required=False, description="基础聊天(匿名可用)")
    registry.add_route(
        "POST",
        "/api/chat/enhanced",
        chat_enhanced,
        auth_required=True,
        description="增强聊天(RAG+个性化,需鉴权)",
    )
    registry.add_route(
        "POST",
        "/api/conversation/reset",
        conversation_reset,
        auth_required=True,
        description="重置对话(需鉴权,P0 修复)",
    )
    registry.add_route(
        "POST",
        "/api/conversation/history",
        conversation_history,
        auth_required=True,
        description="对话历史(需鉴权,P0 修复)",
    )
    registry.add_route(
        "POST",
        "/api/recommendations",
        recommendations,
        auth_required=True,
        description="个性化推荐(画像驱动,需鉴权)",
    )
    registry.add_route(
        "POST",
        "/api/agent/react",
        agent_react,
        auth_required=True,
        description="P6.S.17: ReAct 测试 — LLM 自主选 tool(需鉴权,P0 修复防匿名烧额度)",
    )
    registry.add_route(
        "POST",
        "/api/chat/stream",
        chat_stream_sse,
        auth_required=True,
        description="P6.S.18: SSE 流式 chat(需鉴权,P0 修复防匿名烧额度)",
    )
    registry.add_route(
        "POST",
        "/api/chat/stream-trace",
        chat_trace_stream,
        auth_required=True,
        description="P6.S.x: SSE 实时执行轨迹(逐步 push trace,前端边收边渲染思考过程)",
    )
