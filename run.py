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

# pythonw（无控制台）下 stdout/stderr 是块缓冲，print 不会实时写入重定向文件。
# 强制行缓冲/无缓冲，保证 nssm 日志实时可见，便于诊断。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(line_buffering=True)
    except Exception:
        pass

ROOT = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_DIR = os.path.join(ROOT, "dashboard_app")
sys.path.insert(0, ROOT)  # 让 run.py 能 import shared_lib

from shared_lib.crud import init_default_bot, get_active_bots, set_bot_error, set_bot_active

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
MAX_BOT_RESTARTS = 30       # 单个 Bot 连续重启上限（超过后停止，避免无限循环）

reflex_proc = None
bot_procs: dict[str, subprocess.Popen] = {}   # bot_id -> 子进程
bot_restart_counts: dict[str, int] = {}       # bot_id -> 连续重启次数
bot_start_times: dict[str, float] = {}        # bot_id -> 进程启动时间戳
QUICK_FAIL_SECONDS = 15   # 启动后在该时间内退出视为不可恢复的配置/登录错误


def cleanup():
    """安全关闭所有子进程"""
    print("\n正在关闭所有服务...")
    for name, proc in [("Reflex", reflex_proc)] + [
        (f"Bot:{bid}", p) for bid, p in bot_procs.items()
    ]:
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


def _venv_python() -> str:
    """优先使用 venv 的控制台版 python.exe（能正常跑 bot/reflex）。

    不能用 sys.executable：nssm 用 pythonw（GUI 无控制台版）启动 run.py 时，
    sys.executable 指向 pythonw，而 pythonw 下 discord_bot.main 会静默退出
    （已实测：python.exe 跑 bot 存活，pythonw 跑 bot 约 15s 内退出）。
    """
    venv_py = os.path.join(ROOT, "venv", "Scripts", "python.exe")
    if os.path.exists(venv_py):
        return venv_py
    return sys.executable


def _spawn_reflex() -> subprocess.Popen:
    print("[Reflex] 启动 Reflex Dashboard...")
    return subprocess.Popen(
        [_venv_python(), "-m", "reflex", "run"],
        cwd=DASHBOARD_DIR,
        creationflags=CREATE_FLAGS,
    )


def _spawn_bot(bot_id: str, bot_name: str) -> subprocess.Popen:
    print(f"[Bot] 启动 Discord Bot: {bot_id} ({bot_name})...")
    # 三个标准流全部用 DEVNULL：run.py 由 pythonw 启动时自身 stdio 是无效/异常句柄，
    # 若 bot 子进程继承它们，discord.py 的 asyncio 会读到 EOF 提前退出（实测退出码 0）。
    # bot 自身的运行状态与启动错误都写入数据库（心跳/ last_error），无需依赖 stdio。
    return subprocess.Popen(
        [_venv_python(), "-m", "discord_bot.main", "--bot-id", bot_id],
        creationflags=CREATE_FLAGS,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _read_last_error(bot_id: str) -> str:
    """从数据库读取 bot 最近一次启动失败原因（由 bot 进程自行写入）"""
    try:
        from shared_lib.crud import get_bot_status
        st = get_bot_status(bot_id)
        return st.get("last_error") or "进程异常退出（无错误信息）"
    except Exception as e:
        return f"读取错误信息失败: {e}"


def _spawn_active_bots():
    """根据数据库中所有已激活机器人，各自拉起一个独立进程"""
    bots = get_active_bots()  # [(bot_id, bot_name), ...]
    if not bots:
        print("[Bot] 没有已激活的机器人，跳过启动。")
        return
    for bot_id, bot_name in bots:
        if bot_id in bot_procs and bot_procs[bot_id].poll() is None:
            continue  # 已在运行
        bot_procs[bot_id] = _spawn_bot(bot_id, bot_name)
        bot_restart_counts.setdefault(bot_id, 0)


def main():
    global reflex_proc

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("=" * 60)
    print("  IIP - 启动器")
    print("  Discord Bot(s) + Reflex Dashboard (自动重启版)")
    print("=" * 60)

    # 确保默认机器人记录存在
    init_default_bot()

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

    # 2. 启动所有已激活的 Discord Bot（一 bot 一进程）
    print("\n[2/2] 启动 Discord Bot(s)...")
    _spawn_active_bots()

    print("\n" + "=" * 60)
    print("  全部就绪！按 Ctrl+C 关闭所有服务")
    print("  子进程异常退出将自动重启")
    print("=" * 60)

    # 监控子进程状态并自动重启
    try:
        while True:
            # ── Reflex 监控 ──
            if reflex_proc is not None and reflex_proc.poll() is not None:
                rc = reflex_proc.returncode
                print(f"\n[WARN] Reflex 已退出（退出码 {rc}），10s 后自动重启...")
                time.sleep(10)
                reflex_proc = _spawn_reflex()
                time.sleep(5)

            # ── 热加载：轮询数据库，发现新激活的 Bot 自动拉起进程 ──
            # （用户在后台新增并填好 Token 保存后，无需重启启动器即可上线）
            try:
                active = dict(get_active_bots())
            except Exception as e:
                active = {}
                print(f"[WARN] 读取 active bots 失败: {e}")
            for bot_id, bot_name in active.items():
                if bot_id not in bot_procs or bot_procs.get(bot_id) is None or bot_procs[bot_id].poll() is not None:
                    if bot_id in bot_procs and bot_procs[bot_id] is not None and bot_procs[bot_id].poll() is not None:
                        # 已退出，交给下方重启逻辑处理
                        continue
                    print(f"[HOT] 检测到新激活机器人 {bot_id}，拉起进程...")
                    bot_procs[bot_id] = _spawn_bot(bot_id, bot_name)
                    bot_restart_counts[bot_id] = 0
                    bot_start_times[bot_id] = time.time()

            # ── 停止逻辑：被设为 inactive 的 Bot，终止其进程 ──
            active_ids = set(active.keys())
            for bot_id in list(bot_procs.keys()):
                if bot_id not in active_ids:
                    proc = bot_procs.pop(bot_id, None)
                    bot_restart_counts.pop(bot_id, None)
                    if proc is not None and proc.poll() is None:
                        print(f"[STOP] 机器人 {bot_id} 已被停用，终止进程...")
                        proc.terminate()
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()

            # ── 各 Bot 监控（按 bot_id 维度独立重启）──
            for bot_id in list(bot_procs.keys()):
                proc = bot_procs.get(bot_id)
                if proc is None or proc.poll() is None:
                    continue  # 正常运行中
                rc = proc.returncode
                # 快速失败判定：启动后极短时间内就退出（配置/登录错误），不再无限重启
                started = bot_start_times.get(bot_id, 0)
                if rc != 0 and (time.time() - started) < QUICK_FAIL_SECONDS:
                    err_line = _read_last_error(bot_id)
                    print(f"\n[CRASH] Bot {bot_id} 启动即失败（退出码 {rc}），停止重启并标记错误。")
                    print(f"        原因: {err_line}")
                    set_bot_error(bot_id, err_line)
                    set_bot_active(bot_id, False)  # 标记停止，UI 反映“启动失败”
                    bot_procs.pop(bot_id, None)
                    bot_restart_counts.pop(bot_id, None)
                    bot_start_times.pop(bot_id, None)
                    continue
                bot_restart_counts[bot_id] = bot_restart_counts.get(bot_id, 0) + 1
                if bot_restart_counts[bot_id] > MAX_BOT_RESTARTS:
                    print(f"\n[FATAL] Bot {bot_id} 连续重启超过 {MAX_BOT_RESTARTS} 次，停止重启。请检查原因。")
                    set_bot_error(bot_id, "连续重启次数过多，请检查 Token/网络后手动启动")
                    set_bot_active(bot_id, False)
                    bot_procs.pop(bot_id, None)
                    bot_restart_counts.pop(bot_id, None)
                    bot_start_times.pop(bot_id, None)
                    continue
                print(f"\n[WARN] Discord Bot {bot_id} 已退出（退出码 {rc}），"
                      f"{BOT_RESTART_DELAY}s 后重启（第 {bot_restart_counts[bot_id]}/{MAX_BOT_RESTARTS} 次）...")
                time.sleep(BOT_RESTART_DELAY)
                # 重新取出最新名称（名称可能已在库中被修改）与最新 active 状态
                fresh = dict(get_active_bots())
                if bot_id not in fresh:
                    # 该 Bot 已被停用，终止并移出管理
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    bot_procs.pop(bot_id, None)
                    bot_restart_counts.pop(bot_id, None)
                    bot_start_times.pop(bot_id, None)
                    continue
                # 仅做单次网络探测，不阻塞整个循环（网络不通就让 bot 自行尝试连接）
                if not _network_ready():
                    print("[NET] 网络暂不通，跳过本轮重启，稍后重试...")
                    continue
                name = fresh.get(bot_id, bot_id)
                bot_procs[bot_id] = _spawn_bot(bot_id, name)
                bot_start_times[bot_id] = time.time()

            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()


if __name__ == "__main__":
    main()
