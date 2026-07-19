# 公网部署指南 — 5 分钟把本地服务暴露到公网

> 适用对象:第一次部署到公网的人(产品演示 / 灰度给真实用户试用 / 给导师/评审/合作伙伴一个能点开的链接)。
>
> 读完之后能回答:**为什么选这条路 / 怎么 5 分钟拿到 URL / URL 会不会变 / 怎么让它稳定 / 什么时候该升级到云端**。
>
> 姊妹篇:
> - `docs/RUNBOOK.md` / `docs/DEPLOYMENT_RUNBOOK.md` — 服务器/容器化部署
> - `docs/operations/p11-productionization.md` — 长期运维手册

---

## 1. 为什么选 Cloudflare Tunnel + 本地这条路

| 方案 | 成本 | 耗时 | 需要什么 | 风险 |
|---|---|---|---|---|
| **Cloudflare Tunnel(临时 URL)** ← 本指南 | 0 元,无需信用卡 | 5 分钟 | Windows + Python + 网络 | 重启 URL 变 |
| Hugging Face Spaces | 0 元 | 30~60 分钟 | GitHub 账号 | CPU 限速,LLM API 密钥要走 secret |
| 买 VPS(阿里云/腾讯云轻量) | 50~100 元/月 | 1~2 小时 | 实名 + 备案(国内) + Linux 基础 | 备案周期 7~20 天 |
| Cloudflare Tunnel + 固定 tunnel | 0 元 | 15 分钟 | Cloudflare 账号 + 域名(可选) | 仍依赖本机在线 |

**结论**:
- **只想给几个人试一下 / 演示一次 / 跑个临时分享** → 本指南(5 分钟)
- **想给 > 50 人稳定用 / 想关电脑也能访问** → 见第 7 节"什么时候升级到云端"

### 1.1 这条路的安全边界

- **本地端口 8000** → Cloudflare 全球边缘节点 → 公网用户
- Cloudflare 看不到你的明文流量(它的卖点),Cloudflare 自带 DDoS 防护
- **你的电脑关了 = URL 立即失效**,这是临时方案的本质
- 不需要在路由器上做端口映射 / 不需要公网 IP / 不需要搞 DDNS

---

## 2. 环境要求

| 项 | 要求 | 验证命令 |
|---|---|---|
| 操作系统 | Windows 10 / 11(脚本是 `.bat`,Linux 用 bash 替代) | `winver` |
| Python | 3.13(项目要求) | `python --version` |
| 网络 | 能访问 `github.com` + `*.trycloudflare.com` | 浏览器开 https://trycloudflare.com 能加载 |
| 端口 8000 | 当前空闲 | `netstat -ano \| findstr :8000`(空说明空闲) |
| 磁盘 | < 500 MB 给 logs/ + cloudflared/ | < 50 MB 实际上 |

### 2.1 如果 Python 还没装

到 https://www.python.org/downloads/ 下 3.13.x,装的时候 **勾上 "Add Python to PATH"**。
装完新开一个 cmd 验证:

```bash
python --version   # 应输出:Python 3.13.x
```

### 2.2 如果还没下项目 / 还没装依赖

```bash
cd D:\
git clone https://github.com/loanhoang489352-hub/green-low-carbon-agent.git
cd green-low-carbon-agent
pip install -r requirements.txt
copy .env.example .env   # 然后编辑 .env 填 9 个 API key
```

> `.env` 里的 API key 在启动时会强校验 — 缺一个或还是占位符 `__SET_ME__` / `sk-xxx` 直接报错退出。
> 见 `docs/SECURITY.md` 的"启动强校验"章节。

---

## 3. 三步启动(5 分钟)

### 步骤 1:双击 `scripts/start_public.bat`

路径:`D:\绿色低碳智能体\scripts\start_public.bat`(建议右键 → 固定到开始屏幕)

脚本会自动做 4 件事(全程无需人工干预):

```
[1/4] 清理端口 8000...        ← 杀掉上次残留的 python / cloudflared
[2/4] 启动 AI 服务...         ← 调 python main.py(端口 8000)
[3/4] 等待服务就绪(最多 60 秒) ← 轮询 /api/ready,绿了再继续
[4/4] 启动 Cloudflare 公网隧道...
```

### 步骤 2:看到公网 URL

启动成功后,窗口里会显示一行类似这样的:

```
+-----------------------------------------------------------+
|  Your quick Tunnel has been created! Visit it at:        |
|  https://xxxx-xxxx-xxxx.trycloudflare.com                 |
+-----------------------------------------------------------+
```

把这一行的 URL **复制下来** — 这就是你的公网入口。

### 步骤 3:复制 URL 给用户

直接把这个 URL 发给用户即可,无需加端口号。用户打开就能看到 Web 界面、调用 `/api/health` 等所有端点。

```bash
# 验证公网确实通(在另一台机器 / 手机 4G 网络下测)
curl https://xxxx-xxxx-xxxx.trycloudflare.com/api/health
# 期望: {"status": "ok", ...}
```

---

## 4. 第一次启动会怎样

| 状态 | 现象 | 需不需要操作 |
|---|---|---|
| **首次启动 cloudflared** | 直接出 URL,无任何账号/登录提示 | 不需要 — 临时 tunnel 模式(`tunnel --url`)是匿名 / 免登录的 |
| **首次启动 AI 服务** | 第一次调 LLM 会比较慢(冷启 ~5~15 秒),后续 < 2 秒 | 不需要 — 等就行 |
| **首次访问 URL** | 第一次握手可能 2~3 秒(Cloudflare 边缘冷启) | 不需要 |
| **之后每次启动** | 都一样,无需登录 | 不需要 |

> **重要**:本方案用的是 **临时 tunnel**(`--url` 模式),Cloudflare 给一个 24 小时内有效的随机 URL,**不**会写任何配置到你的账号,也**不**需要你注册 Cloudflare。
> 想稳定 URL 走第 5 节"稳定 URL 怎么做"。

---

## 5. 公网 URL 怎么工作

### 5.1 URL 的生命周期

```
本地 Python 服务 ──┐
                  ├─→ cloudflared 隧道进程 ──→ trycloudflare.com 边缘 ──→ 用户
                  │
关电脑 / 重启 ────┘  ↑
                    │
              进程死 / 重连 ─→ Cloudflare 重新分配一个新 URL
```

| 触发事件 | URL 变化? |
|---|---|
| 本机电脑重启 | **变**(新 URL) |
| `stop_public.bat` 主动停 | **变**(下次启动是新 URL) |
| 网络断开重连(< 1 分钟) | 一般不变(自动重连) |
| 网络断开重连(> 数小时) | 可能变(Cloudflare 主动回收空闲 tunnel) |
| cloudflared 进程被杀 | 立即失效(直到你重启) |

### 5.2 想稳定 URL 怎么做

如果你需要"一个不变的链接长期给用户用",走这条路(需要 Cloudflare 账号,仍免费):

```bash
# 1) 登录(首次会弹浏览器授权)
scripts\cloudflared\cloudflared.exe tunnel login

# 2) 创建一个命名 tunnel(只做一次)
scripts\cloudflared\cloudflared.exe tunnel create green-agent

# 3) 创建配置文件 ~/.cloudflared/config.yml
#   tunnel: green-agent
#   credentials-file: <path-from-step-2>
#   ingress:
#     - hostname: green-agent.example.com   # 要绑定的域名(可选)
#       service: http://localhost:8000
#     - service: http_status:404

# 4) 启动(URL 不再变)
scripts\cloudflared\cloudflared.exe tunnel run green-agent
```

- 没域名?Cloudflare 也能给你一个 `*.cfargotunnel.com` 子域(在 config 里去掉 `hostname` 行)
- 有域名?在 Cloudflare DNS 加一条 CNAME 指向 `<tunnel-id>.cfargotunnel.com`

> 详细官方文档:https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/

---

## 6. 常见问题 FAQ

### Q1:关了 cmd 窗口就停了吗?

**是。** `start_public.bat` 会启动两个子进程:Python 服务 + cloudflared。它们都是这个窗口的"孙子进程",关窗口时会一并结束。
想后台跑?见第 5.2 节的命名 tunnel 模式,或用 NSSM / Windows 任务计划程序。

### Q2:重启电脑后 URL 变了怎么办?

**重新跑 `start_public.bat`,把新 URL 发给用户。**

如果你经常重启但 URL 不希望变,走 5.2 的命名 tunnel。

### Q3:端口 8000 被占怎么办?

**症状**:`start_public.bat` 第 1 步杀不掉端口,启动后报 `Address already in use`。

```bash
# 1) 看是谁占了 8000
netstat -ano | findstr :8000
# 输出最后一段就是 PID,比如 12345

# 2) 杀它
taskkill /F /PID 12345

# 3) 或者跑 stop_public.bat(它会自动做)
scripts\stop_public.bat

# 4) 再启动
scripts\start_public.bat
```

如果 8000 经常被占,可以改端口:编辑 `scripts\start_public.bat`,把 `http://localhost:8000` 全局替换成 `http://localhost:8123` 之类,同时改 `.env` 里的 `PORT=8123`。

### Q4:防火墙拦截怎么办?

**症状**:`start_public.bat` 跑起来,但从手机 / 外网访问不到。

- **首次启动 cloudflared.exe 时**,Windows Defender 防火墙会弹窗问"是否允许"。
  - 勾 **"专用网络"** + **"公用网络"** 两个都勾上,点"允许访问"。
- 如果不小心点了"取消":
  ```bash
  # 控制面板 → 系统和安全 → Windows Defender 防火墙
  # → 允许应用通过防火墙 → 找到 cloudflared,两个网络都勾
  # 或者直接重装 cloudflared.exe,会再问一次
  ```
- 如果是公司/校园网,可能被出口防火墙拦了 `*.trycloudflare.com`:
  ```bash
  # 测试
  curl https://trycloudflare.com
  # 期望:HTML 页面;如果超时/拒绝,需要找网管开白名单或换网络
  ```

### Q5:启动到第 3 步卡住,显示"等待服务就绪(最多 60 秒)"然后超时

**症状**:`[3/4]` 之后 60 秒内 `/api/ready` 没返回 200,然后 `[警告]`。

```bash
# 1) 看 Python 启动日志
type D:\绿色低碳智能体\logs\agent.log

# 常见原因:
#   - .env 里某个 API key 没填 / 还是占位符 → 看到 "API key validation failed"
#   - 依赖没装全 → 看到 "ModuleNotFoundError"
#   - 端口 8000 被占(见 Q3)

# 2) 修复后重跑
scripts\stop_public.bat
scripts\start_public.bat
```

### Q6:`cloudflared.exe` 找不到

**症状**:`[4/4]` 报错 "系统找不到指定的路径 scripts\cloudflared\cloudflared.exe"。

```bash
# 重新下载(约 54 MB)
# 浏览器:https://github.com/cloudflare/cloudflared/releases/latest
# 下 cloudflared-windows-amd64.exe,重命名为 cloudflared.exe,放到 scripts\cloudflared\
```

### Q7:用一段时间后服务变慢

大概率是 **长期记忆 / 短期记忆 DB 太大** 或 **日志盘满**:

```bash
# 看磁盘
dir D:\绿色低碳智能体\data\ /s   # data/*.db 体积
dir D:\绿色低碳智能体\logs\       # 启动日志

# 清旧日志(只删 .log,别动 .db)
del D:\绿色低碳智能体\logs\*.log
```

或者重启一次(临时 URL 会变,见 Q2)。

### Q8:怎么改公网端口?

见 Q3 末尾。改完 `.env` 里的 `PORT` 和 `start_public.bat` 里的 `localhost:8000` 要同步。

---

## 7. 什么时候升级到云端

临时 URL 的"无痛"是有上限的。下面三条**任何一条**触发,就该升级:

| 信号 | 阈值 | 推荐升级路径 |
|---|---|---|
| 日活用户 | > 50 | 见 7.1 / 7.2 |
| 月流量 | > 10 GB | 见 7.1 / 7.2 |
| 想关电脑也能跑 | — | **必须升级**(本方案完全依赖本机在线) |

### 7.1 升级路径 A:Cloudflare 永久免费 tunnel(适合想"白嫖"稳定 URL)

- 优点:仍然 0 元 / 永久免费
- 适用:个人项目 / 演示站 / 小流量(< 100 GB/月)
- 步骤:见 5.2 节"想稳定 URL 怎么做"
- 加分项:绑自己的域名(`green.yourdomain.com`),走 Cloudflare CDN 加速

### 7.2 升级路径 B:Oracle Cloud 永久免费 VPS(适合想"自托管")

- 优点:0 元 / 永久免费 / ARM 4 核 24 GB 内存 / 真服务器
- 适用:中等流量(< 1000 日活) / 想跑别的服务 / 学习 Linux
- 步骤:
  1. 注册 Oracle Cloud(需信用卡验证但不扣费)
  2. 创建 ARM Ampere A1 实例(选 Ubuntu 22.04 / 24.04)
  3. SSH 进去装 Docker,跑项目 `docker-compose up`
  4. 用 nginx 反代 + Let's Encrypt 证书
- 详细教程见 `docs/RUNBOOK.md`(P5-J 待补)

### 7.3 升级路径 C:付费云(适合正式商用)

- 阿里云轻量 / 腾讯云轻量:50~100 元/月,够日活几千
- AWS Lightsail:$3.5/月起,海外用户友好
- Hugging Face Spaces(2 vCPU + 16 GB):$0~9/月,适合 ML Demo
- 步骤:见 `docs/DEPLOYMENT_RUNBOOK.md`

---

## 8. 一页 Cheatsheet

```bash
# 启动
scripts\start_public.bat                  # 一键启动 → 出 URL

# 停止
scripts\stop_public.bat                   # 一键停 → 杀端口 + 杀 cloudflared + 杀 python

# 看日志(排错)
type D:\绿色低碳智能体\logs\agent.log     # AI 服务输出
# cloudflared 输出在 start_public.bat 的窗口里

# 看健康
curl http://localhost:8000/api/health     # 本地
curl https://xxxx.trycloudflare.com/api/health   # 公网(把 xxxx 换你的 URL)

# 升级到稳定 URL(走命名 tunnel)
scripts\cloudflared\cloudflared.exe tunnel login
scripts\cloudflared\cloudflared.exe tunnel create green-agent
# 编辑 ~/.cloudflared/config.yml + DNS CNAME
scripts\cloudflared\cloudflared.exe tunnel run green-agent
```

---

## 9. 相关文档

- `scripts/start_public.bat` / `scripts/stop_public.bat` — 本指南讲的两个脚本
- `docs/RUNBOOK.md` — 服务器/容器化部署,见 P5-J 待补
- `docs/DEPLOYMENT_RUNBOOK.md` — 现有部署运行手册
- `docs/SECURITY.md` — API key / PII / 限流 / 审计
- `docs/API.md` — 35+ 端点清单
