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

    def test_disconnected_buy_recovery_excludes_manual_shares(self):
        from unittest.mock import Mock
        for total, free, expected_fill, expected_free in [
                (100, 100, 0, 0), (300, 300, 200, 200), (200, 70, 100, 70)]:
            with self.subTest(total=total), sqlite3.connect(":memory:") as db:
                sim = FakeSim()
                sim.account = "**1326"
                sim.position = Mock(return_value=dict(total=total, available=free))
                sim.quote = Mock(return_value=dict(total=total, available=free))
                worker = Worker(sim, db)
                key = "2026-11-13/002222"
                plan = dict(code="002222", planned_buy_date="2026-11-13")
                db.execute("INSERT INTO plans VALUES (?,?,NULL)", (key,json.dumps(plan)))
                db.execute("INSERT INTO orders(plan,side,day,qty) VALUES (?,'买入',?,200)",
                           (key,plan["planned_buy_date"]))
                db.execute("INSERT INTO buy_snapshots VALUES (1,100)")
                worker.tick(datetime(2026,11,16,9,16,tzinfo=SHANGHAI))
                sim.position.assert_called_once_with("002222")
                self.assertEqual(db.execute("SELECT filled FROM orders").fetchone()[0], expected_fill)
                self.assertEqual(worker.watch_status[key][1], expected_free)

    def test_triggers(self):
        for price, stamp, reason in [("48","10:10","stop_loss"),("52","10:10","take_profit"),
                                     ("50","14:50","deadline")]:
            with self.subTest(reason=reason):
                self.scenario(price,"2026-11-16T"+stamp,reason)
