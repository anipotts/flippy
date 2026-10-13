"""The app window on Linux: a WebKitGTK 6 web view showing flippy/shell/web, talking to Python through
flippy/shell/bridge.py. The GTK side of flippy/mac/shell_window.py, with the same API:
AppWindow(on_close, command, log).present(route), and run_standalone(route) for `python -m flippy.shell`.

A normal window, not a layer surface (COSMIC can't close those safely, see ui.py). Its title bar is a slim
header bar in the page's chrome color, light or dark as the page reports (Host.set_chrome); that's per window, so
the rest of the daemon's GTK look is left alone. Ctrl+W and Ctrl+Q close the window; quitting Flippy stays in the
panel icon's menu. The window remembers its size in the config directory, and the web view is dropped on close
so WebKit's web process exits.

The page loads from local files only: decide-policy allows file URLs under flippy/shell/web, hands links the
user follows to the default browser, and ignores everything else. Its Content-Security-Policy allows nothing
remote, and the web view uses an ephemeral network session, so nothing is written to disk.
"""
import json
import os
import pathlib
from urllib.parse import unquote, urlsplit

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, WebKit  # noqa: E402

from .. import profile  # noqa: E402
from ..shell.bridge import MAX_MESSAGE, Bridge, Host  # noqa: E402

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shell", "web")
WIDTH, HEIGHT = 1160, 780
MIN_WIDTH, MIN_HEIGHT = 760, 480
SIZE_FILE = "app-window.json"
MAX_IMPORT = 20 * 1024 * 1024
CHROME = {"dark": ("#0b0b0c", "#ececef"), "light": ("#e9e9ec", "#1c1c1f")}  # app.css --chrome, --text
CSS = "".join(f"""
window.flippy-app.{mode}, window.flippy-app.{mode} headerbar {{
  background: {bg}; color: {fg}; box-shadow: none; border: none; }}
window.flippy-app.{mode} headerbar {{ min-height: 30px; padding: 0 6px; }}
window.flippy-app.{mode} headerbar windowcontrols button {{ color: {fg}; background: none; min-height: 20px;
  min-width: 20px; padding: 2px; }}
window.flippy-app.{mode} headerbar windowcontrols button:hover {{ background: alpha({fg}, 0.12); }}
""" for mode, (bg, fg) in CHROME.items())


def navigation(uri, web=WEB):
    """What the web view does with a navigation: "allow" (a file under web), "open" (http or https, in the
    default browser when the user followed a link) or "ignore" (anything else)."""
    try:
        parts = urlsplit(uri or "")
        host = parts.hostname
    except ValueError:
        return "ignore"
    scheme = parts.scheme.lower()
    if scheme == "file":
        if parts.netloc not in ("", "localhost"):
            return "ignore"
        root = os.path.realpath(web)
        path = os.path.realpath(unquote(parts.path))
        return "allow" if path.startswith(root + os.sep) else "ignore"
    if scheme in ("http", "https") and host:
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


def _filters(kinds):
    f = Gtk.FileFilter(name="Images" if len(kinds) > 1 else kinds[0].upper())
    for kind in kinds:
        f.add_suffix(kind)
    return f


def _wait(start):
    """Run a GTK async call to completion: start(done) gets a callback taking the result (or None). The bridge
    answers the page synchronously, like the macOS panels' runModal, so this spins a nested main loop."""
    loop, box = GLib.MainLoop(), {}

    def done(value):
        box["v"] = value
        loop.quit()
    start(done)
    if "v" not in box:
        loop.run()
    return box["v"]


class GtkHost(Host):
    def __init__(self, window):
        self.window = window

    def copy_text(self, text):
        win = self.window.win
        clipboard = (win.get_display() if win else Gdk.Display.get_default()).get_clipboard()
        clipboard.set(text)
        return True

    def _choose(self, save, kinds, suggested=None):
        """A path from the file dialog, or None when cancelled."""
        parent = self.window.win
        if hasattr(Gtk, "FileDialog"):  # GTK 4.10+
            dialog = Gtk.FileDialog(modal=True, title="Export Pointer" if save else "Import Pointer")
            store = Gio.ListStore.new(Gtk.FileFilter)
            store.append(_filters(kinds))
            dialog.set_filters(store)
            if suggested:
                dialog.set_initial_name(suggested)

            def start(done):
                def finished(d, result):
                    try:
                        f = d.save_finish(result) if save else d.open_finish(result)
                        done(f.get_path() if f else None)
                    except GLib.Error:
                        done(None)  # cancelled or dismissed
                (dialog.save if save else dialog.open)(parent, None, finished)
            return _wait(start)
        chooser = Gtk.FileChooserNative.new(None, parent, Gtk.FileChooserAction.SAVE if save
                                            else Gtk.FileChooserAction.OPEN, None, None)
        chooser.set_modal(True)
        chooser.add_filter(_filters(kinds))
        if suggested:
            chooser.set_current_name(suggested)

        def start_native(done):
            def response(c, resp):
                f = c.get_file() if resp == Gtk.ResponseType.ACCEPT else None
                done(f.get_path() if f else None)
            chooser.connect("response", response)
            chooser.show()
        return _wait(start_native)

    def save_file(self, suggested, data, kind):
        path = self._choose(True, [kind], suggested)
        if not path:
            return False
        with open(path, "wb") as f:
            f.write(data)
        return True

    def open_file(self, kinds):
        path = self._choose(False, kinds)
        if not path:
            return None
        if os.path.getsize(path) > MAX_IMPORT:
            raise ValueError("That file is too big for a pointer.")
        with open(path, "rb") as f:
            return os.path.basename(path), f.read()

    def sample_color(self, done):
        done(None)  # Wayland has no screen color picker for apps (the page hides Eyedropper off macOS)

    def set_chrome(self, mode):
        self.window.set_chrome(mode)


_css_ready = False


class AppWindow:
    def __init__(self, on_close=lambda: None, command=lambda cmd: None, log=print, app=None):
        global _css_ready
        if not _css_ready:
            Adw.init()  # libadwaita follows the desktop's light or dark setting, and WebKit's
            #             prefers-color-scheme follows it, for the page's "System" mode
            provider = Gtk.CssProvider()
            provider.load_from_string(CSS) if hasattr(provider, "load_from_string") else provider.load_from_data(
                CSS.encode())
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            _css_ready = True
        self.on_close, self.log = on_close, log
        self.bridge = Bridge(push=self._push, command=command, log=log, host=GtkHost(self))
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
        self.win = Gtk.Window(title="Flippy", default_width=width, default_height=height,
                              css_classes=["flippy-app"])
        if app is not None:
            self.win.set_application(app)
        self.win.set_size_request(MIN_WIDTH, MIN_HEIGHT)
        bar = Gtk.HeaderBar(show_title_buttons=True)
        bar.set_title_widget(Gtk.Box())  # no title text: the page has its own heading
        self.win.set_titlebar(bar)
        self.win.set_child(self.web)
        self.set_chrome("dark")
        keys = Gtk.ShortcutController(scope=Gtk.ShortcutScope.MANAGED)
        for accel in ("<Control>w", "<Control>q"):
            keys.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string(accel),
                                           action=Gtk.CallbackAction.new(lambda *_: self.win.close() or True)))
        self.win.add_controller(keys)
        self.win.connect("close-request", self._closed)
        self.web.load_uri(pathlib.Path(WEB, "index.html").as_uri())

    def set_chrome(self, mode):
        """The title bar and the web view's background (seen before the page paints) follow the page's mode."""
        if self.win is None or mode not in CHROME:
            return
        for other in CHROME:
            self.win.remove_css_class(other)
        self.win.add_css_class(mode)
        rgba = Gdk.RGBA()
        rgba.parse(CHROME[mode][0])
        self.web.set_background_color(rgba)

    def present(self, route=None):
        if route:
            self.bridge.route = route    # read by the page when it loads
            self._push("route", route)   # and sent, in case it already has
        if self.win is not None:
            self.win.present()

    def _decide(self, _web, decision, kind):
        if kind not in (WebKit.PolicyDecisionType.NAVIGATION_ACTION, WebKit.PolicyDecisionType.NEW_WINDOW_ACTION):
            return False  # responses: WebKit's default
        action = decision.get_navigation_action()
        uri = action.get_request().get_uri()
        verdict = navigation(uri)
        if verdict == "allow" and kind == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            decision.use()
            return True
        decision.ignore()
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
            message = json.loads(body) if isinstance(body, str) and len(body) <= MAX_MESSAGE + 4096 else None
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


def run_standalone(route=None):
    """The window on its own, without the daemon (`python -m flippy.shell`); returns when it closes."""
    def no_daemon(cmd):
        raise ValueError("Preview on screen works when Flippy is running.")

    app = Gtk.Application(application_id="dev.flippy.window", flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(a):
        AppWindow(command=no_daemon, log=lambda m: None, app=a).present(route or "settings/appearance")
    app.connect("activate", activate)
    app.run([])
