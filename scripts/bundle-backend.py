"""Embed the exact backend shipped with the APK, no credentials or state."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from phone.backend import bundle

root = Path(__file__).resolve().parents[1]
out = Path(sys.argv[1])
(out / 'assets').mkdir(parents=True, exist_ok=True)
item = bundle(root)
(out / 'assets/backend.json').write_text(json.dumps(item))
(out / 'BuildBackend.java').write_text('package cn.local.simmanager;\npublic final class BuildBackend {\n'
    + 'public static final int API_VERSION = 2;\n'
    + 'public static final String DIGEST = "' + item['digest'] + '";\n}\n')
print('Bundled backend', item['digest'][:12])
