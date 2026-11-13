"""规则降级与槽位抽取：无 Key 时保证全链路可跑、可测、可复现。"""
from __future__ import annotations

import re

CATEGORY_ALIASES = {
    "耳机": ["耳机", "耳麦", "降噪", "入耳", "头戴", "耳塞"],
    "运动鞋": ["运动鞋", "跑鞋", "球鞋", "鞋", "跑步"],
    "双肩包": ["双肩包", "背包", "电脑包", "通勤包", "书包", "旅行包", "登机"],
    "保温杯": ["保温杯", "水杯", "杯子", "随行杯"],
    "机械键盘": ["键盘", "机械键盘", "青轴", "红轴", "码字"],
    "显示器": ["显示器", "屏幕", "显示屏", "2k", "4k"],
    "护肤品": ["护肤品", "面霜", "精华", "洁面", "防晒", "护肤"],
    "咖啡机": ["咖啡机", "咖啡", "胶囊机", "半自动"],
}

POLICY_KEYS = ["退", "换货", "退款", "运费", "包邮", "发票", "保修", "多久", "几天", "政策", "规则", "时限", "无理由", "举证", "证据", "过敏", "判定", "不一致", "预售", "发货时间", "怎么办"]
UNSAFE_KEYS = ["忽略规则", "忽略以上", "无视", "管理员权限", "直接退款", "绕过", "别人订单", "他人的订单", "sql", "drop table", "system prompt"]
AFTER_SALE_KEYS = ["退货", "退款", "换货", "售后", "申请退", "不想要了", "坏了", "破损", "质量", "漏发", "错发", "过敏"]
# 明确表达"要发起申请"的动作词；只出现"退货/退款"字样不算
AFTER_SALE_ACTION_KEYS = ["我要退", "申请退", "帮我退", "我想退", "要退款", "申请售后", "要换货", "退了吧", "办退货"]
ACTION_RE = re.compile(r"(要|想|申请|帮我|麻烦|需要)(退|换)")
# 故障描述也可视为售后诉求（不需要"我要"前缀）
FAULT_KEYS = ["坏了", "坏的", "失灵", "不响", "发错", "错发", "漏发", "少发", "瑕疵", "破损", "漏液", "开胶", "坏点", "少一件", "不能开机", "用不了"]
QUESTION_KEYS = ["吗", "么", "多久", "几天", "能不能", "可不可以", "是否", "怎么", "多少", "什么", "?", "什么时候"]
ORDER_KEYS = ["订单", "物流", "快递", "运单", "到哪", "还没到", "没收到", "什么时候到"]
ADVICE_KEYS = ["推荐", "买", "选", "适合", "预算", "想要", "有没有", "找", "对比", "哪个好"]
GREETING_KEYS = ["你好", "在吗", "hi", "hello", "谢谢"]

ORDER_RE = re.compile(r"(SO\d{10})", re.I)
PRICE_RE = [
    re.compile(r"(\d{2,5})\s*(?:元|块)?\s*(?:以内|以下|之内|内|封顶)"),
    re.compile(r"预算\s*(?:大概|大约)?\s*(\d{2,5})"),
    re.compile(r"不超过\s*(\d{2,5})"),
    re.compile(r"(\d{2,5})\s*(?:元|块)\s*(?:左右|上下)"),
]


def detect_category(text: str) -> str | None:
    t = text.lower()
    best, best_hits = None, 0
    for cat, aliases in CATEGORY_ALIASES.items():
        hits = sum(1 for a in aliases if a.lower() in t)
        if hits > best_hits:
            best, best_hits = cat, hits
    return best if best_hits else None


def detect_price_max(text: str) -> float | None:
    for pattern in PRICE_RE:
        m = pattern.search(text)
        if m:
            return float(m.group(1))
    return None


def detect_order_no(text: str) -> str | None:
    m = ORDER_RE.search(text)
    return m.group(1).upper() if m else None


def classify_intent(text: str) -> tuple[str, float]:
    t = (text or "").lower()
    if not t.strip():
        return "unknown", 0.3
    if any(k in t for k in UNSAFE_KEYS):
        return "unsafe", 0.95

    # 售后动作 vs 政策咨询要分开：有明确动作词/故障描述/订单号才判为申请
    explicit_action = any(k in t for k in AFTER_SALE_ACTION_KEYS) or bool(ACTION_RE.search(t))
    fault = any(k in t for k in FAULT_KEYS)
    has_order = bool(ORDER_RE.search(t))
    policy_question = any(q in t for q in QUESTION_KEYS) and any(k in t for k in POLICY_KEYS)

    if has_order and (explicit_action or fault or any(k in t for k in AFTER_SALE_KEYS)):
        return "after_sales", 0.9
    # "可以申请无理由退货吗"这类疑问句归政策，不当作已决定要退
    if (explicit_action or fault) and not (policy_question and "我要" not in t):
        return "after_sales", 0.88
    if has_order:
        return "order_query", 0.9
    if any(k in t for k in ORDER_KEYS):
        return "order_query", 0.85
    # 提问式政策咨询（"能不能退""多久""是否"）优先于品类导购
    if policy_question or (any(k in t for k in POLICY_KEYS) and not detect_category(t)):
        return "policy_qa", 0.82
    if detect_category(t) and any(k in t for k in ADVICE_KEYS):
        return "product_advice", 0.85
    if detect_category(t):
        return "product_advice", 0.8
    if any(k in t for k in POLICY_KEYS):
        return "policy_qa", 0.78
    if any(k in t for k in ADVICE_KEYS):
        return "product_advice", 0.7
    if any(k in t for k in GREETING_KEYS):
        return "smalltalk", 0.7
    return "unknown", 0.4


SOFT_PREFERENCE_MAP = {
    "不夹头": "戴眼镜不夹头",
    "夹头": "戴眼镜不夹头",
    "降噪": "通勤降噪",
    "通勤": "通勤",
    "轻": "轻便",
    "轻便": "适合跑步的轻便鞋子",
    "透气": "夏天透气不闷脚",
    "不闷": "夏天透气不闷脚",
    "送长辈": "送长辈",
    "送妈妈": "送长辈",
    "小户型": "小户型桌面",
    "占地": "小户型桌面",
    "办公室": "办公室不吵同事",
    "不漏": "放包里不漏",
    "久站": "通勤久站不累",
    "不累": "通勤久站不累",
    "宽脚": "脚宽不挤脚",
    "不挤脚": "脚宽不挤脚",
}


def extract_slots(text: str) -> dict:
    slots: dict = {}
    cat = detect_category(text)
    if cat:
        slots["category"] = cat
    price = detect_price_max(text)
    if price:
        slots["price_max"] = price
    order_no = detect_order_no(text)
    if order_no:
        slots["order_no"] = order_no

    prefs = []
    for k, v in SOFT_PREFERENCE_MAP.items():
        if k in text and v not in prefs:
            prefs.append(v)
    if prefs:
        slots["preferences"] = prefs

    scene = None
    if any(k in text for k in ["质量", "坏", "破损", "故障", "开胶", "过敏", "瑕疵"]):
        scene = "quality"
    elif any(k in text for k in ["错发", "漏发", "发错", "少发"]):
        scene = "wrong_item"
    elif any(k in text for k in ["不想要", "退货", "退款", "无理由"]):
        scene = "no_reason"
    if scene:
        slots["scene"] = scene
        slots["reason"] = text.strip()[:120]
    return slots


def missing_slots(intent: str, slots: dict) -> list[str]:
    if intent == "product_advice":
        missing = []
        if not slots.get("category"):
            missing.append("category")
        return missing
    if intent == "order_query" and not slots.get("order_no"):
        return ["order_no"]
    if intent == "after_sales":
        missing = []
        if not slots.get("order_no"):
            missing.append("order_no")
        if not slots.get("reason"):
            missing.append("reason")
        return missing
    return []


CLARIFY_TEMPLATES = {
    "category": "想买哪一类商品？比如耳机、运动鞋、保温杯、键盘、显示器。告诉我品类和预算，我就能给你挑。",
    "order_no": "请提供订单号（SO 开头加 10 位数字），我只查询你本人名下的订单。",
    "reason": "方便说下具体原因吗？是质量问题、错发漏发，还是不想要了？",
}


def rewrite_query(text: str, slots: dict) -> str:
    parts = [text]
    if slots.get("category"):
        parts.append(slots["category"])
    for p in slots.get("preferences", []):
        parts.append(p)
    return " ".join(parts)


def template_policy_answer(question: str, chunks: list[dict]) -> str:
    if not chunks:
        return ""
    top = chunks[:2]
    lines = [f"根据《{top[0]['title']}》（{top[0]['version']}，{top[0]['effective_at']} 生效）："]
    for c in top:
        lines.append(f"- {c['section']}：{c['content']}")
    lines.append("以上条款以平台最新版本为准；如与你的订单实际情况不符，可转人工复核。")
    return "\n".join(lines)


def template_product_answer(candidates: list[dict], slots: dict) -> str:
    if not candidates:
        return "没有找到同时满足预算与库存条件的商品，可以放宽预算或换个品类试试。"
    head = "按你的需求（"
    bits = []
    if slots.get("category"):
        bits.append(f"品类{slots['category']}")
    if slots.get("price_max"):
        bits.append(f"预算 ≤{slots['price_max']:.0f} 元")
    if slots.get("preferences"):
        bits.append("、".join(slots["preferences"]))
    head += "，".join(bits) + "）先做硬过滤，再按语义相关性和库存、销量精排，给你三个候选："
    rows = []
    for i, c in enumerate(candidates, start=1):
        rows.append(
            f"{i}. **{c['title']}**（{c['price']:.0f} 元，库存 {c['available_qty']} 件）"
            f"——{'; '.join(c['explain'])}"
        )
    tail = "价格与库存为实时查询结果。需要我把某一款加入对比，或按其他偏好再筛一次吗？"
    return head + "\n" + "\n".join(rows) + "\n" + tail
