import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from premarket import SHANGHAI, select_plans
from strategy_settings import load, save, validate
from strategy_worker import Worker
from test_worker import Clock, FakeSim

STOCK = dict(code="002222", planned_buy_date="2026-11-13", planned_sell_date="2026-11-16",
             shallow=dict(buy_low=49,buy_high=50,stop_loss=48,take_profit=52),
             deep=dict(buy_low=39,buy_high=40,stop_loss=38,take_profit=42))


class SettingsTests(unittest.TestCase):
    def test_strategy_and_amount(self):
        day = datetime(2026,11,13).date()
        p = select_plans([STOCK],day,dict(strategy="conservative",target_amount="8000",
                                        min_amount="6000",max_amount="9000",buy_time="10:15"))[0]
        self.assertEqual((p["tier"],p["quantity"],p["limit_price"]),("deep",200,"40"))
        self.assertIn("10:15",p["buy_at"])
        self.assertEqual(p["take_profit"],"42")

    def test_validation_and_atomic_save(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory)/"settings.json"
            save(file,dict(buy_time="10:15"))
            for bad in [dict(min_amount=20001),dict(target_amount="NaN"),dict(max_amount="oops"),
                        dict(buy_time="12:30"),dict(strategy="unknown")]:
                with self.assertRaises(ValueError):
                    save(file,bad)
            self.assertEqual(load(file)["buy_time"],"10:15")

    def test_manual_catchup_and_no_duplicate(self):
        sim = FakeSim()
        with sqlite3.connect(":memory:") as db:
            worker=Worker(sim,db)
            worker.settings=validate(dict(buy_time="10:15"))
            with patch("strategy_worker.datetime",Clock), patch("strategy_worker.fetch_plans",
                    return_value={"stocks":[STOCK]}):
                Clock.current=datetime(2026,11,13,10,30,tzinfo=SHANGHAI)
                worker.tick(Clock.current)
                self.assertEqual(len(sim.rows),0)
                worker.tick(Clock.current,manual=True)
                self.assertEqual(len(sim.rows),1)
                worker.tick(Clock.current,manual=True)
                self.assertEqual(len(sim.rows),1)
                self.assertEqual(db.execute("select count(*) from orders").fetchone()[0],1)

    def test_manual_pending_receipt_kept(self):
        sim=FakeSim()
        with sqlite3.connect(":memory:") as db:
            worker=Worker(sim,db)
            key="2026-11-13/002222"
            db.execute("INSERT INTO plans VALUES (?,?,NULL)",(key,json.dumps(STOCK)))
            db.execute("""INSERT INTO orders(plan,side,day,name,price,qty,started,until)
                           VALUES (?,'买入','2026-11-13','样本','50',200,'09:20:00','09:20:30')""",(key,))
            with patch("strategy_worker.fetch_plans",return_value={"stocks":[STOCK]}):
                worker.tick(datetime(2026,11,13,10,30,tzinfo=SHANGHAI),manual=True)
            self.assertEqual(len(sim.rows),0)
