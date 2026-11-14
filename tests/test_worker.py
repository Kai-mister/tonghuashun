import json
import sqlite3
import unittest
from datetime import datetime
from unittest.mock import patch

from premarket import SHANGHAI
from strategy_worker import Worker


class Clock(datetime):
    current = None

    @classmethod
    def now(cls, tz=None):
        return cls.current


class FakeSim:
    account = "test"

    def __init__(self):
        self.rows = []
        self.last = "50"
        self.available = 200

    def tab(self, name):
        pass

    def submit(self, side, code, qty, price, journal):
        journal("样本")
        self.rows.append(dict(name="样本", time=Clock.current.strftime("%H:%M:%S"), side=side,
                              price=price, quantity=qty, filled=0, status="未成交"))
        return {"contract": str(len(self.rows))}

    def report(self):
        return self.rows

    def position(self, code):
        return dict(total=0 if not self.rows and Clock.current.hour==9 and Clock.current.minute==20 else 200, available=self.available)

    def quote(self, code):
        return dict(last=self.last, limit="47.00", available=self.available, total=200)


class WorkerTests(unittest.TestCase):
    def scenario(self, exit_price, trigger, reason):
        sim = FakeSim()
        db = sqlite3.connect(":memory:")
        worker = Worker(sim, db)
        data = dict(code="002222", planned_buy_date="2026-11-13", planned_sell_date="2026-11-16",
                    shallow=dict(buy_low=49.95,buy_high=50,take_profit=52,stop_loss=48))
        def tick(stamp):
            Clock.current = datetime.fromisoformat(stamp).replace(tzinfo=SHANGHAI)
            worker.tick(Clock.current)
        with patch("strategy_worker.fetch_plans",return_value={"stocks":[data]}), patch("strategy_worker.datetime", Clock):
            tick("2026-11-13T09:19")
            self.assertFalse(sim.rows)
            tick("2026-11-13T09:20")
            self.assertEqual(len(sim.rows), 1)
            worker = Worker(sim, db)
            tick("2026-11-13T09:20:30")
            self.assertEqual(len(sim.rows), 1)
            sim.rows[0].update(status="全部成交",filled=200)
            tick("2026-11-13T09:31")
            sim.rows.clear()
            sim.available = 0
            tick("2026-11-16T09:15")
            key = "2026-11-13/002222"
            self.assertEqual(worker.watch_status[key][1], 0)
            sim.available = 200
            tick("2026-11-16T09:16")
            self.assertEqual(worker.watch_status[key][1], 200)
            self.assertFalse(sim.rows)
            sim.last = exit_price
            tick(trigger)
            self.assertEqual(db.execute("select exit from plans").fetchone()[0], reason)
            self.assertEqual(sim.rows[0]["side"], "卖出")
            sim.rows[0].update(status="部分成交",filled=100)
            tick(trigger)
            self.assertEqual(len(sim.rows), 1)
            sim.rows[0].update(status="全部成交",filled=200)
            tick(trigger)
            self.assertEqual(db.execute("select filled,done from orders where side='卖出'").fetchone()[:], (200,1))
        db.close()

    def test_only_verified_strategy_shares_are_managed(self):
        from unittest.mock import Mock
        # Existing/manual shares, lost receipts, partial fills, and account tails
        # must not change ownership. Available quantity only caps that ownership.
        for account in ["test", "**1326"]:
            for total, free, filled, sold, expected in [
                    (100, 100, 0, 0, 0), (300, 300, 0, 0, 0),
                    (300, 300, 200, 0, 200), (200, 70, 100, 0, 70),
                    (900, 900, 200, 100, 100), (50, 50, 200, 0, 50)]:
                with self.subTest(account=account, total=total, filled=filled, sold=sold), sqlite3.connect(":memory:") as db:
                    sim = FakeSim()
                    sim.account = account
                    sim.position = Mock(return_value=dict(total=total, available=free))
                    sim.quote = Mock(return_value=dict(total=total, available=free))
                    worker = Worker(sim, db)
                    key = "2026-11-13/002222"
                    plan = dict(code="002222", planned_buy_date="2026-11-13")
                    db.execute("INSERT INTO plans VALUES (?,?,NULL)", (key,json.dumps(plan)))
                    db.execute("INSERT INTO orders(plan,side,day,qty,filled,stamp) VALUES (?,'买入',?,200,?,?)",
                               (key,plan["planned_buy_date"],filled,"09:20:00" if filled else None))
                    if sold:
                        db.execute("INSERT INTO orders(plan,side,day,qty,filled,done) VALUES (?,'卖出',?,100,?,1)",
                                   (key,plan["planned_buy_date"],sold))
                    db.execute("INSERT INTO buy_snapshots VALUES (1,100)")
                    worker.tick(datetime(2026,11,16,9,16,tzinfo=SHANGHAI))
                    sim.position.assert_called_once_with("002222")
                    self.assertEqual(db.execute("SELECT filled,done FROM orders WHERE side='买入'").fetchone()[:], (filled,0))
                    self.assertEqual(worker.watch_status[key][1], expected)
                    self.assertTrue(worker.errors)

    def test_upgrade_revokes_inferred_fills_but_preserves_verified_fills(self):
        with sqlite3.connect(":memory:") as db:
            sim = FakeSim()
            Worker(sim, db)
            db.execute("DELETE FROM migrations")
            db.execute("INSERT INTO orders(side,qty,filled,done) VALUES ('买入',200,200,1)")
            db.execute("INSERT INTO orders(side,qty,filled,done,stamp) VALUES ('买入',200,100,1,'09:20:00')")
            Worker(sim, db)
            self.assertEqual([tuple(r) for r in db.execute("SELECT filled,done FROM orders ORDER BY id")],
                             [(0,0),(100,1)])
            Worker(sim, db)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM migrations").fetchone()[0],1)

    def test_triggers(self):
        for price, stamp, reason in [("48","10:10","stop_loss"),("52","10:10","take_profit"),
                                     ("50","14:50","deadline")]:
            with self.subTest(reason=reason):
                self.scenario(price,"2026-11-16T"+stamp,reason)
