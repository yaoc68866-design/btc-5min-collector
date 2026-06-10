"""
BTC 价格 K 线图 (0-100 归一化, 秒级时间轴)
===========================================
- 横坐标: 时间 HH:MM:SS
- 纵坐标: 0-100 (价格归一化, 模拟 Polymarket 买卖单价格)
- K 线周期: 10 秒聚合
- 底层: 高频 tick 数据 (~3 ticks/秒)
"""

import csv
import os
import math
from datetime import datetime, timedelta
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as ticker
import matplotlib.font_manager as fm
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
import numpy as np

# ==== 中文字体配置 ====
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# ============================================================
# 数据加载
# ============================================================
def load_ticks(filepath):
    ticks = []
    with open(filepath, "r") as f:
        for row in csv.DictReader(f):
            ticks.append({
                "time": datetime.fromisoformat(row["datetime"]),
                "price": float(row["price"]),
            })
    return ticks

def load_klines(filepath):
    klines = []
    seen = set()
    with open(filepath, "r") as f:
        for row in csv.DictReader(f):
            key = row["open_time"]
            if key in seen:
                continue
            seen.add(key)
            klines.append({
                "open_time": datetime.fromisoformat(row["open_time"]),
                "close_time": datetime.fromisoformat(row["close_time"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "change_pct": float(row["change_pct"]),
                "direction": row["direction"],
                "ticks": int(row["ticks"]),
            })
    return klines

def ticks_to_klines(ticks, period_seconds=10):
    if not ticks:
        return []
    klines = []
    ws = math.floor(ticks[0]["time"].timestamp() / period_seconds) * period_seconds
    o = h = l = c = ticks[0]["price"]
    tc = 0
    for tick in ticks:
        ts = tick["time"].timestamp()
        w = math.floor(ts / period_seconds) * period_seconds
        if w > ws:
            klines.append({"time": datetime.fromtimestamp(ws), "open": o, "high": h, "low": l, "close": c, "ticks": tc})
            ws = w
            o = h = l = c = tick["price"]
            tc = 1
        else:
            h = max(h, tick["price"])
            l = min(l, tick["price"])
            c = tick["price"]
            tc += 1
    if tc > 0:
        klines.append({"time": datetime.fromtimestamp(ws), "open": o, "high": h, "low": l, "close": c, "ticks": tc})
    return klines

# ============================================================
# 图表绘制
# ============================================================
def plot_micro_klines(klines_10s, klines_5min, output="btc_0_100_chart.png"):
    if not klines_10s:
        print("无数据")
        return

    # 归一化: 价格 -> 0-100
    all_p = []
    for k in klines_10s:
        all_p.extend([k["open"], k["high"], k["low"], k["close"]])
    pmin, pmax = min(all_p), max(all_p)
    prange = pmax - pmin

    def norm(price):
        return (price - pmin) / prange * 100

    # 创建图表
    fig = plt.figure(figsize=(28, 14))
    gs = fig.add_gridspec(2, 1, height_ratios=[4, 1], hspace=0.05)
    ax_main = fig.add_subplot(gs[0])
    ax_vol = fig.add_subplot(gs[1], sharex=ax_main)

    t0 = klines_10s[0]["time"]
    t1 = klines_10s[-1]["time"]
    fig.suptitle(
        f"BTC 价格 K 线图 (0-100 归一化)  |  "
        f"{t0.strftime('%Y-%m-%d %H:%M:%S')} -> {t1.strftime('%H:%M:%S')}  |  "
        f"周期: 10秒 | {len(klines_10s)} 根 K 线  |  "
        f"实际: ${pmin:,.0f} - ${pmax:,.0f}",
        fontsize=14, fontweight="bold",
    )

    # 绘制 10s K 线
    bw = 3.5 / 86400
    for k in klines_10s:
        t = mdates.date2num(k["time"])
        o, h, l, c = norm(k["open"]), norm(k["high"]), norm(k["low"]), norm(k["close"])
        color = "#26a69a" if c >= o else "#ef5350"
        body_bottom = o if c >= o else c
        body_height = max(c - o, 0.001) if c >= o else max(o - c, 0.001)
        ax_main.plot([t, t], [l, h], color=color, linewidth=0.5, alpha=0.7)
        if body_height > 0.005:
            ax_main.add_patch(Rectangle((t - bw/2, body_bottom), bw, body_height,
                               facecolor=color, edgecolor="none", alpha=0.85))

    # 5min 分界线
    for k5 in klines_5min:
        t = mdates.date2num(k5["open_time"])
        ax_main.axvline(x=t, color="#FF9800", linewidth=1.5, linestyle="--", alpha=0.5)
        lbl = f"UP {k5['change_pct']:+.3f}%" if k5["direction"] == "UP" else f"DOWN {k5['change_pct']:+.3f}%"
        ax_main.annotate(lbl, xy=(t, 97), fontsize=7,
                        color="#26a69a" if k5["direction"] == "UP" else "#ef5350",
                        ha="left", fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.7))

    # 中线 & 坐标轴
    ax_main.axhline(y=50, color="#9E9E9E", linewidth=0.5, linestyle="--", alpha=0.4)
    ax_main.set_ylabel("Normalized Price (0-100)", fontsize=11)
    ax_main.set_ylim(-5, 108)
    ax_main.yaxis.set_major_locator(ticker.MultipleLocator(10))
    ax_main.grid(True, alpha=0.2, linestyle="--")

    # 右侧 Y 轴: 实际价格
    ax_price = ax_main.twinx()
    ax_price.set_ylabel("BTC Price (USD)", fontsize=11)
    ax_price.set_ylim(pmin - prange*0.05, pmax + prange*0.08)
    ax_price.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))

    # 图例
    ax_main.legend(handles=[
        Line2D([0], [0], color="#26a69a", lw=3, label="UP (Close>=Open)"),
        Line2D([0], [0], color="#ef5350", lw=3, label="DOWN (Close<Open)"),
        Line2D([0], [0], color="#FF9800", lw=1.5, linestyle="--", label="5min Boundary"),
    ], loc="upper right", fontsize=9)

    # 成交量
    times_num = [mdates.date2num(k["time"]) for k in klines_10s]
    vols = [k["ticks"] for k in klines_10s]
    colors_vol = ["#26a69a" if k["close"] >= k["open"] else "#ef5350" for k in klines_10s]
    ax_vol.bar(times_num, vols, width=bw, color=colors_vol, alpha=0.6)
    ax_vol.set_ylabel("Ticks", fontsize=10)
    ax_vol.grid(True, alpha=0.2, linestyle="--")
    for k5 in klines_5min:
        ax_vol.axvline(x=mdates.date2num(k5["open_time"]), color="#FF9800", linewidth=1, linestyle="--", alpha=0.4)

    # X 轴
    ax_vol.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    total_s = (t1 - t0).total_seconds()
    if total_s < 600:
        ax_vol.xaxis.set_major_locator(mdates.SecondLocator(interval=60))
    elif total_s < 3600:
        ax_vol.xaxis.set_major_locator(mdates.MinuteLocator(interval=2))
    else:
        ax_vol.xaxis.set_major_locator(mdates.MinuteLocator(interval=5))
    ax_vol.set_xlabel("Time (HH:MM:SS)", fontsize=11)
    plt.setp(ax_vol.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)
    ax_vol.set_xlim(mdates.date2num(t0) - 10/86400, mdates.date2num(t1) + 10/86400)

    # 统计框
    ups = [k for k in klines_5min if k["direction"] == "UP"]
    downs = [k for k in klines_5min if k["direction"] == "DOWN"]
    avg_chg = np.mean([abs(k["change_pct"]) for k in klines_5min]) if klines_5min else 0

    stats = (
        f"Period: {t0.strftime('%H:%M:%S')} -> {t1.strftime('%H:%M:%S')}\n"
        f"10s K-lines: {len(klines_10s)}  |  5min K-lines: {len(klines_5min)}\n"
        f"5min UP: {len(ups)} ({len(ups)/len(klines_5min)*100:.0f}%)  "
        f"DOWN: {len(downs)} ({len(downs)/len(klines_5min)*100:.0f}%)\n"
        f"Avg |change|: {avg_chg:.3f}%  |  Price: ${pmin:,.0f} - ${pmax:,.0f}"
    )
    ax_main.text(0.015, 0.985, stats, transform=ax_main.transAxes,
                fontsize=9, verticalalignment="top", fontfamily="monospace",
                bbox=dict(boxstyle="round,pad=0.5", facecolor="white", alpha=0.88, edgecolor="gray"))

    plt.tight_layout()
    os.makedirs(os.path.dirname(output) if os.path.dirname(output) else ".", exist_ok=True)
    plt.savefig(output, dpi=150, bbox_inches="tight")
    print(f"Done: {output}")
    return output

# ============================================================
if __name__ == "__main__":
    BASE = "C:/Users/33487/btc_data"
    ticks_file = os.path.join(BASE, "btc_ticks.csv")
    klines_file = os.path.join(BASE, "btc_5min_klines.csv")
    out_file = os.path.join(BASE, "btc_0_100_chart.png")

    if not os.path.exists(ticks_file):
        print(f"File not found: {ticks_file}")
        exit(1)

    print(f"Loading ticks...")
    ticks = load_ticks(ticks_file)
    print(f"  {len(ticks)} ticks")

    print(f"Loading 5min K-lines...")
    klines_5min = load_klines(klines_file) if os.path.exists(klines_file) else []
    print(f"  {len(klines_5min)} K-lines")

    print(f"Aggregating 10s K-lines...")
    klines_10s = ticks_to_klines(ticks, period_seconds=10)
    print(f"  {len(klines_10s)} 10s K-lines")

    plot_micro_klines(klines_10s, klines_5min, out_file)
