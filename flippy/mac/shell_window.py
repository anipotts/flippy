"""The app window on macOS: a WKWebView showing flippy/shell/web, talking to Python through flippy/shell/bridge.py.

Flippy is a menu bar app (no Dock icon). While this window is open it becomes a regular app, with a Dock icon,
⌘-Tab and a menu bar of its own; closing the window makes it a menu bar app again. ⌘Q in the window closes the
window: quitting Flippy stays in the menu bar icon's menu.

The page loads from local files only; its Content-Security-Policy allows nothing remote. (TODO before shipping:
serve it through a WKURLSchemeHandler instead of file URLs.)
"""
import json
import os

import objc
from AppKit import (NSApp, NSAppearance, NSApplicationActivationPolicyAccessory, NSApplicationActivationPolicyRegular,
                    NSBackingStoreBuffered, NSColor, NSColorSpace, NSMenu, NSMenuItem, NSModalResponseOK, NSOpenPanel,
                    NSPasteboard, NSPasteboardTypeString, NSSavePanel, NSWindow, NSWindowStyleMaskClosable,
                    NSWindowStyleMaskFullSizeContentView, NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable,
                    NSWindowStyleMaskTitled, NSWindowTitleHidden)
from Foundation import NSMakeRect, NSMakeSize, NSObject, NSURL
from WebKit import WKUserContentController, WKWebView, WKWebViewConfiguration

from ..shell.bridge import Bridge, Host

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shell", "web")
WIDTH, HEIGHT = 1160, 780
TITLEBAR = 30          # the strip the traffic lights sit in; the page starts below it so the strip drags the window
AUTOSAVE = "FlippyAppWindow"
CHROME = {"dark": (0x0b / 255, 0x0b / 255, 0x0c / 255), "light": (0xe9 / 255, 0xe9 / 255, 0xec / 255)}  # app.css --chrome
WKScriptMessageHandler = objc.protocolNamed("WKScriptMessageHandler")


class _Handler(NSObject, protocols=[WKScriptMessageHandler]):
    def userContentController_didReceiveScriptMessage_(self, controller, message):
        self.owner._message(message.body())

    def windowWillClose_(self, note):
        self.owner._closed()


def _menu():
    """The window's menu bar: Close (⌘W, and ⌘Q, which doesn't quit Flippy) and Edit, so text fields get
    copy and paste."""
    bar = NSMenu.alloc().init()
    app = NSMenu.alloc().initWithTitle_("Flippy")
    app.addItemWithTitle_action_keyEquivalent_("Close Window", "performClose:", "w")
    app.addItemWithTitle_action_keyEquivalent_("Close Flippy Window", "performClose:", "q")
    app.addItem_(NSMenuItem.separatorItem())
    app.addItemWithTitle_action_keyEquivalent_("Hide Flippy", "hide:", "h")
    edit = NSMenu.alloc().initWithTitle_("Edit")
    for title, action, key in [("Undo", "undo:", "z"), ("Redo", "redo:", "Z"), ("Cut", "cut:", "x"),
                               ("Copy", "copy:", "c"), ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")]:
        edit.addItemWithTitle_action_keyEquivalent_(title, action, key)
    for sub in (app, edit):
        item = NSMenuItem.alloc().init()
        item.setSubmenu_(sub)
        bar.addItem_(item)
    return bar


class MacHost(Host):
    def __init__(self, window):
        self.window = window
        self.sampler = None
        self.buddy = None

    def copy_text(self, text):
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        return bool(pb.setString_forType_(text, NSPasteboardTypeString))

    def save_file(self, suggested, data, kind):
        panel = NSSavePanel.savePanel()
        panel.setNameFieldStringValue_(suggested)
        panel.setAllowedFileTypes_([kind])
        if panel.runModal() != NSModalResponseOK:
            return False
        with open(panel.URL().path(), "wb") as f:
            f.write(data)
        return True

    def open_file(self, kinds):
        panel = NSOpenPanel.openPanel()
        panel.setAllowedFileTypes_(kinds)
        panel.setAllowsMultipleSelection_(False)
        if panel.runModal() != NSModalResponseOK:
            return None
        path = panel.URL().path()
        if os.path.getsize(path) > 20 * 1024 * 1024:
            raise ValueError("That file is too big for a pointer.")
        with open(path, "rb") as f:
            return os.path.basename(path), f.read()

    def sample_color(self, done):
        from AppKit import NSColorSampler

        def picked(color):
            if color is None:
                done(None)
                return
            c = color.colorUsingColorSpace_(NSColorSpace.sRGBColorSpace())
            done("#" + "".join(f"{round(v * 255):02x}" for v in (c.redComponent(), c.greenComponent(), c.blueComponent())))
        self.sampler = NSColorSampler.alloc().init()  # kept while it's up
        self.sampler.showSamplerWithSelectionHandler_(picked)

    def set_chrome(self, mode):
        self.window.set_chrome(mode)

    def setup_state(self):
        from . import setup
        return setup.state()

    def setup_action(self, name):
        from . import setup
        setup.act(name)

    def close(self):
        self.window.win.performClose_(None)

    def drag_target(self, rect):
        """A native, draggable Flippy.app icon over the page's spot for it: System Settings' permission lists
        take a dragged app, which a web page can't offer."""
        from . import setup
        web = self.window.web
        if web is None:
            return
        if rect is None or not setup.installed():
            if self.buddy is not None:
                self.buddy.removeFromSuperview()
                self.buddy = None
            return
        if self.buddy is None:
            from .permission_buddy import app_icon
            self.buddy = app_icon(setup.APP)
            web.addSubview_(self.buddy)
        h = web.bounds().size.height
        y = rect["y"] if web.isFlipped() else h - rect["y"] - rect["h"]
        self.buddy.setFrame_(NSMakeRect(rect["x"], y, rect["w"], rect["h"]))


class AppWindow:
    def __init__(self, on_close=lambda: None, command=lambda cmd: None, log=print):
        self.on_close, self.log = on_close, log
        self.handler = _Handler.alloc().init()
        self.handler.owner = self
        self.bridge = Bridge(push=self._push, command=command, log=log, host=MacHost(self))
        config = WKWebViewConfiguration.alloc().init()
        content = WKUserContentController.alloc().init()
        content.addScriptMessageHandler_name_(self.handler, "flippy")
        config.setUserContentController_(content)
        self.content = content
        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
                 | NSWindowStyleMaskResizable | NSWindowStyleMaskFullSizeContentView)
        self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, HEIGHT), style, NSBackingStoreBuffered, False)
        self.win.setTitle_("Flippy")
        self.win.setTitleVisibility_(NSWindowTitleHidden)
        self.win.setTitlebarAppearsTransparent_(True)
        self.win.setReleasedWhenClosed_(False)
        self.win.setContentMinSize_(NSMakeSize(760, 480))
        self.win.setDelegate_(self.handler)
        bounds = self.win.contentView().bounds()
        frame = NSMakeRect(0, 0, bounds.size.width, bounds.size.height - TITLEBAR)
        self.web = WKWebView.alloc().initWithFrame_configuration_(frame, config)
        self.web.setAutoresizingMask_(18)  # width and height sizable; the strip above stays the title bar
        self.web.setValue_forKey_(False, "drawsBackground")  # no white flash before the page paints
        self.win.contentView().addSubview_(self.web)
        self.set_chrome("dark")
        if not self.win.setFrameUsingName_(AUTOSAVE):
            self.win.center()
        self.win.setFrameAutosaveName_(AUTOSAVE)
        index = NSURL.fileURLWithPath_(os.path.join(WEB, "index.html"))
        self.web.loadFileURL_allowingReadAccessToURL_(index, NSURL.fileURLWithPath_isDirectory_(WEB, True))
        self._old_menu = None

    def set_chrome(self, mode):
        """The title strip and the window frame follow the page's light or dark."""
        self.win.setBackgroundColor_(NSColor.colorWithSRGBRed_green_blue_alpha_(*CHROME[mode], 1))
        self.win.setAppearance_(NSAppearance.appearanceNamed_(
            "NSAppearanceNameDarkAqua" if mode == "dark" else "NSAppearanceNameAqua"))

    @property
    def route(self):
        """The page showing now ("setup", "settings/appearance"...), or the one it's opening on."""
        return self.bridge.current or self.bridge.route

    def present(self, route=None):
        if route:
            self.bridge.route = route    # read by the page when it loads
            self.bridge.current = route
            self._push("route", route)   # and sent, in case it already has
        if NSApp.activationPolicy() != NSApplicationActivationPolicyRegular:
            self._old_menu = NSApp.mainMenu()
            NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
            NSApp.setMainMenu_(_menu())
        self.win.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    def _closed(self):
        self.bridge.close()
        self.content.removeScriptMessageHandlerForName_("flippy")
        NSApp.setMainMenu_(self._old_menu)
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        self.web.removeFromSuperview()  # drop the page so WebKit can end its content process
        self.web = None
        self.on_close()

    def _message(self, body):
        try:
            message = json.loads(body) if isinstance(body, str) and len(body) <= 4 * 1024 * 1024 + 4096 else None
        except ValueError:
            message = None
        self._js("window.flippy.reply", self.bridge.handle(message))

    def _push(self, event, data):
        self._js("window.flippy.event", event, data)

    def _js(self, fn, *args):
        if self.web is None:
            return
        self.web.evaluateJavaScript_completionHandler_(f"{fn}({', '.join(json.dumps(a) for a in args)})", None)
