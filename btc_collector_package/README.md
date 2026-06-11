# Polymarket BTC Up/Down 订单簿采集系统

## 功能

| 模块 | 说明 |
|------|------|
| `collector.py` | Polymarket BTC Up/Down 订单簿采集器，自动发现活跃市场 |
| `analyzer.py` | 订单簿统计分析：价差、隐含概率、买卖失衡、时段分布、趋势图 |
| `start.sh` | 一键部署脚本 |

## 采集的数据

```
data/
└── polymarket_ob_20260610.csv     # Polymarket 订单簿快照
    ├── timestamp                  # Unix 时间戳
    ├── datetime                   # ISO 格式时间
    ├── token                      # Up / Down
    ├── market_title               # 市场标题（含时间段）
    ├── best_bid                   # 最优买价 (0~1)
    ├── best_ask                   # 最优卖价 (0~1)
    ├── bid_size                   # 买盘深度 (美元)
    ├── ask_size                   # 卖盘深度 (美元)
    ├── bids_json                  # 前10档买单 [[price, size], ...]
    └── asks_json                  # 前10档卖单 [[price, size], ...]
```

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

## 分析命令

```bash
# 查看统计报告
python3 analyzer.py

# 分析最近7天
python3 analyzer.py --days 7

# 生成订单簿趋势图
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
| CPU | < 2% (单核) |
| 内存 | ~30MB |
| 磁盘 | ~50MB/天 |
| 网络 | ~3MB/天 |

新加坡服务器到 Polymarket API 延迟 ~50-100ms。
