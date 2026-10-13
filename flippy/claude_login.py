"""Sign in to Claude Code with a claude.ai subscription, without a terminal (#20).

`claude auth login --claudeai` opens Claude's sign-in page in the default browser and finishes through a
localhost callback, so Flippy runs it in the background. The setup window's status check (`claude auth status`,
flippy/providers.py) notices when it's done.
"""
import os
import subprocess
import threading

TIMEOUT = 600  # a sign-in left in the browser stops waiting after ten minutes
_process = None


def start(cli):
    """Open Claude's sign-in page. A sign-in still waiting is replaced, so each press opens a fresh page.
    False when the CLI can't be started."""
    global _process
    cancel()
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}  # or it signs in for API billing
    try:
        process = subprocess.Popen([cli, "auth", "login", "--claudeai"], env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    _process = process
    threading.Thread(target=_expire, args=(process,), daemon=True).start()
    return True


def _expire(process):
    try:
        process.wait(TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def waiting():
    """A sign-in page is open and Flippy is still waiting for it."""
    return _process is not None and _process.poll() is None


def cancel():
    if waiting():
        _process.terminate()
