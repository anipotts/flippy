#!/usr/bin/env python3
"""Disposable macOS input fixture. Run with the project's Python environment.

This process never posts input, opens files, or sends network requests. Its state
exists only in memory. Close the window to quit.
"""
import sys

if sys.platform != 'darwin':
    raise SystemExit('This fixture requires macOS.')

import AppKit as A
import Foundation as F


class Canvas(A.NSView):
    def initWithFrame_(self, frame):
        self = super().initWithFrame_(frame)
        if self is not None:
            self.position = (100, 100)
            self.dragging = False
            self.counts = {'down': 0, 'move': 0, 'up': 0}
            self.flags = 0
            self.changed = False
        return self

    def isFlipped(self):
        return True

    def drawRect_(self, rect):
        (A.NSColor.whiteColor() if not self.changed else A.NSColor.lightGrayColor()).set()
        A.NSRectFill(self.bounds())
        A.NSColor.systemBlueColor().set()
        A.NSBezierPath.bezierPathWithRect_(F.NSMakeRect(*self.position, 80, 80)).fill()
        text = (f'Drag the blue square. down={self.counts["down"]} '
                f'move={self.counts["move"]} up={self.counts["up"]} flags={self.flags}\n'
                f'position={self.position}; content changed={self.changed}')
        F.NSString.stringWithString_(text).drawAtPoint_withAttributes_(
            F.NSMakePoint(20, 20), {A.NSFontAttributeName: A.NSFont.systemFontOfSize_(16)})

    def mouseDown_(self, event):
        self.counts['down'] += 1
        p = self.convertPoint_fromView_(event.locationInWindow(), None)
        x, y = self.position
        self.dragging = x <= p.x <= x + 80 and y <= p.y <= y + 80
        self.offset = (p.x - x, p.y - y)
        self.flags = int(event.modifierFlags())
        self.setNeedsDisplay_(True)

    def mouseDragged_(self, event):
        self.counts['move'] += 1
        if self.dragging:
            p = self.convertPoint_fromView_(event.locationInWindow(), None)
            self.position = (round(p.x - self.offset[0]), round(p.y - self.offset[1]))
        self.flags = int(event.modifierFlags())
        self.setNeedsDisplay_(True)

    def mouseUp_(self, event):
        self.counts['up'] += 1
        self.dragging = False
        self.flags = int(event.modifierFlags())
        self.setNeedsDisplay_(True)


class Delegate(F.NSObject):
    def applicationDidFinishLaunching_(self, notification):
        style = A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable | A.NSWindowStyleMaskResizable
        self.window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            F.NSMakeRect(100, 100, 800, 620), style, A.NSBackingStoreBuffered, False)
        self.window.setTitle_('Flippy disposable action fixture')
        self.window.setDelegate_(self)
        root = self.window.contentView()
        self.field = A.NSTextField.alloc().initWithFrame_(F.NSMakeRect(20, 555, 760, 35))
        self.field.setPlaceholderString_('Type fixture text here. cmd+a and escape are safe to test.')
        root.addSubview_(self.field)
        self.counter = 0
        self.button = A.NSButton.alloc().initWithFrame_(F.NSMakeRect(20, 510, 200, 32))
        self.button.setTitle_('Click counter: 0')
        self.button.setTarget_(self)
        self.button.setAction_('count:')
        root.addSubview_(self.button)
        change = A.NSButton.alloc().initWithFrame_(F.NSMakeRect(240, 510, 240, 32))
        change.setTitle_('Change pixels for stale approval')
        change.setTarget_(self)
        change.setAction_('change:')
        root.addSubview_(change)
        self.scroll = A.NSScrollView.alloc().initWithFrame_(F.NSMakeRect(20, 20, 760, 470))
        self.scroll.setHasVerticalScroller_(True)
        self.scroll.setHasHorizontalScroller_(True)
        self.canvas = Canvas.alloc().initWithFrame_(F.NSMakeRect(0, 0, 1500, 1200))
        self.scroll.setDocumentView_(self.canvas)
        root.addSubview_(self.scroll)
        self.window.makeKeyAndOrderFront_(None)
        A.NSApp.activateIgnoringOtherApps_(True)

    def count_(self, sender):
        self.counter += 1
        sender.setTitle_(f'Click counter: {self.counter}')

    def change_(self, sender):
        self.canvas.changed = not self.canvas.changed
        self.canvas.setNeedsDisplay_(True)

    def windowWillClose_(self, notification):
        A.NSApp.terminate_(None)


app = A.NSApplication.sharedApplication()
app.setActivationPolicy_(A.NSApplicationActivationPolicyRegular)
delegate = Delegate.alloc().init()
app.setDelegate_(delegate)
app.run()
