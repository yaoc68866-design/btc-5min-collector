#!/usr/bin/env python3
"""
Polymarket 订单簿 统计分析器 v2.1
===============================
使用成交量加权中间价 (VWMP) 分析 Polymarket BTC Up/Down 订单簿数据

用法:
  python analyzer.py                    # 分析所有数据
  python analyzer.py --days 7           # 分析最近7天
  python analyzer.py --chart            # 生成订单簿趋势图
"""

import csv, os, json, argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import numpy as np

# ============================================================
# 成交量加权中间价 (VWMP) 计算
# ============================================================
def calc_vwmp(bids: list, asks: list) -> dict:
    """
    从完整深度计算成交量加权价格
    bids/asks: [[price, size], [price, size], ...]
    返回: {"vwap_bid", "vwap_ask", "vwmp", "bid_depth", "ask_depth", "total_depth"}
    """
    result = {"vwap_bid": None, "vwap_ask": None, "vwmp": None,
              "bid_depth": 0, "ask_depth": 0, "total_depth": 0}

    if bids:
        bid_vol = sum(b[0] * b[1] for b in bids)
        bid_size = sum(b[1] for b in bids)
        if bid_size > 0:
            result["vwap_bid"] = bid_vol / bid_size
            result["bid_depth"] = bid_size

    if asks:
        ask_vol = sum(a[0] * a[1] for a in asks)
        ask_size = sum(a[1] for a in asks)
        if ask_size > 0:
            result["vwap_ask"] = ask_vol / ask_size
            result["ask_depth"] = ask_size

    result["total_depth"] = result["bid_depth"] + result["ask_depth"]

    if result["vwap_bid"] is not None and result["vwap_ask"] is not None:
        result["vwmp"] = (result["vwap_bid"] + result["vwap_ask"]) / 2

    return result


def load_all_ob(data_dir: str = "./data", days: int = None) -> list:
    """加载所有 Polymarket 订单簿文件，自动计算 VWMP"""
    records = []
    cutoff = None
    if days:
        cutoff = datetime.now() - timedelta(days=days)

    data_path = Path(data_dir)
    for f in sorted(data_path.glob("polymarket_ob_*.csv")):
        try:
            with open(f, encoding='utf-8') as fp:
                for row in csv.DictReader(fp):
                    ts = float(row["timestamp"])
                    dt = datetime.fromtimestamp(ts)
                    if cutoff and dt < cutoff:
                        continue

                    # 解析订单簿深度
                    bids = json.loads(row.get("bids_json", "[]")) if row.get("bids_json") else []
                    asks = json.loads(row.get("asks_json", "[]")) if row.get("asks_json") else []

                    # 计算 VWMP
                    vw = calc_vwmp(bids, asks)

                    # 普通 mid (best_bid/best_ask)
                    best_bid = float(row["best_bid"]) if row.get("best_bid") else None
                    best_ask = float(row["best_ask"]) if row.get("best_ask") else None
                    simple_mid = (best_bid + best_ask) / 2 if (best_bid is not None and best_ask is not None) else None

                    records.append({
                        "timestamp": ts,
                        "datetime": dt,
                        "token": row["token"],
                        "market_title": row["market_title"],
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "simple_mid": simple_mid,
                        "bid_size": float(row["bid_size"]) if row.get("bid_size") else 0,
                        "ask_size": float(row["ask_size"]) if row.get("ask_size") else 0,
                        "bids": bids,
                        "asks": asks,
                        "vwap_bid": vw["vwap_bid"],
                        "vwap_ask": vw["vwap_ask"],
                        "vwmp": vw["vwmp"],           # 成交量加权中间价 (核心指标)
                        "vwap_spread": (vw["vwap_ask"] - vw["vwap_bid"]) if vw["vwap_bid"] and vw["vwap_ask"] else None,
                        "bid_depth": vw["bid_depth"],
                        "ask_depth": vw["ask_depth"],
                        "total_depth": vw["total_depth"],
                    })
        except Exception as e:
            print(f"  [警告] 无法读取 {f.name}: {e}")

    return sorted(records, key=lambda r: r["timestamp"])


def analyze(records: list) -> dict:
    """使用 VWMP 分析 Polymarket 订单簿"""
    if not records:
        return {"error": "无数据"}

    up_records = [r for r in records if r["token"] == "Up"]
    down_records = [r for r in records if r["token"] == "Down"]

    # ===== VWMP 价差分析 =====
    vwap_spreads = [r["vwap_spread"] for r in records if r["vwap_spread"] is not None]
    vwmps_up = [r["vwmp"] for r in up_records if r["vwmp"] is not None]
    vwmps_down = [r["vwmp"] for r in down_records if r["vwmp"] is not None]

    # ===== 简单 mid (对比用) =====
    simple_mids_up = [r["simple_mid"] for r in up_records if r["simple_mid"] is not None]

    # ===== 深度分析 =====
    bid_depths = [r["bid_depth"] for r in records if r["bid_depth"] > 0]
    ask_depths = [r["ask_depth"] for r in records if r["ask_depth"] > 0]
    total_depths = [r["total_depth"] for r in records if r["total_depth"] > 0]

    # ===== Up VWMP 趋势 =====
    up_vwmp_trend = []
    for r in up_records:
        if r["vwmp"] is not None:
            up_vwmp_trend.append({
                "timestamp": r["timestamp"],
                "datetime": r["datetime"],
                "vwmp": r["vwmp"],
            })

    up_vwmp_change = 0
    if len(up_vwmp_trend) >= 2:
        up_vwmp_change = up_vwmp_trend[-1]["vwmp"] - up_vwmp_trend[0]["vwmp"]

    # ===== VWMP 与简单 mid 的差异 =====
    vwmp_vs_simple = []
    for r in records:
        if r["vwmp"] is not None and r["simple_mid"] is not None:
            vwmp_vs_simple.append(abs(r["vwmp"] - r["simple_mid"]))

    # ===== 时段分析 =====
    hour_stats = defaultdict(lambda: {
        "count": 0, "up_vwmp_sum": 0, "up_vwmp_n": 0,
        "down_vwmp_sum": 0, "down_vwmp_n": 0,
        "avg_vwap_spread": 0, "spread_n": 0,
        "avg_depth": 0, "depth_n": 0,
    })
    for r in records:
        h = r["datetime"].hour
        s = hour_stats[h]
        s["count"] += 1
        if r["vwmp"] is not None:
            if r["token"] == "Up":
                s["up_vwmp_sum"] += r["vwmp"]
                s["up_vwmp_n"] += 1
            else:
                s["down_vwmp_sum"] += r["vwmp"]
                s["down_vwmp_n"] += 1
        if r["vwap_spread"] is not None:
            s["avg_vwap_spread"] += r["vwap_spread"]
            s["spread_n"] += 1
        if r["total_depth"] > 0:
            s["avg_depth"] += r["total_depth"]
            s["depth_n"] += 1

    hour_summary = {}
    for h in sorted(hour_stats.keys()):
        s = hour_stats[h]
        hour_summary[f"{h:02d}:00"] = {
            "样本数": s["count"],
            "Up_VWMP": round(s["up_vwmp_sum"] / s["up_vwmp_n"] * 100, 1) if s["up_vwmp_n"] else None,
            "Down_VWMP": round(s["down_vwmp_sum"] / s["down_vwmp_n"] * 100, 1) if s["down_vwmp_n"] else None,
            "加权价差": round(s["avg_vwap_spread"] / s["spread_n"], 4) if s["spread_n"] else None,
            "平均深度$": round(s["avg_depth"] / s["depth_n"], 0) if s["depth_n"] else 0,
        }

    n = len(records)

    return {
        "样本数": n,
        "Up样本": len(up_records),
        "Down样本": len(down_records),
        "时间范围": f"{records[0]['datetime']} ~ {records[-1]['datetime']}",
        "市场": records[0]["market_title"],

        "VWMP分析": {
            "Up_平均VWMP_%": round(np.mean(vwmps_up) * 100, 1) if vwmps_up else None,
            "Up_最新VWMP_%": round(vwmps_up[-1] * 100, 1) if vwmps_up else None,
            "Up_VWMP变化_%": round(up_vwmp_change * 100, 2),
            "Up_VWMP最高_%": round(max(vwmps_up) * 100, 1) if vwmps_up else None,
            "Up_VWMP最低_%": round(min(vwmps_up) * 100, 1) if vwmps_up else None,
            "Down_平均VWMP_%": round(np.mean(vwmps_down) * 100, 1) if vwmps_down else None,
            "Down_最新VWMP_%": round(vwmps_down[-1] * 100, 1) if vwmps_down else None,
            "VWMP_vs_简单mid_平均偏差": round(np.mean(vwmp_vs_simple) * 100, 2) if vwmp_vs_simple else None,
        },

        "深度分析": {
            "平均买盘深度$": round(np.mean(bid_depths), 0) if bid_depths else 0,
            "平均卖盘深度$": round(np.mean(ask_depths), 0) if ask_depths else 0,
            "平均总深度$": round(np.mean(total_depths), 0) if total_depths else 0,
            "最大总深度$": round(max(total_depths), 0) if total_depths else 0,
            "深度买卖比": round(np.mean(bid_depths) / np.mean(ask_depths), 2) if bid_depths and ask_depths and np.mean(ask_depths) > 0 else None,
        },

        "加权价差分析": {
            "平均加权价差": round(np.mean(vwap_spreads), 4) if vwap_spreads else None,
            "中位数加权价差": round(np.median(vwap_spreads), 4) if vwap_spreads else None,
            "加权价差标准差": round(np.std(vwap_spreads), 4) if vwap_spreads else None,
        },

        "时段分析": hour_summary,
    }


def print_report(stats: dict):
    """打印统计报告"""
    print("\n" + "=" * 60)
    print("  Polymarket BTC 订单簿 分析报告 (VWMP 加权)")
    print("=" * 60)

    print(f"\n  [概览]")
    print(f"  总样本: {stats.get('样本数', 'N/A')}")
    print(f"  Up: {stats.get('Up样本', 'N/A')}  |  Down: {stats.get('Down样本', 'N/A')}")
    print(f"  时间: {stats.get('时间范围', 'N/A')}")
    print(f"  市场: {stats.get('市场', 'N/A')}")

    vwmp = stats.get("VWMP分析", {})
    if vwmp:
        print(f"\n  [VWMP 成交量加权中间价]")
        print(f"  Up   平均: {vwmp.get('Up_平均VWMP_%', 'N/A')}%  最新: {vwmp.get('Up_最新VWMP_%', 'N/A')}%  变化: {vwmp.get('Up_VWMP变化_%', 0):+.1f}%")
        print(f"  Down 平均: {vwmp.get('Down_平均VWMP_%', 'N/A')}%  最新: {vwmp.get('Down_最新VWMP_%', 'N/A')}%")
        if vwmp.get("VWMP_vs_简单mid_平均偏差"):
            print(f"  VWMP vs 简单 mid 偏差: {vwmp['VWMP_vs_简单mid_平均偏差']}%  <- 这就是加权修正的幅度")

    depth = stats.get("深度分析", {})
    if depth:
        print(f"\n  [订单簿深度]")
        print(f"  平均买盘: ${depth.get('平均买盘深度$', 0):,.0f}  平均卖盘: ${depth.get('平均卖盘深度$', 0):,.0f}")
        print(f"  总深度: ${depth.get('平均总深度$', 0):,.0f}  (最大: ${depth.get('最大总深度$', 0):,.0f})")
        if depth.get("深度买卖比"):
            print(f"  买卖深度比: {depth['深度买卖比']} (>1=买方更深)")

    vspread = stats.get("加权价差分析", {})
    if vspread:
        print(f"\n  [VWAP 加权价差]")
        print(f"  均值: {vspread.get('平均加权价差', 'N/A')}  中位数: {vspread.get('中位数加权价差', 'N/A')}")

    print(f"\n  [时段分析]")
    for h, s in stats.get("时段分析", {}).items():
        bar = "|" * min(int(s["样本数"] / 5), 30)
        up_str = f"Up={s['Up_VWMP']}%" if s.get("Up_VWMP") else ""
        down_str = f"Down={s['Down_VWMP']}%" if s.get("Down_VWMP") else ""
        depth_str = f"深度=${s.get('平均深度$', 0):,.0f}" if s.get('平均深度$') else ""
        print(f"    {h}: {s['样本数']:>4d}条  {up_str} {down_str}  {depth_str}  {bar}")

    print("=" * 60)


def generate_chart(records: list, output: str = None):
    """生成 VWMP 订单簿趋势图"""
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

    records = records[-2000:] if len(records) > 2000 else records

    # 提取 VWMP 数据
    up_data = []   # (datetime, vwmp*100, simple_mid*100)
    down_data = []
    depth_data = []  # (datetime, total_depth)
    spread_data = []  # (datetime, vwap_spread)

    for r in records:
        if r["vwmp"] is not None:
            if r["token"] == "Up":
                up_data.append((r["datetime"], r["vwmp"] * 100,
                               r["simple_mid"] * 100 if r["simple_mid"] else None))
            else:
                down_data.append((r["datetime"], r["vwmp"] * 100,
                                 r["simple_mid"] * 100 if r["simple_mid"] else None))
        if r["total_depth"] > 0:
            depth_data.append((r["datetime"], r["total_depth"]))
        if r["vwap_spread"] is not None:
            spread_data.append((r["datetime"], r["vwap_spread"]))

    fig = plt.figure(figsize=(22, 12))
    gs = fig.add_gridspec(3, 1, height_ratios=[3, 2, 1], hspace=0.08)

    # === 图1: Up/Down VWMP 趋势 ===
    ax1 = fig.add_subplot(gs[0])
    if up_data:
        ut, uv = zip(*up_data)
        ax1.plot(ut, uv, color='#26a69a', linewidth=1.2, alpha=0.9, label='Up VWMP %')
    if down_data:
        dt, dv = zip(*down_data)
        ax1.plot(dt, dv, color='#ef5350', linewidth=1.2, alpha=0.9, label='Down VWMP %')

    # 简单 mid 虚线对比
    if up_data and up_data[0][2] is not None:
        ut2, _, us = zip(*up_data)
        ax1.plot(ut2, us, color='#26a69a', linewidth=0.5, alpha=0.3, linestyle='--', label='Up simple mid')
    if down_data and down_data[0][2] is not None:
        dt2, _, ds = zip(*down_data)
        ax1.plot(dt2, ds, color='#ef5350', linewidth=0.5, alpha=0.3, linestyle='--', label='Down simple mid')

    ax1.axhline(y=50, color='gray', linestyle='--', alpha=0.3)
    ax1.set_ylabel("VWMP %", fontsize=11)
    ax1.legend(loc='upper right', fontsize=8)
    ax1.grid(True, alpha=0.3)
    ax1.set_title(f"Polymarket BTC Up/Down VWMP (成交量加权) | {records[0]['datetime']} ~ {records[-1]['datetime']}", fontsize=13)

    # === 图2: 订单簿深度 ===
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    if depth_data:
        dpt, dpv = zip(*depth_data)
        ax2.fill_between(dpt, dpv, alpha=0.4, color='#42a5f5')
        ax2.plot(dpt, dpv, color='#42a5f5', linewidth=0.8, alpha=0.8)
    ax2.set_ylabel("Depth $", fontsize=11)
    ax2.grid(True, alpha=0.3)
    ax2.legend(['Total Order Book Depth'], loc='upper right', fontsize=8)

    # === 图3: VWAP 价差 ===
    ax3 = fig.add_subplot(gs[2], sharex=ax1)
    if spread_data:
        spt, spv = zip(*spread_data)
        ax3.fill_between(spt, spv, alpha=0.4, color='#ff9800')
        ax3.plot(spt, spv, color='#ff9800', linewidth=0.8, alpha=0.8)
    ax3.set_ylabel("VWAP Spread", fontsize=10)
    ax3.set_xlabel("Time", fontsize=11)
    ax3.grid(True, alpha=0.3)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    plt.setp(ax3.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)

    if output is None:
        output = f"polymarket_vwmp_chart_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    plt.tight_layout()
    plt.savefig(output, dpi=150, bbox_inches="tight")
    print(f"图表已保存: {output}")


# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polymarket 订单簿 VWMP 分析器")
    parser.add_argument("--days", type=int, default=None, help="分析最近N天")
    parser.add_argument("--chart", action="store_true", help="生成 VWMP 趋势图")
    parser.add_argument("--output", type=str, default=None, help="图表输出路径")
    parser.add_argument("--data-dir", type=str, default="./data", help="数据目录")
    args = parser.parse_args()

    records = load_all_ob(args.data_dir, args.days)
    print(f"加载了 {len(records)} 条订单簿记录")

    if not records:
        print("没有找到 Polymarket 订单簿数据。请先运行 collector.py 采集数据。")
        exit(1)

    # 统计 VWMP 覆盖率
    vwmp_count = sum(1 for r in records if r["vwmp"] is not None)
    print(f"VWMP 可用: {vwmp_count}/{len(records)} ({vwmp_count/len(records)*100:.0f}%)")

    if args.chart:
        generate_chart(records, args.output)
    else:
        stats = analyze(records)
        print_report(stats)
