"""Graceful OS shutdown, routed through the controller's input cleanup."""
import signal
import threading


def install_shutdown_handlers(quit_app, idle_add):
    """Install on the main thread before the native event loop starts.

    Return a restoration callback for embedding/tests. Repeated signals schedule
    one shutdown; they must not interrupt the native worker's release finally.
    """
    requested = threading.Event()
    previous = {}

    def shutdown(signum, frame):
        if requested.is_set():
            return
        requested.set()
        idle_add(lambda: quit_app() and False)

    for name in ('SIGTERM', 'SIGINT', 'SIGHUP'):
        sig = getattr(signal, name, None)
        if sig is not None:
            previous[sig] = signal.getsignal(sig)
            signal.signal(sig, shutdown)

    def restore():
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return restore
