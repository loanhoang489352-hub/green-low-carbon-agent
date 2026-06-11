# ========== 绿色低碳智能体 - Production Dockerfile (P5-J) ==========
# multi-stage build:
#   1. builder:  装 pip 依赖到 /install
#   2. runtime:  仅复制 /install + 应用代码,non-root,HEALTHCHECK
# 目标镜像: < 500MB

# ========== Stage 1: builder ==========
FROM python:3.12-slim AS builder

# 安装编译期依赖(部分 Python 包需要 C 编译器)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 升级 pip + 安装 wheel(加速后续 pip install)
RUN pip install --no-cache-dir --upgrade pip wheel setuptools

# 复制并安装依赖(单独成层,应用代码变更不重装)
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt \
    && pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt

# ========== Stage 2: runtime ==========
FROM python:3.12-slim

# 安装运行时系统依赖(curl 用于 HEALTHCHECK, tini 用于 PID 1 信号转发)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        tini \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 复制已安装的 site-packages
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 创建非 root 用户(UID 1000,符合大多数 K8s securityContext)
RUN groupadd --system --gid 1000 greenagent \
    && useradd --system --uid 1000 --gid greenagent \
       --home-dir /app --shell /sbin/nologin \
       greenagent

# 设置工作目录
WORKDIR /app

# 复制应用代码
COPY --chown=greenagent:greenagent src/ ./src/
COPY --chown=greenagent:greenagent web/ ./web/
COPY --chown=greenagent:greenagent config/ ./config/
COPY --chown=greenagent:greenagent scripts/ ./scripts/
COPY --chown=greenagent:greenagent agent.bat Makefile requirements.txt ./

# 数据 + 日志目录(空目录,运行时挂载)
RUN mkdir -p /app/data/logs /tmp/greenagent \
    && chown -R greenagent:greenagent /app/data /tmp/greenagent

# 环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # P5-B: 日志配置
    LOG_LEVEL=INFO \
    # P5-C: LLM 可靠性
    LLM_TIMEOUT_SECONDS=30 \
    LLM_MAX_RETRIES=2 \
    # P5-D: 默认非生产模式(生产环境应改成 https://your-domain.com)
    CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# 切换到非 root 用户
USER greenagent

# 暴露端口
EXPOSE 8000

# P5-J: HEALTHCHECK 探活 /api/ready(K8s readiness probe 也用这个)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/ready || exit 1

# tini 作为 PID 1,正确转发 SIGTERM 给 Python 主进程(否则 P5-J graceful 失效)
ENTRYPOINT ["/usr/bin/tini", "--"]

# 启动命令(src 在 PYTHONPATH 里)
CMD ["python", "src/main.py"]
