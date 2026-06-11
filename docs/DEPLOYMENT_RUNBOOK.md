# 部署演练 Runbook — P6.R.1

> 完整"从开发机到生产"的部署演练步骤。
> 本文档**逐步可执行** — 配合 `deploy/` 目录下的 systemd / nssm / nginx 配置使用。
> **前提**:有 Linux 测试机 + Docker + 域名 + HTTPS 证书(或用 Let's Encrypt 自签)。

## 目录

- [0. 前置检查](#0-前置检查)
- [1. 单机 Docker 快速验证](#1-单机-docker-快速验证)
- [2. 生产环境部署(单容器)](#2-生产环境部署单容器)
- [3. 反向代理 + TLS](#3-反向代理--tls)
- [4. 部署后冒烟测试](#4-部署后冒烟测试)
- [5. 监控 + 日志 + 告警](#5-监控--日志--告警)
- [6. 灾备演练(P6.F)](#6-灾备演练p6f)
- [7. 升级流程](#7-升级流程)
- [8. 回滚流程](#8-回滚流程)
- [9. 常见问题排查](#9-常见问题排查)

---

## 0. 前置检查

```bash
# 0.1 域名 + DNS
# 假设域名:green-agent.example.com
dig +short green-agent.example.com  # 应返回生产服务器 IP

# 0.2 服务器
ssh deploy@green-agent.example.com 'uname -a; docker --version; docker compose version'

# 0.3 TLS 证书(Let's Encrypt)
# certbot certonly --nginx -d green-agent.example.com
# 输出 /etc/letsencrypt/live/green-agent.example.com/{fullchain.pem, privkey.pem}

# 0.4 .env.prod 准备
scp .env.prod deploy@green-agent.example.com:/opt/green-agent/.env.prod
ssh deploy@green-agent.example.com 'chmod 600 /opt/green-agent/.env.prod'
# 验证:9 个 API key 都不为 __SET_ME__ / sk-xxx 占位符
ssh deploy@green-agent.example.com 'cd /opt/green-agent && python -c "
import os; from dotenv import load_dotenv; load_dotenv(\".env.prod\")
for k in [\"API_KEY\",\"MINIMAX_API_KEY\",\"OPENAI_API_KEY\",\"ZHIPU_API_KEY\",\"BAIDU_API_KEY\",\"ALI_API_KEY\",\"DEEPSEEK_API_KEY\",\"GAODE_API_KEY\",\"HEFENG_WEATHER_API_KEY\"]:
    v = os.environ.get(k, \"\")
    if not v or v.startswith(\"__\") or v.startswith(\"sk-xxx\"):
        print(f\"FAIL {k}\")
    else:
        print(f\"OK {k}\")"'

# 0.5 数据迁移(从开发机)
scp -r data/ deploy@green-agent.example.com:/opt/green-agent/data/  # 含 7 个 SQLite + ChromaDB
ssh deploy@green-agent.example.com 'cd /opt/green-agent && ls -la data/'
```

## 1. 单机 Docker 快速验证

测试机验证:1 台 Linux + Docker,跑全栈。

```bash
# 1.1 拉取代码
git clone https://github.com/loanhoang489352-hub/green-low-carbon-agent.git
cd green-low-carbon-agent

# 1.2 配 .env.prod
cp .env.example .env.prod
vim .env.prod
# 填入 API key(测试值即可,验证流程)

# 1.3 构建镜像
make docker-build
# 期望: green-agent:2.1.0 镜像,大小 < 500MB

# 1.4 启动容器
make prod
# 期望: green-agent 容器 up,健康检查 200/503
docker compose ps

# 1.5 探活
curl -s -o /dev/null -w "/api/health: HTTP %{http_code}\n" http://localhost:8000/api/health
curl -s -o /dev/null -w "/api/ready:  HTTP %{http_code}\n" http://localhost:8000/api/ready
curl -s http://localhost:8000/api/metrics | python -m json.tool | head -20
```

## 2. 生产环境部署(单容器)

### 2.1 部署目录

```bash
# 2.1.1 服务器准备
sudo mkdir -p /opt/green-agent/{data,logs,backups}
sudo chown -R deploy:deploy /opt/green-agent
cd /opt/green-agent

# 2.1.2 克隆(只读)
git clone https://github.com/loanhoang489352-hub/green-low-carbon-agent.git .

# 2.1.3 配置
cp .env.example .env.prod
vim .env.prod
# 填入 9 个真实 API key
chmod 600 .env.prod
```

### 2.2 启动

```bash
# 2.2.1 构建 + 启动
make docker-build
make prod

# 2.2.2 验证容器健康
docker compose ps
# 期望:
# NAME            STATUS         PORTS
# green-agent     Up (healthy)  0.0.0.0:8000->8000/tcp

# 2.2.3 看启动日志
make prod-logs
# 期望首 20 行:Schema Registry 7 DB ready + APScheduler started + LangGraph ready

# 2.2.4 真探活
make prod-status
# 期望:
# /api/health: HTTP 200
# /api/ready:  HTTP 200
# accounts.db reachable
```

### 2.3 资源限制(docker-compose.yml)

```yaml
deploy:
  resources:
    limits:
      cpus: '2.0'        # 2 vCPU
      memory: 2G         # 最大 2GB
    reservations:
      cpus: '0.5'        # 至少 0.5 vCPU
      memory: 512M       # 至少 512MB
```

监控:`docker stats green-agent` 看实际占用,根据调整。

### 2.4 日志 + 数据持久化

```bash
# 2.4.1 日志轮转(已配 docker logging 100MB × 3 = 300MB 上限)
ls -lah /var/lib/docker/containers/$(docker inspect --format='{{.Id}}' green-agent)/

# 2.4.2 data/ 目录备份(每 6 小时)
0 */6 * * * cd /opt/green-agent && python scripts/backup.py --incremental --keep 4 >> /var/log/green-agent-backup.log 2>&1
```

## 3. 反向代理 + TLS

用 nginx 反代 8000 端口 + TLS 终止 + 限流。

### 3.1 nginx 配置

```bash
# 3.1.1 复制配置
sudo cp deploy/nginx.conf /etc/nginx/sites-available/green-agent
sudo ln -s /etc/nginx/sites-available/green-agent /etc/nginx/sites-enabled/

# 3.1.2 测试配置
sudo nginx -t
# 期望: syntax is ok / test is successful

# 3.1.3 重载
sudo systemctl reload nginx
```

### 3.2 验证

```bash
# 3.2.1 HTTPS + 200
curl -sI https://green-agent.example.com/api/health
# 期望: HTTP/2 200 + 严格 HSTS 头

# 3.2.2 HTTP 自动跳转 HTTPS
curl -sI http://green-agent.example.com/api/health
# 期望: 301 / 308 → https://

# 3.2.3 HSTS 头
curl -sI https://green-agent.example.com | grep -i strict-transport
# 期望: strict-transport-security: max-age=31536000; includeSubDomains

# 3.2.4 /api/metrics 限内网(注释启用后)
curl -s -o /dev/null -w "%{http_code}\n" https://green-agent.example.com/api/metrics
# 期望: 403(从外网访问,内网白名单)
```

## 4. 部署后冒烟测试

**所有测试都应通过**。任何失败 = 部署不通过。

```bash
# 4.1 健康探活
scripts/deploy_smoke_test.sh
# (见下节:本目录 deploy_smoke_test.sh)

# 4.2 限流测试
for i in {1..65}; do
  curl -s -o /dev/null -w "%{http_code} " http://localhost:8000/api/health
done
# 期望: 前 60 个 200,后 5 个 429

# 4.3 鉴权测试
curl -s -X POST http://localhost:8000/api/chat/enhanced
# 期望: 401 + {"error":{"code":"UNAUTHORIZED","message":"需要登录"}}

# 4.4 LLM_MOCK 路径(临时)
docker exec -it green-agent bash -c "LLM_MOCK=true python -c '
import sys; sys.path.insert(0, \"/app/src\")
from agent.core import GreenAgent
agent = GreenAgent()
r = agent.chat_enhanced(\"u_test\", \"测试\")
print(\"OK:\" if r.message else \"FAIL\")
'"
# 期望: OK:...

# 4.5 三层记忆工作
# (类似 e2e 测试,但在生产环境)
```

## 5. 监控 + 日志 + 告警

### 5.1 Prometheus 抓取

`/api/metrics` 返 JSON,可直接抓 `data.metrics.{total_calls, error_rate, p50/p95/p99, total_tokens, query_cache, by_provider}`。

```yaml
# /etc/prometheus/prometheus.yml 加
scrape_configs:
  - job_name: 'green-agent'
    metrics_path: '/api/metrics'
    static_configs:
      - targets: ['localhost:8000']
    scrape_interval: 30s
```

### 5.2 关键告警

```yaml
# /etc/prometheus/rules/green-agent.yml
groups:
  - name: green-agent
    rules:
      - alert: HighErrorRate
        expr: error_rate > 0.1
        for: 5m
        annotations:
          summary: "green-agent 错误率 > 10%"
      - alert: HighLatency
        expr: p95_latency_ms > 5000
        for: 5m
        annotations:
          summary: "green-agent P95 > 5s"
      - alert: ContainerDown
        expr: up{job="green-agent"} == 0
        for: 1m
        annotations:
          summary: "green-agent 容器宕机"
      - alert: DiskSpaceLow
        expr: disk_free_mb < 1000
        for: 5m
        annotations:
          summary: "green-agent 磁盘 < 1GB"
```

## 6. 灾备演练(P6.F)

```bash
# 6.1 全量备份
cd /opt/green-agent
python scripts/backup.py
# 期望: backups/data_YYYYMMDD_HHMMSS.tar.gz + .sha256 + .manifest.json

# 6.2 验证 SHA
sha256sum -c backups/data_*.tar.gz.sha256
# 期望: OK

# 6.3 模拟灾难(改名 data/)
mv data data.corrupt

# 6.4 恢复
python scripts/restore.py --latest --yes
# 期望: 恢复完成,data/ 重新出现

# 6.5 验证 Web 仍工作
curl -s http://localhost:8000/api/health
# 期望: 200

# 6.6 清理
rm -rf data.corrupt
```

## 7. 升级流程

```bash
# 7.1 备份当前
make backup
# 期望: backups/data_BEFORE_UPGRADE_*.tar.gz

# 7.2 拉新代码
cd /opt/green-agent
git fetch --tags
git checkout v2.X.Y  # 或 main

# 7.3 看 CHANGELOG 升级项
less CHANGELOG.md

# 7.4 装新依赖
pip install -r requirements.txt

# 7.5 重启容器(SIGTERM graceful,P5-J 等待 ≤10s)
make prod-restart
# 等 16s 模型加载

# 7.6 验证
make prod-status
python -m pytest tests/ -q  # 本机全量回归(不依赖服务)

# 7.7 监控 30 分钟
# tail -f data/logs/app.log
# /api/metrics 错误率 ≤ 0.05
```

## 8. 回滚流程

升级失败时:

```bash
# 8.1 停服务
make prod-stop

# 8.2 恢复数据(用升级前备份)
python scripts/restore.py --file backups/data_BEFORE_UPGRADE_*.tar.gz --yes

# 8.3 回滚代码
git checkout v2.X-1.Y  # 上一版本

# 8.4 重启
make prod

# 8.5 验证
make prod-status
```

## 9. 常见问题排查

详见 `docs/RUNBOOK.md` 的 4 故障场景(磁盘满 / ChromaDB 损坏 / SQLite 锁 / OOM)。

---

## ✅ 演练检查清单(总览)

| 阶段 | 验证项 | 期望 | 状态 |
|---|---|---|---|
| 0. 前置 | 9 个 API key 不为占位符 | 全 OK | ☐ |
| 0. 前置 | DNS 解析到服务器 IP | 匹配 | ☐ |
| 0. 前置 | TLS 证书生成 | fullchain.pem + privkey.pem 存在 | ☐ |
| 1. Docker 验证 | 镜像构建 < 500MB | < 500MB | ☐ |
| 1. Docker 验证 | 容器 up + healthy | Up (healthy) | ☐ |
| 2. 生产部署 | data/ 已迁移 | 7 SQLite + ChromaDB | ☐ |
| 2. 生产部署 | 资源限制生效 | cpus 2 / mem 2G | ☐ |
| 2. 生产部署 | 日志轮转 100MB × 3 | 验证 | ☐ |
| 3. nginx | HTTPS 200 | 200 | ☐ |
| 3. nginx | HTTP → HTTPS 跳转 | 301 | ☐ |
| 3. nginx | HSTS 头存在 | max-age=31536000 | ☐ |
| 3. nginx | /api/metrics 限内网 | 403 from external | ☐ |
| 4. 冒烟 | /api/health 200 | 200 | ☐ |
| 4. 冒烟 | /api/ready 200 | 200 | ☐ |
| 4. 冒烟 | 限流 60+1 触发 429 | 429 | ☐ |
| 4. 冒烟 | 鉴权 401 | 401 | ☐ |
| 5. 监控 | Prometheus 抓取 | /api/metrics 200 | ☐ |
| 5. 监控 | 告警规则 | 4 个 alert 配置 | ☐ |
| 6. 灾备 | 全量备份 + SHA 验证 | OK | ☐ |
| 6. 灾备 | 恢复后 Web 工作 | 200 | ☐ |
| 7. 升级 | 备份 + 拉新 + 重启 | 全过 | ☐ |
| 8. 回滚 | 恢复数据 + 回滚代码 | 全过 | ☐ |

---

**真上线演练完成 = 18+ 检查项全过**。失败任意 1 项 = 部署不通过,需回滚。

总耗时:**~3-4 小时**(单机);**~1 个工作日**(生产机 + 监控集成)。
