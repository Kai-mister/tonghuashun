"""Private app runtime: no shell, ADB, or downloaded executable code."""
import os
import subprocess
import sys
from pathlib import Path


def enabled():
    return os.environ.get('THS_NATIVE') == '1'


def start(service):
    state = Path('state')
    with (state / (service + '.log')).open('ab') as log:
        child = subprocess.Popen([sys.executable, 'phone/manager.py' if service == 'manager' else 'phone/local.py'],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    (state / (service + '.pid')).write_text(str(child.pid))
