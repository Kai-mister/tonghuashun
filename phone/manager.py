"""Authenticated loopback control channel for the installed Android manager."""
from strategy_settings import load, save
from phone.native import enabled as native, start as native_start
from phone.backend import API_VERSION, UPDATE_PROTOCOL, MAX_BUNDLE, installed_digest
from phone.update import launch
import hmac
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import socket
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

BACKEND_DIGEST = installed_digest()
STATE = Path("state")
TOKEN = (STATE / "manager.key").read_text().strip()
if len(TOKEN) < 32:
    raise RuntimeError("管理凭据无效")


def running():
    try:
        pid = int((STATE / "worker.pid").read_text())
        return b"phone/local.py" in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except (OSError, ValueError):
        return False


def maintain(reason):
    """Recover dead execution services without unpausing or requesting catch-up."""
    if (STATE / 'paused').exists() or (STATE / 'migrated-to-app').exists():
        return
    try:
        with socket.create_connection(('127.0.0.1', 19008) if native() else ('::1', 9008), timeout=.5):
            ui_ready = True
    except OSError:
        ui_ready = False
    restart = not running() or not ui_ready
    if restart:
        env = dict(os.environ)
        env.pop('LD_LIBRARY_PATH', None)
        if native():
            if not running() and ui_ready:
                native_start('worker')
        else:
            subprocess.run(['/system/bin/sh', 'phone/background.sh'], env=env, check=True, timeout=10)
    payload = dict(at=datetime.now().isoformat(), reason=reason, restarted=restart)
    temp = STATE / 'watch-heartbeat.tmp'
    temp.write_text(json.dumps(payload, ensure_ascii=False))
    temp.replace(STATE / 'watch-heartbeat.json')


def snapshot():
    active = running()
    paused = (STATE / "paused").exists()
    status = "已停止"
    heartbeat = STATE / "heartbeat"
    if active:
        status = "等待就绪"
        if heartbeat.exists():
            import time
            heartbeat_pid, phase = heartbeat.read_text().split()
            if heartbeat_pid == (STATE / "worker.pid").read_text().strip():
                status = ("暂停中" if paused else "运行中")
                if paused and phase == "paused":
                    status = "已暂停"
                elif time.time()-heartbeat.stat().st_mtime > 90:
                    status = "等待响应"
    with sqlite3.connect("file:state/strategy.sqlite3?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        account = db.execute("SELECT account FROM identity LIMIT 1").fetchone()
        orders = [dict(r) for r in db.execute("""SELECT plan, name, day, side, qty, price, filled, done
                    FROM orders ORDER BY id DESC LIMIT 20""")]
        checks = [dict(r) for r in db.execute("""SELECT plan, day, total, available FROM morning_checks
                    ORDER BY day DESC, plan LIMIT 20""")]
    update = STATE / "update-result.json"
    return dict(api_version=API_VERSION, backend_digest=BACKEND_DIGEST, update_protocol=UPDATE_PROTOCOL,
                update=json.loads(update.read_text()) if update.exists() else {}, status=status, active=active, paused=paused, account=account[0] if account else "",
                orders=orders, checks=checks, settings=load(STATE / "settings.json"),
                check_result="等待执行" if (STATE / "check-request").exists() else
                ((STATE / "check-result").read_text() if (STATE / "check-result").exists() else ""))


def handoff():
    """User-initiated migration; fence old worker before returning a stable backup."""
    import base64
    from phone.update import stop, pid_for
    if not (STATE / 'paused').exists():
        raise ValueError('请先暂停旧策略')
    pid = pid_for('worker')
    if pid and (STATE / 'heartbeat').read_text().split() != [str(pid), 'paused']:
        raise ValueError('等待旧策略完成当前操作')
    stop('worker')
    # UiAutomation suppresses enabled accessibility services unless disconnected.
    import signal
    for process in Path('/proc').iterdir():
        try:
            if b'com.wetest.uia2.Main' in (process / 'cmdline').read_bytes().split(b'\0'):
                os.kill(int(process.name), signal.SIGTERM)
        except (OSError, ValueError):
            continue
    backup = STATE / 'native-migration.sqlite3'
    with sqlite3.connect('state/strategy.sqlite3') as source, sqlite3.connect(backup) as dest:
        source.backup(dest)
    files = {'state/strategy.sqlite3': backup.read_bytes()}
    for name in ('state/settings.json', '.config/redis-racknerd/stock-api.token'):
        files[name] = Path(name).read_bytes()
    (STATE / 'migrated-to-app').touch(mode=0o600)
    return {'files': {k: base64.b64encode(v).decode() for k,v in files.items()}}


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_api(self, action):
        if not hmac.compare_digest(self.headers.get("Authorization",""), "Bearer "+TOKEN):
            return self.reply(403, {})
        try:
            if (STATE / 'migrated-to-app').exists() and action not in ('status', 'handoff'):
                raise ValueError('已迁移到 App，旧执行器禁止恢复')
            if action == 'diagnostics':
                return self.reply(200, dict(runtime='app' if native() else 'shell', uid=os.getuid(),
                    heartbeat=(STATE/'heartbeat').read_text() if (STATE/'heartbeat').exists() else '',
                    worker_log=(STATE/'worker.log').read_text()[-6000:] if (STATE/'worker.log').exists() else ''))
            if action == 'verify':
                if not native() or not (STATE / 'paused').exists():
                    raise ValueError('无障碍自检仅允许在 App 内置策略暂停时运行')
                if running() and (STATE / 'heartbeat').read_text().split() != [(STATE / 'worker.pid').read_text().strip(), 'paused']:
                    raise ValueError('请等待策略完成当前操作后再自检')
                from phone.local import LocalTrader
                from ths.simulator import Simulator
                sim = Simulator(LocalTrader())
                holdings = sim.holdings()
                rows = sim.report()
                return self.reply(200, dict(status='自检通过', account=sim.account, holdings=holdings, orders=rows))
            if action == 'handoff':
                if native():
                    raise ValueError('已经是 App 内置后台')
                return self.reply(200, handoff())
            if action == "upgrade":
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BUNDLE:
                    raise ValueError("升级包大小无效")
                launch(self.rfile.read(length))
                return self.reply(202, {"accepted": True})
            update = STATE / "update-result.json"
            if action != "status" and update.exists() and json.loads(update.read_text()).get("phase") == "updating":
                raise ValueError("后台正在升级，请等待完成")
            if action == "maintain":
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024:
                    raise ValueError("值守请求长度无效")
                body = json.loads(self.rfile.read(length))
                maintain(str(body.get("reason", "watch"))[:40])
            elif action == "settings":
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 2048:
                    raise ValueError("设置请求长度无效")
                save(STATE / "settings.json", json.loads(self.rfile.read(length)))
            elif action == "check":
                if not running():
                    raise ValueError("请先启动策略")
                (STATE / "check-request").touch(mode=0o600)
            elif action == "pause":
                (STATE / "paused").touch(mode=0o600)
            elif action == "resume":
                if not running():
                    env = dict(os.environ)
                    env.pop("LD_LIBRARY_PATH",None)
                    if native():
                        native_start('worker')
                    else:
                        subprocess.run(["/system/bin/sh","phone/background.sh"],env=env,check=True,timeout=10)
                (STATE / "paused").unlink(missing_ok=True)
            return self.reply(200,snapshot())
        except (ValueError, RuntimeError) as error:
            return self.reply(400, {"error":str(error)})
        except (OSError, sqlite3.Error, subprocess.SubprocessError):
            return self.reply(503, {"error":"无法读取状态或启动策略"})

    def do_GET(self):
        if self.path in ("/status", "/diagnostics"):
            return self.handle_api(self.path[1:])
        self.reply(404,{})

    def do_POST(self):
        if self.path in ("/pause","/resume","/settings","/check","/upgrade","/maintain","/handoff","/verify"):
            return self.handle_api(self.path[1:])
        self.reply(404,{})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1",18736 if native() else 18735), Handler)
    (STATE / 'manager.pid').write_text(str(os.getpid()))
    server.serve_forever()
