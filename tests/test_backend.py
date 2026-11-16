import base64
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from phone.backend import bundle, validate_bundle, FILES
from phone import update

ROOT = Path(__file__).resolve().parents[1]


class BackendTests(unittest.TestCase):
    def test_bundle_rejects_corruption_and_state_files(self):
        good = bundle(ROOT)
        expected, files = validate_bundle(json.dumps(good).encode())
        self.assertEqual(expected, good['digest'])
        self.assertEqual(set(files), set(FILES))
        for kind in ['corrupt', 'state', 'traversal', 'protocol']:
            item = json.loads(json.dumps(good))
            if kind == 'corrupt':
                item['files']['strategy_worker.py'] = base64.b64encode(b'pass').decode()
            elif kind == 'protocol':
                item['protocol'] = 999
            else:
                item['files']['state/manager.key' if kind == 'state' else '../escape.py'] = 'eA=='
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate_bundle(json.dumps(item).encode())

    def test_update_and_rollback_preserve_state_and_pause(self):
        raw = json.dumps(bundle(ROOT)).encode()
        for failed in [False, True]:
            for paused in [False, True]:
                with self.subTest(failed=failed, paused=paused), tempfile.TemporaryDirectory() as directory:
                    before = Path.cwd()
                    os.chdir(directory)
                    try:
                        for name in FILES:
                            p = Path(name);p.parent.mkdir(parents=True, exist_ok=True);p.write_bytes(b'# old code\n')
                        Path('state').mkdir()
                        Path('state/strategy.sqlite3').write_bytes(b'account ledger')
                        Path('state/settings.json').write_bytes(b'custom settings')
                        if paused: Path('state/paused').touch()
                        Path('state/heartbeat').write_text('123 paused')
                        live = {'worker': 123, 'manager': 456}
                        def stop(service): live[service] = None
                        def start(service): live[service] = 789
                        with patch.object(update, 'pid_for', side_effect=lambda service: live[service]), \
                             patch.object(update, 'stop', side_effect=stop), \
                             patch.object(update, 'start', side_effect=start), \
                             patch.object(update, 'healthy', side_effect=RuntimeError('bad health') if failed else None):
                            update.apply(raw)
                        self.assertEqual(Path('state/paused').exists(), paused)
                        self.assertEqual(Path('state/strategy.sqlite3').read_bytes(), b'account ledger')
                        self.assertEqual(Path('state/settings.json').read_bytes(), b'custom settings')
                        self.assertTrue(live['manager']);self.assertTrue(live['worker'])
                        self.assertEqual(json.loads(Path('state/update-result.json').read_text())['phase'],
                                         'failed' if failed else 'success')
                        for name in FILES:
                            self.assertEqual(Path(name).read_bytes(), b'# old code\n' if failed else (ROOT/name).read_bytes())
                    finally:
                        os.chdir(before)
