"""
Polymarket BTC 订单簿 K 线图
============================
- 纵坐标: 0-100 (Polymarket token 价格, 1点=1美分, 代表概率%)
- 横坐标: 时间 HH:MM:SS
- 每秒采集一次订单簿快照
- 聚合为 5 秒 K 线
"""

import requests
import json
import time
import math
import os
import csv
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as ticker
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D
import numpy as np

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# ============================================================
# 配置
# ============================================================
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA_DIR = "C:/Users/33487/btc_data"
OB_TICKS_FILE = os.path.join(DATA_DIR, "polymarket_ob_ticks.csv")

# ============================================================
# 市场扫描
# ============================================================
def find_active_btc_market(session):
    """找到当前活跃的 BTC 5min 市场"""
    now = int(time.time())
    current_window = math.floor(now / 300) * 300

    # 优先当前窗口，再找相邻窗口
    for offset in [0, 1, -1, 2, -2, 3, -3, 4, -4]:
        ts = current_window + offset * 300
        for tf in ['5m', '15m']:
            slug = f'btc-updown-{tf}-{ts}'
            try:
                r = session.get(f'{GAMMA}/events', params={'slug': slug}, timeout=8)
                if r.ok:
                    data = r.json()
                    if isinstance(data, list) and len(data) > 0:
                        ev = data[0]
                        title = ev.get('title', '')
                        if 'bitcoin' in title.lower() or 'btc' in title.lower():
                            mkts = ev.get('markets', [])
                            if mkts:
                                m = mkts[0]
                                outcomes = m.get('outcomes', '[]')
                                clob_ids = m.get('clobTokenIds', '[]')
                                if isinstance(outcomes, str): outcomes = json.loads(outcomes)
                                if isinstance(clob_ids, str): clob_ids = json.loads(clob_ids)
                                vol = float(ev.get('volume', 0))
                                # 只选有流动性的市场
                                if vol >= 0:
                                    return {
                                        'title': title,
                                        'slug': slug,
                                        'tf': tf,
                                        'outcomes': outcomes,
                                        'clob_ids': clob_ids,
                                        'end_time': ev.get('endDateIso', ''),
                                        'volume': vol,
                                    }
            except:
                pass
            time.sleep(0.1)
    return None

def fetch_order_book(session, token_id):
    """获取订单簿"""
    try:
        r = session.get(f'{CLOB}/book', params={'token_id': token_id}, timeout=5)
        if r.ok:
            book = r.json()
            bids = [(float(b['price']) * 100, float(b['size']))
                    for b in book.get('bids', []) if float(b['price']) > 0]
            asks = [(float(a['price']) * 100, float(a['size']))
                    for a in book.get('asks', []) if float(a['price']) < 1]
            best_bid = bids[0][0] if bids else None
            best_ask = asks[0][0] if asks else None
            mid = (best_bid + best_ask) / 2 if best_bid and best_ask else (best_bid or best_ask or 50)
            return {
                'best_bid': best_bid,
                'best_ask': best_ask,
                'mid': mid,
                'spread': (best_ask - best_bid) if best_bid and best_ask else None,
                'bid_size': bids[0][1] if bids else 0,
                'ask_size': asks[0][1] if asks else 0,
                'bids': bids[:5],
                'asks': asks[:5],
            }
    except:
        pass
    return None

# ============================================================
# 采集 + 绘图
# ============================================================
def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # 初始化 CSV
    if not os.path.exists(OB_TICKS_FILE):
        with open(OB_TICKS_FILE, 'w', newline='') as f:
            csv.writer(f).writerow([
                'timestamp', 'datetime', 'token', 'best_bid', 'best_ask',
                'mid', 'spread', 'bid_size', 'ask_size'
            ])

    session = requests.Session()
    session.headers.update({'User-Agent': 'PolyOB-Chart/1.0'})

    print("Scanning for active BTC market...")
    market = find_active_btc_market(session)

    if not market:
        print("No active BTC market found!")
        return

    print(f"Market: {market['title']}")
    print(f"Volume: ${market['volume']:,.0f}")
    print(f"Tokens: {market['clob_ids']}")
    print(f"Outcomes: {market['outcomes']}")
    print()

    # 采集参数
    duration = 300  # 5 分钟
    interval = 1.0  # 1 秒一次
    print(f"Collecting order book every {interval}s for {duration}s...")
    print()

    start_time = time.time()
    snapshots_up = []
    snapshots_down = []
    tick_buffer = []
    last_print = 0

    while time.time() - start_time < duration:
        t = time.time()

        for label, tid in zip(market['outcomes'], market['clob_ids']):
            ob = fetch_order_book(session, tid)
            if ob:
                snap = {
                    'time': t,
                    'label': label,
                    'best_bid': ob['best_bid'],
                    'best_ask': ob['best_ask'],
                    'mid': ob['mid'],
                    'spread': ob['spread'],
                    'bid_size': ob['bid_size'],
                    'ask_size': ob['ask_size'],
                }
                if label == 'Up':
                    snapshots_up.append(snap)
                else:
                    snapshots_down.append(snap)

                tick_buffer.append([
                    t, datetime.fromtimestamp(t).isoformat(), label,
                    ob['best_bid'], ob['best_ask'], ob['mid'],
                    ob['spread'], ob['bid_size'], ob['ask_size'],
                ])

        # 每 50 条批量写入
        if len(tick_buffer) >= 50:
            with open(OB_TICKS_FILE, 'a', newline='') as f:
                csv.writer(f).writerows(tick_buffer)
            tick_buffer.clear()

        # 每秒打印状态
        if time.time() - last_print >= 1.0:
            last_print = time.time()
            elapsed = time.time() - start_time
            parts = []
            if snapshots_up:
                u = snapshots_up[-1]
                parts.append(f"UP: bid={u['best_bid'] or 'N/A':>5} ask={u['best_ask'] or 'N/A':>5} mid={u['mid']:5.1f}")
            if snapshots_down:
                d = snapshots_down[-1]
                parts.append(f"DOWN: bid={d['best_bid'] or 'N/A':>5} ask={d['best_ask'] or 'N/A':>5} mid={d['mid']:5.1f}")
            if parts:
                print(f"\r[{elapsed:5.0f}s] {' | '.join(parts)}", end='', flush=True)

        time.sleep(max(0, interval - (time.time() - t)))

    # 保存剩余
    if tick_buffer:
        with open(OB_TICKS_FILE, 'a', newline='') as f:
            csv.writer(f).writerows(tick_buffer)

    print(f"\n\nCollected {len(snapshots_up)} UP + {len(snapshots_down)} DOWN snapshots")
    print("Generating chart...")

    # ============================================================
    # 绘图
    # ============================================================
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(24, 12), sharex=True)

    fig.suptitle(
        f"Polymarket BTC {market['tf']} Order Book  |  {market['title']}  |  Vol: ${market['volume']:,.0f}",
        fontsize=14, fontweight='bold',
    )

    def plot_token(ax, snaps, token_name, color_up, color_down):
        times = [s['time'] for s in snaps]
        times_num = mdates.date2num([datetime.fromtimestamp(t) for t in times])

        # mid price line
        mids = [s['mid'] for s in snaps]
        ax.plot(times_num, mids, color='#333333', linewidth=1, alpha=0.7, label='Mid Price')

        # bid/ask band
        bids = [s['best_bid'] if s['best_bid'] else None for s in snaps]
        asks = [s['best_ask'] if s['best_ask'] else None for s in snaps]
        if any(b is not None for b in bids):
            ax.plot(times_num, bids, color=color_up, linewidth=1.5, alpha=0.8, label='Best Bid')
        if any(a is not None for a in asks):
            ax.plot(times_num, asks, color=color_down, linewidth=1.5, alpha=0.8, label='Best Ask')

        # fill spread
        ax.fill_between(times_num, bids, asks, alpha=0.1, color='#666666')

        ax.set_ylabel(f'{token_name} Price (0-100)', fontsize=11)
        ax.set_ylim(-5, 105)
        ax.yaxis.set_major_locator(ticker.MultipleLocator(10))
        ax.grid(True, alpha=0.2, linestyle='--')
        ax.legend(loc='upper right', fontsize=9)
        ax.axhline(y=50, color='#999', linewidth=0.5, linestyle='--', alpha=0.4)

        # horizontal reference lines
        for level in [0, 25, 75, 100]:
            ax.axhline(y=level, color='#ddd', linewidth=0.3, alpha=0.5)

        # Stats box
        valid_mids = [m for m in mids if m is not None]
        if valid_mids:
            stats = (
                f"Snapshots: {len(snaps)}\n"
                f"Mid: mean={np.mean(valid_mids):.1f}  "
                f"min={np.min(valid_mids):.1f}  max={np.max(valid_mids):.1f}\n"
                f"Range: {np.max(valid_mids)-np.min(valid_mids):.1f}"
            )
            ax.text(0.015, 0.985, stats, transform=ax.transAxes,
                    fontsize=8, verticalalignment='top', fontfamily='monospace',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.85))

    plot_token(ax1, snapshots_up, 'UP', '#26a69a', '#ef5350')
    plot_token(ax2, snapshots_down, 'DOWN', '#26a69a', '#ef5350')

    # X axis
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    ax2.xaxis.set_major_locator(mdates.SecondLocator(interval=30))
    ax2.set_xlabel('Time (HH:MM:SS)', fontsize=11)
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=30, ha='right', fontsize=8)

    out_path = os.path.join(DATA_DIR, 'polymarket_ob_chart.png')
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f"Chart saved: {out_path}")

    # 缩略版
    from PIL import Image
    img = Image.open(out_path)
    w, h = img.size
    img_small = img.resize((w//2, h//2), Image.LANCZOS)
    small_path = os.path.join(DATA_DIR, 'polymarket_ob_chart_small.png')
    img_small.save(small_path)
    print(f"Small version: {small_path}")

if __name__ == '__main__':
    main()
