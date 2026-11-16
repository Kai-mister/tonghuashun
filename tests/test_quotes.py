import json
import sqlite3
import unittest
from datetime import datetime
from unittest.mock import Mock, patch
from stock_api import parse_quotes, quote_symbol
from premarket import SHANGHAI
from strategy_worker import Worker
from test_worker import FakeSim

class QuotesTests(unittest.TestCase):
    def test_parse_fresh_and_reject_bad_quotes(self):
        now = datetime(2026,11,17,10,0,tzinfo=SHANGHAI)
        def row(price='46.12', stamp='20261117100000', code='301209'):
            f=['']*31;f[2]=code;f[3]=price;f[30]=stamp
            return 'v_sz301209="'+'~'.join(f)+'";'
        self.assertEqual(parse_quotes(row(),['301209'],now)['301209']['last'],'46.12')
        for text in [row(stamp='20261116100000'),row(price='NaN'),row(price='0'),row(code='002222'),row(stamp='20261117100100'),'v_sz301209="";']:
            self.assertEqual(parse_quotes(text,['301209'],now),{})
        self.assertEqual([quote_symbol(c) for c in ['600000','301209','920001']],['sh600000','sz301209','bj920001'])

    def test_price_monitor_uses_api_without_page_reads(self):
        with sqlite3.connect(':memory:') as db:
            sim=FakeSim();sim.position=Mock(return_value=dict(total=200,available=200));sim.quote=Mock()
            worker=Worker(sim,db)
            p=dict(code='301209',planned_buy_date='2026-11-16',liquidate_at='2026-11-17T14:50:00+08:00',stop_loss='45',take_profit='48')
            key='2026-11-16/301209'
            db.execute('INSERT INTO plans VALUES (?,?,NULL)',(key,json.dumps(p)))
            db.execute("INSERT INTO orders(plan,side,day,qty,filled,done,stamp) VALUES (?,'买入','2026-11-16',200,200,1,'09:20:00')",(key,))
            with patch('strategy_worker.fetch_quotes',return_value={'301209':dict(last='46')}) as fetch:
                worker.tick(datetime(2026,11,17,9,16,tzinfo=SHANGHAI))
                worker.tick(datetime(2026,11,17,10,0,tzinfo=SHANGHAI))
                worker.tick(datetime(2026,11,17,10,0,3,tzinfo=SHANGHAI))
                self.assertEqual(fetch.call_count,2)
                sim.position.assert_called_once()
                sim.quote.assert_not_called()
            worker.submit=Mock();sim.quote.return_value=dict(total=200,available=200,limit='40')
            with patch('strategy_worker.fetch_quotes',return_value={}):
                worker.tick(datetime(2026,11,17,10,1,tzinfo=SHANGHAI))
                worker.submit.assert_not_called()
                worker.tick(datetime(2026,11,17,14,50,tzinfo=SHANGHAI))
                worker.submit.assert_called_once_with(key,p,'卖出',200,'40')
