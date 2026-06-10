"""
Polymarket BTC 5min/15min 高频交易机器人 v2
================================================================
策略:
  1. 价差套利 - Polymarket 概率 vs BTC 实际波动率偏差
  2. 动量跟随 - BTC 快速突破时抢先下单
  3. 做市 - 双边挂单吃 spread

数据源: Binance REST API (轮询, ~1s 间隔)
市场: Polymarket BTC Up/Down (5min & 15min)

⚠️ 需要 Polymarket 私钥才能自动下单
   没有私钥 = 只监控不交易（模拟模式）
"""

import requests
import json
import time
import threading
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, List
from dataclasses import dataclass, field

# ============================================================
# 配置
# ============================================================
CONFIG = {
    # Polymarket
    "gamma_api": "https://gamma-api.polymarket.com",
    "clob_api": "https://clob.polymarket.com",

    # BTC 价格源
    "btc_price_url": "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
    # 备用: "https://api.coinbase.com/v2/prices/BTC-USD/spot"

    # 策略参数
    "poll_interval": 1.0,        # BTC 价格轮询间隔（秒）
    "scan_interval": 15,         # 市场扫描间隔（秒）
    "min_volume": 100,           # 最小交易量（USD）
    "max_position": 200,         # 单市场最大仓位（USD）
    "spread_threshold": 0.03,    # 价差阈值 (3%)
    "momentum_threshold": 0.003, # 动量阈值 (0.3%)

    # 风控
    "stop_loss": 0.15,           # 单笔止损 15%
    "take_profit": 0.25,         # 单笔止盈 25%
    "max_daily_loss": 500,       # 日最大亏损

    # API 认证 (下单必需)
    "private_key": "",           # ETH 私钥
    "proxy_wallet": "",          # Polymarket Proxy Wallet 地址

    # 模拟模式 (没有私钥时只监控)
    "simulation": True,
}

# ============================================================
# 数据结构
# ============================================================
@dataclass
class Market:
    id: str
    question: str
    slug: str
    outcomes: List[str]
    outcome_prices: List[float]
    volume: float
    end_time: str
    clob_token_ids: List[str]
    active: bool
    timeframe: str  # "5m" / "15m"

@dataclass
class Position:
    market_id: str
    direction: str
    entry_price: float
    size_usd: float
    token_id: str
    timestamp: float

@dataclass
class PriceSnapshot:
    """BTC 价格快照"""
    price: float
    timestamp: float
    bid: float = 0
    ask: float = 0

# ============================================================
# BTC 价格源 (REST 轮询)
# ============================================================
class BTCPriceFeed:
    """BTC 价格轮询器（REST API，~1s 延迟）"""

    def __init__(self):
        self.current = PriceSnapshot(price=0, timestamp=0)
        self.history: List[PriceSnapshot] = []  # 最近 30 分钟
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def _poll(self):
        """轮询 BTC 价格"""
        session = requests.Session()
        while self._running:
            try:
                r = session.get(CONFIG["btc_price_url"], timeout=3)
                if r.ok:
                    data = r.json()
                    price = float(data.get("price", 0))
                    now = time.time()

                    self.current = PriceSnapshot(price=price, timestamp=now)
                    self.history.append(self.current)

                    # 清理超过 30 分钟的历史
                    cutoff = now - 1800
                    self.history = [p for p in self.history if p.timestamp > cutoff]

            except Exception:
                pass

            time.sleep(CONFIG["poll_interval"])

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()

        # 等待第一个价格
        for _ in range(10):
            if self.current.price > 0:
                break
            time.sleep(0.5)

    def stop(self):
        self._running = False

    def get_momentum(self, seconds: int) -> float:
        """最近 N 秒价格变化率"""
        now = time.time()
        old = [p for p in self.history if p.timestamp <= now - seconds]
        if not old or self.current.price == 0:
            return 0.0
        old_price = old[0].price
        return (self.current.price - old_price) / old_price

    def get_volatility(self, seconds: int) -> float:
        """最近 N 秒内的波动率 (return std)"""
        now = time.time()
        prices = [p.price for p in self.history if p.timestamp >= now - seconds]
        if len(prices) < 5:
            return 0.01

        returns = []
        for i in range(1, len(prices)):
            r = (prices[i] - prices[i-1]) / prices[i-1]
            returns.append(r)

        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        return variance ** 0.5

    def get_price_range(self, seconds: int) -> tuple:
        """最近 N 秒最高/最低价"""
        now = time.time()
        prices = [p.price for p in self.history if p.timestamp >= now - seconds]
        if not prices:
            return (0, 0)
        return (min(prices), max(prices))

# ============================================================
# Polymarket API
# ============================================================
class PolymarketAPI:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "BTC-HFT-Bot/2.0",
            "Accept": "application/json",
        })
        self._last_req = 0

    def _rl(self):
        """防限流"""
        elapsed = time.time() - self._last_req
        if elapsed < 0.5:
            time.sleep(0.5 - elapsed)
        self._last_req = time.time()

    def get_btc_markets(self) -> List[Market]:
        """获取活跃的 BTC up/down 市场"""
        all_markets = []

        for tf in ["5m", "15m"]:
            try:
                self._rl()
                r = self.session.get(
                    f"{CONFIG['gamma_api']}/markets",
                    params={
                        "limit": 15,
                        "order": "endDate",
                        "ascending": True,
                        "active": "true",
                    },
                    timeout=10
                )
                if r.status_code != 200:
                    continue

                for m in r.json():
                    slug = m.get("slug", "")
                    if f"btc-updown-{tf}" not in slug.lower():
                        continue

                    outcomes = m.get("outcomes", [])
                    prices = m.get("outcomePrices", [])
                    clob_ids = m.get("clobTokenIds", [])

                    if isinstance(outcomes, str):
                        outcomes = json.loads(outcomes)
                    if isinstance(prices, str):
                        prices = [float(x) for x in json.loads(prices)]
                    if isinstance(clob_ids, str):
                        clob_ids = json.loads(clob_ids)

                    all_markets.append(Market(
                        id=m.get("id", ""),
                        question=m.get("question", ""),
                        slug=slug,
                        outcomes=outcomes,
                        outcome_prices=prices,
                        volume=float(m.get("volume", 0)),
                        end_time=m.get("endDateIso", ""),
                        clob_token_ids=clob_ids,
                        active=m.get("active", False),
                        timeframe=tf,
                    ))

            except Exception as e:
                print(f"  [API] 扫描 {tf} 异常: {e}")

        return all_markets

    def get_order_book(self, token_id: str) -> Optional[Dict]:
        """获取订单簿"""
        try:
            self._rl()
            r = self.session.get(
                f"{CONFIG['clob_api']}/book",
                params={"token_id": token_id},
                timeout=10
            )
            if r.status_code != 200:
                return None

            data = r.json()
            bids = [{"price": float(b["price"]), "size": float(b["size"])}
                    for b in data.get("bids", [])[:10]]
            asks = [{"price": float(a["price"]), "size": float(a["size"])}
                    for a in data.get("asks", [])[:10]]

            best_bid = bids[0]["price"] if bids else 0
            best_ask = asks[0]["price"] if asks else 0
            spread = best_ask - best_bid if best_ask and best_bid else 0
            mid = (best_bid + best_ask) / 2 if best_ask and best_bid else 0

            return {
                "bids": bids, "asks": asks,
                "best_bid": best_bid, "best_ask": best_ask,
                "spread": spread, "mid_price": mid,
            }

        except Exception as e:
            return None

# ============================================================
# 策略引擎
# ============================================================
class StrategyEngine:
    def __init__(self, feed: BTCPriceFeed, api: PolymarketAPI):
        self.feed = feed
        self.api = api
        self.positions: List[Position] = []
        self.closed_pnl = 0.0
        self.trade_log: List[str] = []

    def analyze(self, market: Market) -> Dict:
        """
        分析市场，返回交易信号

        核心逻辑：
        - BTC 5min 内波动 ~0.2-0.5%，极端时可达 1-2%
        - 如果 Polymarket 上 Up/Down 概率没有反映这个波动率，
          就存在套利空间
        """
        if market.volume < CONFIG["min_volume"]:
            return {"signal": "skip", "reason": "量太小"}

        btc_price = self.feed.current.price
        if btc_price == 0:
            return {"signal": "skip", "reason": "BTC 价格未就绪"}

        window = 300 if market.timeframe == "5m" else 900

        # 获取关键指标
        volatility = self.feed.get_volatility(window)
        momentum_60s = self.feed.get_momentum(60)
        momentum_300s = self.feed.get_momentum(window)
        price_range = self.feed.get_price_range(window)
        range_pct = (price_range[1] - price_range[0]) / btc_price if price_range[0] > 0 else 0

        # Polymarket 当前定价
        poly_up = market.outcome_prices[0] if market.outcome_prices else 0.5

        # 公平概率估算
        # 基于短期动量 + 波动率
        signal_strength = momentum_60s / (volatility + 0.001)
        fair_up = 0.5 + signal_strength * 0.3
        fair_up = max(0.05, min(0.95, fair_up))

        mispricing = fair_up - poly_up

        # 获取订单簿
        ob_up, ob_down = None, None
        if len(market.clob_token_ids) >= 2:
            ob_up = self.api.get_order_book(market.clob_token_ids[0])
            ob_down = self.api.get_order_book(market.clob_token_ids[1])

        signals = []

        # --- 信号 1: 概率偏差套利 ---
        if abs(mispricing) > CONFIG["spread_threshold"]:
            direction = "Up" if mispricing > 0 else "Down"
            edge = abs(mispricing)
            signals.append({
                "type": "mispricing",
                "direction": direction,
                "edge": edge,
                "fair_prob": fair_up if direction == "Up" else 1 - fair_up,
                "poly_prob": poly_up if direction == "Up" else 1 - poly_up,
            })

        # --- 信号 2: 动量突破 ---
        if abs(momentum_60s) > CONFIG["momentum_threshold"]:
            direction = "Up" if momentum_60s > 0 else "Down"
            signals.append({
                "type": "momentum",
                "direction": direction,
                "momentum": momentum_60s,
            })

        # --- 信号 3: 做市机会 ---
        if ob_up and ob_down:
            spread_up = ob_up.get("spread", 0)
            spread_down = ob_down.get("spread", 0)
            if spread_up > 0.005 or spread_down > 0.005:
                signals.append({
                    "type": "market_making",
                    "direction": "both",
                    "spread_up": spread_up,
                    "spread_down": spread_down,
                })

        if not signals:
            return {
                "signal": "hold",
                "btc_price": btc_price,
                "volatility": volatility,
                "momentum_60s": momentum_60s,
                "poly_up": poly_up,
                "fair_up": fair_up,
                "range_pct": range_pct,
            }

        best = max(signals, key=lambda s: abs(s.get("edge", s.get("momentum", s.get("spread_up", 0)))))

        return {
            "signal": "trade",
            "strategy": best,
            "btc_price": btc_price,
            "volatility": volatility,
            "momentum_60s": momentum_60s,
            "momentum_window": momentum_300s,
            "poly_up": poly_up,
            "fair_up": fair_up,
            "range_pct": range_pct,
            "ob_up": ob_up,
            "ob_down": ob_down,
        }

# ============================================================
# 主程序
# ============================================================
class BTCHFTBot:
    def __init__(self):
        self.feed = BTCPriceFeed()
        self.api = PolymarketAPI()
        self.strategy = StrategyEngine(self.feed, self.api)
        self.running = False
        self.iteration = 0

    def print_banner(self):
        print("""
+==============================================================+
|   Polymarket BTC 5min/15min HFT Bot v2                       |
|   策略: 概率套利 + 动量跟随 + 做市                             |
|   模式: """ + ("模拟交易 (只监控)" if CONFIG["simulation"] else "实盘交易") + """
+==============================================================+
""")

    def start(self):
        self.print_banner()

        # 启动 BTC 价格轮询
        print("[启动] 连接 BTC 价格源 (Binance REST)...")
        self.feed.start()
        if self.feed.current.price == 0:
            print("[错误] 无法获取 BTC 价格，退出")
            return
        print(f"[就绪] BTC: ${self.feed.current.price:,.2f}")

        # 主循环
        self.running = True
        self._run()

    def _run(self):
        while self.running:
            self.iteration += 1
            btc = self.feed.current.price
            now = datetime.now().strftime("%H:%M:%S")

            print(f"\n{'='*60}")
            print(f"[{now}] 周期 #{self.iteration} | BTC: ${btc:,.2f}")

            # 扫描市场
            markets = self.api.get_btc_markets()
            print(f"[扫描] 发现 {len(markets)} 个活跃 BTC 市场")

            if not markets:
                print("[提示] 当前没有活跃的 BTC 短期市场")
                print("       Polymarket 可能在非交易时段没有创建新的 Up/Down 市场")

            for m in markets:
                # 显示市场信息
                up_pct = m.outcome_prices[0] * 100 if m.outcome_prices else 0
                down_pct = m.outcome_prices[1] * 100 if len(m.outcome_prices) > 1 else 0

                print(f"\n  [{m.timeframe}] {m.question}")
                print(f"  Polymarket: Up {up_pct:.1f}% | Down {down_pct:.1f}% | Vol ${m.volume:,.0f}")

                # 分析
                result = self.strategy.analyze(m)

                if result["signal"] == "trade":
                    sig = result["strategy"]
                    print(f"  [信号] {sig['type'].upper()}")
                    print(f"         方向: {sig.get('direction', 'N/A')}")
                    if "edge" in sig:
                        print(f"         概率偏差: {sig['edge']*100:.2f}%")
                        print(f"         公平概率: {sig['fair_prob']*100:.1f}% vs Poly: {sig['poly_prob']*100:.1f}%")
                    if "momentum" in sig:
                        print(f"         动量: {sig['momentum']*100:.3f}%")
                    print(f"         BTC: ${result['btc_price']:,.2f}")
                    print(f"         波动率(window): {result['volatility']*100:.2f}%")
                    print(f"         >> 模拟下单: {sig['direction']} @ {result.get('poly_up', 0):.3f}")

                elif result["signal"] == "hold":
                    print(f"  [持仓] 无信号 | vol={result.get('volatility',0)*100:.2f}% "
                          f"mom60s={result.get('momentum_60s',0)*100:.3f}% "
                          f"fair={result.get('fair_up',0.5)*100:.1f}%")

                else:
                    print(f"  [跳过] {result.get('reason', '')}")

            # 风控摘要
            open_pos = len(self.strategy.positions)
            print(f"\n[摘要] 持仓: {open_pos} | 已实现盈亏: ${self.strategy.closed_pnl:,.2f}")

            # 日亏损检查
            if self.strategy.closed_pnl <= -CONFIG["max_daily_loss"]:
                print("[风控] 达到日最大亏损线！停止交易。")
                self.running = False
                break

            print(f"[等待] {CONFIG['scan_interval']}秒后下一轮扫描...")
            time.sleep(CONFIG["scan_interval"])

    def stop(self):
        self.running = False
        self.feed.stop()

# ============================================================
if __name__ == "__main__":
    bot = BTCHFTBot()
    try:
        bot.start()
    except KeyboardInterrupt:
        bot.stop()
        print("\n机器人已安全退出。")
