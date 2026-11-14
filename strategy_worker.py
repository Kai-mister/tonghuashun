"""Run the simulated strategy, with durable per-order reconciliation."""
import fcntl
import json
import logging
import os
import sqlite3
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from premarket import SHANGHAI, exit_progress, exit_reason, select_plans
from stock_api import fetch_plans
from strategy_settings import load, validate
from ths.simulator import Simulator

log = logging.getLogger(__name__)
TERMINAL = {"全部成交", "全部撤单", "部分撤单", "已撤", "废单", "场内废单"}


def match(order, rows):
    candidates = [r for r in rows if r["name"] == order["name"] and r["side"] == order["side"]
                  and Decimal(r["price"]) == Decimal(order["price"])
                  and r["quantity"] == order["qty"]
                  and (order["stamp"] == r["time"] if order["stamp"]
                       else order["started"] <= r["time"] <= order["until"])]
    if len(candidates) == 1:
        return candidates[0]


class Worker:
    def __init__(self, sim, db):
        self.sim = sim
        self.db = db
        self.cache_date = None
        self.cached_plans = []
        self.watch_status = {}
        self.settings = validate({})
        self.manual = False
        self.errors = []
        db.row_factory = sqlite3.Row
        db.executescript("""
          CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, data TEXT NOT NULL, exit TEXT);
          CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, plan TEXT, side TEXT,
            day TEXT, started TEXT, until TEXT, name TEXT, qty INTEGER, price TEXT, contract TEXT,
            stamp TEXT, filled INTEGER DEFAULT 0, done INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS buy_snapshots(
            order_id INTEGER PRIMARY KEY, total_before INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS morning_checks(
            plan TEXT PRIMARY KEY, day TEXT NOT NULL, total INTEGER, available INTEGER);
          CREATE TABLE IF NOT EXISTS identity(account TEXT PRIMARY KEY);
        """)
        sim.tab("查询")
        account = db.execute("SELECT account FROM identity").fetchone()
        if account and sim.account != account[0]:
            raise RuntimeError("策略账本绑定了其他模拟账户")
        with db:
            db.execute("INSERT OR IGNORE INTO identity VALUES (?)", (sim.account,))

    def submit(self, key, plan, side, qty, price):
        from datetime import timedelta
        baseline = self.sim.position(plan["code"])["total"] if side == "买入" else None
        def journal(name):
            nonlocal order_id
            now = datetime.now(SHANGHAI)
            if side == "买入" and not (now.date().isoformat()==plan["planned_buy_date"]
                                      and (now.strftime("%H:%M")==self.settings["buy_time"]
                                           or self.manual and buy_window(now))):
                raise RuntimeError("盘前挂单窗口已结束")
            if side == "卖出" and not market_open(now):
                raise RuntimeError("当前不在交易时段")
            with self.db:
                order_id = self.db.execute("""
                    INSERT INTO orders(plan, side, day, started, until, name, qty, price)
                    VALUES (?,?,?,?,?,?,?,?)""", (key,side,now.date().isoformat(),
                    (now-timedelta(seconds=3)).strftime("%H:%M:%S"),
                    (now+timedelta(seconds=30)).strftime("%H:%M:%S"), name,qty,str(price))).lastrowid
                if baseline is not None:
                    self.db.execute("INSERT INTO buy_snapshots VALUES (?,?)", (order_id,baseline))
        order_id = None
        receipt = self.sim.submit(side, plan["code"], qty, price, journal)
        with self.db:
            self.db.execute("UPDATE orders SET contract=? WHERE id=?", (receipt["contract"],order_id))
        log.info("模拟委托 %s %s %s 股，合同 %s", key,side,qty,receipt["contract"])

    def reconcile(self, now):
        pending = self.db.execute("SELECT * FROM orders WHERE done=0 AND day=?", (now.date().isoformat(),)).fetchall()
        if not pending:
            return
        rows = self.sim.report()
        for order in pending:
            row = match(order,rows)
            if not row or not order["filled"] <= row["filled"] <= order["qty"]:
                log.warning("未能唯一核对委托 %s", order["id"])
                continue
            with self.db:
                self.db.execute("UPDATE orders SET filled=?, stamp=?, done=? WHERE id=?",
                                (row["filled"],row["time"],row["status"] in TERMINAL,order["id"]))
            if order["side"]=="卖出" and row["status"] not in TERMINAL and row["filled"] < order["qty"]:
                plan = json.loads(self.db.execute("SELECT data FROM plans WHERE id=?",(order["plan"],)).fetchone()[0])
                if market_open(now) and now.strftime("%H:%M:%S") > order["until"]:
                    quote = self.sim.quote(plan["code"])
                    if Decimal(quote["limit"]) < Decimal(order["price"]):
                        self.sim.cancel(row, plan["code"])

    def tick(self, now, manual=False):
        self.manual = manual
        self.errors = []
        if manual:
            self.reconcile(now)
        day = now.date().isoformat()
        hm = now.strftime("%H:%M")
        if now.weekday() >= 5:
            return
        if hm == self.settings["buy_time"] or manual and buy_window(now):
            if self.cache_date != (day, str(self.settings)) or not self.cached_plans or manual:
                self.cached_plans = select_plans(fetch_plans()["stocks"], now.date(), self.settings)
                self.cache_date = (day, str(self.settings))
            for p in self.cached_plans:
                if not p["quantity"]:
                    continue
                key = day + "/" + p["code"]
                if not self.db.execute("SELECT 1 FROM orders WHERE plan=?", (key,)).fetchone():
                    with self.db:
                        self.db.execute("INSERT OR REPLACE INTO plans VALUES (?,?,NULL)",(key,json.dumps(p)))
                    try:
                        self.submit(key,p,"买入",p["quantity"],p["limit_price"])
                    except Exception as error:
                        self.errors.append(f"{p['code']} 买单未完成：{error}")
                        log.exception("模拟买单未完成 %s", key)
        self.reconcile(now)
        if manual:
            self.watch_status.clear()
        if not ("09:15" <= hm < "09:20" or market_open(now)):
            return
        for record in self.db.execute("SELECT * FROM plans").fetchall():
            try:
                self.monitor(record, now)
            except Exception as error:
                self.errors.append(f"{record['id']} 持仓或卖出异常：{error}")
                log.exception("模拟持仓查询或退出异常 %s", record["id"])

    def monitor(self, record, now):
        day = now.date().isoformat()
        p = json.loads(record["data"])
        orders = self.db.execute("SELECT * FROM orders WHERE plan=?", (record["id"],)).fetchall()
        bought = sum(o["filled"] for o in orders if o["side"]=="买入")
        sold = sum(o["filled"] for o in orders if o["side"]=="卖出")
        buys = [o for o in orders if o["side"] == "买入"]
        if not buys or day <= p["planned_buy_date"]:
            return
        key = record["id"]
        checked = self.db.execute("SELECT day FROM morning_checks WHERE plan=?", (key,)).fetchone()
        needs_recovery = any(not o["done"] for o in buys)
        if bought <= sold and not needs_recovery and checked:
            return
        if not checked or checked["day"] != day:
            holding = self.sim.position(p["code"])
            with self.db:
                if needs_recovery:
                    bought = self.recover_buy(key, p["code"], buys, sold, holding["total"])
                self.db.execute("INSERT OR REPLACE INTO morning_checks VALUES (?,?,?,?)",
                                (key,day,holding["total"],holding["available"]))
            log.info("模拟持仓核对 %s 总数 %d 可卖 %d 策略余额 %d",
                     key, holding["total"], holding["available"], bought-sold)
        if bought <= sold:
            self.watch_status[key] = (now, 0)
            return
        previous = self.watch_status.get(key)
        # Recheck temporarily unavailable shares; frozen or unfilled orders may change.
        if previous and previous[0].date() == now.date():
            elapsed = (now - previous[0]).total_seconds()
            if (not market_open(now) and previous[1]) or (not previous[1] and elapsed < 60):
                return
        quote = self.sim.quote(p["code"])
        protected = self.protected_shares(p["code"])
        available = min(bought - sold, quote["available"], max(0, quote["total"] - protected))
        self.watch_status[key] = (now, available)
        if not previous or previous[0].date() != now.date() or previous[1] != available:
            log.info("模拟策略监控 %s，可卖 %s 股", key, available)
        if not market_open(now) or not available:
            return
        reserved = sum(o["qty"]-o["filled"] for o in orders if o["side"]=="卖出" and not o["done"])
        progress = exit_progress(bought_filled=bought,sold_filled=sold,sell_open=reserved,
                                 available=available)
        reason = record["exit"] or exit_reason(p,last_price=quote["last"],now=now,
                                                sellable_remaining=bought-sold)
        if reason:
            with self.db:
                self.db.execute("UPDATE plans SET exit=? WHERE id=?",(reason,record["id"]))
            if progress["can_submit"]:
                self.submit(record["id"],p,"卖出",progress["can_submit"],quote["limit"])

    def protected_shares(self, code):
        # Manually tested position, independent of every strategy plan.
        return 100 if self.sim.account == "**1326" and code == "002222" else 0

    def recover_buy(self, key, code, buys, sold, total):
        bought = sum(o["filled"] for o in buys)
        if len(buys) != 1:
            return bought
        buy = buys[0]
        snapshot = self.db.execute("SELECT total_before FROM buy_snapshots WHERE order_id=?",
                                   (buy["id"],)).fetchone()
        if not snapshot:
            log.warning("旧委托 %s 缺少买前持仓基准，仅使用已核实成交", key)
            return bought
        # Another strategy transaction in the same stock invalidates a simple delta.
        others = self.db.execute("""
            SELECT 1 FROM orders o JOIN plans p ON p.id=o.plan
            WHERE o.plan<>? AND o.id>? AND json_extract(p.data,'$.code')=? LIMIT 1
        """, (key,buy["id"],code)).fetchone()
        inferred = total - max(snapshot[0], self.protected_shares(code)) + sold
        if others or not bought <= inferred <= buy["qty"]:
            log.warning("模拟持仓变化不能唯一归入买单 %s", key)
            return bought
        self.db.execute("UPDATE orders SET filled=?, done=1 WHERE id=?", (inferred,buy["id"]))
        return inferred


def buy_window(now):
    hm = now.strftime("%H:%M")
    return now.weekday() < 5 and ("09:15" <= hm < "11:30" or "13:00" <= hm < "15:00")


def market_open(now):
    hm = now.strftime("%H:%M")
    return now.weekday() < 5 and ("09:30" <= hm < "11:30" or "13:00" <= hm < "15:00")


def run(trader, path):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path)+".lock","a") as lock, sqlite3.connect(path) as db:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            try:
                worker = Worker(Simulator(trader), db)
                break
            except RuntimeError:
                log.exception("等待可核实的模拟账户")
                time.sleep(30)
        log.info("手机模拟策略已就绪，账户 %s", worker.sim.account)
        while True:
            try:
                paused = (path.parent / "paused").exists()
                heartbeat = path.parent / "heartbeat"
                pending = path.parent / "heartbeat.tmp"
                pending.write_text(f"{os.getpid()} {'paused' if paused else 'running'}")
                pending.replace(heartbeat)
                worker.settings = load(path.parent / "settings.json")
                request = path.parent / "check-request"
                if request.exists():
                    request.unlink()
                    result = path.parent / "check-result"
                    try:
                        now = datetime.now(SHANGHAI)
                        worker.tick(now, manual=True)
                        unresolved = db.execute("SELECT COUNT(*) FROM orders WHERE done=0 AND stamp IS NULL").fetchone()[0]
                        message = "检查完成" if buy_window(now) else "检查完成，当前非交易时段，未补单"
                        if unresolved:
                            message += f"，{unresolved} 笔回执待核对，已保留原委托"
                        if worker.errors:
                            message += "；" + "；".join(worker.errors)
                        result.write_text(message)
                    except Exception as error:
                        result.write_text("检查失败：" + str(error))
                        raise
                elif not paused:
                    worker.tick(datetime.now(SHANGHAI))
            except Exception:
                log.exception("模拟策略执行异常")
            time.sleep(3)
