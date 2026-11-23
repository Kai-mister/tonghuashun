"""Package an existing Android CPython distribution; never package user state."""
import json, sys, zipfile
from pathlib import Path
prefix, executable, cert, zone, out = map(Path, sys.argv[1:])
out.mkdir(parents=True, exist_ok=True)
links = {}
with zipfile.ZipFile(out/'native.zip','w',zipfile.ZIP_DEFLATED) as native, zipfile.ZipFile(out/'runtime.zip','w',zipfile.ZIP_DEFLATED) as runtime:
    native.write(executable, 'lib/arm64-v8a/libths_python.so')
    for p in sorted(prefix.rglob('*')):
        if not p.is_file() or '__pycache__' in p.parts: continue
        name = 'prefix/' + p.relative_to(prefix).as_posix()
        if p.read_bytes()[:4] == b'\x7fELF':
            target = p.name if p.parent == prefix/'lib' and p.name.endswith('.so') else f'libths_ext_{len(links)}.so'
            native.write(p, 'lib/arm64-v8a/'+target)
            links[name] = target
        else:
            runtime.write(p,name)
    runtime.write(cert, 'ca.pem')
    for p in zone.rglob('*'):
        if p.is_file():runtime.write(p,'zoneinfo/'+p.relative_to(zone).as_posix())
    runtime.writestr('native-links.json',json.dumps(links))
