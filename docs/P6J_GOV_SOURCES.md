# P6.J 政府/媒体源拓源报告

> 2026-06-11 港 IP 实测,自动测试 + 启用 7 个新源。
> 详见 `scripts/test_new_sources.py` 自动测试工具。

## 工具脚本

```bash
# 测试所有 enabled + 候选源(默认 8s 超时)
python scripts/test_new_sources.py

# 只测试新候选源(推荐先用这个)
python scripts/test_new_sources.py --only-candidates

# 自定义超时(港 IP 推荐 8s,大陆 IP 可 5s)
python scripts/test_new_sources.py --timeout 5

# 自定义报告路径
python scripts/test_new_sources.py --report data/my_report.md
```

**输出**:`data/source_test_report.md` — 含:
- 状态码 / 大小 / 延迟 / 关键词命中数
- 建议启用的源(直接给出 yaml 块)
- 不可用源(应保留 disabled)

## 实测结果(2026-06-11 港 IP)

| 源 | 状态 | 大小 | 关键词 | 类别 |
|---|---|---|---|---|
| 新华网-能源频道 | OK | 40KB | 4 | 媒体-能源 |
| 经济参考报-绿色频道 | OK | 47KB | 1 | 媒体-绿色 |
| 财新网-环境频道 | OK | 31KB | 2 | 媒体-环境 |
| 中国新闻网-能源 | FAIL | 0.7KB | 0 | 反爬阻断 |
| 南方周末-绿色 | OK | 59KB | 2 | 媒体-调查 |
| 21 经济网-碳中和 | FAIL | 65KB | 0 | 页面太小/反爬 |
| **国家发改委-双碳** | **OK** | **85KB** | **2** | **政府-发改委** |
| **国家统计局-绿色发展** | **OK** | **139KB** | **4** | **政府-统计** |
| 中国环境与发展国际合作委员会 | FAIL | 0KB | 0 | DNS/SSL |
| Environmental Defense Fund | OK | 252KB | 4 | 国际-NGO |

## 重要发现

**港 IP 居然能访问部分 .gov.cn 站**(国家发改委 + 国家统计局),与之前 CLAUDE.md 写的"8 个 .gov.cn 全部 SSL 失败"矛盾 — 实际只有上海/深圳生态环境局 SSL 失败,**其他部分政府站在港 IP 可通**。

之前 KB-v2/KB-v4 测试可能用更严格的 headers 或不同时间点。

## 启用流程

1. **自动测试**:`python scripts/test_new_sources.py --only-candidates`
2. **看报告**:`data/source_test_report.md`(有"建议启用" yaml 块)
3. **加到 sources.yaml**:复制 yaml 块到 `config/sources.yaml` 的 `policy_sources:`
4. **重启 agent**:`make stop && cd src && python main.py`
5. **跑一次更新**:`curl -X POST http://localhost:8000/api/policy/check-updates`(PolicyUpdater 抓新源内容)
6. **验证知识库**:150 → 150+N 文档块(每源首次抓 1-5 文档)

## 持续工作流

- **每日 02:00**:`APScheduler` 自动跑 `daily_kb_update` 任务,PolicyUpdater 抓 24 小时内新内容
- **每周**:跑 `python scripts/test_new_sources.py` 测新候选源,把通过的加到配置
- **每月**:看 `data/source_test_report.md` 历史,禁用长期失败的源

## 已知不可用(2026-06 实测)

| 源 | 原因 | 备注 |
|---|---|---|
| 上海生态环境局 | DNS 失败 | sthjj.sh.gov.cn 域名可能退役 |
| 深圳生态环境局 | SSL BAD_ECPOINT | 服务器证书问题 |
| 中国新闻网-能源 | 反爬阻断 | 0.7KB 几乎空白 |
| 21 经济网-碳中和 | 反爬/内容少 | 65KB 但 0 关键词 |
| 国合会 cciced.net | ConnectError | 服务器积极拒绝 |

## 数据流

```
scripts/test_new_sources.py
  ↓
httpx GET → 状态码 + 大小 + 关键词
  ↓
data/source_test_report.md(报告)
  ↓
人工 review + 加到 config/sources.yaml
  ↓
APScheduler daily_kb_update → PolicyUpdater 抓内容
  ↓
data/policy_updates.db → 知识库(150 → 150+N)
  ↓
RAG 检索
```

## 候选源池(P6.J 阶段)

10 个候选源(详见 `scripts/test_new_sources.py::CANDIDATE_SOURCES`),可作为下次拓源起点:
- 新华网-能源频道 ✅
- 经济参考报-绿色频道 ✅
- 财新网-环境频道 ✅
- 南方周末-绿色 ✅
- 国家发改委-双碳 ✅
- 国家统计局-绿色发展 ✅
- Environmental Defense Fund ✅
- 中国新闻网-能源 ❌(反爬)
- 21 经济网-碳中和 ❌(反爬)
- 国合会 ❌(DNS)
