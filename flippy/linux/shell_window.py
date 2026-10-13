"""The app window on Linux: a WebKitGTK 6 web view showing flippy/shell/web, talking to Python through
flippy/shell/bridge.py. The GTK side of flippy/mac/shell_window.py, with the same API:
AppWindow(on_close, command, log).present(route).

A normal window, not a layer surface (COSMIC can't close those safely, see ui.py). Ctrl+W and Ctrl+Q close the
window; quitting Flippy stays in the panel icon's menu. The window remembers its size in the config directory,
and the web view is dropped on close so WebKit's web process exits.

The page loads from local files only: decide-policy allows file URLs under flippy/shell/web, hands http(s) links
to the default browser, and ignores everything else. Its Content-Security-Policy allows nothing remote, and the
web view uses an ephemeral network session, so nothing is written to disk.
"""
import json
import os
import pathlib
from urllib.parse import unquote, urlsplit

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, Gtk, WebKit  # noqa: E402

from .. import profile  # noqa: E402
from ..shell.bridge import MAX_MESSAGE, Bridge  # noqa: E402

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shell", "web")
WIDTH, HEIGHT = 820, 600
MIN_WIDTH, MIN_HEIGHT = 640, 420
SIZE_FILE = "app-window.json"


def navigation(uri, web=WEB):
    """What the web view does with a navigation: "allow" (a file under web), "open" (http or https, in the
    default browser) or "ignore" (anything else)."""
    try:
        parts = urlsplit(uri or "")
    except ValueError:
        return "ignore"
    scheme = parts.scheme.lower()
    if scheme == "file":
        if parts.netloc not in ("", "localhost"):
            return "ignore"
        root = os.path.realpath(web)
        path = os.path.realpath(unquote(parts.path))
        return "allow" if path.startswith(root + os.sep) else "ignore"
    if scheme in ("http", "https") and parts.hostname:
        return "open"
    return "ignore"


def _size_path():
    return os.path.join(profile.current().config_dir, SIZE_FILE)


def load_size(path=None):
    """The window's saved (width, height), or the default size."""
    try:
        with open(path or _size_path()) as f:
            data = json.load(f)
        return max(MIN_WIDTH, int(data["width"])), max(MIN_HEIGHT, int(data["height"]))
    except (OSError, ValueError, KeyError, TypeError):
        return WIDTH, HEIGHT


def save_size(width, height, path=None):
    path = path or _size_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"width": int(width), "height": int(height)}, f)
    except OSError:
        pass


def open_external(uri, parent=None):
    """Open an http(s) link in the default browser (through the portal when sandboxed)."""
    Gtk.UriLauncher.new(uri).launch(parent, None, None, None)


_adw_ready = False


class AppWindow:
    def __init__(self, on_close=lambda: None, command=lambda cmd: None, log=print, app=None):
        global _adw_ready
        if not _adw_ready:
            Adw.init()  # the title bar follows the system's light or dark style, like the page
            _adw_ready = True
        self.on_close, self.log = on_close, log
        self.bridge = Bridge(push=self._push, command=command, log=log)
        self.content = WebKit.UserContentManager()
        self.content.register_script_message_handler("flippy", None)
        self.content.connect("script-message-received::flippy", lambda _m, value: self._message(value.to_string()))
        self.web = WebKit.WebView(user_content_manager=self.content,
                                  network_session=WebKit.NetworkSession.new_ephemeral())
        prefs = self.web.get_settings()
        prefs.set_enable_developer_extras(False)
        prefs.set_javascript_can_open_windows_automatically(False)
        prefs.set_allow_file_access_from_file_urls(False)
        prefs.set_allow_universal_access_from_file_urls(False)
        self.web.connect("decide-policy", self._decide)
        self.web.connect("context-menu", lambda *_: True)  # no Reload / Inspect / Back
        width, height = load_size()
        self.win = Gtk.Window(title="Flippy", default_width=width, default_height=height)
        if app is not None:
            self.win.set_application(app)
        self.win.set_size_request(MIN_WIDTH, MIN_HEIGHT)
        self.win.set_child(self.web)
        keys = Gtk.ShortcutController(scope=Gtk.ShortcutScope.MANAGED)
        for accel in ("<Control>w", "<Control>q"):
            keys.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string(accel),
                                           action=Gtk.CallbackAction.new(lambda *_: self.win.close() or True)))
        self.win.add_controller(keys)
        self.win.connect("close-request", self._closed)
        self.web.load_uri(pathlib.Path(WEB, "index.html").as_uri())

    def present(self, route=None):
        if route:
            self.bridge.route = route    # read by the page when it loads
            self._push("route", route)   # and sent, in case it already has
        if self.win is not None:
            self.win.present()

    def _decide(self, _web, decision, kind):
        if kind not in (WebKit.PolicyDecisionType.NAVIGATION_ACTION, WebKit.PolicyDecisionType.NEW_WINDOW_ACTION):
            return False  # responses: WebKit's default
        uri = decision.get_navigation_action().get_request().get_uri()
        verdict = navigation(uri)
        if verdict == "allow" and kind == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            decision.use()
            return True
        decision.ignore()
        action = decision.get_navigation_action()
        if verdict == "open" and (action.is_user_gesture()
                                  or action.get_navigation_type() == WebKit.NavigationType.LINK_CLICKED):
            open_external(uri, self.win)  # a link the user followed, not a script moving the page
        else:
            self.log(f"app window: blocked navigation to {uri[:200]}")
        return True

    def _closed(self, win):
        if not win.is_maximized() and not win.is_fullscreen():
            save_size(*win.get_default_size())
        self.bridge.close()
        self.content.unregister_script_message_handler("flippy", None)
        win.set_child(None)  # drop the page so WebKit can end its web process
        self.web = None
        self.win = None
        self.on_close()
        return False  # let GTK destroy the window

    def _message(self, body):
        try:
            message = json.loads(body) if isinstance(body, str) and len(body) <= MAX_MESSAGE else None
        except ValueError:
            message = None
        self._js("window.flippy.reply", self.bridge.handle(message))

    def _push(self, event, data):
        self._js("window.flippy.event", event, data)

    def _js(self, fn, *args):
        if self.web is None:
            return
        self.web.evaluate_javascript(f"{fn}({', '.join(json.dumps(a) for a in args)})", -1, None, None, None,
                                     None, None)

