# 绿色低碳智能体 — 运维手册(RUNBOOK)

> **本手册覆盖 4 个常见故障场景**:磁盘满 / ChromaDB 损坏 / SQLite 锁 / OOM。
> 每场景给:**症状 → 排查步骤 → 修复命令 → 预防措施**。
>
> 适用版本:v2.0(P5-J production-ready)
> 最后更新:2026-06-11

---

## 目录

- [场景 1:磁盘满(data/ 涨爆)](#场景-1磁盘满data-涨爆)
- [场景 2:ChromaDB 损坏(/api/rag/status 报 state=error)](#场景-2chromadb-损坏apiragstatus-报-stateerror)
- [场景 3:SQLite 锁(并发写阻塞,Database is locked)](#场景-3sqlite-锁并发写阻塞database-is-locked)
- [场景 4:OOM 内存爆掉(OOMKilled / 503)](#场景-4oom-内存爆掉oomkilled--503)
- [附录:常用排查命令速查](#附录常用排查命令速查)

---

## 场景 1:磁盘满(data/ 涨爆)

### 症状

- `GET /api/health` 返 `disk_space.status: "down"`(剩余空间 < 1GB)
- 容器日志: `[ERROR] No space left on device`
- Docker:`docker ps` 显示容器持续重启(restart loop)
- 业务表现:SQLite 写失败,LLM 上下文截断,ChromaDB upsert 报错

### 排查步骤

```bash
# 1) 看容器/主机磁盘使用
docker exec green-agent df -h /app/data

# 2) 看 data/ 各子目录大小(哪个涨得最快)
docker exec green-agent du -sh /app/data/* | sort -h | tail -10

# 3) 看 ChromaDB 索引大小(通常是大头)
du -sh /opt/green-agent/data/vector_db/

# 4) 看日志文件大小(P5-B JSON 日志可能涨得很快)
du -sh /opt/green-agent/data/logs/
```

### 修复命令

```bash
# 1) 紧急:清理过期 RAG 索引(临时禁用 RAG,腾空间)
cd /opt/green-agent
mv data/vector_db data/vector_db.bak
# 服务下次启动会自动重建(用 KB 文档)

# 2) 长期:配置日志轮转
# /etc/logrotate.d/green-agent
cat > /etc/logrotate.d/green-agent <<EOF
/opt/green-agent/data/logs/*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    size 100M
    copytruncate
}
EOF

# 3) SQLite WAL 文件膨胀(常驻 100MB+)
cd /opt/green-agent/data
# 强制 checkpoint
sqlite3 long_term_memory.db "PRAGMA wal_checkpoint(TRUNCATE);"
sqlite3 accounts.db "PRAGMA wal_checkpoint(TRUNCATE);"
# 对所有 .db 跑
for db in *.db; do sqlite3 "$db" "PRAGMA wal_checkpoint(TRUNCATE);"; done

# 4) 如果是 audit_log 表涨爆(> 1GB):
sqlite3 accounts.db "DELETE FROM audit_log WHERE created_at < datetime('now', '-30 days');"
# 加清理 cron: 每天凌晨 4 点清理 30 天前审计
# 0 4 * * * cd /opt/green-agent && python scripts/cleanup_audit.py
```

### 预防措施

- **监控**:`/api/health` 集成到 Prometheus,`disk_space` < 10GB 报警
- **日志轮转**:P5-B 已支持 `max-size: 100m, max-file: 3`(`docker-compose.yml`)
- **数据归档**:每月把 `data/feedback.db` `audit_log` 表迁移到冷存储
- **磁盘预留**:`/app/data` 至少 20GB(知识库 150 文档块 + ChromaDB + 7 个 SQLite)

---

## 场景 2:ChromaDB 损坏(/api/rag/status 报 state=error)

### 症状

- `GET /api/rag/status` 返 `{"state": "error", "message": "..."}`
- `GET /api/chat/enhanced` 报错 `"vector store unavailable"`
- 启动日志:`[ERROR] Failed to load ChromaDB collection: ...`
- 业务表现:聊天返回空 `knowledge_refs`,推荐降级为静态规则

### 排查步骤

```bash
# 1) 查 RAG 状态
curl -s http://localhost:8000/api/rag/status | python -m json.tool

# 2) 查 ChromaDB 物理文件
ls -la /opt/green-agent/data/vector_db/
# 正常: chroma.sqlite3 + <uuid>/ 目录
# 异常: chroma.sqlite3 0 字节 / .lock 残留 / 目录为空

# 3) 尝试手动加载看具体错误
cd /opt/green-agent
python -c "
import sys; sys.path.insert(0, 'src')
from rag.vector_store import create_vector_store
import os
os.environ['CHROMA_PATH'] = 'data/vector_db'
try:
    store = create_vector_store('chroma', 'green_agent_knowledge')
    print(f'count: {store.count()}')
except Exception as e:
    print(f'ERROR: {type(e).__name__}: {e}')
"

# 4) 看重建进度(P5-H 异步)
curl -s http://localhost:8000/api/rag/status
# 期望: {"state": "running", "progress": 45, ...}
```

### 修复命令

```bash
# 1) 紧急:触发异步重建(P5-H 已实现,不动数据)
curl -X POST http://localhost:8000/api/knowledge/reload
# 进度查询: curl http://localhost:8000/api/rag/status

# 2) 中度:数据损坏,需要重置索引
cd /opt/green-agent
# 备份当前索引(防止误删)
mv data/vector_db data/vector_db.corrupt-$(date +%Y%m%d_%H%M%S)
# 重建(后台异步)
curl -X POST http://localhost:8000/api/knowledge/reload
# 等待进度到 100% 大约 2-5 分钟(150 文档块)

# 3) 极端:ChromaDB 内部 SQLite 损坏,需要清空
rm -rf data/vector_db
# 服务重启后会自动重建
docker restart green-agent   # 或 systemctl restart green-agent

# 4) 验证修复
curl -s http://localhost:8000/api/rag/status
# 期望: {"state": "done", "total": 150, ...}
```

### 预防措施

- **定期备份**:`tar czf backups/vector_db_$(date +%Y%m%d).tar.gz data/vector_db/`(每周)
- **磁盘监控**:ChromaDB 异常时通常伴随磁盘满(见场景 1)
- **优雅关闭**:避免 `kill -9` 进程,触发 WAL 损坏
- **监控**:`/api/health` 中 `vector_store.status != ok` 时报警

---

## 场景 3:SQLite 锁(并发写阻塞,Database is locked)

### 症状

- 错误日志:`sqlite3.OperationalError: database is locked`
- 业务表现:聊天写入短期/长期记忆时偶发失败,401/500 比例上升
- `audit_log` 表写入阻塞,login 后用户看到延迟

### 排查步骤

```bash
# 1) 看哪个 DB 锁了
grep "database is locked" /opt/green-agent/data/logs/app.log | tail -20

# 2) 看活跃 SQLite 连接(可能用 lsof)
lsof /opt/green-agent/data/*.db
# 正常: 1-2 个连接(Python 进程)
# 异常: 多个进程同时持有(并发写锁)

# 3) 看 WAL 文件
ls -la /opt/green-agent/data/*.db-wal /opt/green-agent/data/*.db-shm

# 4) 看是否有僵尸 SQLite 进程
ps aux | grep -E "python|sqlite" | grep -v grep
```

### 修复命令

```bash
# 1) 紧急:重置 busy_timeout(临时)
cd /opt/green-agent
python -c "
import sqlite3
for db_file in ['data/accounts.db', 'data/long_term_memory.db', 'data/behavior_tracker.db', 'data/short_term.db']:
    conn = sqlite3.connect(db_file, timeout=30)
    conn.execute('PRAGMA busy_timeout = 5000;')  # 5s 重试
    conn.execute('PRAGMA journal_mode = WAL;')   # WAL 模式(已默认)
    conn.close()
    print(f'{db_file}: OK')
"

# 2) 中度:检查 db_schema.py 的 busy_timeout 配置
grep -A2 "busy_timeout" src/db_schema.py
# 期望看到: timeout=30 / busy_timeout=5000

# 3) 长期:启用连接池(避免每次新建连接)
# (P6 路线图,不阻塞当前)

# 4) 强制 checkpoint + 释放锁
cd /opt/green-agent/data
for db in accounts.db long_term_memory.db behavior_tracker.db short_term.db; do
    sqlite3 "$db" "PRAGMA wal_checkpoint(TRUNCATE);"
done
```

### 预防措施

- **P5-G 修复**:`src/db_schema.py` 已设 `busy_timeout=5000`,自动重试
- **WAL 模式**:7 个 SQLite DB 全部启用,允许并发读 + 单写
- **避免长事务**:不写 `BEGIN; ... sleep(10); COMMIT;`
- **监控**:`/api/health` 中加 `sqlite_locks` 计数器(待补)

---

## 场景 4:OOM 内存爆掉(OOMKilled / 503)

### 症状

- 容器状态:`docker ps` 显示 `Exited (137)` 或 `OOMKilled`
- 业务表现:突发流量后服务挂掉,重启后 503 持续几分钟
- `journalctl`:`Memory cgroup out of memory: Killed process 1234 (python)`

### 排查步骤

```bash
# 1) 看容器退出码
docker ps -a | grep green-agent
# 137 = 128 + 9 (SIGKILL by OOM killer)

# 2) 看内存使用曲线(重启前 vs 重启后)
docker stats green-agent --no-stream
# 期望: < 2GB(limit 设的)
# 异常: 接近 2GB 后被杀

# 3) 看 metrics(P5-B)
curl -s http://localhost:8000/api/metrics | python -m json.tool
# 看 avg_latency_ms / p95 / error_rate
# 长时间高 p95 + 高 error_rate = 资源耗尽

# 4) 看 RAG 引擎是否加载了多个 embedder
# (multi-tenant 场景下每用户一个 embedder 会 OOM)
grep "embedder" /opt/green-agent/data/logs/app.log | tail -20
```

### 修复命令

```bash
# 1) 紧急:提高内存 limit(临时缓解)
# docker-compose.yml
#   deploy.resources.limits.memory: 2G  →  4G
docker compose -f docker-compose.yml up -d

# 2) 中度:减少 RAG 并发 + 加 LRU 缓存
# src/rag/rag_engine.py
#   max_concurrent_queries: 4  (默认)
#   改为 2

# 3) 长期:切换到轻量 embedder
# 当前: paraphrase-multilingual-MiniLM-L12-v2 (100MB)
# 候选: all-MiniLM-L6-v2 (80MB,中文稍弱)
# 或: 切换到 API 调用(无本地内存)

# 4) 长期:启动后立刻 warm-up(避免首请求 OOM)
# 改 src/main.py: 启动时只加载 metadata,不立即 encode 全部 chunks

# 5) 加 swap 兜底(应急)
docker compose -f docker-compose.yml down
fallocate -l 4G /opt/green-agent/swapfile
chmod 600 /opt/green-agent/swapfile
mkswap /opt/green-agent/swapfile
swapon /opt/green-agent/swapfile
docker compose -f docker-compose.yml up -d
```

### 预防措施

- **资源限制**:`docker-compose.yml` 已设 `memory: 2G`(按需调)
- **P5-J SIGTERM graceful**:OOM 前能优雅退出,不留半成品
- **APScheduler 内存泄漏检测**:定期 `docker stats` 监控
- **Embedder 懒加载**:`src/rag/vector_store.py` 已支持,不要在 `init_app` 强制加载
- **告警**:Prometheus + AlertManager 在内存 > 80% 阈值报警

---

## 附录:常用排查命令速查

### 服务管理

```bash
# 启动
make prod                    # Docker 生产模式
systemctl start green-agent  # systemd 模式
nssm start GreenAgent        # Windows 服务模式

# 状态
make prod-status
systemctl status green-agent
docker ps | grep green-agent

# 重启(走 SIGTERM graceful,等待 inflight ≤10s)
make prod-restart
systemctl reload green-agent
docker restart green-agent

# 停止
make prod-stop
systemctl stop green-agent
```

### 灾备(P6.F 脚本)

```bash
# 全量备份(打包 7 个 SQLite + ChromaDB + memory_snapshots 到 backups/)
python scripts/backup.py

# 增量备份(只备份自上次 backup 改过的文件)
python scripts/backup.py --incremental

# 排除 logs/(节省空间)
python scripts/backup.py --exclude-logs

# 保留最近 10 个备份(默认 30)
python scripts/backup.py --keep 10

# 列出要备份的文件(不实际打包)
python scripts/backup.py --dry-run

# 上传到 S3(需 BACKUP_S3_BUCKET env)
BACKUP_S3_BUCKET=my-bucket BACKUP_S3_PREFIX=backups/ python scripts/backup.py --upload s3

# 列出可用备份(交互式选)
python scripts/restore.py

# 直接选最新恢复(--yes 跳过确认)
python scripts/restore.py --latest --yes

# 列出 tar 内容(不实际解压)
python scripts/restore.py --latest --dry-run

# 备份文件命名:data_YYYYMMDD_HHMMSS.tar.gz + .sha256 + .manifest.json
# 恢复前会自动 SHA256 校验,失败返 1
# 恢复前会自动备份当前 data/ 到 data_BEFORE_RESTORE_*.tar.gz
```

**自动备份 cron**(推荐):
```bash
# 每天凌晨 3 点全量 + 保留 14 天
0 3 * * * cd /opt/green-agent && python scripts/backup.py --keep 14 --upload s3
# 每小时增量
0 * * * * cd /opt/green-agent && python scripts/backup.py --incremental --keep 48
```

### 日志查看

```bash
# 应用日志(P5-B JSON formatter,直接 tail)
tail -f /opt/green-agent/data/logs/app.log | python -m json.tool

# 按 trace_id 串联
grep '"trace_id": "abc123def456"' /opt/green-agent/data/logs/app.log

# Docker 日志
docker logs -f --tail=100 green-agent
make prod-logs

# systemd 日志
journalctl -u green-agent -f --since "10 minutes ago"
```

### 健康探活

```bash
# 真探活(7 项子探活)
curl -s http://localhost:8000/api/health | python -m json.tool

# K8s readiness(只查 DB)
curl -s http://localhost:8000/api/ready

# LLM 调用指标
curl -s http://localhost:8000/api/metrics | python -m json.tool

# RAG 重建进度
curl -s http://localhost:8000/api/rag/status
```

### 数据库查询

```bash
# 账号库
sqlite3 data/accounts.db "SELECT * FROM accounts LIMIT 5;"
sqlite3 data/accounts.db "SELECT COUNT(*) FROM audit_log;"

# 长期记忆库
sqlite3 data/long_term_memory.db "SELECT COUNT(*) FROM user_memories;"
sqlite3 data/long_term_memory.db "SELECT user_id, importance, decay_count FROM user_memories ORDER BY importance DESC LIMIT 10;"

# 短期记忆库(P5-G)
sqlite3 data/short_term.db "SELECT conversation_id, message_count FROM conversation_meta ORDER BY message_count DESC LIMIT 10;"

# 行为追踪库
sqlite3 data/behavior_tracker.db "SELECT * FROM behavior_events ORDER BY created_at DESC LIMIT 10;"
sqlite3 data/behavior_tracker.db "SELECT user_id, carbon_kg, week FROM carbon_footprint_log ORDER BY created_at DESC LIMIT 10;"
```

### 数据备份/恢复

```bash
# 全量备份
make backup                  # tar czf backups/data_YYYYMMDD_HHMMSS.tar.gz data/

# 恢复
make restore FILE=backups/data_20260610_120000.tar.gz

# 仅备份 ChromaDB
tar czf backups/vector_db_$(date +%Y%m%d).tar.gz data/vector_db/

# 仅备份 SQLite
tar czf backups/sqlite_$(date +%Y%m%d).tar.gz data/*.db
```

### 性能诊断

```bash
# 实时内存
docker stats green-agent

# 进程级内存
docker exec green-agent ps aux --sort=-%mem | head

# 慢请求追踪
grep '"latency_ms": [0-9]\{4,\}' data/logs/app.log | tail -20

# 错误率趋势
grep -c '"level": "ERROR"' data/logs/app.log
```

---

**作者**:绿色低碳智能体项目组
**最后更新**:2026-06-11(P5-J 完成时同步)
**反馈**:GitHub Issues 或 `make doctor` 检查项目健康
