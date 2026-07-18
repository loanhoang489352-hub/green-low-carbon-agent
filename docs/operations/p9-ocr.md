# P9 OCR — SRE / 运维手册

> **受众**:运维工程师 / 值班 SRE。熟 Linux + Docker,刚接触本项目也能照着命令排障。
> **目标**:出问题时 **5 分钟内** 定位根因 + 应急。
> **适用版本**:v2.0+ / P9.OCR(2026-07-18)。
> **最后更新**:2026-07-18。

---

## 目录

1. [P9 在生产环境的形态](#1-p9-在生产环境的形态)
2. [关键指标(KPI)](#2-关键指标kpi)
3. [告警规则](#3-告警规则)
4. [常见故障 + 排查](#4-常见故障--排查)
5. [应急操作(无需重启)](#5-应急操作无需重启)
6. [维护任务](#6-维护任务)
7. [升级 / 回滚](#7-升级--回滚)
8. [联系 / 升级流程](#8-联系--升级流程)

---

## 1. P9 在生产环境的形态

P9 OCR 是**摄入管道**(inbound ingestion pipeline)的最后一环:政策站 / 知识源返回的 PDF / 图片,先由 pdfplumber 抽文本层,扫不出来再走 PaddleOCR 本地 → 阿里云云端兜底,结果存 JSON 缓存 + 入库。

```
PolicyUpdater / KnowledgeUpdater
  └─→ IngestOrchestrator
        ├─ PDF  → pdfplumber(文本层) → 扫描页 → render_page_to_image → OCR
        └─ Image → 直接 OCR
                                          ↓
                              ┌───────────────────────────┐
                              │ OCRRouter(confidence ≥ ?  │
                              │           ↓ 否则 fallback)│
                              └───────────────────────────┘
                                          ↓                ↓
                                PaddleOCR 本地       阿里云 ReadOCR
                                (ch / 300MB)         (env ALIYUN_OCR_KEY)
                                          ↓                ↓
                                          └───→  merge (高分胜出)
                                                      ↓
                                          data/ocr_cache/<sha256>.json
                                                      ↓
                                          KNOWLEDGE_UPDATED 事件
                                                      ↓
                                  RAG 重建(/api/rag/status 进度)
```

### 1.1 关键路径与文件位置

| 资源 | 路径 / 来源 |
|---|---|
| PaddleOCR 模型目录 | `~/.paddleocr/`(`%USERPROFILE%\.paddleocr\` / Linux `$HOME/.paddleocr/`);首次调用时 PaddleOCR 自动下载 ~300MB 到此目录 |
| 阿里云 API key | **环境变量** `ALIYUN_OCR_KEY` + `ALIYUN_OCR_SECRET`(启动时校验非占位符) |
| 缓存目录 | `<DATA_DIR>/ocr_cache/` —— 容器内 `/app/data/ocr_cache/`,宿主机挂载的 `data/ocr_cache/<sha256>.json` |
| 临时 PDF / 渲染图 | `tempfile.gettempdir()` —— 容器内 `/tmp`,**注意不要持久化** |
| OCR 日志 | `<DATA_DIR>/logs/app.log`(JSON 行,自动滚动) |
| 配置 | `config/settings.yaml::ocr.use_local / cloud_fallback / lang / confidence_threshold` |
| 定时任务 | APScheduler, `30 2 * * *` (Asia/Shanghai) —— job id `ocr_incremental` |
| 主入口 | `src/ingest/ocr_engine.py::get_ocr_engine()`(单例懒加载) |
| 路由 | `src/ingest/ocr_router.py::OCRRouter.should_use_cloud` |
| 缓存 | `src/ingest/ocr_cache.py::get_ocr_cache()` |

### 1.2 容器化注意

`Dockerfile` 已经在 builder / runtime 都装了 `tesseract-ocr + libgl1 + libglib2.0-0`,作为 PaddleOCR 不可用时的**退化路径**。**线上推荐用 PaddleOCR ≥ 2.7 + paddlepaddle CPU 版**,内存占用约 300MB(模型懒加载,首次 `recognize()` 时才 import)。

容器启动顺序:`tini` → `python src/main.py` → `init_app()` → `start_scheduler()` → APScheduler 注册 `ocr_incremental` cron。无 PaddleOCR 时引擎降级为 `engine: "ocr_failed"`,不抛异常。

---

## 2. 关键指标(KPI)

| 指标 | 阈值 / 健康值 | 数据来源 | 端点 |
|---|---|---|---|
| **OCR 成功率**(过去 1h) | ≥ 95% | `data/logs/app.log` 的 `engine` 字段聚合 | `curl /api/metrics` |
| **OCR 成功率**(过去 24h) | ≥ 95% | 同上 | `scripts/eval_ocr.py` |
| **平均处理时长** P50 | ≤ 5s / 单图 | `data/logs/app.log` 解析 `latency_ms` | `curl /api/metrics` |
| **平均处理时长** P95 | ≤ 30s / 单图(含大 PDF 单页渲染) | 同上 | `curl /api/metrics` |
| **本地 OCR 命中率** | ≥ 70%(`engine = "paddleocr"`) | 日志聚合 | `/api/metrics` JSON 聚合 |
| **云端 fallback 命中率** | ≤ 30%(命中后阈值会上调避免抖动) | 日志聚合 | `/api/metrics` JSON 聚合 |
| **缓存命中率** | ≥ 80%(`cached: true` / 总 OCR 调用) | `data/ocr_cache/*.json` 文件数 vs ingest 调用 | 自定义 Prometheus 推算 |
| **失败重试次数** | ≤ 5 / h / 单源 | APScheduler job execution log | `data/logs/app.log` |
| **02:30 cron 是否执行** | 上次执行 < 26h 前 | scheduler last-run timestamp | `/api/health` → `scheduler.detail.jobs` |
| **缓存目录大小** | ≤ 10GB | `du -sh data/ocr_cache/` | crontab 脚本 |
| **磁盘剩余**(`/app/data`) | ≥ 10GB | `df -h` | `/api/health.disk_space` |
| **模型文件大小** | ≥ 200MB(`~/.paddleocr/` 总和) | `du -sh ~/.paddleocr/` | 手动 |

```bash
# 实时拿 LLM 指标(P5-B;OCR 复用 metrics 模块)
curl -s http://localhost:8000/api/metrics | jq '.metrics | {p50: .p50_latency_ms, p95: .p95_latency_ms, error_rate, total_calls}'

# 计算缓存大小
du -sh /opt/green-agent/data/ocr_cache/

# 数缓存文件
ls /opt/green-agent/data/ocr_cache/*.json | wc -l
```

### 2.1 离线指标计算脚本

```bash
# 过去 1 小时 OCR 成功率(从 JSON 日志聚合)
jq -r 'select(.logger | test("ingest|ocr|paddle|aliyun")) |
       "\(.ts) \(.engine // .msg // "")"' data/logs/app.log | \
  awk '/[0-9]+:[0-9]+:[0-9]+/{ ts=$1 } /paddleocr|aliyun|hybrid/{ print ts, $0 }' | \
  tail -5000 | awk '{ if (/aliyun/) cloud++; else local++; total++ }
                    END { print "local=", local, "cloud=", cloud, "rate=", local/total }'
```

---

## 3. 告警规则

> 推荐接 Prometheus Alertmanager / 内部 on-call。所有规则都要对单点抖动做去抖(`for: 5m`),避免 PaddleOCR 首次冷启动触发误报。

| 严重度 | 规则 | 阈值 | 持续 | 自动动作 |
|---|---|---|---|---|
| **P2** | OCR 成功率(过去 1h) | < 95% | 5m | 查本地引擎 + 阿里云 key;`echo OCR_LOW_RATE \| notify` |
| **P2** | P95 处理时长 | > 30s | 10m | 检查 CPU / 内存;是否大批量 PDF |
| **P2** | PaddleOCR 不可用 | `engine = "paddleocr_unavailable"` 在日志出现 ≥ 3 次 / 5m | 5m | 重启 / 修复 paddlepaddle 依赖 |
| **P2** | 阿里云 4xx | ≥ 10 / h | 1h | 检查 key 过期;`engine = "aliyun_unavailable: ALIYUN_OCR_KEY/SECRET 未配置"` |
| **P3** | 缓存目录 | > 10GB | 1h | 触发清理 job(`find data/ocr_cache/ -mtime +30 -delete`) |
| **P3** | 缓存命中率 | < 50% 持续 24h | 24h | 检查 `content_hash` 是否真正重复;可能源站文件被改 |
| **P3** | cron 没跑 | `ocr_incremental` 上次执行 > 26h 前 | — | 重启 scheduler;查 `data/logs/app.log` `[Scheduler]` |
| **P3** | 磁盘剩余 | < 5GB | 5m | 触发 `RUNBOOK.md::场景1` 清理 |
| **P3** | OCR 引擎 fall-through 日志 | `[OCRRouter] 置信度 %s < %s 但云端 key 未配置` 出现 1 次 | 1m | 配 key |
| **P4** | PDF 文档渲染失败 | `save_page_image` 异常 ≥ 1 次 / h | 1h | 检查 pdfplumber + libgl1 |

### 3.1 告警对应 Prometheus 样例

```yaml
# /etc/prometheus/rules/ocr.yml
groups:
  - name: ocr_alerts
    rules:
      - alert: OCRSuccessRateLow
        expr: ocr_success_1h / ocr_total_1h < 0.95
        for: 5m
        labels: { severity: page }
        annotations:
          summary: "OCR success rate {{ $value | humanizePercentage }} < 95%"
          runbook: docs/operations/p9-ocr.md#4-常见故障

      - alert: OCRLatencyHigh
        expr: histogram_quantile(0.95, ocr_latency_seconds_bucket) > 30
        for: 10m
        labels: { severity: warn }

      - alert: OCRCacheSizeLarge
        expr: ocr_cache_bytes > 10 * 1024 * 1024 * 1024
        for: 1h
        labels: { severity: warn }

      - alert: AliyunOCR4xxBurst
        expr: rate(ocr_aliyun_4xx_total[1h]) * 3600 > 10
        for: 5m
        labels: { severity: page }
```

---

## 4. 常见故障 + 排查

> 形式:**症状 → 排查命令 → 修复动作**。

### 4.1 症状:PDF 入库失败 / 日志 `OCR engine not initialized`

```bash
# 1) 看具体错误
grep -E "paddleocr_unavailable|recognize_failed|ocr_failed" data/logs/app.log | tail -20

# 2) 看 PaddleOCR 是否下载完整
du -sh ~/.paddleocr/        # 期望 ≥ 200MB
ls ~/.paddleocr/2.5/       # 应有 det / rec / cls 三个子目录

# 3) 看依赖是否齐全
python -c "from paddleocr import PaddleOCR; PaddleOCR(lang='ch', use_angle_cls=True)" 2>&1 | tail -5

# 4) 看磁盘
df -h /tmp /app/data       # 模型下载需要 ~500MB 临时空间

# 5) 权限(容器内)
docker exec green-agent ls -la /home/greenagent/.paddleocr/   # 应属 greenagent 用户
```

**修复**:
```bash
# a) 模型文件丢,强制重新下载
rm -rf ~/.paddleocr/        # 或 docker 容器内 /home/greenagent/.paddleocr/
systemctl restart green-agent   # 或 docker restart green-agent

# b) paddlepaddle 报错(常见:libstdc++ 版本低)
pip install --upgrade paddlepaddle paddleocr

# c) 权限问题(容器部署)
docker exec -u root green-agent chown -R greenagent:greenagent /home/greenagent/.paddleocr
docker restart green-agent

# d) 完全不可用 → 临时降级到云端 only
# config/settings.yaml → ocr.use_local: false  →  reload(service 监听 SIGHUP)
```

### 4.2 症状:云端 fallback 不工作

```bash
# 1) 看 router 日志
grep "OCRRouter\|aliyun_unavailable\|aliyun_failed" data/logs/app.log | tail -20

# 2) 校验环境变量(注意占位符)
docker exec green-agent env | grep -i ALIYUN_OCR
# 期望:
#   ALIYUN_OCR_KEY=LTAI5xxx(不是 __SET_ME__)
#   ALIYUN_OCR_SECRET=xxx(不是 your_secret_key)

# 3) 直连测试阿里云 SDK
docker exec green-agent python -c "
from aliyunsdkcore.client import AcsClient
c = AcsClient('\$ALIYUN_OCR_KEY', '\$ALIYUN_OCR_SECRET', 'cn-shanghai')
print('client ok')
"

# 4) 看 SDK 配额(aliyun 控制台 → OCR 概览 → QPS / 月调用量)
```

**修复**:
```bash
# a) env 缺失
export ALIYUN_OCR_KEY="LTAI5xxxxxxxxxxxxx"
export ALIYUN_OCR_SECRET="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
# 写入 systemd EnvironmentFile 或 K8s Secret

# b) 占位符未替换(常见于 .env.example 拷贝完没改)
grep -E "__SET_ME__|your_access_key" .env          # 应为零
# 修:vim .env → 填真实值

# c) github.com / 政府站点域名被防火墙拦截(罕见)
curl -I https://github.com/PaddlePaddle/PaddleOCR  # 测试通
curl -I https://market.aliyun.com/products/57124001/cmapi020020.html

# d) 服务端返回 4xx(配额满 / access denied)
# 控制台 https://ram.console.aliyun.com/manage/ak 重新生成 KeyPair
# 配额见 https://ocr.console.aliyun.com/  → 用量 / 告警
```

### 4.3 症状:02:30 定时任务没跑

```bash
# 1) scheduler 是否活
curl -s http://localhost:8000/api/health | jq '.health.checks.scheduler'
# 期望: "scheduler running, jobs=6"

# 2) 列出所有 job
curl -s http://localhost:8000/api/health | jq '.health.checks.scheduler.detail'

# 3) 历史日志
grep "ocr_incremental\|增量 OCR 完成\|增量 OCR 失败" data/logs/app.log | tail -20

# 4) 看时区(注意:容器默认 UTC,02:30 UTC = 北京时间 10:30)
docker exec green-agent date
docker exec green-agent cat /etc/timezone 2>/dev/null
```

**修复**:
```bash
# a) scheduler 未启动
systemctl restart green-agent
# b) 时区问题
docker run -e TZ=Asia/Shanghai ...   # K8s pod.spec.tz 或 env
# c) job 异常被换 coalesce
# 改 src/scheduler.py::start_scheduler → ocr_incremental 替换 → 重启
# d) 手动跑一次(不重启)
docker exec green-agent python -c "
from knowledge.updater import KnowledgeUpdater
print(KnowledgeUpdater().process_pending_ocr())
"
```

### 4.4 症状:OCR 慢 / 队列堆积

```bash
# 1) CPU / 内存
top -p $(pgrep -f "python.*main.py" | head -1)

# 2) 当前 in-flight 请求
ss -tnp | grep ":8000" | grep -c ESTAB

# 3) PaddleOCR 是否 FP16(默认 false)
grep -E "use_fp16|model_precision" /home/greenagent/.paddleocr/*/config.json  # 若 GPU 部署改 true

# 4) 是否大批量 PDF(单文件 > 50 页)
grep "page_count" data/ocr_cache/*.json | awk -F'"page_count":' '{print $2}' | \
  awk -F',' '{print $1}' | sort -n | tail -5

# 5) DPI 是否过大(默认 200)
grep -i "dpi" src/ingest/pdf_extractor.py   # render_page_to_image(dpi=200)
```

**修复**:
```bash
# a) CPU 被打满 → 切多 worker(K8s HPA + Gunicorn)或加并发数
# b) PDF 页数过多 → 临时限制
# src/ingest/orchestrator.py → IngestOrchestrator.__init__(max_pdf_pages=20)
# c) 临时降到 150 DPI(2 倍速)
# src/ingest/pdf_extractor.py::render_page_to_image(dpi=150)
# d) GPU 部署 → use_fp16=true(降一半显存 + 提速)
```

### 4.5 症状:重复 OCR 同一文件 / 缓存未命中

```bash
# 1) 看 cache 命中率
ls data/ocr_cache/*.json | wc -l         # 当前缓存数
grep "cached.*true\|cached.*false" data/logs/app.log | tail -100 | \
  awk '{ if ($0 ~ /true/) hit++; else miss++ } END { print "hit=", hit, "miss=", miss }'

# 2) 权限问题(写入失败 → 缓存失效)
ls -la data/ocr_cache/ | head -5
docker exec green-agent stat data/ocr_cache/test.json 2>&1 | head -5

# 3) content_hash 是否真重复?
python -c "
import hashlib, json, pathlib
for p in pathlib.Path('data/ocr_cache').glob('*.json'):
    d = json.loads(p.read_text(encoding='utf-8'))
    print(p.name, d.get('source_url'), d.get('page_count'), d.get('saved_at'))
" | head -10
```

**修复**:
```bash
# a) 权限(容器部署)
chown -R greenagent:greenagent data/ocr_cache/

# b) hash 算法变更 → 旧缓存失效(预期)
#    见 CHANGELOG.md 中 OCRCache.compute_hash 变更后,需清理 data/ocr_cache/
rm -rf data/ocr_cache/*.json  # 注意:下次会全部重 OCR(峰值压力)

# c) URL 加随机参数(部分政府站加 ?t=timestamp)
#    src/ingest/orchestrator.py::ingest_url → 提取前先 normalize URL
```

### 4.6 症状:`/api/health` 返 disk_space:DOWN

→ 切到 `RUNBOOK.md::场景 1`(OCR 缓存 > 50GB 时极端情况)清理。

### 4.7 症状:PaddleOCR 在 GPU 主机上报 OOM

```bash
# 查 nvidia-smi
nvidia-smi --query-gpu=memory.used,memory.total --format=csv

# PaddleOCR 3.x 默认 model_precision='fp32',在 GPU 上需 fp16
# ~/.paddleocr/2.5/det/config.json → model_precision: "fp16"
docker exec green-agent bash -c 'find ~/.paddleocr -name config.json | xargs sed -i "s/model_precision.*/model_precision: fp16/"'
docker restart green-agent
```

---

## 5. 应急操作(无需重启)

### 5.1 强制重建缓存(下次重 OCR)

```bash
# 仅失效本次想刷新的源:删对应 hash 文件
python -c "
import json, pathlib
target = 'https://www.gov.cn/.../policy.pdf'
for p in pathlib.Path('data/ocr_cache').glob('*.json'):
    d = json.loads(p.read_text(encoding='utf-8'))
    if d.get('source_url') == target:
        p.unlink()
        print('deleted', p)
"
# 全量清(慎用 → 下次 ingest 高峰)
rm -rf data/ocr_cache/*.json

# 清空并 reload(无需重启)—— 服务读 data/ocr_cache/ 在每次 OCR 调用,所以清理即时生效
```

### 5.2 临时禁用 OCR

```yaml
# config/settings.yaml
ocr:
  use_local: false          # 本地关
  cloud_fallback: false     # 云端关
```

```bash
# 让服务重读配置(假设接 SIGHUP,见 src/main.py)
systemctl reload green-agent
# 否则:用环境变量盖(无需改文件)
docker exec green-agent sed -i 's/use_local: true/use_local: false/' /app/config/settings.yaml
docker exec green-agent kill -HUP 1
```

**完全关掉(返回空 OCR 结果)**:把 `confidence_threshold` 调到 `1.0`,所有结果都 fallback → fallback 也关 → 直接 `error="OCR disabled"`。

### 5.3 切到云端 only(降级用阿里云)

```yaml
ocr:
  use_local: false         # PaddleOCR 不启
  cloud_fallback: true      # 走阿里云
```

### 5.4 关闭某源(避免反复触发)

```yaml
# config/sources.yaml
sources:
  - name: "故障源"
    url: "https://xxx"
    enabled: false   # PolicyUpdater._check_source 跳过
```

### 5.5 手动触发一次增量(不重启)

```bash
docker exec green-agent python -c "
from knowledge.updater import KnowledgeUpdater
print('processed:', KnowledgeUpdater().process_pending_ocr())
"
```

### 5.6 临时禁用 02:30 任务

```python
# src/scheduler.py → comment add_job ocr_incremental → 重启
# 或:docker exec -it green-agent bash
#      python -c "from scheduler import _scheduler; _scheduler.remove_job('ocr_incremental')"
# 注意:重启用同样代码 / 重启服务
```

---

## 6. 维护任务

### 6.1 每周(周一上午)

```bash
# 1) 缓存大小体检
du -sh data/ocr_cache/
COUNT=$(ls data/ocr_cache/*.json | wc -l)
echo "files: $COUNT"

# 2) 清理 > 30 天的缓存(未变更的政府文件一般是长期有效)
find data/ocr_cache/ -name "*.json" -mtime +30 -delete
# 注:mtime 是文件 mtime,不是 OCR saved_at 字段;如要更精确可用 saved_at 解析
python -c "
import json, pathlib, datetime, os
cutoff = datetime.datetime.now() - datetime.timedelta(days=30)
for p in pathlib.Path('data/ocr_cache').glob('*.json'):
    d = json.loads(p.read_text(encoding='utf-8'))
    try:
        ts = datetime.datetime.fromisoformat(d['saved_at'])
    except Exception:
        continue
    if ts < cutoff:
        os.remove(p)
        print('removed:', p.name)
"
```

### 6.2 每月(1 号凌晨)

```bash
# 1) PaddleOCR 模型版本核查
python -c "import paddleocr; print(paddleocr.__version__)"
python -c "import paddle; print(paddle.__version__)"

# 当前版本: PaddleOCR 3.x(API: ocr())/ 2.x(API: ocr(..., cls=True))—— 双 try 兼容

# 2) 跑回归测试
pytest tests/test_ocr_ingestion.py tests/test_ocr_engine.py -v

# 3) 核对阿里云 OCR 配额
# https://ocr.console.aliyun.com/  → 用量 / 余额
# 推荐设置:资源包 1 万次/月(政府站单次消费)

# 4) 备份缓存(对象存储)
tar czf /backup/ocr_cache_$(date +%Y%m%d).tgz data/ocr_cache/
```

### 6.3 每季度

```bash
# 1) 真 OCR 评估(CI gate)
USE_REAL_OCR=1 python scripts/eval_ocr.py
# 期望:char_error_rate_avg ≤ 0.10 且 keyword_hit_rate ≥ 0.85 → exit 0
# 报告: data/eval_report_ocr.md

# 2) 误判案例人工 review
cat data/eval_report_ocr.md | grep -A3 "未通过明细"

# 3) 重新抓 gov.cn / 各省政策,看 OCR 命中质量
curl -X POST http://localhost:8000/api/knowledge/reload
```

### 6.4 systemd timer 替代品(可选)

`Dockerfile` 用 tini,容器内 cron 不便。K8s 部署用 `CronJob`:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ocr-incremental
spec:
  schedule: "30 2 * * *"   # Asia/Shanghai(注意 K8s 默认 UTC,需配 timezone)
  timeZone: "Asia/Shanghai"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: ocr
              image: green-agent:latest
              command: ["python", "-c",
                "from knowledge.updater import KnowledgeUpdater; \
                 print(KnowledgeUpdater().process_pending_ocr())"]
```

---

## 7. 升级 / 回滚

### 7.1 PaddleOCR 升级

```bash
# 1) 锁版本(避免 breaking change 突然拉新版)
pip install -U paddleocr==<NEW_VERSION>
# requirements.txt
# paddleocr==<NEW_VERSION>      # 锁定

# 2) 备份模型(老版本不一定兼容)
cp -r ~/.paddleocr ~/.paddleocr.bak.$(date +%Y%m%d)

# 3) 测
pytest tests/test_ocr_engine.py tests/test_ocr_ingestion.py -v

# 4) 重启 + 切小流量观察
docker restart green-agent
# 监控 30 分钟:engine / confidence / error_rate

# 5) 跑端到端 eval
USE_REAL_OCR=1 python scripts/eval_ocr.py
```

**回滚**:

```bash
pip install paddleocr==<OLD_VERSION>
rm -rf ~/.paddleocr        # 强制模型重下(避免新旧混)
mv ~/.paddleocr.bak.<date> ~/.paddleocr/  # 或恢复
docker restart green-agent
```

### 7.2 阿里云 SDK 升级

```bash
pip install -U aliyun-python-sdk-ocr aliyun-python-sdk-core
# requirements.txt 锁版本
pytest tests/ -v -k ocr
docker restart green-agent
```

### 7.3 配置变更(无须重启 / 需 reload)

`config/settings.yaml::ocr` 改动后:

```bash
# 开发:
# 重启 uvicorn / python src/main.py
# 生产:
docker exec green-agent kill -HUP 1   # 假设 service 监听 SIGHUP
# 否则只能 docker restart green-agent
```

### 7.4 代码变更

```
branch: feat/p9-ocr-* (fork from main)
  ↓
PR + 2 review (SRE + 算法)
  ↓
CI 必须全绿:
  - tests/test_ocr_engine.py  (33+ case)
  - tests/test_ocr_ingestion.py
  - scripts/eval_ocr.py exit 0
  ↓
merge to main
  ↓
image tag v2.x.y → K8s rolling update
```

---

## 8. 联系 / 升级流程

### 8.1 责任分工

| 角色 | 联系方式 | 职责 |
|---|---|---|
| **SRE oncall** | PagerDuty `green-agent-sre` | 7x24 故障响应,/api/health down / disk / cache 满 / scheduler 死 |
| **OCR 算法 owner** | @ocr-owner | PaddleOCR 模型升级 / accuracy regression / 阈值调优 |
| **Dev owner** | @backend-owner | 代码改动 / 缺陷修复 / 性能调优 |
| **阿里云账号 admin** | @infra-admin | RAM / AK 轮换 / 配额扩容 |

### 8.2 故障升级路径

```
L1: SRE oncall → 5min 内 acknowledge
    ├─ 可自助处理 → 关 OCR / 切云端 / 清缓存 → 30 min
    └─ 需算法协助 → 拉 @ocr-owner

L2: @ocr-owner → 评估依赖兼容性 → 必要时切 mock + 发 hotfix
    └─ 仍不解 → 拉 @backend-owner

L3: 拉 infra 升级 / 退款 / 限额
    └─ P0 业务断流 → 写入 postmortem 模板,24h 内复盘
```

### 8.3 报告产物

| 触发 | 产出 |
|---|---|
| OCR 成功率 < 95% 持续 30min | Slack `data-incident` 频道 + 引用本文 §3 规则 |
| P95 > 30s 持续 1h | Slack `data-perf` + grep `latency_ms` |
| 阿里云 4xx burst | 阿里云工单 + RAM 控制台截图 |
| 缓存 > 10GB | 自动清理日志(为审计留档) |
| PaddleOCR 模型损坏 | postmortem(归档到 `docs/operations/postmortem-YYYYMMDD.md`) |

### 8.4 关键链接(模板)

- **Prometheus 规则**:`/etc/prometheus/rules/ocr.yml`(见 §3.1)
- **Grafana Dashboard**:`dashboard/ocr-overview.json`
- **Postmortem 模板**:`docs/operations/postmortem-template.md`
- **变更管理**:`docs/operations/CHANGE_LOG.md`(每次改 settings.yaml / 模型版本 / 阿里云配额都登记)
- **Git 仓库**:`https://github.com/<org>/green-agent`
- **镜像仓库**:`registry.example.com/green-agent:v2.x.y`
- **生产 K8s**:`kubectl -n green-agent get deploy green-agent`

---

## 附录 A:关键文件路径速查

```text
<PROJECT_ROOT>/
├── config/
│   ├── settings.yaml          # ocr.*(use_local / cloud_fallback / threshold)
│   └── sources.yaml           # OCR 增量源(URL 列表)
├── src/ingest/
│   ├── ocr_engine.py          # OCREngine + get_ocr_engine()
│   ├── ocr_router.py          # OCRRouter(阈值决策)
│   ├── image_ocr.py           # PaddleOCR + AliyunOCR
│   ├── pdf_extractor.py       # pdfplumber 文本层 + 扫描页 OCR 兜底
│   ├── orchestrator.py        # IngestOrchestrator(URL / bytes 入口)
│   ├── ocr_cache.py           # OCRCache 文件型
│   ├── html_media_extractor.py
│   └── front_matter.py        # 缓存 schema
├── src/scheduler.py           # 02:30 cron 入口(_ocr_incremental_job)
├── src/knowledge/updater.py   # _check_source_ocr / process_pending_ocr
├── src/policy/updater.py      # _fetch_and_ingest_ocr
├── data/
│   ├── ocr_cache/*.json       # 缓存文件(sha256[:32].json)
│   └── logs/app.log           # JSON 行日志
├── scripts/
│   └── eval_ocr.py            # 真 OCR 评估(golden set gate)
└── tests/eval/
    ├── ocr_golden_set.jsonl   # 50+ 条 curated / full
    └── build_golden.py        # 数据集构建
```

## 附录 B:一行命令速查

```bash
# 健康
curl -s http://localhost:8000/api/health | jq '.health'
curl -s http://localhost:8000/api/metrics | jq '.metrics.p95_latency_ms'

# 缓存大小
du -sh data/ocr_cache/

# 模型目录
du -sh ~/.paddleocr/

# 最近 24h 错误日志
grep -iE "ocr.*error|ocr.*failed|paddleocr_unavailable" data/logs/app.log | tail -50

# 阿里云 key 是否设置
docker exec green-agent bash -c 'echo "${ALIYUN_OCR_KEY:-MISSING}|${ALIYUN_OCR_SECRET:-MISSING}"'

# 手动触发一次
docker exec green-agent python -c "from knowledge.updater import KnowledgeUpdater; print(KnowledgeUpdater().process_pending_ocr())"

# 关 OCR(运行时)
docker exec green-agent sed -i 's/cloud_fallback: true/cloud_fallback: false/' /app/config/settings.yaml
docker exec green-agent kill -HUP 1 || docker restart green-agent

# 评估
USE_REAL_OCR=1 python scripts/eval_ocr.py

# 测试
pytest tests/test_ocr_engine.py tests/test_ocr_ingestion.py -v
```

---

**附**:本手册被 `docs/RUNBOOK.md` 引用(场景 1 磁盘清理 + 场景 2 ChromaDB 都可能波及 OCR 缓存);`docs/SECURITY.md` §3 密钥管理涉及 `ALIYUN_OCR_KEY/SECRET` 的轮换策略(每 90 天强轮,失效期间降级到本地 only)。所有 OCR 相关的 ingest 操作经 `data/logs/app.log`(JSON 行)可追溯,grep `engine` 字段可聚合引擎分布。
