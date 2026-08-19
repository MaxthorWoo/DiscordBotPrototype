"""
IIP Bot 管理 一键启动器
同时运行 Discord Bot 和 Reflex 后台管理面板

特性：
- 子进程崩溃后自动重启（含网络未就绪时的等待重试）
- 启动前检查 discord.com 网络连通性，避免开机 DNS 未就绪导致 Bot 首次启动失败
- 记录重启次数 / 退出码到日志

用法: python run.py
"""
import subprocess
import sys
import os
import time
import signal
import socket

ROOT = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_DIR = os.path.join(ROOT, "dashboard_app")

IS_WIN = os.name == "nt"
CREATE_FLAGS = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WIN else 0

# Discord 网关域名
DISCORD_HOST = "discord.com"
DISCORD_PORT = 443

# 网络就绪检测参数
NET_CHECK_INTERVAL = 3      # 每次网络检测间隔（秒）
NET_CHECK_MAX_WAIT = 120    # 最多等网络就绪时长（秒）
NET_CHECK_TIMEOUT = 5       # 单次 socket 连接超时（秒）

# Bot 自动重启参数
BOT_RESTART_DELAY = 3       # Bot 崩溃后等待重启的秒数
MAX_BOT_RESTARTS = 30       # 连续重启上限（超过后停止，避免无限循环）

reflex_proc = None
bot_proc = None


def cleanup():
    """安全关闭所有子进程"""
    print("\n正在关闭所有服务...")
    for name, proc in [("Reflex", reflex_proc), ("Discord Bot", bot_proc)]:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
                print(f"  [{name}] 已关闭")
            except subprocess.TimeoutExpired:
                proc.kill()
                print(f"  [{name}] 已强制关闭")
    print("所有服务已关闭。")


def signal_handler(sig, frame):
    cleanup()
    sys.exit(0)


def _network_ready() -> bool:
    """检测 discord.com:443 是否可连通（DNS 解析 + TCP 连接）"""
    try:
        sock = socket.create_connection(
            (DISCORD_HOST, DISCORD_PORT), timeout=NET_CHECK_TIMEOUT)
        sock.close()
        return True
    except Exception:
        return False


def _wait_network_ready() -> bool:
    """等待网络就绪（开机初期 DNS/网络未初始化时，返回 False 则继续等待）

    返回 True 表示网络已就绪。
    """
    elapsed = 0
    while elapsed < NET_CHECK_MAX_WAIT:
        if _network_ready():
            return True
        print(f"  [NET] 网络未就绪，{NET_CHECK_INTERVAL}s 后重试...")
        time.sleep(NET_CHECK_INTERVAL)
        elapsed += NET_CHECK_INTERVAL
    print(f"  [NET] 等待网络就绪超时（{NET_CHECK_MAX_WAIT}s）")
    return False


def _spawn_reflex() -> subprocess.Popen:
    print("[Reflex] 启动 Reflex Dashboard...")
    return subprocess.Popen(
        [sys.executable, "-m", "reflex", "run"],
        cwd=DASHBOARD_DIR,
        creationflags=CREATE_FLAGS,
    )


def _spawn_bot() -> subprocess.Popen:
    print("[Bot] 启动 Discord Bot...")
    return subprocess.Popen(
        [sys.executable, "-m", "discord_bot.main"],
        creationflags=CREATE_FLAGS,
    )


def main():
    global reflex_proc, bot_proc

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("=" * 60)
    print("  IIP - 启动器")
    print("  Discord Bot + Reflex Dashboard (自动重启版)")
    print("=" * 60)

    # 首次启动前先等网络就绪，避免开机 DNS 未就绪导致 Bot 启动失败
    print("\n[网络] 检查 discord.com 连通性...")
    _wait_network_ready()
    print("[网络] 就绪")

    # 1. 启动 Reflex Dashboard
    print("\n[1/2] 启动 Reflex Dashboard...")
    reflex_proc = _spawn_reflex()
    print("  等待 Reflex 就绪（约 10 秒）...")
    time.sleep(10)
    if reflex_proc.poll() is not None:
        print("[FAIL] Reflex 首次启动失败，将自动重试")
    else:
        print("[ OK ] Reflex Dashboard 已启动")

    # 2. 启动 Discord Bot
    print("\n[2/2] 启动 Discord Bot...")
    bot_proc = _spawn_bot()

    print("\n" + "=" * 60)
    print("  全部就绪！按 Ctrl+C 关闭所有服务")
    print("  子进程异常退出将自动重启")
    print("=" * 60)

    # 监控子进程状态并自动重启
    bot_restart_count = 0
    try:
        while True:
            # ── Reflex 监控 ──
            if reflex_proc is not None and reflex_proc.poll() is not None:
                rc = reflex_proc.returncode
                print(f"\n[WARN] Reflex 已退出（退出码 {rc}），10s 后自动重启...")
                time.sleep(10)
                reflex_proc = _spawn_reflex()
                time.sleep(5)

            # ── Bot 监控 ──
            if bot_proc is not None and bot_proc.poll() is not None:
                rc = bot_proc.returncode
                bot_restart_count += 1
                if bot_restart_count > MAX_BOT_RESTARTS:
                    print(f"\n[FATAL] Bot 连续重启超过 {MAX_BOT_RESTARTS} 次，停止重启。请检查原因。")
                    bot_proc = None
                    break
                print(f"\n[WARN] Discord Bot 已退出（退出码 {rc}），"
                      f"{BOT_RESTART_DELAY}s 后重启（第 {bot_restart_count}/{MAX_BOT_RESTARTS} 次）...")
                time.sleep(BOT_RESTART_DELAY)
                # 重启前再次确认网络就绪
                if not _network_ready():
                    print("[NET] 网络中断，等待恢复...")
                    _wait_network_ready()
                bot_proc = _spawn_bot()
            else:
                # Bot 正常运行中，重置连续重启计数
                bot_restart_count = 0

            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()


if __name__ == "__main__":
    main()
