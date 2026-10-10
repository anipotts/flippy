"""Borrowing a window on COSMIC for input Wayland can't send in the background: the Linux side of macOS's
Platform._borrow_pointer (flippy/mac/ui.py).

Wayland has no "send this key to that app" (no CGEventPostToPid), so keys AT-SPI can't do and clicks by position
need the app's window in front: wait until the user pauses, bring the window forward (zcosmic_toplevel_manager_v1),
do the input, and give the focus back to the window they were in. Wayland doesn't let a client read the pointer's
position, so a borrowed pointer can't be put back where it was: it stays where the click left it.
"""
import time

from ..actions import ActionError, RetryableActionError

IDLE_S = 1.0        # the window is borrowed only after this long without the user's input...
WAIT_S = 45.0       # ...waiting at most this long for such a pause
FRONT_S = 1.5       # for the compositor to bring the window forward


class Borrow:
    def __init__(self, conn, clock=time):
        self.conn, self.clock = conn, clock

    def __call__(self, tl, act, cancel, point=None):
        """Run act() with tl in front, while the user is idle; point: the screen spot it acts on, which must be on
        tl's window. The window they were in gets the focus back, whatever happens."""
        conn, clock = self.conn, self.clock
        deadline = clock.monotonic() + WAIT_S
        while conn.idle_s() < IDLE_S:
            if cancel.is_set():
                raise ActionError("Task canceled.")
            if clock.monotonic() > deadline:
                raise RetryableActionError("The user kept working, so Flippy didn't take the window. Try again later "
                                           "in the task, or use the app's controls or menus.")
            clock.sleep(0.1)
        if tl is None or tl.ext_id not in conn.toplevels:
            raise RetryableActionError("The app's window closed. Look again.")
        before = conn.active()
        try:
            if not tl.activated:
                conn.activate(tl)
                end = clock.monotonic() + FRONT_S
                while not tl.activated and clock.monotonic() < end:
                    clock.sleep(0.03)
                if not tl.activated:
                    raise RetryableActionError("COSMIC didn't bring the window forward, so Flippy didn't act. Look "
                                               "again and retry, or use a control or menu instead.")
            if point is not None and not _inside(point, tl.geometry):
                raise RetryableActionError("That spot isn't on the app's window. Look again and retry.")
            if conn.idle_s() <= 0:  # they picked the mouse or keyboard back up while the window came forward
                raise RetryableActionError("The user started working again, so Flippy gave the window back. Try again "
                                           "later in the task.")
            clock.sleep(0.05)  # the keyboard follows the focus a moment later
            result = act()
            if result not in (None, "ok", True):
                raise ActionError(str(result))
            clock.sleep(0.15)
        finally:
            if before is not None and before is not tl and before.ext_id in conn.toplevels:
                conn.activate(before)


def _inside(point, geometry):
    if not geometry:
        return False
    x, y = point
    gx, gy, gw, gh = geometry
    return gx <= x < gx + gw and gy <= y < gy + gh
