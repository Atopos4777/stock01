"""HTTP 压测：并发打 /api/chat（SSE），统计延迟分位、吞吐与错误率。

用法：python eval/load_test.py --base http://127.0.0.1:8022 --concurrency 20 --requests 160
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import httpx

QUERIES = [
    "2000以内通勤降噪耳机，戴眼镜不夹头",
    "查一下订单 SO2026000123",
    "耳机拆封之后还能七天无理由退货吗",
    "推荐一款适合跑步的轻便鞋子",
    "你好",
]


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    i = min(len(s) - 1, max(0, int(round(p / 100 * (len(s) - 1)))))
    return round(s[i], 2)


async def one(client: httpx.AsyncClient, base: str, token: str, query: str) -> tuple[float, float, bool, str, int]:
    """返回 (总耗时ms, 首块时间ms, 是否成功, 意图, 状态码)。"""
    t0 = time.perf_counter()
    ttft = -1.0
    intent = ""
    ok = True
    code = 0
    try:
        async with client.stream(
            "POST", f"{base}/api/chat",
            json={"message": query, "thread_id": f"th-load-{token[-6:]}"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=120,
        ) as r:
            code = r.status_code
            ok = r.status_code == 200
            async for line in r.aiter_lines():
                if line.startswith("event: token") and ttft < 0:
                    ttft = (time.perf_counter() - t0) * 1000
                if line.startswith("data:") and '"intent"' in line:
                    try:
                        intent = json.loads(line[5:].strip()).get("intent", "")
                    except json.JSONDecodeError:
                        pass
    except Exception:  # noqa: BLE001
        ok = False
    return (time.perf_counter() - t0) * 1000, (ttft if ttft > 0 else (time.perf_counter() - t0) * 1000), ok, intent, code


async def main_async(base: str, concurrency: int, total: int) -> dict:
    # 每个并发用一个独立用户，避免同一用户 30 次/分钟的限流把错误率打满
    token = (await httpx.AsyncClient().get(f"{base}/api/token", params={"user_id": "u0001", "role": "consumer"})).json()["token"]
    tokens = [
        (await httpx.AsyncClient().get(f"{base}/api/token", params={"user_id": f"u{i + 1:04d}", "role": "consumer"})).json()["token"]
        for i in range(max(concurrency, 10))
    ]
    sem = asyncio.Semaphore(concurrency)
    lat, ttft, oks, intents, codes = [], [], [], [], []

    async with httpx.AsyncClient() as client:
        async def worker(idx: int):
            async with sem:
                q = QUERIES[idx % len(QUERIES)]
                r = await one(client, base, tokens[idx % len(tokens)], q)
                lat.append(r[0]); ttft.append(r[1]); oks.append(r[2]); intents.append(r[3]); codes.append(r[4])

        started = time.perf_counter()
        await asyncio.gather(*(worker(i) for i in range(total)))
        wall = time.perf_counter() - started

    err = oks.count(False)
    code_count: dict[str, int] = {}
    for c in codes:
        code_count[str(c)] = code_count.get(str(c), 0) + 1
    return {
        "base": base,
        "concurrency": concurrency,
        "requests": total,
        "wall_seconds": round(wall, 2),
        "rps": round(total / wall, 2),
        "error_rate": round(err / total, 4),
        "status_codes": code_count,
        "latency_ms": {
            "mean": round(statistics.mean(lat), 2),
            "p50": pct(lat, 50), "p90": pct(lat, 90), "p95": pct(lat, 95), "p99": pct(lat, 99),
            "max": round(max(lat), 2),
        },
        "ttft_ms": {"p50": pct(ttft, 50), "p95": pct(ttft, 95)},
        "intents": sorted({i for i in intents if i}),
        "demo_token_used": bool(token),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8022")
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--requests", type=int, default=160)
    args = ap.parse_args()
    result = asyncio.run(main_async(args.base, args.concurrency, args.requests))
    out = Path(__file__).with_name("load_report.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
