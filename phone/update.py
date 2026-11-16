"""Detached updater: quiesce, replace code, health-check, rollback on failure."""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.request import Request, urlopen

from phone.backend import FILES, validate_bundle

STATE = Path('state')


def result(phase, message):
    path = STATE / 'update-result.tmp'
    path.write_text(json.dumps(dict(phase=phase, message=message), ensure_ascii=False))
    path.replace(STATE / 'update-result.json')


def pid_for(service):
    try:
        pid = int((STATE / (service + '.pid')).read_text())
        expected = b'phone/local.py' if service == 'worker' else b'phone/manager.py'
        return pid if expected in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0') else None
    except (ValueError, OSError):
        return None


def stop(service):
    pid = pid_for(service)
    if not pid:
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if pid_for(service) != pid:
            return
        time.sleep(.1)
    raise RuntimeError(f'{service} 未退出，停止升级')


def start(service):
    args = ['/system/bin/sh', 'phone/start.sh'] + (['manager'] if service == 'manager' else [])
    env = dict(os.environ)
    env.pop('LD_LIBRARY_PATH', None)
    with (STATE / (service + '.log')).open('ab') as log:
        child = subprocess.Popen(args, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=log, start_new_session=True)
    (STATE / (service + '.pid')).write_text(str(child.pid))


def healthy(expected):
    token = (STATE / 'manager.key').read_text().strip()
    for _ in range(30):
        try:
            request = Request('http://127.0.0.1:18735/status', headers={'Authorization': 'Bearer ' + token})
            with urlopen(request, timeout=1) as response:
                data = json.load(response)
            if data.get('backend_digest') == expected:
                return
        except (OSError, ValueError):
            pass
        time.sleep(.5)
    raise RuntimeError('新版后台健康检查未通过')


def replace_files(files):
    for name, data in files.items():
        path = Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + '.update-tmp')
        temp.write_bytes(data)
        temp.replace(path)


def apply(raw):
    expected, files = validate_bundle(raw)
    paused = STATE / 'paused'
    was_paused, was_running = paused.exists(), bool(pid_for('worker'))
    old = {name: Path(name).read_bytes() for name in FILES}
    paused.touch(mode=0o600)
    replaced = False
    manager_stopped = False
    try:
        # Let an in-flight UI order finish and journal its result before stopping.
        deadline = time.monotonic() + 90
        while pid_for('worker'):
            heartbeat = (STATE / 'heartbeat').read_text().split() if (STATE / 'heartbeat').exists() else []
            if heartbeat == [str(pid_for('worker')), 'paused']:
                break
            if time.monotonic() > deadline:
                raise RuntimeError('策略仍在执行或等待就绪，请稍后重试')
            time.sleep(.5)
        stop('worker')
        stop('manager')
        manager_stopped = True
        replaced = True
        replace_files(files)
        start('manager')
        healthy(expected)
        if was_running:
            start('worker')
        if not was_paused:
            paused.unlink(missing_ok=True)
        result('success', '后台更新完成，已保留原有设置、账本和启停状态')
    except Exception as error:
        try:
            if replaced:
                stop('worker')
                stop('manager')
                replace_files(old)
            if manager_stopped:
                start('manager')
            if was_running and not pid_for('worker'):
                start('worker')
            if not was_paused:
                paused.unlink(missing_ok=True)
            result('failed', '升级失败，已保留或恢复原后台：' + str(error))
        except Exception as rollback_error:
            result('failed', '升级恢复失败，策略保持暂停，请用 USB 修复：' + str(rollback_error))


def launch(raw):
    validate_bundle(raw)
    lock = (STATE / 'update.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise ValueError('后台正在升级，请等待完成')
    (STATE / 'backend-pending.json').write_bytes(raw)
    result('updating', '正在等待策略完成当前操作并更新后台')
    try:
        with (STATE / 'update.log').open('ab') as log:
            subprocess.Popen([sys.executable, 'phone/update.py', str(lock.fileno())],
                             pass_fds=(lock.fileno(),), start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    except Exception:
        result('failed', '无法启动升级进程')
        raise
    finally:
        lock.close()


if __name__ == '__main__':
    # Keep inherited flock until process exit; allow HTTP response to reach App.
    time.sleep(1)
    apply((STATE / 'backend-pending.json').read_bytes())
