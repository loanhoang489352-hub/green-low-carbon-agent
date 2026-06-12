# 源可达性测试报告 — 2026-06-12 09:06:40

**测试源数**: 18
**通过**: 12
**失败**: 6

## 结果汇总

| 名称 | 状态 | 大小 | 延迟 | 关键词 | 错误 |
|------|------|------|------|--------|------|
| 新华网-能源频道 | ✅ 200 | 40.3 KB | 364.17ms | 4 | - |
| 经济参考报-绿色频道 | ✅ 200 | 47.2 KB | 563.98ms | 1 | - |
| 财新网-环境频道 | ✅ 200 | 31.6 KB | 378.51ms | 2 | - |
| 中国新闻网-能源 | ❌ 200 | 0.7 KB | 372.53ms | 0 | - |
| 南方周末-绿色 | ✅ 200 | 59.6 KB | 516.39ms | 2 | - |
| 21 经济网-碳中和 | ❌ 200 | 65.6 KB | 609.23ms | 0 | - |
| 国家发改委-双碳 | ✅ 200 | 85.6 KB | 567.73ms | 2 | - |
| 国家统计局-绿色发展 | ✅ 200 | 139.3 KB | 519.79ms | 4 | - |
| 中国环境与发展国际合作委员会 | ❌ 0 | 0.0 KB | 2426.72ms | 0 | ConnectError: [WinError 10061] 由于目标计算机积极拒绝，无法连接。 |
| Environmental Defense Fund | ✅ 200 | 252.9 KB | 785.43ms | 4 | - |
| 生态环境部-政策文件 | ❌ 200 | 0.0 KB | 804.85ms | 0 | - |
| 国家发改委-双碳 | ✅ 200 | 43.6 KB | 1026.92ms | 2 | - |
| 国家能源局 | ✅ 200 | 106.0 KB | 716.74ms | 3 | - |
| 工信部-节能与综合利用 | ✅ 200 | 37.2 KB | 632.77ms | 3 | - |
| 住建部-绿色建筑 | ❌ 404 | 0.1 KB | 740.44ms | 0 | - |
| 交通运输部-绿色交通 | ❌ 404 | 0.3 KB | 941.27ms | 0 | - |
| 农业农村部-生态农业 | ✅ 200 | 108.6 KB | 1267.35ms | 3 | - |
| 国家林草局-碳汇 | ✅ 200 | 83.0 KB | 361.62ms | 3 | - |

## 建议启用(可达 + 内容匹配)

```yaml
# 加到 config/sources.yaml 的 policy_sources:
policy_sources:
  - name: "新华网-能源频道"
    url: "http://www.news.cn/energy/"
    type: "html"
    category: "媒体-能源"
    enabled: true
    check_interval_hours: 24
    note: "新华社能源频道,权威媒体 + 大陆政府背景"
  - name: "经济参考报-绿色频道"
    url: "http://www.jjckb.cn/"
    type: "html"
    category: "媒体-绿色"
    enabled: true
    check_interval_hours: 24
    note: "新华社主办经济参考报,绿色经济报道密集"
  - name: "财新网-环境频道"
    url: "https://www.caixin.com/environment/"
    type: "html"
    category: "媒体-环境"
    enabled: true
    check_interval_hours: 24
    note: "财新环境频道,深度报道,需付费(但首页可访问)"
  - name: "南方周末-绿色"
    url: "https://www.infzm.com/"
    type: "html"
    category: "媒体-调查"
    enabled: true
    check_interval_hours: 24
    note: "南方周末,深度环境报道"
  - name: "国家发改委-双碳"
    url: "https://www.ndrc.gov.cn/"
    type: "html"
    category: "政府-发改委"
    enabled: true
    check_interval_hours: 24
    note: "国家发改委(.gov.cn,港 IP 测试可能 SSL 失败)"
  - name: "国家统计局-绿色发展"
    url: "https://www.stats.gov.cn/"
    type: "html"
    category: "政府-统计"
    enabled: true
    check_interval_hours: 24
    note: "国家统计局(.gov.cn,数据权威)"
  - name: "Environmental Defense Fund"
    url: "https://www.edf.org/"
    type: "html"
    category: "国际-NGO"
    enabled: true
    check_interval_hours: 24
    note: "EDF,国际环保 NGO(英文),港 IP 应可通"
  - name: "国家发改委-双碳"
    url: "https://www.ndrc.gov.cn/xxgk/zcfb/tz/"
    type: "html"
    category: "政府-发改委"
    enabled: true
    check_interval_hours: 24
    note: "P6.R.2: 政策原文(已 P6.J 启用首页,此处是子页)"
  - name: "国家能源局"
    url: "https://www.nea.gov.cn/"
    type: "html"
    category: "政府-能源局"
    enabled: true
    check_interval_hours: 24
    note: "P6.R.2: 需大陆 IP"
  - name: "工信部-节能与综合利用"
    url: "https://www.miit.gov.cn/jgsj/jns/"
    type: "html"
    category: "政府-工信部"
    enabled: true
    check_interval_hours: 24
    note: "P6.R.2: 需大陆 IP"
  - name: "农业农村部-生态农业"
    url: "https://www.moa.gov.cn/"
    type: "html"
    category: "政府-农业农村部"
    enabled: true
    check_interval_hours: 24
    note: "P6.R.2: 需大陆 IP"
  - name: "国家林草局-碳汇"
    url: "https://www.forestry.gov.cn/"
    type: "html"
    category: "政府-林草局"
    enabled: true
    check_interval_hours: 24
    note: "P6.R.2: 需大陆 IP,森林碳汇权威"
```

## 不可用源(应保留 disabled)

- **中国新闻网-能源** (https://www.chinanews.com/energy/): None
- **21 经济网-碳中和** (https://www.21jingji.com/): None
- **中国环境与发展国际合作委员会** (https://www.cciced.net/): ConnectError: [WinError 10061] 由于目标计算机积极拒绝，无法连接。
- **生态环境部-政策文件** (https://www.mee.gov.cn/xxgk2018/xxgk/xxgk03/): None
- **住建部-绿色建筑** (https://www.mohurd.gov.cn/gongkai/zhengce/zhengcefilelib/): None
- **交通运输部-绿色交通** (https://www.mot.gov.cn/zhengcejiedu/green/): None