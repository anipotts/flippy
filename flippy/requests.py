"""One lifetime for capture, inference, approvals and the resulting playback."""
import threading
from dataclasses import dataclass, field


@dataclass(eq=False)
class Request:
    identity: int
    mode: str
    canceled: threading.Event = field(default_factory=threading.Event)
    future: object = None
    pending: bool = True
    timers: set = field(default_factory=set)

    def owns(self, current):
        return current is self and not self.canceled.is_set()

    def cancel(self, remove_timer):
        """Idempotent, UI-thread teardown; native workers share the cancellation event."""
        if self.canceled.is_set():
            return False
        self.canceled.set()
        for timer in tuple(self.timers):
            remove_timer(timer)
        self.timers.clear()
        if self.future is not None and self.pending:
            self.future.cancel()
        return True
