"""
BTC 5min K线高频采集器 + 统计分析系统
=====================================
功能:
  1. 每秒 3 次抓取 BTC 价格（~333ms 间隔）
  2. 自动切分 5 分钟 K 线（OHLCV）
  3. 统计 5min 涨跌规律
  4. 数据持久化到本地 CSV

用途: 为 Polymarket BTC Up/Down 交易策略提供统计基础
"""

import requests
import json
import time
import csv
import os
from datetime import datetime, timezone, timedelta
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Dict
import math

# ============================================================
# 配置
# ============================================================
CONFIG = {
    # 数据采集
    "sample_rate": 3,           # 每秒采样次数
    "sample_interval": 1/3,     # 采样间隔（秒）

    # 数据源（多源容错）
    "price_sources": [
        "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
        "https://api.bybit.com/v5/market/tickers?category=spot&symbol=BTCUSDT",
        "https://api.coinbase.com/v2/prices/BTC-USD/spot",
    ],

    # K线
    "kline_period": 300,        # 5 分钟 = 300 秒

    # 存储
    "data_dir": "btc_data",
    "ticks_file": "btc_ticks.csv",
    "klines_file": "btc_5min_klines.csv",
}

# ============================================================
# 数据结构
# ============================================================
@dataclass
class Tick:
    """单次价格采样"""
    timestamp: float
    price: float
    source: str

@dataclass
class Kline:
    """5分钟 K 线"""
    open_time: float
    close_time: float
    open: float
    high: float
    low: float
    close: float
    volume_ticks: int       # 采集到的 tick 数
    price_changes: List[float] = field(default_factory=list)  # 所有涨跌幅序列

    @property
    def change_pct(self) -> float:
        """涨跌幅 %"""
        return ((self.close - self.open) / self.open) * 100 if self.open > 0 else 0

    @property
    def high_low_range(self) -> float:
        """振幅 %"""
        return ((self.high - self.low) / self.open) * 100 if self.open > 0 else 0

    @property
    def direction(self) -> str:
        """方向"""
        return "UP" if self.close >= self.open else "DOWN"

    def to_dict(self) -> Dict:
        return {
            "open_time": datetime.fromtimestamp(self.open_time).isoformat(),
            "close_time": datetime.fromtimestamp(self.close_time).isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "change_pct": round(self.change_pct, 4),
            "high_low_range": round(self.high_low_range, 4),
            "direction": self.direction,
            "ticks": self.volume_ticks,
        }

# ============================================================
# 价格采集器
# ============================================================
class PriceCollector:
    """多源价格采集器"""

    def __init__(self):
        self.session = requests.Session()
        self.current_price = 0.0

    def fetch(self) -> Optional[Tick]:
        """从多个数据源获取价格（取最快响应）"""
        for url in CONFIG["price_sources"]:
            try:
                r = self.session.get(url, timeout=2)
                if not r.ok:
                    continue

                data = r.json()
                price = 0.0

                # 解析不同数据源的格式
                if "api.binance.com" in url:
                    price = float(data.get("price", 0))
                elif "api.bybit.com" in url:
                    price = float(data["result"]["list"][0]["lastPrice"])
                elif "api.coinbase.com" in url:
                    price = float(data["data"]["amount"])

                if price > 0:
                    return Tick(
                        timestamp=time.time(),
                        price=price,
                        source=url.split("/")[2].split(".")[-2]
                    )

            except Exception:
                continue

        return None

# ============================================================
# K线聚合器
# ============================================================
class KlineAggregator:
    """实时 K 线聚合"""

    def __init__(self):
        self.current_kline: Optional[Kline] = None
        self.completed_klines: List[Kline] = []
        self.tick_buffer: deque = deque(maxlen=10000)
        self._last_price = 0.0

    def add_tick(self, tick: Tick) -> Optional[Kline]:
        """
        添加 tick，自动维护当前 K 线
        返回: 如果当前 K 线完成，返回完成的 K 线；否则返回 None
        """
        self.tick_buffer.append(tick)

        # 确定当前 tick 属于哪个 5 分钟窗口
        window_start = math.floor(tick.timestamp / CONFIG["kline_period"]) * CONFIG["kline_period"]

        completed = None

        # 检查是否需要开始新的 K 线
        if self.current_kline is None:
            self.current_kline = Kline(
                open_time=window_start,
                close_time=window_start + CONFIG["kline_period"],
                open=tick.price,
                high=tick.price,
                low=tick.price,
                close=tick.price,
                volume_ticks=1,
            )

        elif window_start > self.current_kline.open_time:
            # 当前 K 线完成，保存并开始新的
            self.current_kline.close = self._last_price
            self.completed_klines.append(self.current_kline)
            completed = self.current_kline

            # 初始化新 K 线
            prev_close = self._last_price
            self.current_kline = Kline(
                open_time=window_start,
                close_time=window_start + CONFIG["kline_period"],
                open=tick.price,
                high=tick.price,
                low=tick.price,
                close=tick.price,
                volume_ticks=1,
            )

        else:
            # 更新当前 K 线
            self.current_kline.high = max(self.current_kline.high, tick.price)
            self.current_kline.low = min(self.current_kline.low, tick.price)
            self.current_kline.close = tick.price
            self.current_kline.volume_ticks += 1

        # 记录价格变化
        if self._last_price > 0:
            chg = (tick.price - self._last_price) / self._last_price
            if self.current_kline:
                self.current_kline.price_changes.append(chg)

        self._last_price = tick.price
        return completed

# ============================================================
# 统计分析器
# ============================================================
class StatAnalyzer:
    """5min K 线统计分析"""

    @staticmethod
    def analyze(klines: List[Kline]) -> Dict:
        """分析 K 线序列的统计特征"""
        if not klines:
            return {}

        changes = [k.change_pct for k in klines]
        n = len(changes)

        # 基础统计
        up_count = sum(1 for c in changes if c > 0)
        down_count = sum(1 for c in changes if c < 0)
        flat_count = sum(1 for c in changes if c == 0)

        mean_chg = sum(changes) / n
        abs_changes = [abs(c) for c in changes]
        mean_abs_chg = sum(abs_changes) / n

        # 波动率
        variance = sum((c - mean_chg) ** 2 for c in changes) / n
        std_chg = variance ** 0.5

        # 极值
        max_up = max(changes)
        max_down = min(changes)

        # 分位数
        sorted_chg = sorted(changes)
        p25 = sorted_chg[int(n * 0.25)]
        p50 = sorted_chg[int(n * 0.50)]
        p75 = sorted_chg[int(n * 0.75)]
        p90 = sorted_chg[int(n * 0.90)]
        p95 = sorted_chg[int(n * 0.95)]
        p99 = sorted_chg[int(n * 0.99)]

        # 振幅统计
        ranges = [k.high_low_range for k in klines]
        avg_range = sum(ranges) / n

        # 序列相关性（自相关 lag=1）
        if n > 1:
            mean_c = sum(changes) / n
            var_c = sum((c - mean_c) ** 2 for c in changes) / n
            if var_c > 0:
                autocorr = sum((changes[i] - mean_c) * (changes[i-1] - mean_c)
                               for i in range(1, n)) / ((n-1) * var_c)
            else:
                autocorr = 0
        else:
            autocorr = 0

        # 连续涨/跌统计
        streaks_up = []
        streaks_down = []
        current_streak = 0
        current_dir = None

        for c in changes:
            if c > 0:
                if current_dir == "up":
                    current_streak += 1
                else:
                    if current_dir == "down":
                        streaks_down.append(current_streak)
                    current_streak = 1
                    current_dir = "up"
            elif c < 0:
                if current_dir == "down":
                    current_streak += 1
                else:
                    if current_dir == "up":
                        streaks_up.append(current_streak)
                    current_streak = 1
                    current_dir = "down"
            else:
                if current_dir == "up":
                    streaks_up.append(current_streak)
                elif current_dir == "down":
                    streaks_down.append(current_streak)
                current_streak = 0
                current_dir = None

        if current_dir == "up":
            streaks_up.append(current_streak)
        elif current_dir == "down":
            streaks_down.append(current_streak)

        avg_streak_up = sum(streaks_up) / len(streaks_up) if streaks_up else 0
        avg_streak_down = sum(streaks_down) / len(streaks_down) if streaks_down else 0
        max_streak_up = max(streaks_up) if streaks_up else 0
        max_streak_down = max(streaks_down) if streaks_down else 0

        # 时段统计（按 UTC 小时）
        hour_stats = {}
        for k in klines:
            hour = datetime.fromtimestamp(k.open_time).hour
            if hour not in hour_stats:
                hour_stats[hour] = {"up": 0, "down": 0, "total": 0, "changes": []}
            hour_stats[hour]["total"] += 1
            hour_stats[hour]["changes"].append(k.change_pct)
            if k.direction == "UP":
                hour_stats[hour]["up"] += 1
            else:
                hour_stats[hour]["down"] += 1

        # 返回结果
        return {
            "样本数": n,
            "上涨次数": up_count,
            "下跌次数": down_count,
            "持平次数": flat_count,
            "上涨概率": round(up_count / n * 100, 1) if n > 0 else 0,
            "下跌概率": round(down_count / n * 100, 1) if n > 0 else 0,
            "平均涨跌幅_%": round(mean_chg, 4),
            "平均绝对涨跌幅_%": round(mean_abs_chg, 4),
            "标准差_%": round(std_chg, 4),
            "最大涨幅_%": round(max_up, 4),
            "最大跌幅_%": round(max_down, 4),
            "平均振幅_%": round(avg_range, 4),
            "自相关_lag1": round(autocorr, 4),
            "分位数": {
                "P25_%": round(p25, 4),
                "P50_%": round(p50, 4),
                "P75_%": round(p75, 4),
                "P90_%": round(p90, 4),
                "P95_%": round(p95, 4),
                "P99_%": round(p99, 4),
            },
            "连续上涨均值": round(avg_streak_up, 1),
            "连续下跌均值": round(avg_streak_down, 1),
            "最长连涨": max_streak_up,
            "最长连跌": max_streak_down,
            "时段统计": {
                h: {
                    "up_rate": round(stats["up"] / stats["total"] * 100, 1),
                    "avg_change": round(sum(stats["changes"]) / len(stats["changes"]) * 100, 2),
                    "count": stats["total"]
                }
                for h, stats in sorted(hour_stats.items())
            },
        }

# ============================================================
# 数据持久化
# ============================================================
class DataStore:
    """数据存储到 CSV"""

    def __init__(self):
        os.makedirs(CONFIG["data_dir"], exist_ok=True)

    def save_ticks(self, ticks: List[Tick]):
        """追加保存 tick 数据"""
        filepath = os.path.join(CONFIG["data_dir"], CONFIG["ticks_file"])
        is_new = not os.path.exists(filepath)

        with open(filepath, "a", newline="") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow(["timestamp", "datetime", "price", "source"])
            for t in ticks:
                writer.writerow([
                    t.timestamp,
                    datetime.fromtimestamp(t.timestamp).isoformat(),
                    t.price,
                    t.source,
                ])

    def save_kline(self, kline: Kline):
        """追加保存 K 线"""
        filepath = os.path.join(CONFIG["data_dir"], CONFIG["klines_file"])
        is_new = not os.path.exists(filepath)

        with open(filepath, "a", newline="") as f:
            writer = csv.writer(f)
            if is_new:
                writer.writerow([
                    "open_time", "close_time",
                    "open", "high", "low", "close",
                    "change_pct", "high_low_range", "direction", "ticks"
                ])
            d = kline.to_dict()
            writer.writerow([
                d["open_time"], d["close_time"],
                d["open"], d["high"], d["low"], d["close"],
                d["change_pct"], d["high_low_range"], d["direction"], d["ticks"]
            ])

# ============================================================
# 主程序
# ============================================================
class BTCDataCollector:
    """BTC 5min 数据采集主控"""

    def __init__(self):
        self.collector = PriceCollector()
        self.aggregator = KlineAggregator()
        self.analyzer = StatAnalyzer()
        self.store = DataStore()
        self.running = False
        self.tick_buffer: List[Tick] = []

    def start(self, duration_minutes: int = 0):
        """
        启动数据采集
        duration_minutes: 采集时长，0 = 无限运行
        """
        print("""
╔══════════════════════════════════════════════════════════════╗
║     BTC 5min K线 高频数据采集系统                              ║
║     采样率: 3次/秒  |  K线: 5分钟                               ║
╚══════════════════════════════════════════════════════════════╝
        """)

        print(f"[启动] 开始采集 BTC 价格数据...")
        print(f"[启动] 采样率: {CONFIG['sample_rate']} 次/秒 (间隔 {CONFIG['sample_interval']*1000:.0f}ms)")
        print(f"[启动] K线周期: {CONFIG['kline_period']}s (5分钟)")
        print(f"[启动] 数据保存: {CONFIG['data_dir']}/{CONFIG['klines_file']}")

        self.running = True
        start_time = time.time()
        end_time = start_time + duration_minutes * 60 if duration_minutes > 0 else float("inf")

        tick_count = 0
        kline_count = 0
        last_report = start_time
        last_summary = start_time

        while self.running and time.time() < end_time:
            loop_start = time.time()

            # 采集价格
            tick = self.collector.fetch()
            if tick:
                tick_count += 1
                self.tick_buffer.append(tick)

                # 聚合到 K 线
                completed = self.aggregator.add_tick(tick)
                if completed:
                    self.store.save_kline(completed)
                    kline_count += 1

            # 每秒报告进度
            if time.time() - last_report >= 1.0:
                last_report = time.time()
                k = self.aggregator.current_kline
                if k:
                    elapsed = time.time() - k.open_time
                    remaining = CONFIG["kline_period"] - elapsed
                    bar = "█" * int(elapsed / CONFIG["kline_period"] * 30)
                    bar += "░" * (30 - len(bar))
                    direction_symbol = "🟢" if k.change_pct > 0 else ("🔴" if k.change_pct < 0 else "⚪")
                    print(f"\r[{bar}] {direction_symbol} "
                          f"O:{k.open:,.0f} H:{k.high:,.0f} L:{k.low:,.0f} "
                          f"C:{k.close:,.0f} "
                          f"{k.change_pct:+.3f}% | 剩余{remaining:.0f}s | "
                          f"Ticks:{tick_count} Klines:{kline_count}",
                          end="", flush=True)

            # 每5分钟输出摘要
            if time.time() - last_summary >= 300:
                last_summary = time.time()
                print()  # 换行
                if kline_count >= 12:  # 至少 1 小时数据
                    stats = self.analyzer.analyze(self.aggregator.completed_klines)
                    self._print_stats(stats)

            # 批量保存 tick
            if len(self.tick_buffer) >= 100:
                self.store.save_ticks(self.tick_buffer)
                self.tick_buffer.clear()

            # 控制采样率
            elapsed = time.time() - loop_start
            sleep_time = CONFIG["sample_interval"] - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        # 清理
        if self.tick_buffer:
            self.store.save_ticks(self.tick_buffer)
        print("\n")

        # 最终统计
        if len(self.aggregator.completed_klines) > 0:
            print("=" * 60)
            print("  最终统计分析")
            print("=" * 60)
            stats = self.analyzer.analyze(self.aggregator.completed_klines)
            self._print_stats(stats)

        print(f"\n[完成] 共采集 {tick_count} ticks, {kline_count} K线")

    def _print_stats(self, stats: Dict):
        """打印统计报告"""
        print(f"""
┌─────────────────────────────────────────────────────────────┐
│                    5min K线 统计分析                          │
├─────────────────────────────────────────────────────────────┤
│ 样本数: {stats.get('样本数', 0):>6}                                              │
│ 上涨: {stats.get('上涨次数', 0):>6} 次 ({stats.get('上涨概率', 0):.1f}%)                                    │
│ 下跌: {stats.get('下跌次数', 0):>6} 次 ({stats.get('下跌概率', 0):.1f}%)                                    │
├─────────────────────────────────────────────────────────────┤
│ 平均涨跌: {stats.get('平均涨跌幅_%', 0):>+.4f}%                                        │
│ 平均振幅: {stats.get('平均振幅_%', 0):.4f}%                                          │
│ 标准差:   {stats.get('标准差_%', 0):.4f}%                                          │
│ 自相关:   {stats.get('自相关_lag1', 0):.4f}  (趋势性 vs 均值回归)                    │
├─────────────────────────────────────────────────────────────┤
│ 极端值:                                                     │
│   最大涨幅: {stats.get('最大涨幅_%', 0):.4f}%                                        │
│   最大跌幅: {stats.get('最大跌幅_%', 0):.4f}%                                        │
├─────────────────────────────────────────────────────────────┤
│ 连续统计:                                                   │
│   平均连续上涨: {stats.get('连续上涨均值', 0):.1f} 根  |  最长: {stats.get('最长连涨', 0)}                               │
│   平均连续下跌: {stats.get('连续下跌均值', 0):.1f} 根  |  最长: {stats.get('最长连跌', 0)}                               │
├─────────────────────────────────────────────────────────────┤
│ 分位数 (涨跌幅%):                                           │
│   P25: {stats['分位数']['P25_%']:.4f}%  P50: {stats['分位数']['P50_%']:.4f}%  P75: {stats['分位数']['P75_%']:.4f}%    │
│   P90: {stats['分位数']['P90_%']:.4f}%  P95: {stats['分位数']['P95_%']:.4f}%  P99: {stats['分位数']['P99_%']:.4f}%    │
└─────────────────────────────────────────────────────────────┘
""")

        # 时段分析
        if stats.get("时段统计"):
            print("  时段分析 (UTC):")
            print(f"  {'Hour':<6} {'Up%':<8} {'AvgChg%':<10} {'Count':<6}")
            print(f"  {'-'*35}")
            for h, s in stats["时段统计"].items():
                print(f"  {h:02d}:00  {s['up_rate']:>5.1f}%  {s['avg_change']:>+8.4f}%  {s['count']:>5d}")

    def stop(self):
        self.running = False

# ============================================================
if __name__ == "__main__":
    collector = BTCDataCollector()
    try:
        # 运行 30 分钟（采集约 5400 个 tick，~6 根 K 线）
        collector.start(duration_minutes=30)
    except KeyboardInterrupt:
        collector.stop()
        print("\n采集已手动停止。")
