"""临时：手动启动 reflex 编译，捕获页面编译错误"""
import subprocess, sys, time, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

dashboard_dir = r"e:\WebApp\Infinite-Immortal-Path\dashboard_app"
p = subprocess.Popen(
    [sys.executable, "-m", "reflex", "run"],
    cwd=dashboard_dir,
    stdout=open(os.path.join(dashboard_dir, "_rc_out.log"), "w", encoding="utf-8"),
    stderr=open(os.path.join(dashboard_dir, "_rc_err.log"), "w", encoding="utf-8"),
)
time.sleep(22)
if p.poll() is None:
    print("Reflex RUNNING")
    # 检查端口
    import socket
    s = socket.socket()
    try:
        s.settimeout(2)
        s.connect(("127.0.0.1", 3000))
        print("PORT 3000 OPEN")
    except Exception as e:
        print("PORT 3000 CLOSED:", e)
    finally:
        s.close()
    p.terminate()
    try:
        p.wait(timeout=5)
    except Exception:
        p.kill()
else:
    print("Reflex EXITED rc=", p.returncode)
