import json
import sqlite3
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime
from unittest.mock import Mock, patch
from premarket import SHANGHAI
from strategy_worker import Worker
from ths.simulator import Simulator
from test_worker import FakeSim

class HoldingsBatchTests(unittest.TestCase):
    def setUp(self):
        plans = patch('strategy_worker.fetch_plans', return_value={'stocks': []})
        plans.start()
        self.addCleanup(plans.stop)

    def at(self, day, hour, minute):return datetime(2026,11,day,hour,minute,tzinfo=SHANGHAI)

    def test_schedule_once_persists_and_manual_does_not_replace_scheduled(self):
        with sqlite3.connect(':memory:') as db:
            sim=FakeSim();sim.holdings=Mock(return_value=[])
            w=Worker(sim,db)
            for minute in [15,16,17]:w.tick(self.at(19,9,minute))
            sim.holdings.assert_not_called()
            w.check_holdings(self.at(19,10,0),force=True)
            w.tick(self.at(19,16,29))
            w.tick(self.at(19,9,20));w.tick(self.at(19,9,20))
            Worker(sim,db).tick(self.at(19,9,20))
            self.assertEqual(sim.holdings.call_count,2)
            Worker(sim,db).tick(self.at(20,9,20))
            self.assertEqual(sim.holdings.call_count,3)

    def test_failed_scan_not_retried_and_keeps_previous_snapshot(self):
        with sqlite3.connect(':memory:') as db:
            sim=FakeSim();sim.holdings=Mock(side_effect=RuntimeError('incomplete'))
            w=Worker(sim,db)
            db.execute("INSERT INTO morning_checks VALUES ('p','2026-11-18',200,0)")
            w.tick(self.at(19,9,20));Worker(sim,db).tick(self.at(19,9,20))
            sim.holdings.assert_called_once()
            self.assertEqual(db.execute('SELECT total FROM morning_checks').fetchone()[0],200)
            self.assertEqual(db.execute('SELECT status FROM holdings_runs').fetchone()[0],'failed')

    def test_tplus_one_monitoring_uses_total_and_never_infers_fills(self):
        with sqlite3.connect(':memory:') as db:
            sim=FakeSim();sim.position=Mock();sim.holdings=Mock(return_value=[dict(name='样本',total=500,available=0)])
            w=Worker(sim,db)
            plan=dict(code='301236',planned_buy_date='2026-11-19',liquidate_at='2026-11-20T14:50:00+08:00',stop_loss='1',take_profit='99')
            db.execute('INSERT INTO plans VALUES (?,?,NULL)',('p',json.dumps(plan)))
            db.execute("INSERT INTO orders(plan,name,side,day,qty,filled,done,stamp) VALUES ('p','样本','买入','2026-11-19',300,300,1,'09:30:00')")
            w.tick(self.at(19,9,20))
            w=Worker(sim,db)
            with patch('strategy_worker.fetch_quotes',return_value={'301236':dict(last='34')}):w.tick(self.at(20,10,0))
            self.assertEqual(w.watch_status['p'][1],300)
            sim.position.assert_not_called()
            self.assertEqual(db.execute('SELECT filled FROM orders').fetchone()[0],300)

    @patch('ths.simulator.time.sleep')
    def test_scrolls_complete_list_without_stock_search(self,sleep):
        s=Simulator(Mock());s.tab=Mock();s.check_account=Mock();s.form=Mock()
        a=dict(name='A',total=100,available=100);b=dict(name='B',total=200,available=0)
        s.holdings_page=Mock(side_effect=[([a],False,[0,0,100,100]),([a],False,[0,0,100,100]),
                                              ([a],False,[0,0,100,100]),([a,b],True,[0,0,100,100])])
        self.assertEqual(s.holdings(),[a,b]);s.form.assert_not_called()

    def test_real_row_schema_and_footer(self):
        s=Simulator(Mock())
        root=ET.fromstring('<hierarchy><node text="持仓/可用"/><node resource-id="'+s.pkg+':id/recyclerview_id" bounds="[0,0][100,100]" scrollable="false"><node>'+
          ''.join('<node text="'+v+'"/>' for v in ['软通动力','10239','26','0.2%','300','0','34.04','34.13'])+
          '</node><node><node resource-id="'+s.pkg+':id/stock_manage" text="持仓管理"/></node></node></hierarchy>')
        s.nodes=Mock(return_value=list(root.iter('node')))
        self.assertEqual(s.holdings_page(),([dict(name='软通动力',total=300,available=0)],True,None))

    def test_manual_fill_sync_and_next_morning_checked_once(self):
        with sqlite3.connect(':memory:') as db:
            sim=FakeSim()
            sim.holdings=Mock(return_value=[dict(name='样本',total=300,available=0)])
            sim.report=Mock(return_value=[dict(name='样本',side='买入',price='34.21',
                quantity=300,filled=300,status='全部成交',time='09:30:00')])
            w=Worker(sim,db)
            plan=dict(code='301236',planned_buy_date='2026-11-19',liquidate_at='2026-11-20T14:50:00+08:00',stop_loss='1',take_profit='99')
            db.execute('INSERT INTO plans VALUES (?,?,NULL)',('p',json.dumps(plan)))
            db.execute("INSERT INTO orders(plan,name,side,day,qty,filled,done,stamp,price) VALUES ('p','样本','买入','2026-11-19',300,0,0,'09:30:00','34.21')")
            # Manual checks still synchronize same-day delayed fills.
            w.check_holdings(self.at(19,10,0), force=True)
            self.assertEqual(tuple(db.execute('SELECT filled,done FROM orders').fetchone()),(300,1))
            self.assertEqual(db.execute('SELECT total FROM morning_checks').fetchone()[0],300)
            sim.holdings.return_value=[dict(name='样本',total=300,available=300)]
            w=Worker(sim,db)
            with patch('strategy_worker.fetch_plans',return_value={'stocks':[]}):
                w.tick(self.at(20,9,20));w.tick(self.at(20,9,20))
                Worker(sim,db).tick(self.at(20,9,20))
            self.assertEqual(sim.holdings.call_count,2)
            with patch('strategy_worker.fetch_quotes',return_value={'301236':dict(last='34')}):
                w.tick(self.at(20,10,0))
            self.assertEqual(w.watch_status['p'][1],300)
            w.tick(self.at(20,16,30))
            self.assertEqual(sim.holdings.call_count,2)
            sim.report.assert_called_once()

    def test_report_failure_still_saves_holdings_and_manual_can_retry(self):
        with sqlite3.connect(':memory:') as db:
            sim=FakeSim();sim.holdings=Mock(return_value=[])
            sim.report=Mock(side_effect=RuntimeError('report unavailable'))
            w=Worker(sim,db)
            db.execute("INSERT INTO orders(side,day,qty) VALUES ('买入','2026-11-19',100)")
            w.tick(self.at(19,9,20));w.tick(self.at(19,16,31))
            sim.report.assert_called_once();sim.holdings.assert_called_once()
            self.assertEqual(db.execute('SELECT status,data FROM holdings_runs').fetchone()[:],('partial','[]'))
            sim.report.return_value=[];sim.report.side_effect=None
            w.check_holdings(self.at(19,16,33),force=True)
            self.assertEqual(sim.holdings.call_count,2)

    def test_no_afternoon_holdings_or_report_scan(self):
        with sqlite3.connect(':memory:') as db:
            sim = FakeSim()
            sim.holdings = Mock()
            sim.report = Mock()
            w = Worker(sim, db)
            for minute in range(29, 37):
                w.tick(self.at(19, 16, minute))
            sim.holdings.assert_not_called()
            sim.report.assert_not_called()
