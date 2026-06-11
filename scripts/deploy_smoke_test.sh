#!/usr/bin/env bash
# 部署后冒烟测试 — P6.R.1
#
# 用法:
#   bash scripts/deploy_smoke_test.sh                    # 默认 localhost:8000
#   bash scripts/deploy_smoke_test.sh https://green.example.com  # 远程生产
#
# 退出码:
#   0 = 全部通过
#   1 = 至少 1 个失败

set -e

URL="${1:-http://localhost:8000}"
PASS=0
FAIL=0
FAILED_TESTS=()

run_test() {
    local name="$1"
    local cmd="$2"
    local expected="$3"

    echo -n "  [TEST] $name ... "
    if result=$(eval "$cmd" 2>&1); then
        if [[ -z "$expected" ]] || [[ "$result" == *"$expected"* ]]; then
            echo "PASS"
            ((PASS++))
        else
            echo "FAIL (期望含 '$expected', 实际 '$result')"
            ((FAIL++))
            FAILED_TESTS+=("$name")
        fi
    else
        echo "FAIL (命令退出 $?)"
        ((FAIL++))
        FAILED_TESTS+=("$name")
    fi
}

echo "═══ 部署后冒烟测试 — $URL ═══"
echo ""

# === 1. 健康探活 ===
echo "[1/5] 健康探活"
run_test "GET /api/health" \
    "curl -s -o /dev/null -w '%{http_code}' $URL/api/health" \
    "200"
run_test "GET /api/ready" \
    "curl -s -o /dev/null -w '%{http_code}' $URL/api/ready" \
    "200"
run_test "GET /api/metrics" \
    "curl -s -o /dev/null -w '%{http_code}' $URL/api/metrics" \
    "200"

# === 2. 鉴权 ===
echo ""
echo "[2/5] 鉴权"
run_test "POST /api/chat/enhanced (无 token)" \
    "curl -s -X POST $URL/api/chat/enhanced -H 'Content-Type: application/json' -d '{}' | python -c 'import json,sys;d=json.load(sys.stdin);print(d[\"error\"][\"code\"])'" \
    "UNAUTHORIZED"

# === 3. 限流 ===
echo ""
echo "[3/5] 限流(60+1 次 /api/health)"
echo "  (跑 65 次约 1-2s)"
# 禁用 rate limit 时这测不适用
LIMIT_STATUS=$(for i in {1..65}; do
    curl -s -o /dev/null -w "%{http_code}\n" $URL/api/health
done | sort -u)
if echo "$LIMIT_STATUS" | grep -q "429"; then
    echo "  [TEST] 限流触发 ... PASS (有 429)"
    ((PASS++))
else
    echo "  [TEST] 限流触发 ... WARN(只看到 $LIMIT_STATUS,可能 RATE_LIMIT_ENABLED=false)"
    # 不算 fail(开发模式常禁限流)
fi

# === 4. i18n ===
echo ""
echo "[4/5] 国际化"
run_test "GET /i18n.js 返 JS" \
    "curl -s $URL/i18n.js | head -1" \
    "(function"
run_test "错误消息跟随 Accept-Language: en" \
    "curl -s -X POST $URL/api/chat/enhanced -H 'Accept-Language: en' -H 'Content-Type: application/json' -d '{}' | python -c 'import json,sys;d=json.load(sys.stdin);print(d[\"error\"][\"message\"])'" \
    "Authentication"

# === 5. Query Cache + Metrics ===
echo ""
echo "[5/5] Metrics + Query Cache"
run_test "/api/metrics 含 query_cache 字段" \
    "curl -s $URL/api/metrics | python -c 'import json,sys;d=json.load(sys.stdin);print(\"query_cache\" in d[\"metrics\"])'" \
    "True"
run_test "ChatGPT 401 i18n 消息(Accept-Language: zh)" \
    "curl -s -X POST $URL/api/chat/enhanced -H 'Accept-Language: zh' -H 'Content-Type: application/json' -d '{}' | python -c 'import json,sys;d=json.load(sys.stdin);print(d[\"error\"][\"message\"])'" \
    "登录"

# === 总结 ===
echo ""
echo "═══ 总结 ═══"
echo "  PASS: $PASS"
echo "  FAIL: $FAIL"

if [[ $FAIL -gt 0 ]]; then
    echo ""
    echo "失败的测试:"
    for t in "${FAILED_TESTS[@]}"; do
        echo "  - $t"
    done
    exit 1
fi

echo ""
echo "✅ 所有冒烟测试通过"
exit 0
