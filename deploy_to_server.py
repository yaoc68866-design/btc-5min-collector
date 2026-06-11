"""
一键部署 Polymarket 订单簿采集器 到远程服务器
用法: python deploy_to_server.py
"""
import paramiko
import os
import sys

HOST = "43.133.47.32"
USER = "Administrator"
PASS = "2570731785Cy!"
LOCAL_PACKAGE = os.path.dirname(os.path.abspath(__file__)) + "/btc_collector_package"
REMOTE_DIR = "C:/btc_collector"


def ssh_cmd(ssh, cmd, desc=""):
    """执行远程命令"""
    if desc:
        print(f"  [{desc}]")
    print(f"  $ {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
    out = stdout.read().decode('utf-8', errors='ignore')
    err = stderr.read().decode('utf-8', errors='ignore')
    if out.strip():
        print(f"  {out.strip()}")
    if err.strip() and "warning" not in err.lower():
        print(f"  [stderr] {err.strip()}")
    return out, err


def main():
    print("=" * 60)
    print("  Polymarket 订单簿采集器 — 部署到远程服务器")
    print(f"  {HOST}  ({USER})")
    print("=" * 60)

    # 检查本地文件
    if not os.path.isdir(LOCAL_PACKAGE):
        print(f"[错误] 找不到部署包: {LOCAL_PACKAGE}")
        sys.exit(1)

    files_to_upload = [f for f in os.listdir(LOCAL_PACKAGE)
                       if os.path.isfile(os.path.join(LOCAL_PACKAGE, f))]
    print(f"\n  待上传文件 ({len(files_to_upload)} 个):")
    for fn in files_to_upload:
        print(f"    - {fn}")

    # 连接
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        print(f"\n[1] 连接 {USER}@{HOST}:22 ...")
        ssh.connect(HOST, username=USER, password=PASS, timeout=15,
                     look_for_keys=False, allow_agent=False)
        print("  ✓ 已连接")
    except Exception as e:
        print(f"  ✗ 连接失败: {e}")
        print("\n  请确认:")
        print("  1. 服务器已开启 OpenSSH Server")
        print("  2. 防火墙已放行端口 22")
        print("  3. 密码正确")
        sys.exit(1)

    # 检查系统类型
    out, _ = ssh_cmd(ssh, "ver", "检查系统")
    is_windows = "Windows" in out
    print(f"  系统类型: {'Windows' if is_windows else 'Linux'}")

    # 检测 Python
    if is_windows:
        out, _ = ssh_cmd(ssh, "where python", "检查 Python")
        python = "python" if "python" in out.lower() else None
        if not python:
            out, _ = ssh_cmd(ssh, "where python3", "检查 Python3")
            python = "python3" if "python3" in out.lower() else None
    else:
        out, _ = ssh_cmd(ssh, "which python3 || which python", "检查 Python")
        python = "python3" if "python3" in out else ("python" if "python" in out else None)

    if not python:
        print("  [错误] 服务器未安装 Python，请先安装 Python 3.10+")
        ssh.close()
        sys.exit(1)
    print(f"  Python: {python}")

    # 上传文件
    print(f"\n[2] 上传文件到 {REMOTE_DIR} ...")
    try:
        sftp = ssh.open_sftp()
        # 创建远程目录
        try:
            sftp.stat(REMOTE_DIR)
        except FileNotFoundError:
            sftp.mkdir(REMOTE_DIR)
        try:
            sftp.stat(REMOTE_DIR + "/data")
        except FileNotFoundError:
            sftp.mkdir(REMOTE_DIR + "/data")

        for fname in files_to_upload:
            local_path = os.path.join(LOCAL_PACKAGE, fname)
            remote_path = f"{REMOTE_DIR}/{fname}".replace("\\", "/")
            try:
                sftp.put(local_path, remote_path)
                print(f"  ✓ {fname}")
            except Exception as e:
                print(f"  ✗ {fname}: {e}")
        sftp.close()
    except Exception as e:
        print(f"  ✗ 上传失败: {e}")
        ssh.close()
        sys.exit(1)

    # 安装依赖
    print(f"\n[3] 安装 Python 依赖...")
    ssh_cmd(ssh, f"cd /d {REMOTE_DIR} && {python} -m pip install -r requirements.txt --quiet 2>&1",
            "pip install")

    # 停止旧进程
    print(f"\n[4] 停止旧采集器 (如有)...")
    if is_windows:
        ssh_cmd(ssh,
                f'taskkill /F /FI "WINDOWTITLE eq collector*" 2>nul & '
                f'wmic process where "name like \'%python%\' and commandline like \'%collector.py%\'" delete 2>nul',
                "停止旧进程")
    else:
        ssh_cmd(ssh, "pkill -f collector.py 2>/dev/null; sleep 1", "停止旧进程")

    # 启动采集器
    print(f"\n[5] 启动采集器...")
    if is_windows:
        # Windows: 用 pythonw 后台运行（无窗口）
        ssh_cmd(ssh,
                f'cd /d {REMOTE_DIR} && '
                f'start "" /B {python} collector.py > data\\nohup.log 2>&1',
                "后台启动")
        # 验证是否启动成功
        import time
        time.sleep(3)
        out, _ = ssh_cmd(ssh,
                         f'wmic process where "commandline like \'%collector.py%\'" get ProcessId 2>nul',
                         "验证进程")
        if "ProcessId" in out and any(line.strip().isdigit() for line in out.split("\n") if line.strip()):
            print("  ✓ 采集器已启动")
        else:
            print("  ⚠ 进程检测失败，请手动验证")
    else:
        ssh_cmd(ssh,
                f"cd {REMOTE_DIR} && nohup {python} collector.py > data/nohup.log 2>&1 &",
                "nohup 后台启动")
        import time
        time.sleep(2)
        out, _ = ssh_cmd(ssh, f"pgrep -f collector.py", "验证进程")
        if out.strip():
            print(f"  ✓ 采集器已启动 (PID: {out.strip()})")
        else:
            print("  ⚠ 进程检测失败，请手动验证")

    # 完成
    print(f"\n{'=' * 60}")
    print(f"  部署完成!")
    print(f"  数据目录: {REMOTE_DIR}/data/")
    print(f"  查看日志: type {REMOTE_DIR}\\data\\collector.log")
    print(f"  分析数据: cd {REMOTE_DIR} && {python} analyzer.py")
    print(f"{'=' * 60}")

    ssh.close()


if __name__ == "__main__":
    main()
