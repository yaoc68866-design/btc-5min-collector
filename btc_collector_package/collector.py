
#!/usr/bin/env python3
"""
BTC 5min K线 高频采集器 + Polymarket 订单簿采集器
===============================================
部署在新加坡云服务器，24x7 运行

功能:
  1. Binance BTC 价格采集 (3次/秒)
  2. Polymarket BTC Up/Down 订单簿采集 (1次/秒)
  3. 5min K线自动聚合
  4. 数据保存为 CSV (按天分文件)

运行:
  python collector.py            # 前台运行
  nohup python collector.py &    # 后台运行
"""

import requests, csv, os, time, math, json, sys, signal
from datetime import datetime, timezone
from pathlib import Path

# ============================================================
# 配置
# ============================================================
CONFIG = {
    # 数据保存目录
    "data_dir": "./data",

    # BTC 价格源 (新加坡服务器优先用 Binance)
    "btc_price_urls": [
        "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
        "https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT",
        "https://api.binance.com/api/v3/ticker/bookTicker?symbol=BTCUSDT",  # 有 bid/ask
    ],

    # Polymarket API
    "gamma_api": "https://gamma-api.polymarket.com",
    "clob_api": "https://clob.polymarket.com",

    # 采集参数
    "btc_sample_rate": 3,        # BTC 每秒采样
    "poly_sample_interval": 2,   # Polymarket OB 采样间隔(秒)
    "kline_period": 300,         # K线周期 5min (秒)

    # 日志
    "log_file": "./data/collector.log",
}

# ============================================================
# 工具函数
# ============================================================
def log(msg: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] {msg}"
    print(line, flush=True)
    try:
        with open(CONFIG["log_file"], "a") as f:
            f.write(line + "\n")
    except:
        pass

def ensure_dir(path: str):
    Path(path).mkdir(parents=True, exist_ok=True)

def today_str() -> str:
    return datetime.now().strftime("%Y%m%d")

# ============================================================
# BTC 价格采集器
# ============================================================
class BTCCollector:
    """从 Binance/Bybit 采集 BTC 价格"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "BTC-Collector/2.0"})
        self.current_price = 0.0
        self.current_bid = 0.0
        self.current_ask = 0.0

    def fetch(self) -> dict:
        """多源容错获取 BTC 价格"""
        for url in CONFIG["btc_price_urls"]:
            try:
                r = self.session.get(url, timeout=3)
                if not r.ok:
                    continue
                data = r.json()

                result = {"price": 0, "bid": 0, "ask": 0, "source": ""}

                if "api.binance.com" in url:
                    if "bookTicker" in url:
                        result["price"] = (float(data["bidPrice"]) + float(data["askPrice"])) / 2
                        result["bid"] = float(data["bidPrice"])
                        result["ask"] = float(data["askPrice"])
                    else:
                        result["price"] = float(data["price"])
                    result["source"] = "binance"
                elif "bybit" in url:
                    ticker = data["result"]["list"][0]
                    result["price"] = float(ticker["lastPrice"])
                    result["bid"] = float(ticker.get("bid1Price", 0))
                    result["ask"] = float(ticker.get("ask1Price", 0))
                    result["source"] = "bybit"

                if result["price"] > 0:
                    return result
            except:
                continue
        return None

# ============================================================
# Polymarket 采集器
# ============================================================
class PolymarketCollector:
    """采集 BTC Up/Down 市场订单簿"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Poly-Collector/2.0"})
        self.last_market_scan = 0
        self.active_market = None

    def find_btc_market(self) -> dict:
        """找到当前活跃的 BTC 5min 市场"""
        now = int(time.time())
        window = math.floor(now / 300) * 300

        # 也检查 15min
        for tf in ["5m", "15m"]:
            for offset in [0, 1, -1]:
                ts = window + offset * (900 if tf == "15m" else 300)
                slug = f"btc-updown-{tf}-{ts}"
                try:
                    r = self.session.get(
                        f"{CONFIG['gamma_api']}/events",
                        params={"slug": slug},
                        timeout=8
                    )
                    if r.ok:
                        data = r.json()
                        if isinstance(data, list) and data:
                            ev = data[0]
                            if "bitcoin" in ev.get("title", "").lower():
                                mkts = ev.get("markets", [])
                                if mkts:
                                    m = mkts[0]
                                    outcomes = m.get("outcomes", "[]")
                                    clob_ids = m.get("clobTokenIds", "[]")
                                    if isinstance(outcomes, str):
                                        outcomes = json.loads(outcomes)
                                    if isinstance(clob_ids, str):
                                        clob_ids = json.loads(clob_ids)
                                    return {
                                        "title": ev["title"],
                                        "tf": tf,
                                        "outcomes": outcomes,
                                        "clob_ids": clob_ids,
                                        "volume": float(ev.get("volume", 0)),
                                    }
                except:
                    pass
                time.sleep(0.1)
        return None

    def get_order_book(self, token_id: str) -> dict:
        """获取订单簿"""
        try:
            r = self.session.get(
                f"{CONFIG['clob_api']}/book",
                params={"token_id": token_id},
                timeout=5
            )
            if r.ok:
                book = r.json()
                bids = [(float(b["price"]), float(b["size"])) for b in book.get("bids", [])[:5]]
                asks = [(float(a["price"]), float(a["size"])) for a in book.get("asks", [])[:5]]
                return {
                    "best_bid": bids[0][0] if bids else None,
                    "best_ask": asks[0][0] if asks else None,
                    "bid_size": bids[0][1] if bids else 0,
                    "ask_size": asks[0][1] if asks else 0,
                    "bids": bids,
                    "asks": asks,
                }
        except:
            pass
        return None

# ============================================================
# K线聚合器
# ============================================================
class KlineAggregator:
    """实时聚合 5min K线 + 保存"""

    def __init__(self):
        self.open_time = 0
        self.o = self.h = self.l = self.c = 0.0
        self.ticks = 0
        self.kline_count = 0

    def add(self, price: float, ts: float) -> dict:
        """添加一个价格点, 如果K线完成则返回完成的K线"""
        window = math.floor(ts / CONFIG["kline_period"]) * CONFIG["kline_period"]

        completed = None

        if self.open_time == 0:
            self.open_time = window
            self.o = self.h = self.l = self.c = price
            self.ticks = 1
        elif window > self.open_time:
            # 完成当前K线
            completed = self.to_dict()
            self.kline_count += 1
            # 开始新的
            self.open_time = window
            self.o = self.h = self.l = self.c = price
            self.ticks = 1
        else:
            self.h = max(self.h, price)
            self.l = min(self.l, price)
            self.c = price
            self.ticks += 1

        return completed

    def to_dict(self) -> dict:
        change_pct = ((self.c - self.o) / self.o) * 100 if self.o > 0 else 0
        range_pct = ((self.h - self.l) / self.o) * 100 if self.o > 0 else 0
        return {
            "open_time": datetime.fromtimestamp(self.open_time).isoformat(),
            "open": round(self.o, 2),
            "high": round(self.h, 2),
            "low": round(self.l, 2),
            "close": round(self.c, 2),
            "change_pct": round(change_pct, 4),
            "range_pct": round(range_pct, 4),
            "direction": "UP" if self.c >= self.o else "DOWN",
            "ticks": self.ticks,
        }

# ============================================================
# 数据存储
# ============================================================
class DataStore:
    """按天分文件存储数据"""

    def __init__(self):
        ensure_dir(CONFIG["data_dir"])

    def save_ticks(self, ticks: list):
        """保存 BTC tick 数据"""
        fname = f"btc_ticks_{today_str()}.csv"
        fpath = os.path.join(CONFIG["data_dir"], fname)
        is_new = not os.path.exists(fpath)
        with open(fpath, "a", newline="") as f:
            w = csv.writer(f)
            if is_new:
                w.writerow(["timestamp", "datetime", "price", "bid", "ask", "source"])
            w.writerows(ticks)

    def save_kline(self, kline: dict):
        """保存完成的 K 线"""
        fname = f"btc_5min_klines_{today_str()}.csv"
        fpath = os.path.join(CONFIG["data_dir"], fname)
        is_new = not os.path.exists(fpath)
        with open(fpath, "a", newline="") as f:
            w = csv.writer(f)
            if is_new:
                w.writerow(["open_time", "open", "high", "low", "close",
                           "change_pct", "range_pct", "direction", "ticks"])
            w.writerow([kline["open_time"], kline["open"], kline["high"],
                       kline["low"], kline["close"], kline["change_pct"],
                       kline["range_pct"], kline["direction"], kline["ticks"]])

    def save_poly_ob(self, snapshots: list):
        """保存 Polymarket 订单簿快照"""
        fname = f"polymarket_ob_{today_str()}.csv"
        fpath = os.path.join(CONFIG["data_dir"], fname)
        is_new = not os.path.exists(fpath)
        with open(fpath, "a", newline="") as f:
            w = csv.writer(f)
            if is_new:
                w.writerow(["timestamp", "datetime", "token", "market_title",
                           "best_bid", "best_ask", "bid_size", "ask_size",
                           "bids_json", "asks_json"])
            w.writerows(snapshots)

# ============================================================
# 主循环
# ============================================================
class CollectorDaemon:
    """采集器守护进程"""

    def __init__(self):
        self.btc = BTCCollector()
        self.poly = PolymarketCollector()
        self.kline_agg = KlineAggregator()
        self.store = DataStore()
        self.running = True

        # 缓冲区
        self.tick_buffer = []
        self.poly_buffer = []

        # 统计
        self.stats = {"btc_ticks": 0, "klines": 0, "poly_snaps": 0, "errors": 0}

        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        log("收到停止信号，保存数据...")
        self.running = False

    def run(self):
        log("=" * 60)
        log("BTC 5min 采集器启动")
        log(f"数据目录: {os.path.abspath(CONFIG['data_dir'])}")
        log(f"BTC 采样: {CONFIG['btc_sample_rate']}次/秒")
        log(f"Poly OB采样: {CONFIG['poly_sample_interval']}秒间隔")
        log(f"K线周期: {CONFIG['kline_period']}秒 (5分钟)")
        log("=" * 60)

        last_btc_fetch = 0
        last_poly_fetch = 0
        last_status = 0
        last_market_scan = 0

        while self.running:
            now = time.time()

            # ---- BTC 价格采集 ----
            btc_interval = 1.0 / CONFIG["btc_sample_rate"]
            if now - last_btc_fetch >= btc_interval:
                result = self.btc.fetch()
                if result and result["price"] > 0:
                    self.stats["btc_ticks"] += 1
                    price = result["price"]

                    # 记录 tick
                    self.tick_buffer.append([
                        now, datetime.fromtimestamp(now).isoformat(),
                        price, result.get("bid", ""), result.get("ask", ""),
                        result.get("source", ""),
                    ])

                    # 聚合 K 线
                    completed = self.kline_agg.add(price, now)
                    if completed:
                        self.store.save_kline(completed)
                        self.stats["klines"] += 1
                        log(f"K线#{self.stats['klines']}: {completed['direction']} "
                            f"{completed['change_pct']:+.4f}% "
                            f"O:{completed['open']:.0f} C:{completed['close']:.0f}")

                    # 批量写入 tick (每200条)
                    if len(self.tick_buffer) >= 200:
                        self.store.save_ticks(self.tick_buffer)
                        self.tick_buffer.clear()

                else:
                    self.stats["errors"] += 1
                last_btc_fetch = now

            # ---- Polymarket 订单簿采集 ----
            if now - last_poly_fetch >= CONFIG["poly_sample_interval"]:
                # 每5分钟扫描一次新市场
                if now - last_market_scan >= 300:
                    market = self.poly.find_btc_market()
                    if market:
                        self.poly.active_market = market
                        log(f"Poly市场: {market['title']} (Vol:${market['volume']:,.0f})")
                    last_market_scan = now

                if self.poly.active_market:
                    for label, tid in zip(
                        self.poly.active_market["outcomes"],
                        self.poly.active_market["clob_ids"]
                    ):
                        ob = self.poly.get_order_book(tid)
                        if ob:
                            self.stats["poly_snaps"] += 1
                            self.poly_buffer.append([
                                now, datetime.fromtimestamp(now).isoformat(),
                                label, self.poly.active_market["title"],
                                ob["best_bid"], ob["best_ask"],
                                ob["bid_size"], ob["ask_size"],
                                json.dumps(ob["bids"]), json.dumps(ob["asks"]),
                            ])

                # 批量写入 (每50条)
                if len(self.poly_buffer) >= 50:
                    self.store.save_poly_ob(self.poly_buffer)
                    self.poly_buffer.clear()

                last_poly_fetch = now

            # ---- 每30秒状态报告 ----
            if now - last_status >= 30:
                k = self.kline_agg
                if k.open_time > 0:
                    elapsed = now - k.open_time
                    remaining = CONFIG["kline_period"] - elapsed
                    chg = ((k.c - k.o) / k.o) * 100 if k.o > 0 else 0
                    log(f"状态: BTC=${k.c:,.0f} {chg:+.3f}% | "
                        f"K线剩余{remaining:.0f}s | "
                        f"Ticks:{self.stats['btc_ticks']} "
                        f"Klines:{self.stats['klines']} "
                        f"Poly:{self.stats['poly_snaps']} "
                        f"Err:{self.stats['errors']}")
                last_status = now

            # 控制循环速率
            time.sleep(0.05)

        # ---- 退出清理 ----
        if self.tick_buffer:
            self.store.save_ticks(self.tick_buffer)
        if self.poly_buffer:
            self.store.save_poly_ob(self.poly_buffer)

        log(f"采集器已停止。总: {self.stats}")

# ============================================================
if __name__ == "__main__":
    daemon = CollectorDaemon()
    daemon.run()
