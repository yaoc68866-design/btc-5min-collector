#!/usr/bin/env python3
"""
BTC 5min K线 统计分析器
======================
分析采集的 K 线数据，输出统计报告和图表

用法:
  python analyzer.py                    # 分析所有数据
  python analyzer.py --days 7           # 分析最近7天
  python analyzer.py --chart            # 生成图表
"""

import csv, os, json, argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
import numpy as np

# ============================================================
def load_all_klines(data_dir: str = "./data", days: int = None) -> list:
    """加载所有 K 线文件"""
    klines = []
    cutoff = None
    if days:
        cutoff = datetime.now() - timedelta(days=days)

    data_path = Path(data_dir)
    for f in sorted(data_path.glob("btc_5min_klines_*.csv")):
        try:
            with open(f) as fp:
                for row in csv.DictReader(fp):
                    dt = datetime.fromisoformat(row["open_time"])
                    if cutoff and dt < cutoff:
                        continue
                    klines.append({
                        "open_time": dt,
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "change_pct": float(row["change_pct"]),
                        "range_pct": float(row["range_pct"]),
                        "direction": row["direction"],
                        "ticks": int(row["ticks"]),
                    })
        except Exception as e:
            print(f"  [警告] 无法读取 {f.name}: {e}")

    return sorted(klines, key=lambda k: k["open_time"])

def analyze(klines: list) -> dict:
    """统计分析"""
    if not klines:
        return {"error": "无数据"}

    n = len(klines)
    changes = [k["change_pct"] for k in klines]
    ranges = [k["range_pct"] for k in klines]

    up = [c for c in changes if c > 0]
    down = [c for c in changes if c < 0]

    mean = np.mean(changes)
    std = np.std(changes)

    # 自相关 lag1
    if n > 1:
        autocorr = np.corrcoef(changes[:-1], changes[1:])[0, 1]
    else:
        autocorr = 0

    # 时段分析
    hour_stats = defaultdict(lambda: {"up": 0, "down": 0, "total": 0})
    for k in klines:
        h = k["open_time"].hour
        hour_stats[h]["total"] += 1
        if k["direction"] == "UP":
            hour_stats[h]["up"] += 1
        else:
            hour_stats[h]["down"] += 1

    return {
        "样本数": n,
        "时间范围": f"{klines[0]['open_time']} ~ {klines[-1]['open_time']}",
        "上涨次数": len(up),
        "下跌次数": len(down),
        "上涨概率_%": round(len(up) / n * 100, 1),
        "下跌概率_%": round(len(down) / n * 100, 1),
        "平均涨跌幅_%": round(mean, 4),
        "平均绝对涨跌_%": round(np.mean(np.abs(changes)), 4),
        "标准差_%": round(std, 4),
        "年化波动率_%": round(std * np.sqrt(365 * 24 * 12), 2),
        "平均振幅_%": round(np.mean(ranges), 4),
        "最大涨幅_%": round(max(changes), 4),
        "最大跌幅_%": round(min(changes), 4),
        "自相关_lag1": round(autocorr, 4),
        "分位数": {
            "P10": round(np.percentile(changes, 10), 4),
            "P25": round(np.percentile(changes, 25), 4),
            "P50": round(np.percentile(changes, 50), 4),
            "P75": round(np.percentile(changes, 75), 4),
            "P90": round(np.percentile(changes, 90), 4),
            "P95": round(np.percentile(changes, 95), 4),
            "P99": round(np.percentile(changes, 99), 4),
        },
        "时段分析": {
            f"{h:02d}:00": {
                "涨率%": round(s["up"] / s["total"] * 100, 1) if s["total"] else 0,
                "样本": s["total"],
            }
            for h, s in sorted(hour_stats.items())
        },
    }

def print_report(stats: dict):
    """打印统计报告"""
    print("\n" + "=" * 60)
    print("  BTC 5min K线 统计分析报告")
    print("=" * 60)

    for k, v in stats.items():
        if k == "分位数":
            print(f"\n  {k}:")
            for pk, pv in v.items():
                print(f"    {pk}: {pv}%")
        elif k == "时段分析":
            print(f"\n  {k}:")
            for h, s in v.items():
                bar = "█" * int(s["涨率%"] / 100 * 20)
                print(f"    {h}: {s['涨率%']:>5.1f}% {bar} ({s['样本']}根)")
        elif k != "时间范围":
            print(f"  {k}: {v}")

    print(f"\n  时间范围: {stats.get('时间范围', 'N/A')}")
    print("=" * 60)

    # 交易建议
    up_pct = stats.get("上涨概率_%", 50)
    avg_abs = stats.get("平均绝对涨跌_%", 0.15)
    print(f"""
  策略建议:
  ┌─────────────────────────────────────────────┐
  │ 5min Up 概率: {up_pct}%                            │
  │ 平均 |变动|: {avg_abs:.3f}%                          │
  │                                             │
  │ 如果 Polymarket 定价:                        │
  │   Up < {up_pct - 5:.0f}%  → 买入 Up (正期望)         │
  │   Up > {up_pct + 5:.0f}%  → 买入 Down (正期望)       │
  │   定价在 [{up_pct - 5:.0f}-{up_pct + 5:.0f}] → 不交易          │
  └─────────────────────────────────────────────┘
""")

def generate_chart(klines: list, output: str = None):
    """生成 K 线图"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        print("[错误] 需要 matplotlib: pip install matplotlib")
        return

    if not klines:
        print("无数据可画图")
        return

    # 取最近288根 (24小时)
    klines = klines[-288:] if len(klines) > 288 else klines

    times = [k["open_time"] for k in klines]
    opens = [k["open"] for k in klines]
    highs = [k["high"] for k in klines]
    lows = [k["low"] for k in klines]
    closes = [k["close"] for k in klines]

    # 归一化 0-100
    all_p = opens + highs + lows + closes
    pmin, pmax = min(all_p), max(all_p)
    prange = pmax - pmin

    def norm(p):
        return (p - pmin) / prange * 100

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(20, 10),
                                     gridspec_kw={"height_ratios": [3, 1]})

    colors = ['#26a69a' if closes[i] >= opens[i] else '#ef5350' for i in range(len(klines))]

    # K 线
    bw = 0.0008
    for i, k in enumerate(klines):
        t = mdates.date2num(k["open_time"])
        o, h, l, c = norm(k["open"]), norm(k["high"]), norm(k["low"]), norm(k["close"])
        ax1.plot([t, t], [l, h], color=colors[i], linewidth=1, alpha=0.8)
        body_bottom = o if c >= o else c
        body_height = max(c - o, o - c, 0.001)
        from matplotlib.patches import Rectangle
        ax1.add_patch(Rectangle((t - bw/2, body_bottom), bw, body_height,
                                facecolor=colors[i], edgecolor="none", alpha=0.9))

    ax1.set_ylabel("Normalized Price (0-100)")
    ax1.set_ylim(-5, 105)
    ax1.grid(True, alpha=0.3)
    ax1.set_title(f"BTC 5min K-line  |  {klines[0]['open_time']} ~ {klines[-1]['open_time']}  |  {len(klines)} bars")

    # 成交量
    vols = [k["ticks"] for k in klines]
    ax2.bar([mdates.date2num(k["open_time"]) for k in klines], vols, width=bw, color=colors, alpha=0.7)
    ax2.set_ylabel("Ticks")
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha="right")

    if output is None:
        output = f"btc_5min_chart_{datetime.now().strftime('%Y%m%d')}.png"
    plt.tight_layout()
    plt.savefig(output, dpi=120)
    print(f"图表已保存: {output}")

# ============================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=None, help="分析最近N天")
    parser.add_argument("--chart", action="store_true", help="生成图表")
    parser.add_argument("--output", type=str, default=None, help="图表输出路径")
    parser.add_argument("--data-dir", type=str, default="./data", help="数据目录")
    args = parser.parse_args()

    klines = load_all_klines(args.data_dir, args.days)
    print(f"加载了 {len(klines)} 根 K 线")

    if args.chart:
        generate_chart(klines, args.output)
    else:
        stats = analyze(klines)
        print_report(stats)
