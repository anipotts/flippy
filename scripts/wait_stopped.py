"""Wait for the selected profile's socket to close, without terminating a process."""
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flippy.profile import current

deadline = time.monotonic() + 30
while True:
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(1)
            connection.connect(current().socket)
    except (FileNotFoundError, ConnectionRefusedError):
        break
    if time.monotonic() >= deadline:
        raise SystemExit('previous instance is still cleaning up; rebuild stopped')
    time.sleep(.1)
