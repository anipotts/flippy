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
from AppKit import (NSApp, NSApplicationActivationPolicyAccessory, NSApplicationActivationPolicyRegular,
                    NSBackingStoreBuffered, NSMenu, NSMenuItem, NSWindow, NSWindowStyleMaskClosable,
                    NSWindowStyleMaskMiniaturizable, NSWindowStyleMaskResizable, NSWindowStyleMaskTitled)
from Foundation import NSMakeRect, NSMakeSize, NSObject, NSURL
from WebKit import WKUserContentController, WKWebView, WKWebViewConfiguration

from ..shell.bridge import Bridge

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "shell", "web")
WIDTH, HEIGHT = 820, 600
AUTOSAVE = "FlippyAppWindow"
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


class AppWindow:
    def __init__(self, on_close=lambda: None, command=lambda cmd: None, log=print):
        self.on_close, self.log = on_close, log
        self.handler = _Handler.alloc().init()
        self.handler.owner = self
        self.bridge = Bridge(push=self._push, command=command, log=log)
        config = WKWebViewConfiguration.alloc().init()
        content = WKUserContentController.alloc().init()
        content.addScriptMessageHandler_name_(self.handler, "flippy")
        config.setUserContentController_(content)
        self.content = content
        style = (NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
                 | NSWindowStyleMaskResizable)
        self.win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, HEIGHT), style, NSBackingStoreBuffered, False)
        self.win.setTitle_("Flippy")
        self.win.setReleasedWhenClosed_(False)
        self.win.setContentMinSize_(NSMakeSize(640, 420))
        self.win.setDelegate_(self.handler)
        self.web = WKWebView.alloc().initWithFrame_configuration_(self.win.contentView().bounds(), config)
        self.web.setAutoresizingMask_(18)  # width and height sizable
        self.win.contentView().addSubview_(self.web)
        if not self.win.setFrameUsingName_(AUTOSAVE):
            self.win.center()
        self.win.setFrameAutosaveName_(AUTOSAVE)
        index = NSURL.fileURLWithPath_(os.path.join(WEB, "index.html"))
        self.web.loadFileURL_allowingReadAccessToURL_(index, NSURL.fileURLWithPath_isDirectory_(WEB, True))
        self._old_menu = None

    def present(self, route=None):
        if route:
            self.bridge.route = route    # read by the page when it loads
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
            message = json.loads(body) if isinstance(body, str) and len(body) <= 64 * 1024 else None
        except ValueError:
            message = None
        self._js("window.flippy.reply", self.bridge.handle(message))

    def _push(self, event, data):
        self._js("window.flippy.event", event, data)

    def _js(self, fn, *args):
        if self.web is None:
            return
        self.web.evaluateJavaScript_completionHandler_(f"{fn}({', '.join(json.dumps(a) for a in args)})", None)
