#!/usr/bin/env python3
"""
Polymarket 订单簿 统计分析器
==========================
分析采集的 Polymarket BTC Up/Down 订单簿数据，输出统计报告和图表

用法:
  python analyzer.py                    # 分析所有数据
  python analyzer.py --days 7           # 分析最近7天
  python analyzer.py --chart            # 生成订单簿图表
"""

import csv, os, json, argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import numpy as np

# ============================================================
def load_all_ob(data_dir: str = "./data", days: int = None) -> list:
    """加载所有 Polymarket 订单簿文件"""
    records = []
    cutoff = None
    if days:
        cutoff = datetime.now() - timedelta(days=days)

    data_path = Path(data_dir)
    for f in sorted(data_path.glob("polymarket_ob_*.csv")):
        try:
            with open(f) as fp:
                for row in csv.DictReader(fp):
                    ts = float(row["timestamp"])
                    dt = datetime.fromtimestamp(ts)
                    if cutoff and dt < cutoff:
                        continue
                    records.append({
                        "timestamp": ts,
                        "datetime": dt,
                        "token": row["token"],
                        "market_title": row["market_title"],
                        "best_bid": float(row["best_bid"]),
                        "best_ask": float(row["best_ask"]),
                        "bid_size": float(row["bid_size"]),
                        "ask_size": float(row["ask_size"]),
                        "bids": json.loads(row["bids_json"]) if row.get("bids_json") else [],
                        "asks": json.loads(row["asks_json"]) if row.get("asks_json") else [],
                    })
        except Exception as e:
            print(f"  [警告] 无法读取 {f.name}: {e}")

    return sorted(records, key=lambda r: r["timestamp"])


def analyze(records: list) -> dict:
    """统计分析 Polymarket 订单簿"""
    if not records:
        return {"error": "无数据"}

    # 按 token 分组
    up_records = [r for r in records if r["token"] == "Up"]
    down_records = [r for r in records if r["token"] == "Down"]

    # ===== 价差分析 =====
    spreads = [r["best_ask"] - r["best_bid"] for r in records if r["best_bid"] and r["best_ask"]]
    mid_prices = [(r["best_bid"] + r["best_ask"]) / 2 for r in records if r["best_bid"] and r["best_ask"]]

    # ===== 买卖不平衡 =====
    # bid_size / (bid_size + ask_size)  > 0.5 表示买方深度更大
    imbalances = []
    for r in records:
        total = r["bid_size"] + r["ask_size"]
        if total > 0:
            imbalances.append(r["bid_size"] / total)

    # ===== Up 价格变化 =====
    up_mids = []
    for r in up_records:
        if r["best_bid"] and r["best_ask"]:
            up_mids.append({
                "timestamp": r["timestamp"],
                "datetime": r["datetime"],
                "mid": (r["best_bid"] + r["best_ask"]) / 2,
            })

    # Up 价格趋势 (首尾比较)
    up_mid_change = 0
    if len(up_mids) >= 2:
        up_mid_change = up_mids[-1]["mid"] - up_mids[0]["mid"]

    # ===== 时段分析 =====
    hour_stats = defaultdict(lambda: {
        "count": 0, "avg_spread": 0, "avg_up_mid": 0, "up_count": 0,
        "avg_bid_size": 0, "avg_ask_size": 0,
    })
    for r in records:
        h = r["datetime"].hour
        s = hour_stats[h]
        s["count"] += 1
        if r["best_bid"] and r["best_ask"]:
            s["avg_spread"] += (r["best_ask"] - r["best_bid"])
        if r["token"] == "Up" and r["best_bid"] and r["best_ask"]:
            s["avg_up_mid"] += (r["best_bid"] + r["best_ask"]) / 2
            s["up_count"] += 1
        s["avg_bid_size"] += r["bid_size"]
        s["avg_ask_size"] += r["ask_size"]

    for h in hour_stats:
        s = hour_stats[h]
        if s["count"] > 0:
            s["avg_spread"] = round(s["avg_spread"] / s["count"], 4)
            s["avg_bid_size"] = round(s["avg_bid_size"] / s["count"], 2)
            s["avg_ask_size"] = round(s["avg_ask_size"] / s["count"], 2)
        if s["up_count"] > 0:
            s["avg_up_mid"] = round(s["avg_up_mid"] / s["up_count"], 4)

    # ===== 订单簿深度分析 =====
    # 取最近一条记录展示
    latest = records[-1]

    n = len(records)

    return {
        "样本数": n,
        "Up样本": len(up_records),
        "Down样本": len(down_records),
        "时间范围": f"{records[0]['datetime']} ~ {records[-1]['datetime']}",
        "价差分析": {
            "平均价差": round(np.mean(spreads), 4) if spreads else 0,
            "中位数价差": round(np.median(spreads), 4) if spreads else 0,
            "最大价差": round(max(spreads), 4) if spreads else 0,
            "最小价差": round(min(spreads), 4) if spreads else 0,
            "价差标准差": round(np.std(spreads), 4) if spreads else 0,
        },
        "Up隐含概率": {
            "平均中间价": round(np.mean(up_mids) * 100 if up_mids else 0, 1),
            "最新中间价": round(up_mids[-1]["mid"] * 100 if up_mids else 0, 1),
            "趋势变动": round(up_mid_change * 100, 2),
            "最高": round(max(m["mid"] for m in up_mids) * 100 if up_mids else 0, 1),
            "最低": round(min(m["mid"] for m in up_mids) * 100 if up_mids else 0, 1),
        } if up_mids else {},
        "买卖失衡": {
            "平均bid占比": round(np.mean(imbalances) * 100, 1) if imbalances else 0,
            "偏向": "买方深度更大" if (np.mean(imbalances) > 0.5 if imbalances else False) else "卖方深度更大",
        } if imbalances else {},
        "最新订单簿": {
            "Up": {
                "best_bid": latest["best_bid"] if latest["token"] == "Up" else None,
                "best_ask": latest["best_ask"] if latest["token"] == "Up" else None,
                "bid_size": latest["bid_size"] if latest["token"] == "Up" else None,
                "ask_size": latest["ask_size"] if latest["token"] == "Up" else None,
            },
            "市场": latest["market_title"],
        },
        "时段分析": {
            f"{h:02d}:00": {
                "样本数": s["count"],
                "平均价差": s["avg_spread"],
                "Up平均中间价": s["avg_up_mid"],
                "平均bid深度$": s["avg_bid_size"],
                "平均ask深度$": s["avg_ask_size"],
            }
            for h, s in sorted(hour_stats.items())
        },
    }


def print_report(stats: dict):
    """打印统计报告"""
    print("\n" + "=" * 60)
    print("  Polymarket BTC 订单簿 统计分析报告")
    print("=" * 60)

    print(f"\n  📊 概览")
    print(f"  总样本数: {stats.get('样本数', 'N/A')}")
    print(f"  Up样本: {stats.get('Up样本', 'N/A')}  |  Down样本: {stats.get('Down样本', 'N/A')}")
    print(f"  时间: {stats.get('时间范围', 'N/A')}")

    spread = stats.get("价差分析", {})
    if spread:
        print(f"\n  📉 价差分析 (spread = best_ask - best_bid)")
        print(f"  平均价差: {spread['平均价差']:.4f}")
        print(f"  中位数:   {spread['中位数价差']:.4f}")
        print(f"  最大/最小: {spread['最大价差']:.4f} / {spread['最小价差']:.4f}")
        print(f"  标准差:   {spread['价差标准差']:.4f}")

    up_prob = stats.get("Up隐含概率", {})
    if up_prob:
        print(f"\n  🎯 Up 隐含概率 (mid price × 100)")
        print(f"  平均: {up_prob['平均中间价']}%")
        print(f"  最新: {up_prob['最新中间价']}%")
        print(f"  趋势: {up_prob['趋势变动']:+.1f}¢")
        print(f"  区间: {up_prob['最低']}% ~ {up_prob['最高']}%")

    imbalance = stats.get("买卖失衡", {})
    if imbalance:
        print(f"\n  ⚖️  买卖比: {imbalance['平均bid占比']}% ({imbalance['偏向']})")

    print(f"\n  🕐 时段分析:")
    for h, s in stats.get("时段分析", {}).items():
        bar = "█" * min(int(s["样本数"] / 10), 20)
        up_pct_str = f"Up中价={s['Up平均中间价']:.2f}" if s["Up平均中间价"] else ""
        print(f"    {h}: {s['样本数']:>4d}条  价差={s['平均价差']:.4f}  {up_pct_str}  {bar}")

    print("=" * 60)


def generate_chart(records: list, output: str = None):
    """生成订单簿趋势图"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        print("[错误] 需要 matplotlib: pip install matplotlib")
        return

    if not records:
        print("无数据可画图")
        return

    # 取最近1000条
    records = records[-1000:] if len(records) > 1000 else records

    times = [r["datetime"] for r in records]
    up_mids = []
    down_mids = []
    spreads = []

    for r in records:
        if r["best_bid"] and r["best_ask"]:
            mid = (r["best_bid"] + r["best_ask"]) / 2
            spread = r["best_ask"] - r["best_bid"]
            if r["token"] == "Up":
                up_mids.append((r["datetime"], mid * 100))
            else:
                down_mids.append((r["datetime"], mid * 100))
            spreads.append((r["datetime"], spread))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(20, 10),
                                     gridspec_kw={"height_ratios": [3, 1]})

    # 图1: Up/Down 隐含概率趋势
    if up_mids:
        ut, uv = zip(*up_mids)
        ax1.plot(ut, uv, color='#26a69a', linewidth=1, alpha=0.8, label='Up Mid Price %')
    if down_mids:
        dt, dv = zip(*down_mids)
        ax1.plot(dt, dv, color='#ef5350', linewidth=1, alpha=0.8, label='Down Mid Price %')

    ax1.axhline(y=50, color='gray', linestyle='--', alpha=0.3)
    ax1.set_ylabel("Implied Probability %")
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.set_title(f"Polymarket BTC Up/Down Order Book  |  {records[0]['datetime']} ~ {records[-1]['datetime']}")

    # 图2: 价差变化
    if spreads:
        st, sv = zip(*spreads)
        ax2.fill_between(st, sv, alpha=0.5, color='#ff9800')
        ax2.plot(st, sv, color='#ff9800', linewidth=0.5, alpha=0.8)
    ax2.set_ylabel("Spread")
    ax2.set_xlabel("Time")
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha="right")

    if output is None:
        output = f"polymarket_ob_chart_{datetime.now().strftime('%Y%m%d')}.png"
    plt.tight_layout()
    plt.savefig(output, dpi=120)
    print(f"图表已保存: {output}")


# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polymarket 订单簿分析器")
    parser.add_argument("--days", type=int, default=None, help="分析最近N天")
    parser.add_argument("--chart", action="store_true", help="生成订单簿图表")
    parser.add_argument("--output", type=str, default=None, help="图表输出路径")
    parser.add_argument("--data-dir", type=str, default="./data", help="数据目录")
    args = parser.parse_args()

    records = load_all_ob(args.data_dir, args.days)
    print(f"加载了 {len(records)} 条订单簿记录")

    if not records:
        print("没有找到 Polymarket 订单簿数据。请先运行 collector.py 采集数据。")
        exit(1)

    if args.chart:
        generate_chart(records, args.output)
    else:
        stats = analyze(records)
        print_report(stats)
