"""
BTC 5min K线 长期采集器（简化版）
===============================
每秒 3 次采样，5 分钟聚合一根 K 线
持续运行，数据保存到 btc_data/

运行方式:
  python btc_5min_collector_daemon.py

按 Ctrl+C 停止
"""

import requests, csv, os, time, math, json, sys
from datetime import datetime
from collections import deque

# === 配置 ===
SAMPLE_RATE = 3          # 每秒采样次数
KLINE_PERIOD = 300       # 5 分钟
DATA_DIR = "btc_data"
TICKS_FILE = os.path.join(DATA_DIR, "btc_ticks.csv")
KLINES_FILE = os.path.join(DATA_DIR, "btc_5min_klines.csv")

PRICE_URLS = [
    "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
    "https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT",
]

def fetch_price(session):
    """获取 BTC 价格（多源容错）"""
    for url in PRICE_URLS:
        try:
            r = session.get(url, timeout=2)
            if not r.ok: continue
            data = r.json()
            if "binance" in url:
                return float(data["price"])
            if "bybit" in url:
                return float(data["result"]["list"][0]["lastPrice"])
        except:
            continue
    return None

def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    print("""
╔══════════════════════════════════════════════════════════╗
║   BTC 5min K线 数据采集器（长期运行版）                    ║
║   采样: 3次/秒 | K线: 5分钟                               ║
║   按 Ctrl+C 停止                                          ║
╚══════════════════════════════════════════════════════════╝
    """)

    session = requests.Session()
    session.headers.update({"User-Agent": "BTC-Collector/1.0"})

    # 初始化文件（如不存在则写表头）
    if not os.path.exists(TICKS_FILE):
        with open(TICKS_FILE, "w", newline="") as f:
            csv.writer(f).writerow(["timestamp", "datetime", "price"])

    if not os.path.exists(KLINES_FILE):
        with open(KLINES_FILE, "w", newline="") as f:
            csv.writer(f).writerow([
                "open_time", "close_time", "open", "high", "low", "close",
                "change_pct", "range_pct", "direction", "ticks"
            ])

    # === 状态变量 ===
    kline_open_time = 0
    kline_o = kline_h = kline_l = kline_c = 0.0
    kline_ticks = 0
    last_price = 0.0

    tick_buffer = []
    tick_count = 0
    kline_count = 0
    start_time = time.time()
    last_status = start_time

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始采集...")
    print(f"[提示] 每 5 分钟生成一根 K 线\n")

    try:
        while True:
            loop_start = time.time()

            # 采集价格
            price = fetch_price(session)
            if price is None:
                time.sleep(0.1)
                continue

            now = time.time()
            tick_count += 1

            # 保存 tick（批量写入）
            tick_buffer.append((now, datetime.now().isoformat(), price))
            if len(tick_buffer) >= 100:
                with open(TICKS_FILE, "a", newline="") as f:
                    csv.writer(f).writerows(tick_buffer)
                tick_buffer.clear()

            # === K 线聚合 ===
            window_start = math.floor(now / KLINE_PERIOD) * KLINE_PERIOD

            if kline_open_time == 0:
                # 第一根 K 线
                kline_open_time = window_start
                kline_o = kline_h = kline_l = kline_c = price
                kline_ticks = 1

            elif window_start > kline_open_time:
                # 当前 K 线完成，保存
                change_pct = ((kline_c - kline_o) / kline_o) * 100 if kline_o > 0 else 0
                range_pct = ((kline_h - kline_l) / kline_o) * 100 if kline_o > 0 else 0
                direction = "UP" if kline_c >= kline_o else "DOWN"

                with open(KLINES_FILE, "a", newline="") as f:
                    csv.writer(f).writerow([
                        datetime.fromtimestamp(kline_open_time).isoformat(),
                        datetime.fromtimestamp(kline_open_time + KLINE_PERIOD).isoformat(),
                        round(kline_o, 2),
                        round(kline_h, 2),
                        round(kline_l, 2),
                        round(kline_c, 2),
                        round(change_pct, 4),
                        round(range_pct, 4),
                        direction,
                        kline_ticks,
                    ])

                kline_count += 1
                print(f"\n[{datetime.fromtimestamp(kline_open_time).strftime('%H:%M')}] "
                      f"K线#{kline_count}: {direction} {change_pct:+.4f}% "
                      f"O:{kline_o:.0f} H:{kline_h:.0f} L:{kline_l:.0f} C:{kline_c:.0f} "
                      f"振幅:{range_pct:.3f}% | 累计{tick_count}ticks")

                # 开始新 K 线
                kline_open_time = window_start
                kline_o = price
                kline_h = price
                kline_l = price
                kline_c = price
                kline_ticks = 1

            else:
                # 更新当前 K 线
                kline_h = max(kline_h, price)
                kline_l = min(kline_l, price)
                kline_c = price
                kline_ticks += 1

            last_price = price

            # 每秒显示状态
            if time.time() - last_status >= 1.0:
                last_status = time.time()
                elapsed = time.time() - kline_open_time
                remaining = KLINE_PERIOD - elapsed
                bar_len = 30
                bar_fill = int(elapsed / KLINE_PERIOD * bar_len)
                bar = "█" * bar_fill + "░" * (bar_len - bar_fill)
                dir_sym = "+" if kline_c >= kline_o else "-"

                print(f"\r[{bar}] {dir_sym} "
                      f"O:{kline_o:,.0f} C:{kline_c:,.0f} "
                      f"{(kline_c-kline_o)/kline_o*100:+.3f}% "
                      f"| {remaining:.0f}s | T:{tick_count} K:{kline_count}",
                      end="", flush=True)

            # 控制采样率
            elapsed = time.time() - loop_start
            sleep_time = 1.0 / SAMPLE_RATE - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        # 保存缓冲数据
        if tick_buffer:
            with open(TICKS_FILE, "a", newline="") as f:
                csv.writer(f).writerows(tick_buffer)

        print(f"\n\n[停止] 共采集 {tick_count} ticks, {kline_count} K线")
        print(f"[数据] {TICKS_FILE}")
        print(f"[数据] {KLINES_FILE}")
        print(f"[分析] 运行: python btc_5min_analyzer.py")

if __name__ == "__main__":
    main()
