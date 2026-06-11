# 更新日志

## v2.0.0 — 纯 Polymarket 订单簿采集 (2026-06-11)

### 重大变更

#### 移除
- ❌ **BTC 价格采集**：删除了 `BTCCollector` 类，不再从 Binance/Bybit 抓取 BTC 价格
- ❌ **K线聚合**：删除了 `KlineAggregator` 类，不再生成 5min K线数据
- ❌ **BTC tick 存储**：删除了 `save_ticks()` 和 `save_kline()` 方法
- ❌ **chart_generator.py**：删除独立的 K 线图生成脚本，功能已合并到 `analyzer.py`

#### 新增 / 优化
- ✅ **纯 Polymarket 订单簿采集**：`collector.py` 专注于采集 BTC Up/Down 市场的订单簿数据
- ✅ **采样频率提升**：Polymarket 订单簿采样间隔从 2 秒提升到 **1 秒**
- ✅ **订单簿深度扩展**：每个订单簿快照从前 5 档扩展到 **前 10 档**
- ✅ **活跃度检测**：`find_btc_market()` 新增订单簿活跃度过滤
  - 自动跳过已结算市场（`closed=True`）
  - 自动跳过无流动性市场（mid price 不在 0.3~0.7 范围，或价差 > 0.3）
- ✅ **analyzer.py 重写**：从 K 线分析改为 Polymarket 订单簿分析
  - 价差分布（均值/中位数/最大/最小/标准差）
  - Up 隐含概率趋势分析
  - 买卖失衡分析（bid/(bid+ask) 深度偏向）
  - 按小时统计（价差、中间价、买卖深度）
  - 订单簿趋势图（Up/Down 隐含概率 + 价差变化）
- ✅ **README.md 更新**：移除 BTC 价格相关内容，更新数据输出说明
- ✅ **start.sh 更新**：更新标题和 systemd 服务描述

### 部署影响
- 磁盘占用从 ~100MB/天 降到 **~50MB/天**
- CPU 占用从 <5% 降到 **<2%**
- 内存从 ~50MB 降到 **~30MB**
- 不再需要访问 Binance/Bybit API

---

## v1.0.0 — 初始版本 (2026-06-10)

- BTC 价格采集 (3次/秒，Binance/Bybit)
- Polymarket 订单簿采集 (2秒间隔)
- 5min K 线聚合
- CSV 按天分文件存储
- 统计分析器 (K 线分析 + 图表)
- 一键部署脚本 (systemd)
