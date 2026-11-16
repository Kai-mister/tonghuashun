import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import HTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]


class ManagerTests(unittest.TestCase):
    def test_auth_settings_and_upgrade_acknowledgement(self):
        with tempfile.TemporaryDirectory() as folder:
            previous = Path.cwd()
            os.chdir(folder)
            try:
                Path('state').mkdir();Path('state/manager.key').write_text('a'*64)
                with sqlite3.connect('state/strategy.sqlite3') as db:
                    db.executescript('CREATE TABLE identity(account TEXT);'
                        'CREATE TABLE orders(id INTEGER,plan TEXT,day TEXT,side TEXT,qty INTEGER,price TEXT,filled INTEGER,done INTEGER);'
                        'CREATE TABLE morning_checks(plan TEXT,day TEXT,total INTEGER,available INTEGER);')
                with patch('phone.backend.installed_digest', return_value='digest'):
                    spec=importlib.util.spec_from_file_location('test_manager_module',ROOT/'phone/manager.py')
                    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                server=HTTPServer(('127.0.0.1',0),module.Handler)
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                def request(path, body=None, auth=True):
                    headers={'Authorization':'Bearer '+'a'*64} if auth else {}
                    req=Request('http://127.0.0.1:'+str(server.server_port)+path,body,headers)
                    try:
                        with urlopen(req) as r:return r.status,json.load(r)
                    except HTTPError as e:return e.code,json.load(e)
                try:
                    self.assertEqual(request('/settings',b'{}',False)[0],403)
                    self.assertEqual(request('/unknown',b'{}')[0],404)
                    status,data=request('/settings',b'{"buy_time":"10:15"}')
                    self.assertEqual(status,200);self.assertEqual(data['settings']['buy_time'],'10:15')
                    self.assertEqual(data['api_version'],2)
                    self.assertEqual(request('/settings',b'{"buy_time":"oops"}')[0],400)
                    self.assertEqual(request('/status')[1]['settings']['buy_time'],'10:15')
                    with patch.object(module,'launch') as launch:
                        self.assertEqual(request('/upgrade',b'{}'),(202,{'accepted':True}))
                        launch.assert_called_once_with(b'{}')
                    Path('state/update-result.json').write_text('{"phase":"updating"}')
                    self.assertEqual(request('/settings',b'{}')[0],400)
                finally:
                    server.shutdown();server.server_close();thread.join()
            finally:
                os.chdir(previous)
