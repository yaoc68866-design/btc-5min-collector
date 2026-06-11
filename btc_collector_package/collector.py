#!/usr/bin/env python3
"""
Polymarket BTC Up/Down 订单簿采集器
==================================
部署在新加坡云服务器，24x7 运行

功能:
  1. Polymarket BTC Up/Down 订单簿采集
  2. 自动发现当前活跃市场 (5min / 15min)
  3. 数据保存为 CSV (按天分文件)

运行:
  python collector.py            # 前台运行
  nohup python collector.py &    # 后台运行
"""

import csv, os, time, math, json, signal, requests
from datetime import datetime
from pathlib import Path

# ============================================================
# 配置
# ============================================================
CONFIG = {
    # 数据保存目录
    "data_dir": "./data",

    # Polymarket API
    "gamma_api": "https://gamma-api.polymarket.com",
    "clob_api": "https://clob.polymarket.com",

    # 采集参数
    "poly_sample_interval": 1,   # Polymarket OB 采样间隔(秒)

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
# Polymarket 采集器
# ============================================================
class PolymarketCollector:
    """采集 BTC Up/Down 市场订单簿"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Poly-Collector/3.0"})
        self.last_market_scan = 0
        self.active_market = None

    def find_btc_market(self) -> dict:
        """找到当前活跃的 BTC 5min/15min 市场（过滤已结算/无流动性的）"""
        now = int(time.time())
        window = math.floor(now / 300) * 300

        for tf in ["5m", "15m"]:
            tf_sec = 900 if tf == "15m" else 300
            # 搜索前后各 6 个窗口
            for offset in range(-6, 7):
                ts = window + offset * tf_sec
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
                            if "bitcoin" not in ev.get("title", "").lower():
                                continue
                            if ev.get("closed"):
                                continue  # 已结算，跳过
                            mkts = ev.get("markets", [])
                            if not mkts:
                                continue
                            m = mkts[0]
                            outcomes = m.get("outcomes", "[]")
                            clob_ids = m.get("clobTokenIds", "[]")
                            if isinstance(outcomes, str):
                                outcomes = json.loads(outcomes)
                            if isinstance(clob_ids, str):
                                clob_ids = json.loads(clob_ids)
                            if not clob_ids:
                                continue

                            # 检查订单簿是否活跃（过滤已归零/无流动性的）
                            active = True
                            ob_details = []
                            for tid in clob_ids:
                                ob = self.get_order_book(tid)
                                if ob and ob["best_bid"] is not None and ob["best_ask"] is not None:
                                    mid = (ob["best_bid"] + ob["best_ask"]) / 2
                                    spread = ob["best_ask"] - ob["best_bid"]
                                    ob_details.append(f"mid={mid:.2f} spread={spread:.2f}")
                                    # 活跃市场: mid不在极端(0或1), spread < 0.98
                                    if 0.01 <= mid <= 0.99 and spread <= 0.98:
                                        pass  # 活跃
                                    else:
                                        active = False
                                        break
                                else:
                                    active = False
                                    break

                            log(f"  扫描市场: {ev['title']} closed={ev.get('closed')} {'活跃' if active else '跳过'} ({', '.join(ob_details)})")

                            if active:
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
                bids = [(float(b["price"]), float(b["size"])) for b in book.get("bids", [])[:10]]
                asks = [(float(a["price"]), float(a["size"])) for a in book.get("asks", [])[:10]]
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
# 数据存储
# ============================================================
class DataStore:
    """按天分文件存储 Polymarket 订单簿数据"""

    def __init__(self):
        ensure_dir(CONFIG["data_dir"])

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
    """Polymarket 订单簿采集守护进程"""

    def __init__(self):
        self.poly = PolymarketCollector()
        self.store = DataStore()
        self.running = True

        # 缓冲区
        self.poly_buffer = []

        # 统计
        self.stats = {"poly_snaps": 0, "market_scans": 0, "errors": 0}

        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _shutdown(self, signum, frame):
        log("收到停止信号，保存数据...")
        self.running = False

    def run(self):
        log("=" * 60)
        log("Polymarket BTC Up/Down 订单簿采集器启动")
        log(f"数据目录: {os.path.abspath(CONFIG['data_dir'])}")
        log(f"Polymarket OB 采样间隔: {CONFIG['poly_sample_interval']}秒")
        log("=" * 60)

        last_poly_fetch = 0
        last_status = 0
        last_market_scan = 0

        while self.running:
            now = time.time()

            # ---- Polymarket 订单簿采集 ----
            if now - last_poly_fetch >= CONFIG["poly_sample_interval"]:
                # 每5分钟扫描一次新市场
                if now - last_market_scan >= 300:
                    market = self.poly.find_btc_market()
                    if market:
                        self.poly.active_market = market
                        self.stats["market_scans"] += 1
                        log(f"发现市场: {market['title']} (Vol:${market['volume']:,.0f} | TF:{market['tf']})")
                    else:
                        self.stats["errors"] += 1
                        log("警告: 未找到活跃的BTC市场")
                    last_market_scan = now

                if self.poly.active_market:
                    # 分别获取 Up 和 Down 的订单簿
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
                        else:
                            self.stats["errors"] += 1

                # 批量写入 (每50条)
                if len(self.poly_buffer) >= 50:
                    self.store.save_poly_ob(self.poly_buffer)
                    self.poly_buffer.clear()

                last_poly_fetch = now

            # ---- 每30秒状态报告 ----
            if now - last_status >= 30:
                market_title = self.poly.active_market["title"] if self.poly.active_market else "搜索中..."
                log(f"状态: 市场={market_title} | "
                    f"Poly快照:{self.stats['poly_snaps']} "
                    f"扫描:{self.stats['market_scans']} "
                    f"错误:{self.stats['errors']}")
                last_status = now

            # 控制循环速率
            time.sleep(0.05)

        # ---- 退出清理 ----
        if self.poly_buffer:
            self.store.save_poly_ob(self.poly_buffer)

        log(f"采集器已停止。总计: {self.stats}")

# ============================================================
if __name__ == "__main__":
    daemon = CollectorDaemon()
    daemon.run()
