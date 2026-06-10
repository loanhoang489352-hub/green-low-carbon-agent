.PHONY: help install test lint clean docker-run docker-build

help:
	@echo "绿���低碳智能体 - Makefile"
	@echo ""
	@echo "可用命令:"
	@echo "  make install    - 安装依赖"
	@echo "  make test    - 运行测试"
	@echo "  make lint   - 代码检查"
	@echo "  make clean  - 清理缓存"
	@echo "  make docker-run  - 运行 Docker"
	@echo "  make docker-build - 构建 Docker"

install:
	pip install -r requirements.txt

test:
	pytest tests/ -v

lint:
	ruff check src/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
	rm -rf .coverage
	rm -rf htmlcov

docker-run:
	docker-compose up -d

docker-build:
	docker-compose build
