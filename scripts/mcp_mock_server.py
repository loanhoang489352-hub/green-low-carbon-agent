"""
Mock MCP Server — 用于测试 MCP 客户端

提供 3 个示例 tool:
  - mock_echo:    回显输入
  - mock_weather: 返回固定天气数据
  - mock_carbon:  计算碳排放(简单公式)

启动: python scripts/mcp_mock_server.py

P6.S.16: 同步实现(避免 asyncio + stdin 在 Windows pipe 上的兼容问题)
"""
import json
import sys


def handle_request(request):
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if req_id is None and method.startswith("notifications/"):
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {
                    "name": "mock-mcp-server",
                    "version": "1.0.0",
                },
                "capabilities": {"tools": {}},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "mock_echo",
                        "description": "回显输入的文本(用于测试 MCP 集成)",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string", "description": "要回显的文本"},
                            },
                            "required": ["text"],
                        },
                    },
                    {
                        "name": "mock_weather",
                        "description": "返回模拟天气数据(MCP 集成测试用)",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "city": {"type": "string", "description": "城市名"},
                            },
                            "required": ["city"],
                        },
                    },
                    {
                        "name": "mock_carbon",
                        "description": "计算简单碳排放(距离 × 系数)",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "distance_km": {"type": "number", "description": "距离(km)"},
                                "mode": {"type": "string", "description": "交通方式: car/bus/cycling/walking"},
                            },
                            "required": ["distance_km"],
                        },
                    },
                ],
            },
        }
    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        if name == "mock_echo":
            text = args.get("text", "")
            content = f"echo: {text}"
        elif name == "mock_weather":
            city = args.get("city", "未知")
            content = json.dumps({
                "city": city,
                "temp_c": 22,
                "description": "多云",
                "humidity": 60,
                "wind": "东南风 3级",
            }, ensure_ascii=False)
        elif name == "mock_carbon":
            try:
                distance = float(args.get("distance_km", 0))
            except (ValueError, TypeError):
                distance = 0.0
            mode = args.get("mode", "car")
            factors = {"car": 0.21, "bus": 0.08, "cycling": 0, "walking": 0, "transit": 0.05}
            factor = factors.get(mode, 0.21)
            carbon = round(distance * factor, 3)
            content = json.dumps({
                "distance_km": distance,
                "mode": mode,
                "factor_kg_per_km": factor,
                "carbon_kg": carbon,
            }, ensure_ascii=False)
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": f"Tool not found: {name}"},
            }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": content}],
                "isError": False,
            },
        }
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main():
    print("[mock-mcp] 启动, 等待 stdin JSON-RPC 请求", file=sys.stderr, flush=True)
    try:
        for line in sys.stdin:
            text = line.strip()
            if not text:
                continue
            try:
                request = json.loads(text)
            except Exception as e:
                err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse: {e}"}}
                sys.stdout.write(json.dumps(err, ensure_ascii=False) + "\n")
                sys.stdout.flush()
                continue
            response = handle_request(request)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
    except (EOFError, BrokenPipeError):
        pass
    except Exception as e:
        print(f"[mock-mcp] loop error: {e}", file=sys.stderr, flush=True)
    print("[mock-mcp] 退出", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
