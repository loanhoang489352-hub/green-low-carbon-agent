#!/usr/bin/env bash
# ============================================================
# CI smoke test (P11.A) — 本地一行跑完生产容器验证
#
# 用法:
#   bash scripts/ci_smoke.sh
#   IMAGE=green-agent:test bash scripts/ci_smoke.sh
#   URL=http://localhost:8000 bash scripts/ci_smoke.sh   # 跳过 docker,直接对现成服务测
#
# 行为:
#   1) 若容器未跑 → docker build + run(detached)
#   2) 等 /api/ready 至多 60s
#   3) 跑 /api/ready /api/health /api/chat 三件套
#   4) 收尾: 若本脚本启动的容器,自动 stop & rm
#
# 退出码:
#   0 = 全部通过
#   1 = smoke 失败
#   2 = docker build 失败
# ============================================================

set -euo pipefail

IMAGE="${IMAGE:-green-agent:test}"
CONTAINER_NAME="${CONTAINER_NAME:-green-agent-ci}"
HOST_PORT="${HOST_PORT:-8000}"
URL="${URL:-http://localhost:${HOST_PORT}}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-60}"
OWNED_CONTAINER=0
PASS=0
FAIL=0

# ---------- 颜色 ----------
if [[ -t 1 ]]; then
    RED=$'\033[0;31m'
    GRN=$'\033[0;32m'
    YLW=$'\033[0;33m'
    CYN=$'\033[0;36m'
    RST=$'\033[0m'
else
    RED="" GRN="" YLW="" CYN="" RST=""
fi

log()  { echo -e "${CYN}[ci-smoke]${RST} $*"; }
ok()   { echo -e "${GRN}  PASS${RST} $*"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}  FAIL${RST} $*"; FAIL=$((FAIL+1)); }
warn() { echo -e "${YLW}  WARN${RST} $*"; }

cleanup() {
    if [[ "$OWNED_CONTAINER" == "1" ]]; then
        log "Cleaning up container $CONTAINER_NAME..."
        docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
        docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

# ---------- 前置:docker 可用? ----------
need_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        echo -e "${RED}[ci-smoke] docker not found in PATH${RST}" >&2
        exit 2
    fi
    if ! docker info >/dev/null 2>&1; then
        echo -e "${RED}[ci-smoke] docker daemon not reachable${RST}" >&2
        exit 2
    fi
}

# ---------- 1. 确保容器在跑 ----------
ensure_container() {
    if curl -sf "$URL/api/ready" >/dev/null 2>&1; then
        log "Service already up at $URL — using existing instance"
        return 0
    fi

    need_docker

    # 已存在同名容器?(上次残留)
    if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        log "Removing stale container $CONTAINER_NAME"
        docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi

    # 镜像存在?
    if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^${IMAGE}$"; then
        log "Image $IMAGE not found — building..."
        if ! docker build -t "$IMAGE" .; then
            echo -e "${RED}[ci-smoke] docker build failed${RST}" >&2
            exit 2
        fi
    fi

    log "Starting container $CONTAINER_NAME from $IMAGE"
    docker run -d \
        --name "$CONTAINER_NAME" \
        -p "${HOST_PORT}:8000" \
        -e LLM_MOCK=true \
        -e USE_MOCK_LLM=true \
        -e LOG_LEVEL=WARNING \
        -e ENV=ci \
        "$IMAGE" >/dev/null
    OWNED_CONTAINER=1
}

# ---------- 2. 等就绪 ----------
wait_ready() {
    log "Waiting for $URL/api/ready (timeout ${WAIT_TIMEOUT}s)..."
    for i in $(seq 1 "$WAIT_TIMEOUT"); do
        if curl -sf "$URL/api/ready" >/dev/null 2>&1; then
            log "Service ready after ${i}s"
            return 0
        fi
        sleep 1
    done
    echo -e "${RED}[ci-smoke] Service did NOT become ready in ${WAIT_TIMEOUT}s${RST}" >&2
    if [[ "$OWNED_CONTAINER" == "1" ]]; then
        echo "--- last 50 lines of container log ---" >&2
        docker logs "$CONTAINER_NAME" 2>&1 | tail -50 >&2 || true
    fi
    return 1
}

# ---------- 3. 测试套件 ----------
smoke_ready() {
    log "[1/3] GET /api/ready"
    local code
    code=$(curl -s -o /tmp/ci_ready.json -w "%{http_code}" "$URL/api/ready")
    if [[ "$code" == "200" ]]; then
        ok "/api/ready -> 200"
        cat /tmp/ci_ready.json
        echo ""
    else
        fail "/api/ready -> $code"
        cat /tmp/ci_ready.json
        echo ""
        return 1
    fi
}

smoke_health() {
    log "[2/3] GET /api/health"
    local code body
    code=$(curl -s -o /tmp/ci_health.json -w "%{http_code}" "$URL/api/health")
    body=$(cat /tmp/ci_health.json)
    if [[ "$code" == "200" ]]; then
        if echo "$body" | grep -qE '"status"\s*:\s*"(ok|healthy|degraded)"'; then
            ok "/api/health -> 200 (status=ok/healthy/degraded)"
            echo "    $body"
        else
            fail "/api/health -> 200 but status field missing"
            echo "    $body"
            return 1
        fi
    else
        fail "/api/health -> $code"
        echo "    $body"
        return 1
    fi
}

smoke_chat() {
    log "[3/3] POST /api/chat"
    local code body
    code=$(curl -s -o /tmp/ci_chat.json -w "%{http_code}" \
        -X POST "$URL/api/chat" \
        -H "Content-Type: application/json" \
        -d '{"message":"你好"}')
    body=$(cat /tmp/ci_chat.json)
    if [[ "$code" == "200" ]]; then
        ok "/api/chat -> 200"
        echo "    $body" | head -c 400
        echo ""
    else
        fail "/api/chat -> $code"
        echo "    $body" | head -c 400
        echo ""
        return 1
    fi
}

# ---------- 4. 主流程 ----------
main() {
    log "=== CI smoke test ==="
    log "  IMAGE   = $IMAGE"
    log "  URL     = $URL"
    log "  TIMEOUT = ${WAIT_TIMEOUT}s"
    echo ""

    ensure_container
    wait_ready
    echo ""

    smoke_ready
    smoke_health
    smoke_chat

    echo ""
    log "=== Result ==="
    log "  PASS: $PASS"
    log "  FAIL: $FAIL"

    if [[ $FAIL -gt 0 ]]; then
        echo -e "${RED}[ci-smoke] smoke test FAILED${RST}" >&2
        exit 1
    fi

    echo -e "${GRN}[ci-smoke] all smoke tests PASSED${RST}"
    exit 0
}

main "$@"