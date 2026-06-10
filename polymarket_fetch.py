"""
Polymarket 数据抓取脚本
使用 Polymarket Gamma API 获取市场数据
"""

import requests
import json

BASE_URL = "https://gamma-api.polymarket.com"

def fetch_events(limit=20):
    """获取热门预测事件（含内嵌 markets）"""
    url = f"{BASE_URL}/events"
    params = {
        "limit": limit,
        "order": "volume",
        "ascending": False,
        "includeMarkets": "true",   # 直接在事件中返回市场
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json()

def fetch_markets_for_event(event_slug, limit=5):
    """通过 markets 端点获取某事件下的市场"""
    url = f"{BASE_URL}/markets"
    params = {
        "event_slug": event_slug,
        "limit": limit,
        "order": "volume",
        "ascending": False,
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json()

def format_price(price):
    """将价格格式化为百分比"""
    if price is None:
        return "N/A"
    return f"{float(price) * 100:.1f}%"

def main():
    print("=" * 70)
    print("Polymarket 热门预测市场")
    print("=" * 70)

    events = fetch_events(limit=10)

    for i, event in enumerate(events, 1):
        title = event.get("title", "Unknown")
        volume = float(event.get("volume", 0))
        slug = event.get("slug", "")

        print(f"\n{'─' * 70}")
        print(f"#{i} {title}")
        print(f"   总交易量: ${volume:,.0f}")

        # 优先用事件自带 markets，否则单独查询
        markets = event.get("markets", [])
        if not markets:
            try:
                markets = fetch_markets_for_event(slug, limit=5)
            except Exception as e:
                print(f"   [获取详情失败: {e}]")
                continue

        if not markets:
            print(f"   (暂无活跃市场)")
            continue

        # 按交易量排序，取前 6 个市场
        sorted_markets = sorted(
            markets,
            key=lambda m: float(m.get("volume", 0) or 0),
            reverse=True
        )[:6]

        for m in sorted_markets:
            question = m.get("question", "") or m.get("title", "")
            outcomes = m.get("outcomes", [])
            outcome_prices = m.get("outcomePrices", [])

            # Gamma API 返回的 outcomes 和 outcomePrices 都是 JSON 字符串
            if isinstance(outcomes, str):
                outcomes = json.loads(outcomes)
            if isinstance(outcome_prices, str):
                outcome_prices = json.loads(outcome_prices)

            volume_m = float(m.get("volume", 0) or 0)
            q_short = question[:70] if question else title[:70]

            print(f"   ├─ {q_short}")
            print(f"   │  交易量: ${volume_m:,.0f}", end="")

            if outcomes and outcome_prices:
                print("  |  ", end="")
                items = []
                for o, p in zip(outcomes, outcome_prices):
                    items.append(f"{o}: {format_price(p)}")
                print(", ".join(items))
            else:
                print()

    print(f"\n{'=' * 70}")
    print("数据来源: Polymarket Gamma API")

if __name__ == "__main__":
    main()
