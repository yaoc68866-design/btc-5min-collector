#!/bin/bash
# ============================================
# BTC 5min 数据采集器 启动脚本
# 用于新加坡云服务器
# ============================================

set -e

cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"

echo "=========================================="
echo " BTC 5min 采集器 部署脚本"
echo "=========================================="

# 1. 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 需要 Python 3.10+"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "  CentOS/RHEL:   sudo yum install python3 python3-pip"
    exit 1
fi

echo "[OK] Python: $(python3 --version)"

# 2. 安装依赖
echo "[安装] Python 依赖..."
pip3 install -r requirements.txt --quiet

# 3. 创建数据目录
mkdir -p data

# 4. 启动采集器
echo ""
echo "选择运行模式:"
echo "  1) 前台运行 (终端关闭即停止)"
echo "  2) 后台运行 (nohup)"
echo "  3) 安装为 systemd 服务 (推荐, 开机自启)"
echo ""
read -p "请选择 [1/2/3]: " choice

case $choice in
    1)
        echo "[启动] 前台模式..."
        python3 collector.py
        ;;
    2)
        echo "[启动] 后台模式..."
        nohup python3 collector.py > data/nohup.log 2>&1 &
        PID=$!
        echo "PID: $PID"
        echo "查看日志: tail -f data/collector.log"
        echo "停止: kill $PID"
        ;;
    3)
        SERVICE_FILE="/etc/systemd/system/btc-collector.service"
        echo "[安装] systemd 服务..."
        sudo tee $SERVICE_FILE > /dev/null <<EOF
[Unit]
Description=BTC 5min K-line Collector
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$SCRIPT_DIR
ExecStart=/usr/bin/python3 $SCRIPT_DIR/collector.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

        sudo systemctl daemon-reload
        sudo systemctl enable btc-collector
        sudo systemctl start btc-collector
        echo "[OK] 服务已安装并启动"
        echo ""
        echo "管理命令:"
        echo "  sudo systemctl status btc-collector  # 查看状态"
        echo "  sudo systemctl stop btc-collector     # 停止"
        echo "  sudo systemctl restart btc-collector  # 重启"
        echo "  tail -f data/collector.log            # 查看日志"
        ;;
    *)
        echo "无效选择"
        exit 1
        ;;
esac
