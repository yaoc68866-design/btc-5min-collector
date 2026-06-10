# BTC 5min K线 高频数据采集系统

## 功能

| 模块 | 说明 |
|------|------|
| `collector.py` | 主采集器：BTC价格(3次/秒) + Polymarket订单簿 + 5min K线聚合 |
| `analyzer.py` | 统计分析器：涨跌概率、波动率、时段分布、生成K线图 |
| `start.sh` | 一键部署脚本 |

## 在新加坡服务器上部署

### 1. 上传文件

```bash
# 在本地打包
cd btc_collector_package
tar czf btc_collector.tar.gz *

# 上传到服务器
scp btc_collector.tar.gz root@your-server-ip:/opt/
```

### 2. 解压安装

```bash
ssh root@your-server-ip
cd /opt
tar xzf btc_collector.tar.gz -C btc_collector
cd btc_collector
```

### 3. 一键启动

```bash
chmod +x start.sh
./start.sh
# 选择 3 (systemd 服务，推荐)
```

### 4. 手动启动（无需交互）

```bash
pip3 install -r requirements.txt
nohup python3 collector.py > data/nohup.log 2>&1 &
```

## 数据输出

```
data/
├── btc_ticks_20260610.csv        # 每秒3次的BTC价格
├── btc_5min_klines_20260610.csv   # 5分钟K线(OHLCV)
├── polymarket_ob_20260610.csv     # Polymarket订单簿快照
└── collector.log                  # 运行日志
```

## 分析命令

```bash
# 查看统计报告
python3 analyzer.py

# 分析最近7天
python3 analyzer.py --days 7

# 生成K线图
python3 analyzer.py --chart

# 查看实时日志
tail -f data/collector.log
```

## 服务管理 (systemd)

```bash
sudo systemctl status btc-collector   # 状态
sudo systemctl stop btc-collector     # 停止
sudo systemctl restart btc-collector  # 重启
journalctl -u btc-collector -f        # 查看日志
```

## 资源消耗

| 指标 | 约值 |
|------|------|
| CPU | < 5% (单核) |
| 内存 | ~50MB |
| 磁盘 | ~100MB/天 |
| 网络 | ~5MB/天 |

新加坡服务器到 Binance API 延迟 ~5-10ms，到 Polymarket API 延迟 ~50-100ms。
