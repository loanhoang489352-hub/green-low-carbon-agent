"""
P9: OCR 评估样本生成器

生成 20 个 mock PDF / PNG 样本,覆盖 4 类文档:
- pdf_digital (5): 数字文本 PDF,ReportLab 生成,可被 PyMuPDF 直接抽出文本
- pdf_scanned (5): 扫描件风格 PDF,图片 + PyMuPDF overlay 文本层
- image_text (7): PIL 绘制的 PNG,中文 + 英文混合
- mixed_layout (3): 多栏 / 表格混排 PDF,验证版式解析

输出:
    tests/eval/ocr_samples/*.pdf
    tests/eval/ocr_samples/*.png

使用:
    cd D:/绿色低碳智能体
    python tests/eval/generate_samples.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib import colors

SAMPLES_DIR = Path(__file__).parent / "ocr_samples"
SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

# 注册 reportlab 内置中文字体(STSong-Light)
try:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    CN_FONT = "STSong-Light"
except Exception:
    CN_FONT = "Helvetica"

FONT_PATH = Path("C:/Windows/Fonts/simhei.ttf")
if not FONT_PATH.exists():
    FONT_PATH = Path("C:/Windows/Fonts/msyh.ttc")


# ---------------------------------------------------------------------------
# 1. 数字文本 PDF(5 个)— ReportLab 生成,直接抽出
# ---------------------------------------------------------------------------

DIGITAL_PDFS = [
    {
        "id": "policy_001",
        "title": "全国碳排放权交易市场覆盖钢铁、水泥、铝冶炼行业工作方案",
        "content": [
            "为稳步扩大全国碳排放权交易市场覆盖范围,根据《碳排放权交易管理暂行条例》,"
            "制定本工作方案。",
            "一、总体要求",
            "以习近平生态文明思想为指导,坚持稳步扩大、平稳过渡,分阶段将钢铁、"
            "水泥、铝冶炼三个行业纳入全国碳排放权交易市场。",
            "二、实施步骤",
            "2024 年为首个履约周期,2024 年 7 月前完成配额核定与分配。",
            "三、监督管理",
            "生态环境部会同有关部门对重点排放单位进行监督管理,加强对碳排放数据"
            "质量的监管。",
        ],
        "keywords": ["碳排放", "钢铁", "水泥", "铝冶炼", "2024"],
    },
    {
        "id": "subsidy_001",
        "title": "北京市 2024 年新能源汽车置换补贴实施细则",
        "content": [
            "为促进新能源汽车消费,推进绿色低碳出行,北京市发布 2024 年置换补贴政策。",
            "一、补贴对象",
            "在北京地区购买纯电动小客车的个人消费者,车辆须纳入《免征车辆购置税的"
            "新能源汽车车型目录》。",
            "二、补贴标准",
            "每辆新车补贴 8000 元,置换旧车额外补贴 2000 元。",
            "三、申报方式",
            "通过北京市新能源汽车促消费平台在线申报,审核通过后 30 个工作日内"
            "拨付补贴资金。",
        ],
        "keywords": ["新能源汽车", "补贴", "8000", "置换"],
    },
    {
        "id": "carbon_001",
        "title": "2024 年中国区域电网二氧化碳排放因子",
        "content": [
            "生态环境部、国家统计局发布 2024 年中国区域电网二氧化碳排放因子。",
            "华北区域电网排放因子为 0.5823 kg CO2/kWh。",
            "东北区域电网排放因子为 0.5949 kg CO2/kWh。",
            "华东区域电网排放因子为 0.4544 kg CO2/kWh。",
            "华中区域电网排放因子为 0.4418 kg CO2/kWh。",
            "西北区域电网排放因子为 0.5262 kg CO2/kWh。",
            "南方区域电网排放因子为 0.3853 kg CO2/kWh。",
        ],
        "keywords": ["电网", "排放因子", "0.5823", "2024"],
    },
    {
        "id": "sort_001",
        "title": "上海市生活垃圾分类投放指南(2024 修订版)",
        "content": [
            "为推进生活垃圾分类,上海市修订发布本指南。",
            "一、可回收物",
            "适宜回收和资源利用的废弃物,包括废纸、废塑料、废金属、废玻璃、废织物等。",
            "二、有害垃圾",
            "对人体健康或自然环境造成直接或潜在危害的废弃物,包括废电池、废荧光灯管、"
            "废药品等。",
            "三、湿垃圾(厨余垃圾)",
            "食材废料、剩菜剩饭、过期食品等易腐烂的生物质废弃物。",
            "四、干垃圾(其他垃圾)",
            "除可回收物、有害垃圾、湿垃圾之外的其他生活废弃物。",
        ],
        "keywords": ["可回收物", "有害垃圾", "湿垃圾", "干垃圾"],
    },
    {
        "id": "cert_001",
        "title": "中国产品碳足迹标识认证试点办法",
        "content": [
            "为建立产品碳足迹管理体系,市场监管总局开展产品碳足迹标识认证试点。",
            "一、试点范围",
            "首批试点产品包括:锂电池、纺织品、塑料制品、电子产品、纸制品、"
            "农产品等 6 大类。",
            "二、认证流程",
            "企业向认证机构提交产品碳足迹核算报告,经第三方核查后获得认证证书。",
            "三、标识使用",
            "通过认证的产品可在包装或宣传材料上使用碳足迹标识,有效期 3 年。",
        ],
        "keywords": ["碳足迹", "认证", "锂电池", "纺织品"],
    },
]


def make_pdf_digital(case: dict) -> Path:
    """ReportLab 生成多段中文 PDF,文本层可复制"""
    out = SAMPLES_DIR / f"{case['id']}.pdf"
    doc = SimpleDocTemplate(
        str(out), pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title", parent=styles["Heading1"],
        fontName=CN_FONT, fontSize=18, leading=24,
        spaceAfter=12, alignment=1,
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["BodyText"],
        fontName=CN_FONT, fontSize=11, leading=18, spaceAfter=8,
    )

    flow = [Paragraph(case["title"], title_style), Spacer(1, 6)]
    for para in case["content"]:
        flow.append(Paragraph(para, body_style))
        flow.append(Spacer(1, 4))

    doc.build(flow)
    return out


# ---------------------------------------------------------------------------
# 2. 扫描件风格 PDF(5 个)— PyMuPDF 嵌入图片 + overlay 文本层
# ---------------------------------------------------------------------------

SCANNED_PDFS = [
    {
        "id": "scanned_001",
        "title": "深圳市生态环境局关于 2024 年第三季度执法检查的通知",
        "content": (
            "各相关企业:\n"
            "根据《深圳市 2024 年生态环境执法工作计划》安排,我局将于 2024 年 10 月至 12 月\n"
            "开展第三季度专项执法检查,重点检查企业碳排放报告数据质量与污染防治设施\n"
            "运行情况。请各单位做好迎检准备。\n"
            "特此通知。\n"
            "深圳市生态环境局\n"
            "2024 年 9 月 15 日"
        ),
        "keywords": ["执法检查", "碳排放", "2024", "深圳"],
    },
    {
        "id": "scanned_002",
        "title": "广东省 2024 年碳排放配额分配方案",
        "content": (
            "为做好广东省 2024 年度碳排放配额分配工作,根据《广东省碳排放管理试行办法》,\n"
            "制定本方案。\n"
            "一、分配对象\n"
            "纳入广东省碳排放管理和交易范围的重点排放单位。\n"
            "二、分配方法\n"
            "采用基准法与历史强度下降法相结合的混合分配方式。\n"
            "三、配额总量\n"
            "2024 年度广东省碳排放配额总量为 2.4 亿吨二氧化碳当量。"
        ),
        "keywords": ["广东", "配额", "2.4 亿吨", "基准法"],
    },
    {
        "id": "scanned_003",
        "title": "杭州市公共交通低碳出行倡议书",
        "content": (
            "广大市民朋友们:\n"
            "为深入践行绿色低碳发展理念,共建美丽杭州,我们倡议:\n"
            "一、优先选择公共交通、步行、骑行等绿色出行方式。\n"
            "二、购买新能源汽车,减少私家车使用频次。\n"
            "三、自觉践行垃圾分类,减少一次性用品使用。\n"
            "杭州市生态环境局\n"
            "2024 年 5 月 1 日"
        ),
        "keywords": ["公共交通", "低碳", "杭州", "倡议"],
    },
    {
        "id": "scanned_004",
        "title": "国务院关于印发《2024 年节能减排工作要点》的通知",
        "content": (
            "各省、自治区、直辖市人民政府,国务院各部委、各直属机构:\n"
            "现将《2024 年节能减排工作要点》印发给你们,请结合实际认真贯彻执行。\n"
            "一、能源结构调整\n"
            "二、工业能效提升\n"
            "三、建筑节能改造\n"
            "四、交通运输绿色化\n"
            "国务院办公厅\n"
            "2024 年 3 月 20 日"
        ),
        "keywords": ["节能减排", "2024", "国务院", "能源结构"],
    },
    {
        "id": "scanned_005",
        "title": "中国循环经济协会关于推动废旧纺织品资源化的指导意见",
        "content": (
            "为推进废旧纺织品资源化利用,提出以下意见:\n"
            "一、建立完善的废旧纺织品回收体系。\n"
            "二、加快再生纤维技术研发与产业化应用。\n"
            "三、培育龙头骨干企业,推动产业集聚发展。\n"
            "四、加强国际合作,参与全球纺织品循环利用标准制定。\n"
            "中国循环经济协会\n"
            "2024 年 8 月"
        ),
        "keywords": ["纺织品", "资源化", "循环经济", "再生纤维"],
    },
]


def make_pdf_scanned(case: dict) -> Path:
    """扫描件风格 PDF:先 ReportLab 生成单页文字再叠加"扫描"风格
    文本层是真实可读的中文,模拟"扫描得到的 PDF"
    """
    out = SAMPLES_DIR / f"{case['id']}.pdf"
    c = canvas.Canvas(str(out), pagesize=A4)
    width, height = A4

    # 浅灰背景(模拟扫描底色)
    c.setFillColorRGB(0.97, 0.97, 0.95)
    c.rect(0, 0, width, height, fill=1, stroke=0)

    c.setFillColorRGB(0.05, 0.05, 0.05)
    c.setFont(CN_FONT, 14)
    title = case["title"]
    c.drawString(2 * cm, height - 3 * cm, title)
    c.line(2 * cm, height - 3.2 * cm, width - 2 * cm, height - 3.2 * cm)

    c.setFont(CN_FONT, 11)
    y = height - 4.5 * cm
    for line in case["content"].split("\n"):
        if y < 3 * cm:
            c.showPage()
            y = height - 3 * cm
            c.setFillColorRGB(0.97, 0.97, 0.95)
            c.rect(0, 0, width, height, fill=1, stroke=0)
            c.setFillColorRGB(0.05, 0.05, 0.05)
            c.setFont(CN_FONT, 11)
        c.drawString(2 * cm, y, line.strip())
        y -= 0.7 * cm

    # 页脚 + 印章(模拟扫描件特征)
    c.setFont(CN_FONT, 8)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawString(2 * cm, 1.5 * cm, "扫描件 — 仅供评估测试使用")
    c.showPage()
    c.save()
    return out


# ---------------------------------------------------------------------------
# 3. 纯文本图片 PNG / JPG(7 张)— PIL 绘制
# ---------------------------------------------------------------------------

IMAGE_TEXTS = [
    {
        "id": "img_001",
        "title": "image_text_policy.png",
        "content": [
            "关于推进绿色低碳产业发展的实施意见",
            "",
            "一、总体目标",
            "到 2025 年,绿色低碳产业产值年均增长 8%以上。",
            "",
            "二、重点任务",
            "1. 培育绿色低碳龙头企业 100 家",
            "2. 建设零碳工厂示范项目 50 个",
            "3. 推广绿色建材应用比例达到 60%",
            "",
            "三、保障措施",
            "加强财政金融支持,完善标准体系。",
        ],
        "keywords": ["绿色低碳", "2025", "零碳工厂"],
    },
    {
        "id": "img_002",
        "title": "image_text_subsidy.png",
        "content": [
            "上海市 2024 年绿色家电以旧换新补贴公告",
            "",
            "补贴范围:空调、冰箱、洗衣机、电视、热水器",
            "补贴标准:一级能效产品补贴 10%,最高 1000 元",
            "申请方式:线上申请,通过后 15 日内到账",
            "有效期:2024 年 1 月 1 日至 12 月 31 日",
        ],
        "keywords": ["绿色家电", "补贴", "以旧换新", "1000"],
    },
    {
        "id": "img_003",
        "title": "image_text_carbon.png",
        "content": [
            "2024 年中国居民人均碳排放量统计",
            "",
            "全国居民人均碳排放:约 3.5 吨 CO2/人",
            "其中:",
            "- 食品消费:0.8 吨",
            "- 居住能耗:1.2 吨",
            "- 交通出行:1.0 吨",
            "- 消费支出:0.5 吨",
            "",
            "数据来源:生态环境部环境规划院",
        ],
        "keywords": ["碳排放", "3.5 吨", "2024", "居民"],
    },
    {
        "id": "img_004",
        "title": "image_text_sort.jpg",
        "content": [
            "北京生活垃圾分类标识",
            "",
            "[可回收物] 蓝色 — 废纸/塑料/金属/玻璃/织物",
            "[有害垃圾] 红色 — 电池/灯管/药品/油漆",
            "[厨余垃圾] 绿色 — 剩菜/果皮/茶叶渣",
            "[其他垃圾] 灰色 — 烟头/尘土/污染纸",
        ],
        "keywords": ["可回收物", "有害垃圾", "厨余垃圾"],
    },
    {
        "id": "img_005",
        "title": "image_text_cert.png",
        "content": [
            "中国环境标志产品认证证书",
            "",
            "证书编号:CEC-2024-EL-12345",
            "认证产品:水性内墙涂料",
            "认证企业:某建材有限公司",
            "发证日期:2024 年 6 月 1 日",
            "有效期至:2027 年 5 月 31 日",
            "认证机构:中环联合认证中心",
        ],
        "keywords": ["环境标志", "认证", "涂料", "2024"],
    },
    {
        "id": "img_006",
        "title": "image_text_battery.png",
        "content": [
            "电动汽车动力电池回收利用管理办法",
            "",
            "第一章 总则",
            "第一条 为规范动力电池回收,根据《固废法》制定本办法。",
            "第二条 动力电池生产者责任延伸。",
            "",
            "第二章 回收网络",
            "第三条 建立新能源汽车动力电池回收服务点。",
            "第四条 鼓励 4S 店与电池企业合作建设回收渠道。",
        ],
        "keywords": ["动力电池", "回收", "生产者责任"],
    },
    {
        "id": "img_007",
        "title": "image_text_province.png",
        "content": [
            "江苏省 2024 年低碳示范园区名单",
            "",
            "1. 苏州工业园区",
            "2. 南京江北新区",
            "3. 无锡高新区",
            "4. 常州武进国家高新区",
            "5. 南通经济技术开发区",
            "6. 徐州经济技术开发区",
            "7. 盐城环保科技城",
            "8. 扬州经济技术开发区",
        ],
        "keywords": ["江苏", "低碳", "示范园区", "2024"],
    },
]


def make_image_text(case: dict) -> Path:
    """PIL 绘制中文图片,模拟手机拍摄/截图 OCR 场景"""
    out = SAMPLES_DIR / case["title"]
    font_title = ImageFont.truetype(str(FONT_PATH), 22)
    font_body = ImageFont.truetype(str(FONT_PATH), 16)

    # 估算高度
    line_height = 32
    height = max(280, len(case["content"]) * line_height + 60)
    img = Image.new("RGB", (820, height), color=(252, 252, 245))
    draw = ImageDraw.Draw(img)

    # 边框(模拟扫描件)
    draw.rectangle([(4, 4), (816, height - 4)], outline=(180, 180, 175), width=1)

    y = 24
    for line in case["content"]:
        if line.strip() == "":
            y += line_height // 2
            continue
        is_title = y == 24
        font = font_title if is_title else font_body
        color = (10, 30, 80) if is_title else (20, 20, 20)
        draw.text((24, y), line, fill=color, font=font)
        y += line_height

    img.save(out, quality=92)
    return out


# ---------------------------------------------------------------------------
# 4. 多栏 / 表格混合版式 PDF(3 个)
# ---------------------------------------------------------------------------

MIXED_PDFS = [
    {
        "id": "mixed_001",
        "title": "2024 年主要城市空气质量与碳排放对比报告",
        "intro": "本报告对比北京、上海、广州、深圳、成都、杭州六大城市 2024 年空气质量与碳排放数据。",
        "left_col": [
            "北京 2024 年 PM2.5 年均浓度 32 微克/立方米",
            "上海 2024 年 PM2.5 年均浓度 28 微克/立方米",
            "广州 2024 年 PM2.5 年均浓度 24 微克/立方米",
            "深圳 2024 年 PM2.5 年均浓度 20 微克/立方米",
            "成都 2024 年 PM2.5 年均浓度 35 微克/立方米",
            "杭州 2024 年 PM2.5 年均浓度 30 微克/立方米",
        ],
        "right_col": [
            "北京 2024 年碳排放强度:0.42 kg/万元",
            "上海 2024 年碳排放强度:0.38 kg/万元",
            "广州 2024 年碳排放强度:0.36 kg/万元",
            "深圳 2024 年碳排放强度:0.31 kg/万元",
            "成都 2024 年碳排放强度:0.45 kg/万元",
            "杭州 2024 年碳排放强度:0.34 kg/万元",
        ],
        "keywords": ["PM2.5", "碳排放强度", "北京", "深圳"],
    },
    {
        "id": "mixed_002",
        "title": "中国可再生能源发展 2024 年度报告(节选)",
        "intro": "2024 年中国可再生能源装机容量继续保持快速增长。",
        "table": [
            ["类型", "装机容量(万千瓦)", "同比增长"],
            ["水电", "42000", "+2.1%"],
            ["风电", "45000", "+18.5%"],
            ["光伏", "61000", "+28.2%"],
            ["生物质", "4500", "+9.0%"],
            ["合计", "152500", "+15.3%"],
        ],
        "right_col": [
            "可再生能源发电量占总发电量比重达到 35.1%。",
            "风电、光伏新增装机连续多年位居全球第一。",
            "海上风电累计装机突破 4000 万千瓦。",
            "分布式光伏新增装机占比超过 60%。",
        ],
        "keywords": ["可再生能源", "光伏", "风电", "45000"],
    },
    {
        "id": "mixed_003",
        "title": "企业 ESG 报告披露指引(2024 修订)",
        "intro": "为提升企业 ESG 信息披露质量,本指引涵盖环境、社会、治理三大维度。",
        "left_col": [
            "环境(E):",
            "1. 温室气体排放总量与强度",
            "2. 能源消耗结构",
            "3. 水资源使用与回用",
            "4. 废弃物产生与处置",
            "5. 生物多样性影响",
        ],
        "right_col": [
            "社会(S):",
            "1. 员工健康与安全",
            "2. 多元化与包容性",
            "3. 供应链责任",
            "4. 社区参与",
            "5. 数据安全与隐私",
        ],
        "keywords": ["ESG", "温室气体", "供应链", "2024"],
    },
]


def make_mixed_layout(case: dict) -> Path:
    """两栏 + 表格混排,验证版式还原能力"""
    out = SAMPLES_DIR / f"{case['id']}.pdf"
    doc = SimpleDocTemplate(
        str(out), pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title", parent=styles["Heading1"],
        fontName=CN_FONT, fontSize=16, leading=22, alignment=1, spaceAfter=10,
    )
    intro_style = ParagraphStyle(
        "Intro", parent=styles["BodyText"],
        fontName=CN_FONT, fontSize=11, leading=18, spaceAfter=12,
    )
    col_style = ParagraphStyle(
        "Col", parent=styles["BodyText"],
        fontName=CN_FONT, fontSize=10, leading=16,
    )

    flow = [
        Paragraph(case["title"], title_style),
        Paragraph(case["intro"], intro_style),
    ]

    if "table" in case:
        table = Table(case["table"], colWidths=[5 * cm, 6 * cm, 4 * cm])
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), CN_FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        flow.append(table)
        flow.append(Spacer(1, 12))

    left_para = [Paragraph(p, col_style) for p in case.get("left_col", [])]
    right_para = [Paragraph(p, col_style) for p in case.get("right_col", [])]
    flow.append(Table(
        [[left_para, right_para]],
        colWidths=[8 * cm, 8 * cm],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEAFTER", (0, 0), (0, -1), 0.5, colors.grey),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]),
    ))

    doc.build(flow)
    return out


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    print(f"[gen] 输出目录: {SAMPLES_DIR}")

    for case in DIGITAL_PDFS:
        p = make_pdf_digital(case)
        print(f"  [digital] {p.name}")

    for case in SCANNED_PDFS:
        p = make_pdf_scanned(case)
        print(f"  [scanned] {p.name}")

    for case in IMAGE_TEXTS:
        p = make_image_text(case)
        print(f"  [image]   {p.name}")

    for case in MIXED_PDFS:
        p = make_mixed_layout(case)
        print(f"  [mixed]   {p.name}")

    print(f"\n[OK] 共生成 {len(DIGITAL_PDFS) + len(SCANNED_PDFS) + len(IMAGE_TEXTS) + len(MIXED_PDFS)} 个样本")


if __name__ == "__main__":
    main()