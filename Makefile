.PHONY: help install test lint clean run stop doctor \
        docker-build docker-up docker-down docker-logs docker-ps docker-shell \
        prod prod-stop prod-logs prod-shell prod-status prod-restart \
        backup restore db-shell lint-fix format

# ========== 顶层入口 ==========

help:           ## 显示帮助
	@echo "绿色低碳智能体 - Makefile (P5-J production-ready)"
	@echo ""
	@echo "═══ 开发命令 ═══"
	@echo "  make install        安装依赖(pip install -r requirements.txt)"
	@echo "  make test           运行全量测试(pytest tests/ -v)"
	@echo "  make lint           ruff 检查 src/"
	@echo "  make lint-fix       ruff 自动修复"
	@echo "  make format         black 格式化 src/"
	@echo "  make run            本地启动 Web 服务(端口 8000)"
	@echo "  make stop           停止本地 Web 服务"
	@echo "  make doctor         项目健康自检(5/5 应过)"
	@echo "  make clean          清理 pyc/__pycache__/.pytest_cache"
	@echo ""
	@echo "═══ Docker 开发模式 ═══"
	@echo "  make docker-build   构建开发镜像"
	@echo "  make docker-up      启动开发容器(后台)"
	@echo "  make docker-down    停止开发容器"
	@echo "  make docker-logs    跟踪开发容器日志"
	@echo "  make docker-ps      查看开发容器状态"
	@echo "  make docker-shell   进入开发容器 shell"
	@echo ""
	@echo "═══ Docker 生产模式(P5-J) ═══"
	@echo "  make prod           启动生产容器(读 .env.prod, 后台)"
	@echo "  make prod-stop      停止生产容器"
	@echo "  make prod-logs      跟踪生产容器日志(最近 100 行)"
	@echo "  make prod-shell     进入生产容器 shell"
	@echo "  make prod-status    查看生产容器 + 健康状态"
	@echo "  make prod-restart   重启生产容器(SIGTERM graceful 5s)"
	@echo ""
	@echo "═══ 运维 ═══"
	@echo "  make backup         备份 data/ 目录到 backups/"
	@echo "  make restore FILE=  从备份恢复"
	@echo "  make db-shell       SQLite 调试(进入 src/main.py REPL)"

# ========== 开发命令 ==========

install:
	pip install -r requirements.txt

test:
	pytest tests/ -v --tb=short

test-fast:
	pytest tests/ -q --tb=line -x --timeout=30

lint:
	ruff check src/ scripts/ tests/

lint-fix:
	ruff check src/ scripts/ tests/ --fix

format:
	black src/ scripts/ tests/

run:            ## 本地启动 Web 服务
	cd src && python main.py

stop:           ## 停止本地 Web 服务(按端口 8000)
	@echo "Stopping local Web on :8000..."
	@-cmd //c "for /f \"tokens=5\" %a in ('netstat -ano ^| findstr :8000') do taskkill /F /PID %a" 2>/dev/null
	@echo "Done."

doctor:
	python scripts/doctor.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov
	@echo "Cleaned."

# ========== Docker 开发模式 ==========

docker-build:
	docker build -t green-agent:dev .

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f --tail=100

docker-ps:
	docker compose ps

docker-shell:
	docker compose exec green-agent /bin/bash || docker compose exec green-agent /bin/sh

# ========== Docker 生产模式(P5-J) ==========

# 检查 .env.prod 存在,不存在则提示创建
prod-precheck:
	@if [ ! -f .env.prod ]; then \
		echo "[ERROR] .env.prod 不存在。复制 .env.example 为 .env.prod 并填入真实 API key:"; \
		echo "  cp .env.example .env.prod && vim .env.prod"; \
		exit 1; \
	fi

prod: prod-precheck            ## 启动生产容器(P5-J)
	docker compose -f docker-compose.yml --env-file .env.prod up -d
	@echo ""
	@echo "═══ 生产容器启动完成 ═══"
	@echo "健康检查:  curl http://localhost:8000/api/health"
	@echo "指标:      curl http://localhost:8000/api/metrics"
	@echo "日志跟踪:  make prod-logs"
	@echo "状态:      make prod-status"

prod-stop:
	docker compose -f docker-compose.yml down

prod-logs:
	docker compose -f docker-compose.yml logs -f --tail=100

prod-shell:
	docker compose -f docker-compose.yml exec green-agent /bin/bash || docker compose -f docker-compose.yml exec green-agent /bin/sh

prod-status:
	@echo "═══ 容器状态 ═══"
	docker compose -f docker-compose.yml ps
	@echo ""
	@echo "═══ 健康探活 ═══"
	@curl -s -m 5 http://localhost:8000/api/health | head -c 500 || echo "[WARN] 服务未启动或不可达"
	@echo ""
	@echo ""
	@echo "═══ K8s readiness ═══"
	@curl -s -m 5 http://localhost:8000/api/ready || echo "[WARN] 服务未启动或不可达"
	@echo ""

prod-restart:
	docker compose -f docker-compose.yml restart green-agent
	@echo "容器已重启(走 SIGTERM graceful shutdown,等待 inflight ≤ 10s)"

# ========== 运维 ==========

backup:
	@mkdir -p backups
	@TS=$$(date +%Y%m%d_%H%M%S); \
	tar czf backups/data_$$TS.tar.gz data/ 2>/dev/null || (echo "[WARN] data/ 不存在或为空" && tar czf backups/data_$$TS.tar.gz --files-from /dev/null); \
	echo "[OK] 备份到 backups/data_$$TS.tar.gz"

restore:
	@if [ -z "$(FILE)" ]; then \
		echo "[ERROR] 用法: make restore FILE=backups/data_xxx.tar.gz"; \
		exit 1; \
	fi
	@echo "[WARN] 将覆盖现有 data/ 目录"
	@read -p "确认继续? (yes/no): " confirm && [ "$$confirm" = "yes" ]
	tar xzf $(FILE)
	@echo "[OK] 已从 $(FILE) 恢复"

db-shell:
	@echo "进入 data/accounts.db 调试(用 sqlite3):"
	@echo "  sqlite3 data/accounts.db '.tables'"
	@echo "  sqlite3 data/accounts.db 'SELECT * FROM accounts LIMIT 5;'"
	@echo "  sqlite3 data/audit_log.db 'SELECT * FROM audit_log ORDER BY id DESC LIMIT 10;'"
	@echo ""
	@echo "或 Python REPL:"
	@echo "  cd src && python -c \"import sqlite3; conn=sqlite3.connect('../data/accounts.db'); print(conn.execute('SELECT name FROM sqlite_master WHERE type=\\\"table\\\"').fetchall())\""
