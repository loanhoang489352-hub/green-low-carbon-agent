# P6.R.2:政府站拓源操作手册

> 港 IP 下多数 .gov.cn 站 SSL 失败(政府站服务器端拒绝海外 IP)。
> 本手册说明**如何切大陆 IP + 用 P6.R.2 工具脚本测 8 个 .gov.cn 源**。
>
> **前提**:你能切换到中国大陆 IP(家庭宽带 / 公司 VPN / 云主机都行)。
> **风险**:本机可能被记录为"高频访问政府站",适度即可。

## 1. 切换到大陆 IP

### 选项 A:公司 VPN(推荐)
- 用公司 VPN 客户端连到大陆节点
- 验证:`curl -s https://api.ipify.org` 应返回大陆 IP(如 1.2.3.4 中国电信)

### 选项 B:云主机
- 阿里云 / 腾讯云 / 华为云 选大陆 region 的 ECS
- 按小时计费,跑脚本几小时就关
- 验证同上

### 选项 C:家庭宽带
- 直接用自己的家庭宽带(需大陆 ISP)

## 2. 验证大陆 IP

```bash
# 2.1 IP 检测
curl -s https://api.ipify.org
# 应是 1.2.3.4 / 36.x.x.x / 114.x.x.x 等大陆 IP

# 2.2 反向 DNS 验证
nslookup $(curl -s https://api.ipify.org)
# 应解析到中国电信/联通/移动

# 2.3 试访问一个 .gov.cn
curl -s -I https://www.mee.gov.cn/ | head -1
# 应 HTTP/1.1 200 OK
```

## 3. 跑 P6.R.2 测试脚本

切到大陆 IP 后,跑:

```bash
# 3.1 完整测(测所有候选 + 8 个 .gov.cn)
python scripts/test_new_sources.py --only-candidates --report data/p6r2_gov_test.md --timeout 15

# 3.2 实时看报告
cat data/p6r2_gov_test.md
```

期望(8 个 .gov.cn):
- **3-5 个可达**(mee.gov.cn / ndrc.gov.cn / nea.gov.cn 等大概率通)
- **3-5 个 SSL/超时失败**(有些政府站 IP 白名单很严)
- 报告里"建议启用"块直接给出 yaml

## 4. 启用通过的源

```bash
# 4.1 复制 report 里"建议启用"块
cat data/p6r2_gov_test.md | sed -n '/## 建议启用/,/```/p'

# 4.2 追加到 config/sources.yaml
# 在 policy_sources: 末尾 + # ====== P6.R.2 拓源 ====== 段
# 复制上面 yaml 内容粘贴

# 4.3 重启 agent(用新配置)
make stop
cd src && nohup python main.py > /tmp/web.log 2>&1 &
sleep 16

# 4.4 验证新源被 PolicyUpdater 抓
curl -X POST http://localhost:8000/api/policy/check-updates
# 返 JSON 含 policy_update 计数

# 4.5 知识库增长
sqlite3 data/policy_updates.db "SELECT COUNT(*) FROM policies"
# 比启用前多
```

## 4.5 切回海外 IP + 测试

切回海外 IP 后:

```bash
# 4.5.1 测启用后是否仍能跑(不依赖大陆 IP 维护)
python scripts/test_new_sources.py --only-candidates --report data/p6r2_post_check.md

# 4.5.2 如果某些启用源断了,改 .env
# 如 SSE/streaming 源,加 PROXY_URL
```

## 5. 持久化(纳入 sources.yaml 注释)

`config/sources.yaml` 顶部应注明 P6.R.2 启用日期 + 实际可达源:

```yaml
# P6.R.2 拓源 — 2026-06-XX 切大陆 IP 实测
# 启用: mee.gov.cn 政策文件页 / nea.gov.cn / 国家能源局首页
# 失败: 国家林草局 / 工信部(SSL 限制)
# 下次拓源: 切大陆 IP + 跑 python scripts/test_new_sources.py --only-candidates
```

## 6. 时间线

| 阶段 | 时间 | 操作 |
|---|---|---|
| 切 IP | 5min | 启 VPN / 云主机 |
| 验证 IP | 2min | curl ipify |
| 跑测 | 10min | python test_new_sources.py |
| 改 yaml | 5min | vim config/sources.yaml |
| 重启 + 验证 | 20min | make stop + start + check_updates |
| **合计** | **~45min** | 单次完整拓源 |

## 7. 已知问题

- **政府站反爬**:有些 .gov.cn 用 JavaScript 渲染,需用 playwright(已在 P6.P 装)
- **频率限制**:连发 10+ 请求可能触发临时 ban,默认 timeout 15s 间隔已足够
- **IP 记录**:测完后建议切回普通 IP,避免被列入政府站黑名单

## 8. 失败源记录

失败源(SSL/DNS/超时)记录到 `config/sources.yaml::disabled_sources`,如:

```yaml
disabled_sources:
  - name: "国家林草局-碳汇"
    url: "https://www.forestry.gov.cn/"
    reason: "SSL 错误(BAD_ECPOINT)"
    tested_date: "2026-06-XX"
    note: "P6.R.2 实测: 大陆 IP 也 SSL 失败,服务器端可能升级到 TLS 1.3 客户端不支持"
```

---

**总投入**:~45 min(切 IP + 测 + 启用 + 验证)
**预期产出**:8 个 .gov.cn 候选中 3-5 个可达,知识库 +15-30 文档块
**回退**:改 `config/sources.yaml` 把 enabled 改回 false + 重启即可

---

P6.R.2 是 P6.J 拓源的延伸,验证"工具 + 流程"能跨大陆 IP 工作。
