"""Read-only runtime inventory; no credential inspection or native auth flow."""
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flippy.profile import current

profile = current()
versions = {}
for package in ('claude-agent-sdk', 'Pillow', 'pycairo', 'pyobjc-framework-Cocoa'):
    try: versions[package] = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError: versions[package] = None
revision = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True)
dirty = subprocess.run(['git', '-C', str(ROOT), 'status', '--porcelain'], capture_output=True, text=True)
runtime = subprocess.run([str(ROOT / 'bin/flippy-ask'), 'doctor'], capture_output=True, text=True)
try: live = json.loads(runtime.stdout) if runtime.returncode == 0 else None
except ValueError: live = None
print(json.dumps({'profile': profile.name, 'root': str(ROOT), 'app': os.environ.get('FLIPPY_APP') or profile.app,
                  'config': profile.config_dir, 'socket': profile.socket, 'log': profile.log,
                  'revision': revision.stdout.strip(), 'dirty': bool(dirty.stdout.strip()), 'dependencies': versions,
                  'live': live, 'authentication': 'verify native Claude login through Setup; credentials not inspected'}, indent=2))
