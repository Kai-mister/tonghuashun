"""One-time USB upgrade for installations predating the in-App updater."""
import importlib.util
import json,os,signal,sqlite3,subprocess,time
from pathlib import Path

root=Path('/data/local/tmp/ths-sim');os.chdir(root)
state=Path('state');paused=state/'paused'
was_paused=paused.exists()
def pid_for(service):
 try:
  pid=int((state/(service+'.pid')).read_text())
  expected=b'phone/local.py' if service=='worker' else b'phone/manager.py'
  return pid if expected in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0') else None
 except (OSError,ValueError):return None
was_running=bool(pid_for('worker'))
spec=importlib.util.spec_from_file_location('staged_backend',Path('upgrade/phone/backend.py'))
backend=importlib.util.module_from_spec(spec);spec.loader.exec_module(backend)
files=backend.FILES
backup=state/('before-backend-update-'+time.strftime('%Y%m%d-%H%M%S'));backup.mkdir()
old={n:Path(n).read_bytes() if Path(n).exists() else None for n in files}
for name,data in old.items():
 if data is not None:
  path=backup/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
with sqlite3.connect('file:state/strategy.sqlite3?mode=ro',uri=True) as source,sqlite3.connect(backup/'strategy.sqlite3') as dest:source.backup(dest)
(backup/'original-state.json').write_text(json.dumps(dict(paused=was_paused,running=was_running)))
paused.touch(mode=0o600)
end=time.monotonic()+60
while pid_for('worker'):
 if (state/'heartbeat').read_text().split()==[str(pid_for('worker')),'paused']:break
 if time.monotonic()>end:
  if not was_paused:paused.unlink(missing_ok=True)
  raise RuntimeError('Worker did not reach safe pause; no code replaced')
 time.sleep(.5)
def stop(service):
 pid=pid_for(service)
 if pid:
  os.kill(pid,signal.SIGTERM)
  for _ in range(50):
   if pid_for(service)!=pid:return
   time.sleep(.1)
  raise RuntimeError(service+' did not stop')
def start(service):
 env=dict(os.environ);env.pop('LD_LIBRARY_PATH',None)
 with (state/(service+'.log')).open('ab') as log:
  p=subprocess.Popen(['/system/bin/sh','phone/start.sh']+(['manager'] if service=='manager' else []),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
 (state/(service+'.pid')).write_text(str(p.pid))
try:
 stop('worker');stop('manager')
 for name in files:
  path=Path(name);path.parent.mkdir(parents=True,exist_ok=True)
  temp=path.with_name(path.name+'.bootstrap-tmp');temp.write_bytes((Path('upgrade')/name).read_bytes());temp.replace(path)
 from phone.backend import installed_digest
 from phone.update import healthy
 start('manager');healthy(installed_digest())
 if was_running:start('worker')
 if not was_paused:paused.unlink(missing_ok=True)
 print('USB bootstrap complete; backend',installed_digest(),'state preserved; backup',backup)
except Exception:
 stop('worker');stop('manager')
 for name,data in old.items():
  if data is None:Path(name).unlink(missing_ok=True)
  else:Path(name).write_bytes(data)
 start('manager')
 if was_running:start('worker')
 if not was_paused:paused.unlink(missing_ok=True)
 raise
