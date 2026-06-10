"""
PII 脱敏工具(P5-I.A)

目标:在落库前对自由文本字段中的个人敏感信息做规则化脱敏,
降低 feedback.comment / behavior event_data 等"用户输入"字段
在数据库明文落库后的泄露风险(符合个保法/GDPR 最小化原则)。

支持类型:
- 手机号(中国大陆 11 位):138****1234
- 邮箱:zhang***@example.com
- 身份证号 18 位:110101********1234
- 银行卡号(13-19 位连续数字,luhn 可选):保留前 4 后 4
- 详细地址(关键词"路/街/号/室"后):截断为前 12 字符 + ***

设计原则:
- 纯正则匹配,无外部依赖,落库前一次扫描
- "识别不到就原样保留"(宁可漏不可错)
- 静默不抛异常(主流程不能因脱敏失败挂掉)
"""
from __future__ import annotations

import re
from typing import Any, Optional


_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(
    r"([A-Za-z0-9._%+\-]+)@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})"
)
_ID_CARD_RE = re.compile(r"(?<!\d)[1-9]\d{16}[\dXx](?!\d)")
_BANK_CARD_RE = re.compile(r"(?<!\d)\d{13,19}(?!\d)")

# 详细地址:含"省/市/区/县/路/街/道/号/室/栋/单元/楼"等中文地址关键词
_ADDRESS_RE = re.compile(
    r"([一-龥A-Za-z0-9]{2,8}"
    r"(?:省|市|自治区|特别行政区|区|县|州|盟|旗|路|街|道|巷|弄|号|室|栋|单元|楼|层|户|院))"
    r"[一-龥A-Za-z0-9号室栋单元楼层户号\-]{2,40}"
)


def mask_phone(text: str) -> str:
    """手机号脱敏:13800001234 → 138****1234

    保留前 3 + 后 4,中间 4 位用 **** 替代。
    11 位中国大陆手机号(1[3-9]xxxxxxxxx)。
    """
    if not text:
        return text
    return _PHONE_RE.sub(lambda m: m.group(0)[:3] + "****" + m.group(0)[7:], text)


def mask_email(text: str) -> str:
    """邮箱脱敏:zhangsan@example.com → zhan***@example.com

    用户名前 4 字符保留,余者用 *** 替代;域名整体保留。
    """
    if not text:
        return text

    def _sub(m: re.Match) -> str:
        local = m.group(1)
        domain = m.group(2)
        if len(local) <= 4:
            masked_local = local[:1] + "***"
        else:
            masked_local = local[:4] + "***"
        return masked_local + "@" + domain

    return _EMAIL_RE.sub(_sub, text)


def mask_id_card(text: str) -> str:
    """身份证号脱敏:110101199001011234 → 110101********1234

    18 位身份证号,保留前 6 + 后 4,中间 8 位用 ******** 替代。
    """
    if not text:
        return text
    return _ID_CARD_RE.sub(
        lambda m: m.group(0)[:6] + "********" + m.group(0)[14:], text
    )


def mask_bank_card(text: str) -> str:
    """银行卡号脱敏:6222021234567890123 → 6222**********0123

    13-19 位连续数字,保留前 4 + 后 4。
    注意:可能会误识别长数字串(如身份证已单独处理、订单号长串);
    此处只在明显"无前后数字相邻"时替换。
    """
    if not text:
        return text
    return _BANK_CARD_RE.sub(
        lambda m: m.group(0)[:4] + "*" * (len(m.group(0)) - 8) + m.group(0)[-4:],
        text,
    )


def mask_address(text: str) -> str:
    """详细地址脱敏:截断为前 12 字符 + '***'

    识别"省/市/路/号/室"等中文地址关键词;为避免把普通句子切坏,
    限定 2-50 字符总长度。
    """
    if not text:
        return text
    return _ADDRESS_RE.sub(
        lambda m: m.group(0)[:12] + "***", text
    )


def mask_pii(text: str) -> str:
    """综合脱敏入口:依次应用 phone / email / id_card / bank_card / address

    顺序重要:id_card 优先于 bank_card(避免身份证被当成银行卡多识别一次)
    """
    if not text:
        return text
    text = mask_id_card(text)
    text = mask_phone(text)
    text = mask_bank_card(text)
    text = mask_email(text)
    text = mask_address(text)
    return text


def mask_pii_in_dict(data: Optional[dict]) -> Optional[dict]:
    """递归地对 dict 的所有 str 叶子节点做 PII 脱敏

    不动 list / int / float / bool / None;str 字段统一过 mask_pii。
    """
    if data is None:
        return data
    if not isinstance(data, dict):
        return data

    masked: dict = {}
    for k, v in data.items():
        if isinstance(v, str):
            masked[k] = mask_pii(v)
        elif isinstance(v, dict):
            masked[k] = mask_pii_in_dict(v)
        elif isinstance(v, list):
            masked[k] = [
                mask_pii(item) if isinstance(item, str)
                else (mask_pii_in_dict(item) if isinstance(item, dict) else item)
                for item in v
            ]
        else:
            masked[k] = v
    return masked


def mask_pii_in_value(value: Any) -> Any:
    """通用入口:str → mask_pii,dict → mask_pii_in_dict,其他原样返回"""
    if isinstance(value, str):
        return mask_pii(value)
    if isinstance(value, dict):
        return mask_pii_in_dict(value)
    return value
