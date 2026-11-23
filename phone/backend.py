"""Versioned backend protocol and deterministic, code-only update bundles."""
import base64
import hashlib
import json
from pathlib import Path

API_VERSION = 2
UPDATE_PROTOCOL = 1
FILES = (
    'strategy_settings.py', 'premarket.py', 'strategy_worker.py', 'stock_api.py',
    'phone/manager.py', 'phone/local.py', 'phone/backend.py', 'phone/update.py', 'phone/native.py',
    'phone/start.sh', 'phone/background.sh', 'ths/__init__.py', 'ths/simulator.py',
)
MAX_BUNDLE = 2 * 1024 * 1024


def digest(files):
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


def installed_digest(root=Path('.')):
    return digest({name: (root / name).read_bytes() for name in FILES})


def bundle(root):
    files = {name: (root / name).read_bytes() for name in FILES}
    return dict(protocol=UPDATE_PROTOCOL, api_version=API_VERSION, digest=digest(files),
                files={name: base64.b64encode(data).decode() for name, data in files.items()})


def validate_bundle(raw):
    if len(raw) > MAX_BUNDLE:
        raise ValueError('升级包过大')
    try:
        item = json.loads(raw)
        if item['protocol'] != UPDATE_PROTOCOL or item['api_version'] != API_VERSION:
            raise ValueError('升级协议不兼容，请使用 USB 升级包')
        if set(item['files']) != set(FILES):
            raise ValueError('升级文件列表不符')
        files = {name: base64.b64decode(data, validate=True) for name, data in item['files'].items()}
        if sum(map(len, files.values())) > MAX_BUNDLE or digest(files) != item['digest']:
            raise ValueError('升级包校验失败')
        for name, data in files.items():
            if name.endswith('.py'):
                compile(data, name, 'exec')
        return item['digest'], files
    except (KeyError, TypeError, SyntaxError) as error:
        raise ValueError('升级包格式错误') from error
