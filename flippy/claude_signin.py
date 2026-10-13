"""Claude sign-in without a terminal: run the CLI's `auth login --claudeai` in the background.

The bundled CLI opens the Claude sign-in page in the default browser and waits for its localhost callback, so
the user only ever sees the browser. A watcher thread polls `claude auth status` until the claude.ai login shows
up (or a timeout), then stops the login process. No UI here: setup windows call start() and read the result.
Flippy never sees the sign-in URL, codes or tokens; nothing the CLI prints is kept or logged.
"""
import atexit
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time

STARTED, RUNNING, ALREADY, FALLBACK = "started", "running", "already", "fallback"
TIMEOUT_S = 600   # the user may take a while in the browser (password manager, 2FA, choosing an org)
POLL_S = 2
STATUS_TIMEOUT_S = 10
EXIT_GRACE_S = 5  # after a login shows up, the CLI normally exits by itself; give it this long first


def log(*args):
    """Same shape as flippy.daemon.log (stderr ends up in Flippy's log), without importing the daemon."""
    print(time.strftime("%H:%M:%S"), *args, file=sys.stderr, flush=True)


def claude_cli():
    """The CLI the Agent SDK uses: its bundled copy, else `claude` on PATH, else None."""
    try:
        import claude_agent_sdk
    except ImportError:
        return shutil.which("claude")
    bundled = os.path.join(os.path.dirname(claude_agent_sdk.__file__), "_bundled", "claude")
    return bundled if os.path.isfile(bundled) else shutil.which("claude")


def login_env():
    """Never an API-key login: the CLI would prefer ANTHROPIC_API_KEY. Flippy's own variables stay out too."""
    return {k: v for k, v in os.environ.items()
            if not k.startswith(("FLIPPY_", "PYTHON")) and k not in ("SSL_CERT_FILE", "ANTHROPIC_API_KEY")}


def signed_in(cli, env=None, run=subprocess.run):
    """`claude auth status` says a claude.ai subscription login (the same test as providers.claude_available)."""
    try:
        done = run([cli, "auth", "status", "--json"], env=env, stdin=subprocess.DEVNULL, capture_output=True,
                   timeout=STATUS_TIMEOUT_S)
        status = json.loads(done.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0 and status.get("loggedIn") is True and status.get("authMethod") == "claude.ai"


def _stop(process):
    """Stop the login and anything it started (it runs in its own session), politely first."""
    if process.poll() is not None:
        return
    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        try:
            os.killpg(process.pid, sig)
        except (ProcessLookupError, PermissionError, AttributeError):
            try:
                process.send_signal(sig)
            except ProcessLookupError:
                return
        try:
            process.wait(wait)
            return
        except subprocess.TimeoutExpired:
            continue


class SignIn:
    """One background sign-in at a time. start() returns right away; watch() runs on a daemon thread."""

    def __init__(self, popen=subprocess.Popen, status=signed_in, clock=time.monotonic, sleep=time.sleep,
                 thread=True):
        self.popen, self.status, self.clock, self.sleep, self.thread = popen, status, clock, sleep, thread
        self.process = None
        self.result = None  # None while running, then "signed-in", "timeout", "exited" or "cancelled"
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    def running(self):
        return self.process is not None and self.result is None

    def start(self, force=False, fallback=None, connected=None, timeout=TIMEOUT_S, on_done=None):
        """force: sign in again even though already connected (Reconnect, after the user confirmed).
        fallback: called (and its result returned) when the background login can't start, e.g. the old terminal.
        connected: whether Claude is known to be connected; defaults to providers.CONNECTION_STATUS, which the
        setup window keeps fresh and which decides its "Reconnect…" label."""
        with self._lock:
            if self.running():
                log("claude sign-in: already in progress, not starting another")
                return RUNNING
            if connected is None:
                from .providers import CONNECTION_STATUS
                connected = CONNECTION_STATUS["claude"] is True
            if connected and not force:
                log("claude sign-in: already signed in, not starting a new login")
                return ALREADY
            cli = claude_cli()
            if not cli:
                return self._fallback("no claude CLI found", fallback)
            env = login_env()
            try:
                self.process = self.popen([cli, "auth", "login", "--claudeai"], env=env, stdin=subprocess.DEVNULL,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                          start_new_session=True)
            except OSError as e:
                return self._fallback(f"couldn't start the claude CLI ({type(e).__name__})", fallback)
            self.result = None
            self._cancel.clear()
            log("claude sign-in: started in the background, waiting for the browser")
        # signing in again: `auth status` already says yes, so only the login finishing counts
        args = (cli, env, timeout, fallback, on_done, connected)
        if self.thread:
            threading.Thread(target=self.watch, args=args, name="claude-signin", daemon=True).start()
        else:
            self.watch(*args)
        return STARTED

    def _fallback(self, reason, fallback):
        log(f"claude sign-in: {reason}; " + ("opening a terminal instead" if fallback else "no fallback"))
        return fallback() if fallback else FALLBACK

    def watch(self, cli, env, timeout, fallback=None, on_done=None, again=False):
        """Poll the login state until signed in, the login process gives up, a timeout or cancel().
        again: already signed in before (Reconnect), so wait for the login process itself to finish."""
        process, deadline = self.process, self.clock() + timeout
        result = "timeout"
        while self.clock() < deadline:
            if self._cancel.is_set():
                result = "cancelled"
                break
            if not again and self.status(cli, env):
                result = "signed-in"
                break
            if process.poll() is not None:
                # one last look: the CLI exits right after saving the login
                result = "signed-in" if self.status(cli, env) else "exited"
                break
            self.sleep(POLL_S)
        if result == "signed-in":
            try:
                process.wait(EXIT_GRACE_S)
            except subprocess.TimeoutExpired:
                pass
            from .providers import CONNECTION_STATUS
            CONNECTION_STATUS["claude"] = True  # the setup window ticks it now, not on the next refresh
        _stop(process)
        self.result = result
        if result == "exited":
            log(f"claude sign-in: the login exited without signing in (rc={process.returncode})")
            if fallback and process.returncode not in (0, None, -signal.SIGTERM):
                try:
                    self._fallback("the background login failed", fallback)
                except Exception as e:  # a missing terminal on Linux; the window still says "Not connected"
                    log(f"claude sign-in: fallback failed ({type(e).__name__})")
        else:
            log(f"claude sign-in: {result}")
        if on_done:
            on_done(result)
        return result

    def cancel(self):
        """Stop a pending login (Flippy quitting); the watcher notices within POLL_S."""
        self._cancel.set()
        if self.process is not None and self.result is None:
            _stop(self.process)


SIGN_IN = SignIn()
atexit.register(SIGN_IN.cancel)


def start(force=False, fallback=None):
    """The setup windows' entry point: STARTED, RUNNING, ALREADY, or whatever fallback() returns."""
    return SIGN_IN.start(force=force, fallback=fallback)
