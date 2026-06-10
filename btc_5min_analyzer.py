"""
BTC 5min K线统计分析器
====================
基于采集的 K 线数据，分析涨跌规律，为 Polymarket 交易策略提供依据

核心问题：
  1. 5分钟线涨跌概率分布是怎样的？
  2. 涨跌有趋势性还是均值回归？
  3. 哪些时段胜率更高？
  4. 振幅的统计特征？
  5. 是否存在可预测的模式？
"""

import csv
import json
import math
import os
from datetime import datetime, timezone
from collections import defaultdict
from typing import List, Dict, Tuple

# ============================================================
# 数据加载
# ============================================================
def load_klines(filepath: str = "btc_data/btc_5min_klines.csv") -> List[Dict]:
    """加载 K 线数据"""
    klines = []
    if not os.path.exists(filepath):
        print(f"[错误] 文件不存在: {filepath}")
        return klines

    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["open"] = float(row["open"])
            row["high"] = float(row["high"])
            row["low"] = float(row["low"])
            row["close"] = float(row["close"])
            row["change_pct"] = float(row["change_pct"])
            row["high_low_range"] = float(row["high_low_range"])
            row["ticks"] = int(row["ticks"])
            klines.append(row)

    return klines

# ============================================================
# 统计分析
# ============================================================
class KlineAnalyzer:
    """5min K 线统计分析"""

    def __init__(self, klines: List[Dict]):
        self.klines = klines
        self.changes = [k["change_pct"] for k in klines]
        self.ranges = [k["high_low_range"] for k in klines]
        self.n = len(klines)

    # ---- 基础统计 ----
    def basic_stats(self) -> Dict:
        """涨跌基础统计"""
        up = [c for c in self.changes if c > 0]
        down = [c for c in self.changes if c < 0]
        flat = [c for c in self.changes if c == 0]

        return {
            "总K线数": self.n,
            "上涨": len(up),
            "下跌": len(down),
            "持平": len(flat),
            "涨率": round(len(up) / self.n * 100, 1) if self.n > 0 else 0,
            "跌率": round(len(down) / self.n * 100, 1) if self.n > 0 else 0,
            "平均涨幅": round(sum(up) / len(up), 4) if up else 0,
            "平均跌幅": round(sum(down) / len(down), 4) if down else 0,
            "最大涨幅": round(max(self.changes), 4),
            "最大跌幅": round(min(self.changes), 4),
        }

    def distribution(self) -> Dict:
        """涨跌幅分布"""
        bins = [
            ("-∞ ~ -1.0%", lambda x: x <= -1.0),
            ("-1.0% ~ -0.5%", lambda x: -1.0 < x <= -0.5),
            ("-0.5% ~ -0.3%", lambda x: -0.5 < x <= -0.3),
            ("-0.3% ~ -0.1%", lambda x: -0.3 < x <= -0.1),
            ("-0.1% ~ 0%", lambda x: -0.1 < x < 0),
            ("0%", lambda x: x == 0),
            ("0% ~ 0.1%", lambda x: 0 < x <= 0.1),
            ("0.1% ~ 0.3%", lambda x: 0.1 < x <= 0.3),
            ("0.3% ~ 0.5%", lambda x: 0.3 < x <= 0.5),
            ("0.5% ~ 1.0%", lambda x: 0.5 < x <= 1.0),
            ("1.0% ~ +∞", lambda x: x > 1.0),
        ]

        dist = []
        for label, condition in bins:
            count = sum(1 for c in self.changes if condition(c))
            pct = round(count / self.n * 100, 1) if self.n > 0 else 0
            dist.append({"区间": label, "次数": count, "占比%": pct})

        return dist

    def volatility_stats(self) -> Dict:
        """波动率统计"""
        mean = sum(self.changes) / self.n if self.n > 0 else 0
        variance = sum((c - mean) ** 2 for c in self.changes) / self.n if self.n > 0 else 0
        std = variance ** 0.5

        sorted_changes = sorted(self.changes)

        def percentile(p):
            idx = int(self.n * p / 100)
            return sorted_changes[min(idx, self.n - 1)] if self.n > 0 else 0

        return {
            "标准差": round(std, 4),
            "年化波动率": round(std * math.sqrt(365 * 24 * 12), 2),  # 5min -> 年化
            "平均绝对涨跌": round(sum(abs(c) for c in self.changes) / self.n, 4) if self.n > 0 else 0,
            "平均振幅": round(sum(self.ranges) / len(self.ranges), 4) if self.ranges else 0,
            "分位数_P10": round(percentile(10), 4),
            "分位数_P25": round(percentile(25), 4),
            "分位数_P50": round(percentile(50), 4),
            "分位数_P75": round(percentile(75), 4),
            "分位数_P90": round(percentile(90), 4),
            "分位数_P95": round(percentile(95), 4),
            "分位数_P99": round(percentile(99), 4),
        }

    def autocorrelation(self, max_lag: int = 5) -> Dict:
        """自相关分析（判断趋势性 vs 均值回归）"""
        if self.n < max_lag + 1:
            return {}

        mean = sum(self.changes) / self.n
        var = sum((c - mean) ** 2 for c in self.changes) / self.n

        acf = {}
        for lag in range(1, max_lag + 1):
            if self.n > lag:
                cov = sum(
                    (self.changes[i] - mean) * (self.changes[i - lag] - mean)
                    for i in range(lag, self.n)
                ) / (self.n - lag)
                acf[f"lag_{lag}"] = round(cov / var, 4) if var > 0 else 0

        return acf

    def streak_analysis(self) -> Dict:
        """连续涨跌分析"""
        streaks_up = []
        streaks_down = []
        current = 0
        direction = None

        for c in self.changes:
            if c > 0:
                if direction == "up":
                    current += 1
                else:
                    if direction == "down":
                        streaks_down.append(current)
                    current = 1
                    direction = "up"
            elif c < 0:
                if direction == "down":
                    current += 1
                else:
                    if direction == "up":
                        streaks_up.append(current)
                    current = 1
                    direction = "down"
            else:
                if direction == "up":
                    streaks_up.append(current)
                elif direction == "down":
                    streaks_down.append(current)
                current = 0
                direction = None

        # 收尾
        if direction == "up":
            streaks_up.append(current)
        elif direction == "down":
            streaks_down.append(current)

        return {
            "平均连涨": round(sum(streaks_up) / len(streaks_up), 1) if streaks_up else 0,
            "平均连跌": round(sum(streaks_down) / len(streaks_down), 1) if streaks_down else 0,
            "最长连涨": max(streaks_up) if streaks_up else 0,
            "最长连跌": max(streaks_down) if streaks_down else 0,
            "连涨分布": {str(n): streaks_up.count(n) for n in sorted(set(streaks_up))},
            "连跌分布": {str(n): streaks_down.count(n) for n in sorted(set(streaks_down))},
        }

    def hourly_analysis(self) -> Dict:
        """时段分析"""
        hour_data = defaultdict(lambda: {
            "up": 0, "down": 0, "changes": [], "ranges": [],
        })

        for k in self.klines:
            try:
                dt = datetime.fromisoformat(k["open_time"])
                h = dt.hour
            except:
                continue

            hour_data[h]["changes"].append(k["change_pct"])
            hour_data[h]["ranges"].append(k["high_low_range"])
            if k["change_pct"] > 0:
                hour_data[h]["up"] += 1
            elif k["change_pct"] < 0:
                hour_data[h]["down"] += 1

        result = {}
        for h in sorted(hour_data.keys()):
            d = hour_data[h]
            total = d["up"] + d["down"]
            result[f"{h:02d}:00 UTC"] = {
                "样本": total,
                "涨率": round(d["up"] / total * 100, 1) if total > 0 else 0,
                "平均涨跌": round(sum(d["changes"]) / len(d["changes"]) * 100, 2) if d["changes"] else 0,
                "平均振幅": round(sum(d["ranges"]) / len(d["ranges"]), 4) if d["ranges"] else 0,
            }

        return result

    def trading_signal_analysis(self) -> Dict:
        """
        交易信号分析

        回答关键问题:
        - 涨了之后下一根继续涨 vs 反转的概率？
        - 大跌之后反弹的概率？
        - 振幅扩大后下一根的方向？
        """
        signals = []

        for i in range(1, len(self.klines)):
            prev = self.klines[i - 1]
            curr = self.klines[i]

            signals.append({
                "prev_change": prev["change_pct"],
                "prev_range": prev["high_low_range"],
                "curr_change": curr["change_pct"],
                "prev_dir": "UP" if prev["change_pct"] > 0 else "DOWN",
                "curr_dir": "UP" if curr["change_pct"] > 0 else "DOWN",
            })

        # 1. 动量效应：上根涨 -> 下根继续涨？
        after_up = [s for s in signals if s["prev_dir"] == "UP"]
        continuation = sum(1 for s in after_up if s["curr_dir"] == "UP")
        reversal = len(after_up) - continuation

        # 2. 反转效应：大跌后反弹？
        big_drops = [s for s in signals if s["prev_change"] < -0.3]
        bounce = sum(1 for s in big_drops if s["curr_dir"] == "UP")

        # 3. 振幅扩大 -> ?
        high_range = [s for s in signals if s["prev_range"] > 0.15]
        hr_up = sum(1 for s in high_range if s["curr_dir"] == "UP")

        return {
            "动量效应": {
                "涨后继续涨": continuation,
                "涨后反转": reversal,
                "继续涨概率": round(continuation / len(after_up) * 100, 1) if after_up else 0,
                "反转概率": round(reversal / len(after_up) * 100, 1) if after_up else 0,
            },
            "均值回归": {
                "大跌后反弹": bounce,
                "大跌样本": len(big_drops),
                "反弹概率": round(bounce / len(big_drops) * 100, 1) if big_drops else 0,
            },
            "高波动后": {
                "高振幅后涨": hr_up,
                "高振幅样本": len(high_range),
                "涨率": round(hr_up / len(high_range) * 100, 1) if high_range else 0,
            },
            "涨跌期望": {
                "涨后期望收益": round(
                    sum(s["curr_change"] for s in after_up) / len(after_up) * 100, 4
                ) if after_up else 0,
                "全样本期望收益": round(
                    sum(s["curr_change"] for s in signals) / len(signals) * 100, 4
                ) if signals else 0,
            },
        }

# ============================================================
# 报告输出
# ============================================================
def print_report(klines: List[Dict]):
    """打印完整分析报告"""
    analyzer = KlineAnalyzer(klines)

    if analyzer.n == 0:
        print("没有 K 线数据可分析。请先运行 btc_5min_collector.py 采集数据。")
        return

    print("""
╔══════════════════════════════════════════════════════════════╗
║          BTC 5min K线 统计分析报告                            ║
╚══════════════════════════════════════════════════════════════╝
""")
    print(f"样本: {analyzer.n} 根 5分钟 K 线")
    print(f"时间范围: {klines[0]['open_time']} ~ {klines[-1]['close_time']}")

    # 基础统计
    print(f"\n{'='*60}")
    print("  1. 涨跌统计")
    print(f"{'='*60}")
    basic = analyzer.basic_stats()
    for k, v in basic.items():
        print(f"  {k}: {v}")

    # 分布
    print(f"\n{'='*60}")
    print("  2. 涨跌幅分布")
    print(f"{'='*60}")
    dist = analyzer.distribution()
    max_count = max(d["次数"] for d in dist) if dist else 1
    for d in dist:
        bar = "█" * int(d["次数"] / max_count * 40)
        print(f"  {d['区间']:<18} {d['次数']:>5} ({d['占比%']:>5}%) {bar}")

    # 波动率
    print(f"\n{'='*60}")
    print("  3. 波动率分析")
    print(f"{'='*60}")
    vol = analyzer.volatility_stats()
    for k, v in vol.items():
        print(f"  {k}: {v}")

    # 自相关
    print(f"\n{'='*60}")
    print("  4. 自相关分析")
    print(f"{'='*60}")
    acf = analyzer.autocorrelation(5)
    if acf:
        print("  滞后  自相关系数  含义")
        print("  " + "-" * 40)
        for lag, val in acf.items():
            lag_n = int(lag.split("_")[1])
            if val > 0.1:
                meaning = "趋势性（涨了继续涨）" if analyzer.changes and sum(analyzer.changes)/len(analyzer.changes) > 0 else "趋势性"
            elif val < -0.1:
                meaning = "均值回归（涨了会反转）"
            else:
                meaning = "接近随机游走"
            print(f"  {lag_n:4d}   {val:+.4f}        {meaning}")

    # 连续涨跌
    print(f"\n{'='*60}")
    print("  5. 连续涨跌分析")
    print(f"{'='*60}")
    streaks = analyzer.streak_analysis()
    for k, v in streaks.items():
        if "分布" not in k:
            print(f"  {k}: {v}")
    print(f"\n  连涨分布: {streaks.get('连涨分布', {})}")
    print(f"  连跌分布: {streaks.get('连跌分布', {})}")

    # 交易信号
    print(f"\n{'='*60}")
    print("  6. 交易信号分析（关键！）")
    print(f"{'='*60}")
    signals = analyzer.trading_signal_analysis()

    print("\n  [动量效应]")
    for k, v in signals["动量效应"].items():
        print(f"    {k}: {v}")

    print("\n  [均值回归]")
    for k, v in signals["均值回归"].items():
        print(f"    {k}: {v}")

    print("\n  [高波动后方向]")
    for k, v in signals["高波动后"].items():
        print(f"    {k}: {v}")

    print("\n  [条件期望收益]")
    for k, v in signals["涨跌期望"].items():
        print(f"    {k}: {v}%")

    # 时段分析
    if analyzer.n >= 24:  # 至少 2 小时
        print(f"\n{'='*60}")
        print("  7. 时段分析")
        print(f"{'='*60}")
        hourly = analyzer.hourly_analysis()
        for h, stats in hourly.items():
            bar = "█" * int(stats["涨率"] / 100 * 20)
            print(f"  {h}: 涨率 {stats['涨率']:>5}% {bar} 振幅均值 {stats['平均振幅']:.4f}% ({stats['样本']}根)")

    # 策略建议
    print(f"\n{'='*60}")
    print("  8. Polymarket 策略建议")
    print(f"{'='*60}")

    up_prob = basic["涨率"]
    avg_up = basic["平均涨幅"]
    avg_down = basic["平均跌幅"]
    p50 = analyzer.volatility_stats()["分位数_P50"]

    print(f"""
  基于当前 {analyzer.n} 根 K 线的统计：

  1. 基础概率: 5min 上涨概率 = {up_prob}%
     → Polymarket Up 定价低于 {up_prob}% 时有正期望

  2. 期望收益: 无条件买入 Up 的期望 = {round(sum(analyzer.changes)/analyzer.n*100, 4)}%
     → 扣除手续费后的净收益

  3. 条件交易:
     - 上根大涨(>0.3%)后 → 下根继续涨概率: {signals['动量效应']['继续涨概率']}%
     - 上根大跌(<-0.3%)后 → 下根反弹概率: {signals['均值回归']['反弹概率']}%

  4. 止损建议: P95 分位 = {analyzer.volatility_stats()['分位数_P95']}%
     → 单笔止损设在此值以内

  5. 仓位建议: 凯利公式
     win_rate = {up_prob/100 if up_prob < 60 else 0.55}
     avg_win_pct = {avg_up}
     avg_loss_pct = {abs(avg_down)}
     kelly_val = (win_rate * avg_win_pct - (1-win_rate) * avg_loss_pct) / max(avg_win_pct, 0.001)
     → 建议仓位: {max(0, round(kelly_val * 100, 1))}%
""")

# ============================================================
if __name__ == "__main__":
    # 尝试多个路径
    paths = [
        "btc_data/btc_5min_klines.csv",
        "../btc_data/btc_5min_klines.csv",
        "/c/Users/33487/btc_data/btc_5min_klines.csv",
        "C:/Users/33487/btc_data/btc_5min_klines.csv",
    ]

    klines = []
    for p in paths:
        klines = load_klines(p)
        if klines:
            print(f"[加载] {p} → {len(klines)} 根 K 线")
            break

    if not klines:
        print("[错误] 找不到 K 线数据文件")
        print("请先运行: python btc_5min_collector.py")
    else:
        print_report(klines)
