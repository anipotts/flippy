"""A file drag for the exact installed app, with a Finder fallback."""
import os

from AppKit import NSDraggingItem, NSDragOperationCopy, NSImageView, NSWorkspace
from Foundation import NSMakeRect, NSURL


class PermissionBuddy(NSImageView):
    """Drag the app itself, never a generated build or its Python executable."""

    def mouseDragged_(self, event):
        if not self.app_path or not os.path.isdir(self.app_path):
            return
        url = NSURL.fileURLWithPath_(self.app_path)
        item = NSDraggingItem.alloc().initWithPasteboardWriter_(url)
        item.setDraggingFrame_contents_(self.bounds(), self.image())
        self.beginDraggingSessionWithItems_event_source_([item], event, self)

    def draggingSession_sourceOperationMaskForDraggingContext_(self, session, context):
        return NSDragOperationCopy

    def ignoreModifierKeysForDraggingSession_(self, session):
        return True


def app_icon(app_path):
    icon = PermissionBuddy.alloc().initWithFrame_(NSMakeRect(0, 0, 64, 64))
    icon.app_path = os.path.abspath(app_path)
    icon.setImage_(NSWorkspace.sharedWorkspace().iconForFile_(icon.app_path))
    icon.setToolTip_("Drag this app into a permission list that accepts apps")
    icon.setAccessibilityLabel_("Drag " + os.path.basename(icon.app_path) + " to System Settings")
    return icon


def reveal_app(app_path):
    NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_([
        NSURL.fileURLWithPath_(os.path.abspath(app_path))])
