"""Settings pages for the app window, generated from flippy/settings.py.

Every setting shows up somewhere: a key without an entry in LABELS gets a label made from its name, and a section
without a page entry gets its own page. So settings added elsewhere appear without window work. Only the copy,
grouping and when-to-show live here; types, choices, bounds and validation stay in settings.py.
"""
import sys

from .. import settings

# page id, title, icon, and its groups: (group title or None, [sections])
PAGES = [
    ("general", "General", "gear", [(None, ["provider", "updates"]), ("Scripting", ["automation"])]),
    ("appearance", "Appearance", "sun", [(None, ["window", "look"])]),  # laid out by the page (appearance.js)
    ("models", "Models", "sparkle", [("Claude", ["claude"]), ("Codex / ChatGPT", ["codex"])]),
    ("tasks", "Desktop tasks", "cursor", [(None, ["act"])]),
    ("shortcuts", "Shortcuts", "keyboard", [(None, ["keys"])]),
    ("timing", "Timing", "timer", [(None, ["timing"])]),
    ("help", "Help mode", "lifebuoy", [(None, ["help"])]),
]
HIDDEN = {("onboarding", "done")}  # state, not a preference
ADVANCED = {("timing", "glide_seconds"), ("timing", "speed"), ("claude", "image"), ("help", "muted")}

# (section, key): (label, help, platforms or None for all)
LABELS = {
    ("provider", "mode"): ("Use", "Automatic picks the only connected subscription.", None),
    ("updates", "check"): ("Check for updates", "Look for a new release once a day and offer to install it.", None),
    ("automation", "clicks"): ("Let scripts click", "Allow flippy-ask click to click on screen.", ("darwin",)),
    ("window", "mode"): ("Mode", "This window follows the system, or stays light or dark.", None),
    ("look", "theme"): ("Theme", "How answer cards look.", None),
    ("look", "pointer"): ("Pointer", None, None),
    ("look", "pointer_size"): ("Pointer size", None, None),
    ("look", "text_size"): ("Text size", "Answer text, in points.", None),
    ("look", "card_opacity"): ("Card opacity", None, None),
    ("look", "glass_tint"): ("Tint strength", None, None),
    ("look", "glass_color"): ("Tint", None, None),
    ("look", "controls"): ("Controls on every theme", "Playback controls on every card, not only the players.", None),
    ("look", "player_shine"): ("Shine", "Gloss bars on the Media Player card.", ("darwin",)),
    ("look", "frosted"): ("Frosted glass", "The compositor blurs behind glass cards.", ("linux",)),
    ("claude", "model"): ("Model", None, None),
    ("claude", "effort"): ("Effort", "Higher thinks longer and uses more of your plan.", None),
    ("claude", "image"): ("Screenshot size", "Larger is sharper and uses more of your plan.", None),
    ("codex", "model"): ("Model", None, None),
    ("codex", "effort"): ("Effort", None, None),
    ("act", "mode"): ("Approval", "When Flippy asks before acting in an app.", None),
    ("act", "allowed_apps"): ("Allowed apps", "Apps you approved once. Remove one to be asked again.", None),
    ("act", "infer"): ("Do things when I ask", "A request like “open Spotify” runs as a desktop task.", None),
    ("keys", "ask"): ("Ask about the screen", None, None),
    ("keys", "draw"): ("Circle and ask", None, None),
    ("keys", "video"): ("Check a video edit", None, None),
    ("keys", "pause"): ("Pause a walkthrough", None, None),
    ("timing", "show_seconds"): ("Answer stays at least", "Seconds after it finishes.", None),
    ("timing", "max_show_seconds"): ("Answer stays at most", "Seconds.", None),
    ("timing", "step_pace"): ("Step pace", "How long each walkthrough step holds.", None),
    ("timing", "glide_seconds"): ("Pointer glide", "Seconds between points.", None),
    ("timing", "speed"): ("Walkthrough speed", None, None),
    ("timing", "wait_for_clicks"): ("Wait for my clicks", "Steps marked to click wait until you click.", ("darwin",)),
    ("help", "mode"): ("Help mode", None, None),
    ("help", "apps"): ("Apps to watch", "Comma-separated app ids.", None),
    ("help", "muted"): ("Muted apps", "Apps where you chose “don't ask”.", None),
}
# Shown only while another setting has one of these values (a theme's own options stay with that theme).
WHEN = {
    ("look", "player_shine"): ("look.theme", ["mediaplayer"]),
    ("look", "frosted"): ("look.theme", ["glass", "mediaplayer"]),
}
# Two-value choices shown as a switch: (value when on, value when off).
SWITCHES = {("look", "controls"): ("all", "players")}
UNITS = {("look", "text_size"): "pt", ("timing", "show_seconds"): "s", ("timing", "max_show_seconds"): "s",
         ("timing", "glide_seconds"): "s", ("timing", "speed"): "×", ("look", "pointer_size"): "×"}


def platform():
    return "darwin" if sys.platform == "darwin" else "linux"


def _label_from_key(key):
    return key.replace("_", " ").capitalize()


def control(section, key):
    """The control kind for one setting, from its default and spec."""
    spec = settings.SETTINGS[section, key]
    if (section, key) in SWITCHES:
        return "switch"
    if spec.choices:
        return "choice"
    if isinstance(spec.default, bool):
        return "switch"
    if spec.minimum is not None:
        return "slider"
    if isinstance(spec.default, list):
        return "list"
    if section == "keys":
        return "shortcut"
    return "text"


def field(section, key, plat=None):
    """One setting as plain data for the page, or None when it doesn't apply on this platform."""
    label, help_text, platforms = LABELS.get((section, key), (_label_from_key(key), None, None))
    if platforms and (plat or platform()) not in platforms:
        return None
    spec = settings.SETTINGS[section, key]
    out = {"id": f"{section}.{key}", "section": section, "key": key, "label": label, "help": help_text,
           "control": control(section, key), "value": settings.get(section, key), "default": spec.default,
           "advanced": (section, key) in ADVANCED}
    if spec.choices:
        out["choices"] = [{"value": v, "label": text} for v, text in spec.choices]
    if spec.minimum is not None:
        out.update(min=spec.minimum, max=spec.maximum, step=spec.step, digits=spec.digits)
    if (section, key) in SWITCHES:
        out["on"], out["off"] = SWITCHES[section, key]
    if (section, key) in WHEN:
        out["when"] = {"id": WHEN[section, key][0], "values": WHEN[section, key][1]}
    if (section, key) in UNITS:
        out["unit"] = UNITS[section, key]
    return out


def pages(plat=None):
    """Every settings page with its groups of fields. Sections no page claims get a page of their own, at the end."""
    claimed = {s for *_, groups in PAGES for _, sections in groups for s in sections}
    extra = [(s, _label_from_key(s), "dots", [(None, [s])]) for s in settings.DEFAULTS if s not in claimed]
    out = []
    for page_id, title, icon, groups in PAGES + extra:
        built = []
        for group_title, sections in groups:
            fields = [f for s in sections if s in settings.DEFAULTS for k in settings.DEFAULTS[s]
                      if (s, k) not in HIDDEN and (f := field(s, k, plat)) is not None]
            if fields:
                built.append({"title": group_title, "fields": fields})
        if built:
            out.append({"id": page_id, "title": title, "icon": icon, "groups": built,
                        "fields": [f for g in built for f in g["fields"]]})
    return out
