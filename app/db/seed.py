"""种子数据：2,000 SKU、1,000 订单、售后规则与政策知识库（全部合成/脱敏）。"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from sqlalchemy import select

from app.db.models import (
    AfterSaleRule, Inventory, KnowledgeChunk, Order, OrderItem, Product,
)
from app.db.session import init_db, session_scope

RNG = random.Random(20261113)
NOW = datetime(2026, 11, 13, 9, 0, 0)

CATEGORIES = {
    "耳机": {
        "sub": ["头戴式", "入耳式", "半入耳式", "骨传导"],
        "brands": ["声岛", "声阔", "倍思", "漫步者", "韶音"],
        "price": (129, 2299),
        "attrs": {
            "降噪": ["主动降噪", "通话降噪", "无降噪"],
            "佩戴": ["头戴包耳", "入耳", "半入耳", "挂耳"],
            "连接": ["蓝牙5.3", "蓝牙5.4", "双设备连接"],
            "续航": ["20小时", "30小时", "40小时"],
        },
        "soft": ["通勤降噪", "戴眼镜不夹头", "久戴不闷", "跑步不掉", "通话清晰"],
        "review": [
            "戴眼镜连续戴两小时太阳穴不夹，通勤地铁降噪够用",
            "耳罩偏紧，戴眼镜会有点压耳，适合短时间听歌",
            "半入耳很轻，跑步不掉，风噪控制一般",
            "通话清晰，地铁里对方能听清",
        ],
    },
    "运动鞋": {
        "sub": ["跑鞋", "板鞋", "健步鞋", "篮球鞋"],
        "brands": ["逐风", "轻迹", "速野", "踏浪"],
        "price": (159, 1299),
        "attrs": {
            "缓震": ["回弹中底", "软弹中底", "硬质支撑"],
            "重量": ["单只210g", "单只240g", "单只270g"],
            "鞋型": ["宽楦", "标准楦", "窄楦"],
            "季节": ["四季", "夏季透气", "秋冬保暖"],
        },
        "soft": ["适合跑步的轻便鞋子", "通勤久站不累", "脚宽不挤脚", "夏天透气不闷脚"],
        "review": [
            "单只二百多克，跑五公里很轻快，回弹一般",
            "宽楦对胖脚友好，久站一天脚不酸",
            "夏天穿有点闷，鞋面透气一般",
        ],
    },
    "双肩包": {
        "sub": ["通勤包", "电脑包", "旅行包", "轻便包"],
        "brands": ["行者", "简行", "北道", "山野"],
        "price": (99, 899),
        "attrs": {
            "容量": ["16L", "20L", "24L", "30L"],
            "电脑位": ["可放14寸", "可放15.6寸", "可放16寸"],
            "背负": ["透气背板", "减负肩带", "普通肩带"],
            "防水": ["防泼水", "不防水"],
        },
        "soft": ["通勤装电脑", "背一天不压肩", "出差能登机", "轻便不占地"],
        "review": [
            "背板透气，夏天背一天肩不闷",
            "16寸电脑能放，但装满后有点重",
            "防泼水，小雨没问题",
        ],
    },
    "保温杯": {
        "sub": ["随行杯", "办公杯", "户外杯"],
        "brands": ["暖山", "恒温", "简物"],
        "price": (59, 399),
        "attrs": {
            "容量": ["350ml", "500ml", "750ml"],
            "保温": ["6小时", "12小时", "24小时"],
            "材质": ["316不锈钢", "304不锈钢", "陶瓷内胆"],
            "开盖": ["一键弹盖", "旋盖", "吸管"],
        },
        "soft": ["办公室喝水", "放包里不漏", "送长辈", "保温久"],
        "review": [
            "12小时还烫，办公室用够",
            "一键弹盖单手能开，开车方便",
            "杯身偏重，装包里明显",
        ],
    },
    "机械键盘": {
        "sub": ["87键", "98键", "104键", "客制化"],
        "brands": ["键行", "轴语", "码上"],
        "price": (199, 1599),
        "attrs": {
            "轴体": ["青轴", "红轴", "茶轴", "静音轴"],
            "连接": ["有线", "三模", "蓝牙"],
            "配列": ["87键", "98键", "104键"],
            "灯效": ["RGB", "单色背光", "无光"],
        },
        "soft": ["办公室不吵同事", "码字手感", "游戏响应快", "桌面不占地方"],
        "review": [
            "青轴手感好，但办公室确实吵",
            "静音轴开会也能用，同事没意见",
            "98配列省地方，数字区还在",
        ],
    },
    "显示器": {
        "sub": ["办公屏", "设计屏", "游戏屏"],
        "brands": ["视界", "光年", "清屏"],
        "price": (699, 4599),
        "attrs": {
            "尺寸": ["24寸", "27寸", "32寸"],
            "分辨率": ["1080P", "2K", "4K"],
            "刷新率": ["60Hz", "144Hz", "165Hz"],
            "面板": ["IPS", "VA", "MiniLED"],
        },
        "soft": ["小户型桌面", "写代码看文档", "设计校色", "打游戏不拖影"],
        "review": [
            "2K 27寸看代码很清楚，字不糊",
            "底座占地大，小桌面要换支架",
            "144Hz 打游戏顺滑",
        ],
    },
    "护肤品": {
        "sub": ["面霜", "精华", "洁面", "防晒"],
        "brands": ["清屿", "草木言", "素研"],
        "price": (49, 699),
        "attrs": {
            "肤质": ["干皮", "油皮", "混合皮", "敏感肌"],
            "功效": ["保湿", "修护", "控油", "提亮"],
            "质地": ["清爽", "滋润", "凝露"],
            "规格": ["30ml", "50ml", "100ml"],
        },
        "soft": ["敏感肌能用", "夏天不油", "送妈妈", "换季不干"],
        "review": [
            "敏感肌用两周没泛红，质地偏清爽",
            "冬天干皮单用不够，要叠面霜",
            "上脸不搓泥，后续上妆服帖",
        ],
    },
    "咖啡机": {
        "sub": ["胶囊机", "半自动", "全自动", "手冲"],
        "brands": ["晨煮", "豆集", "一豆"],
        "price": (299, 3999),
        "attrs": {
            "类型": ["胶囊", "半自动", "全自动"],
            "压力": ["15Bar", "19Bar", "20Bar"],
            "奶泡": ["自动奶泡", "手动奶泡", "无"],
            "清洁": ["免拆清洗", "需定期除垢"],
        },
        "soft": ["小户型厨房", "早上三分钟出杯", "办公室用", "新手好上手"],
        "review": [
            "早上三分钟一杯，清洗方便",
            "机器占地不小，小厨房要量尺寸",
            "奶泡偏粗，做拉花不行",
        ],
    },
}

SCENES = ["no_reason", "quality", "wrong_item"]


def _money(v: float) -> float:
    return round(v + 0.0, 2)


def _build_product(idx: int) -> tuple[Product, Inventory]:
    cat = RNG.choice(list(CATEGORIES.keys()))
    cfg = CATEGORIES[cat]
    sub = RNG.choice(cfg["sub"])
    brand = RNG.choice(cfg["brands"])
    model = f"{RNG.choice(['A', 'B', 'C', 'X', 'P'])}{RNG.randint(1, 9)}{RNG.randint(0, 9)}"
    attrs = {k: RNG.choice(v) for k, v in cfg["attrs"].items()}
    price = _money(RNG.randint(*[int(x) for x in cfg["price"]]))
    soft = RNG.sample(cfg["soft"], k=2)
    review = RNG.choice(cfg["review"])
    title = f"{brand} {sub}{model} {cat} {attrs.get('连接', attrs.get('功效', ''))}".strip()
    desc = (
        f"{title}，适用于{soft[0]}与{soft[1]}场景。"
        + "；".join(f"{k}：{v}" for k, v in attrs.items())
        + f"。{desc_tail(cat)}"
    )
    sku = f"SKU{idx:05d}"
    p = Product(
        sku_id=sku,
        spu_id=f"SPU{idx // 3:05d}",
        title=title,
        category=cat,
        sub_category=sub,
        brand=brand,
        price=price,
        attributes=attrs,
        description=desc,
        review_summary=review,
        sales_30d=RNG.randint(0, 5000),
        rating=round(RNG.uniform(3.8, 4.9), 1),
        status="on_sale" if RNG.random() > 0.06 else "off_shelf",
        updated_at=NOW - timedelta(days=RNG.randint(0, 30)),
    )
    qty = RNG.randint(0, 500) if RNG.random() > 0.08 else 0
    inv = Inventory(sku_id=sku, warehouse_id="WH01", available_qty=qty, version=RNG.randint(1, 50))
    return p, inv


def desc_tail(cat: str) -> str:
    tails = {
        "耳机": "支持双设备切换，附三种耳塞尺寸。",
        "运动鞋": "鞋面采用织物拼接，鞋底耐磨橡胶。",
        "双肩包": "内部分区含笔电仓与水杯袋。",
        "保温杯": "杯口食品级密封圈，可整体水洗。",
        "机械键盘": "支持全键无冲，键帽为 PBT 材质。",
        "显示器": "支持 HDMI 与 DP 双接口，可壁挂。",
        "护肤品": "不含酒精香精，开封后 12 个月内用完。",
        "咖啡机": "水箱可拆，附赠清洗刷。",
    }
    return tails.get(cat, "")


def seed_all(reset: bool = True) -> dict:
    init_db(reset=reset)
    with session_scope() as db:
        # 商品与库存
        existing = db.scalar(select(Product).limit(1))
        if existing is None:
            n_sku = 2000
            for i in range(n_sku):
                p, inv = _build_product(i)
                db.add(p)
                db.flush()
                db.add(inv)
            db.flush()

        # 售后规则
        if db.scalar(select(AfterSaleRule).limit(1)) is None:
            base = datetime(2025, 1, 1)
            for cat in list(CATEGORIES.keys()) + ["general"]:
                for scene in SCENES:
                    if scene == "no_reason":
                        window, need_ev, allowed = 7, 0, 1
                        cond = "签收 7 日内、商品完好、不影响二次销售"
                    elif scene == "quality":
                        window, need_ev, allowed = 15, 1, 1
                        cond = "签收 15 日内、质量问题需提供图片或视频证据"
                    else:
                        window, need_ev, allowed = 7, 1, 1
                        cond = "签收 7 日内、错发漏发需提供开箱证据"
                    # 生鲜/贴身类目不支持无理由
                    if cat in {"护肤品"} and scene == "no_reason":
                        allowed = 0
                        cond = "已拆封化妆品不支持七天无理由"
                    db.add(
                        AfterSaleRule(
                            category=cat, scene=scene, condition=cond,
                            window_days=window, need_evidence=need_ev, allowed=allowed,
                            effective_from=base, effective_to=None,
                            version=f"R-2026.09-{cat}",
                        )
                    )
            db.flush()

        # 订单
        if db.scalar(select(Order).limit(1)) is None:
            prod_rows = db.scalars(select(Product)).all()
            for i in range(1000):
                user_id = f"u{RNG.randint(1, 100):04d}"
                status = RNG.choices(
                    ["PAID", "SHIPPED", "SIGNED", "COMPLETED", "CANCELLED"],
                    weights=[10, 20, 40, 27, 3],
                )[0]
                created = NOW - timedelta(days=RNG.randint(1, 40), minutes=RNG.randint(0, 600))
                signed = None
                if status in {"SIGNED", "COMPLETED"}:
                    signed = created + timedelta(days=RNG.randint(1, 4))
                    if signed > NOW:
                        signed = NOW - timedelta(hours=RNG.randint(1, 30))
                order_no = f"SO{2026000000 + i}"
                items = []
                total = 0.0
                for _ in range(RNG.randint(1, 3)):
                    p = RNG.choice(prod_rows)
                    qty = RNG.randint(1, 2)
                    total += p.price * qty
                    items.append(
                        OrderItem(
                            order_no=order_no, sku_id=p.sku_id, title=p.title,
                            category=p.category, qty=qty, unit_price=p.price,
                        )
                    )
                db.add(
                    Order(
                        order_no=order_no, user_id=user_id, status=status,
                        paid_amount=_money(total), created_at=created, signed_at=signed,
                        logistics_no=f"LG{RNG.randint(10**9, 10**10 - 1)}", version=RNG.randint(1, 8),
                    )
                )
                db.flush()
                for it in items:
                    db.add(it)
            db.flush()

        # 政策知识库
        if db.scalar(select(KnowledgeChunk).limit(1)) is None:
            for doc in POLICY_DOCS:
                for i, (section, content) in enumerate(doc["sections"]):
                    db.add(
                        KnowledgeChunk(
                            doc_id=doc["doc_id"], title=doc["title"], section=section,
                            content=content, category=doc["category"], authority=doc["authority"],
                            version=doc["version"], effective_at=doc["effective_at"],
                            chunk_index=i,
                        )
                    )
            db.flush()

        counts = {
            "products": db.query(Product).count(),
            "orders": db.query(Order).count(),
            "rules": db.query(AfterSaleRule).count(),
            "chunks": db.query(KnowledgeChunk).count(),
        }
    return counts


POLICY_DOCS = [
    {
        "doc_id": "POL-001", "title": "七天无理由退换货规则", "category": "general",
        "authority": "平台售后政策", "version": "v2026.09", "effective_at": datetime(2026, 9, 1),
        "sections": [
            ("适用范围", "自签收之日起 7 个自然日内，商品完好、不影响二次销售，可申请无理由退货。"),
            ("例外品类", "已拆封的化妆品、贴身衣物、定制类商品不支持七天无理由退货。"),
            ("运费承担", "无理由退货的往返运费由消费者承担；质量问题由商家承担。"),
            ("退款时效", "商家签收退货后 48 小时内完成验货，验货通过后 24 小时内发起退款，原路退回。"),
        ],
    },
    {
        "doc_id": "POL-002", "title": "质量问题退换货与举证要求", "category": "general",
        "authority": "平台售后政策", "version": "v2026.09", "effective_at": datetime(2026, 9, 1),
        "sections": [
            ("时限", "签收后 15 日内出现质量问题可申请退换货，超时需走保修流程。"),
            ("举证", "需提供商品问题部位的清晰图片或视频，必要时提供开箱视频。"),
            ("处理", "证据充分且判定为质量问题时，商家承担往返运费并按原价退款或换新。"),
            ("争议", "商家与消费者对质量判定不一致时，转平台介入，由人工客服复核。"),
        ],
    },
    {
        "doc_id": "POL-003", "title": "发货、配送与运费说明", "category": "general",
        "authority": "平台物流政策", "version": "v2026.09", "effective_at": datetime(2026, 9, 1),
        "sections": [
            ("发货时效", "现货商品在付款后 48 小时内发出，预售商品以详情页标注时间为准。"),
            ("配送时效", "普通快递 3–5 天送达，偏远地区 5–7 天；大件商品另行预约。"),
            ("运费标准", "单笔订单满 99 元包邮，未满收取 8 元运费；偏远地区加收 5 元。"),
            ("超时未发货", "超过承诺发货时间未发出，可申请补偿或取消订单全额退款。"),
        ],
    },
    {
        "doc_id": "POL-004", "title": "发票开具与保修凭证", "category": "general",
        "authority": "平台财务规则", "version": "v2026.09", "effective_at": datetime(2026, 9, 1),
        "sections": [
            ("开票时间", "订单完成后 30 天内可申请电子发票，支持个人与企业抬头。"),
            ("发票类型", "默认电子普通发票，企业客户可申请增值税专用发票，需提供完整税务信息。"),
            ("保修凭证", "电子发票与订单号均可作为保修凭证，无需纸质发票。"),
        ],
    },
    {
        "doc_id": "POL-005", "title": "高价值商品售后特别规定", "category": "general",
        "authority": "平台风控规则", "version": "v2026.09", "effective_at": datetime(2026, 9, 1),
        "sections": [
            ("认定标准", "单笔订单实付金额超过 1000 元的商品视为高价值商品。"),
            ("审批要求", "高价值商品退款需客服主管复核，必要时要求退回验货后再退款。"),
            ("风控", "同一用户 30 天内高价值退款超过 3 次，进入人工风控审核。"),
        ],
    },
    {
        "doc_id": "POL-006", "title": "耳机类目售后细则", "category": "耳机",
        "authority": "类目运营规范", "version": "v2026.09", "effective_at": datetime(2026, 9, 1),
        "sections": [
            ("佩戴不适", "入耳式耳机因尺寸不合可申请换耳塞，不属于质量问题。"),
            ("拆封规则", "耳机拆封后仍支持 7 天无理由，但需保证配件齐全、无佩戴污渍。"),
            ("保修", "主机保修 12 个月，耳塞、线材等配件保修 3 个月。"),
        ],
    },
    {
        "doc_id": "POL-007", "title": "运动鞋类目售后细则", "category": "运动鞋",
        "authority": "类目运营规范", "version": "v2026.09", "effective_at": datetime(2026, 9, 1),
        "sections": [
            ("试穿标准", "室内试穿允许，鞋底磨损或室外穿着后不支持无理由退货。"),
            ("尺码问题", "尺码不合适可申请换码，往返运费由消费者承担。"),
            ("质量问题", "开胶、断底等质量问题 15 日内可退换，需提供鞋底与鞋面照片。"),
        ],
    },
    {
        "doc_id": "POL-008", "title": "护肤品与个护类目售后细则", "category": "护肤品",
        "authority": "类目运营规范", "version": "v2026.09", "effective_at": datetime(2026, 9, 1),
        "sections": [
            ("拆封限制", "已拆封化妆品不支持七天无理由退货，未拆封且不影响二次销售可退。"),
            ("过敏处理", "使用后出现过敏，需提供就医记录或皮肤检测证明，可申请退款。"),
            ("有效期", "收到商品保质期不足 6 个月的，可无条件退货。"),
        ],
    },
]


if __name__ == "__main__":
    print(seed_all())
