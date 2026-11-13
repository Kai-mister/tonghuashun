"""Authenticated loopback control channel for the installed Android manager."""
import hmac
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

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
        orders = [dict(r) for r in db.execute("""SELECT plan, day, side, qty, price, filled, done
                    FROM orders ORDER BY id DESC LIMIT 20""")]
        checks = [dict(r) for r in db.execute("""SELECT plan, day, total, available FROM morning_checks
                    ORDER BY day DESC, plan LIMIT 20""")]
    return dict(status=status, active=active, paused=paused, account=account[0] if account else "",
                orders=orders, checks=checks)


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
            if action == "pause":
                (STATE / "paused").touch(mode=0o600)
            elif action == "resume":
                if not running():
                    env = dict(os.environ)
                    env.pop("LD_LIBRARY_PATH",None)
                    subprocess.run(["/system/bin/sh","phone/background.sh"],env=env,check=True,timeout=10)
                (STATE / "paused").unlink(missing_ok=True)
            return self.reply(200,snapshot())
        except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError):
            return self.reply(503, {"error":"无法读取状态或启动策略"})

    def do_GET(self):
        if self.path == "/status":
            return self.handle_api("status")
        self.reply(404,{})

    def do_POST(self):
        if self.path in ("/pause","/resume"):
            return self.handle_api(self.path[1:])
        self.reply(404,{})

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1",18735), Handler).serve_forever()
