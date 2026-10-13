"""Settings pages for the app window, generated from flippy/settings.py.

Every setting shows up somewhere: a key without an entry in LABELS gets a label made from its name, and a section
without a page entry gets its own page. So settings added elsewhere appear without window work. Only the copy and
grouping live here; types, choices, bounds and validation stay in settings.py.
"""
import sys

from .. import settings

# page id, title, and the settings sections it shows, in sidebar order
PAGES = [
    ("general", "General", ["provider", "updates", "automation"]),
    ("appearance", "Appearance", ["look"]),
    ("models", "Models", ["claude", "codex"]),
    ("tasks", "Desktop tasks", ["act"]),
    ("shortcuts", "Shortcuts", ["keys"]),
    ("timing", "Timing", ["timing"]),
    ("help", "Help mode", ["help"]),
]
HIDDEN = {("onboarding", "done")}  # state, not a preference

# (section, key): (label, help, platforms or None for all)
LABELS = {
    ("provider", "mode"): ("Use", "Automatic picks the only connected subscription.", None),
    ("updates", "check"): ("Check for updates", "Look for a new release once a day and offer to install it.", None),
    ("automation", "clicks"): ("Let scripts click", "Allow `flippy-ask click` to click on screen.", ("darwin",)),
    ("look", "theme"): ("Theme", "How answer cards look.", None),
    ("look", "pointer"): ("Pointer", None, None),
    ("look", "pointer_size"): ("Pointer size", None, None),
    ("look", "text_size"): ("Text size", "Answer text, in points.", None),
    ("look", "card_opacity"): ("Card opacity", None, None),
    ("look", "glass_tint"): ("Glass tint", "How strongly the Glass and Media Player cards are tinted.", None),
    ("look", "glass_color"): ("Glass color", None, None),
    ("look", "controls"): ("Playback controls", None, None),
    ("look", "player_shine"): ("Media Player shine", None, ("darwin",)),
    ("look", "frosted"): ("Frosted glass", "The compositor blurs behind glass cards.", ("linux",)),
    ("claude", "model"): ("Claude model", None, None),
    ("claude", "effort"): ("Claude effort", None, None),
    ("claude", "image"): ("Screenshot size", "Larger is sharper and uses more of your plan.", None),
    ("codex", "model"): ("Codex model", None, None),
    ("codex", "effort"): ("Codex effort", None, None),
    ("act", "mode"): ("Approval", "When Flippy asks before acting in an app.", None),
    ("act", "allowed_apps"): ("Apps allowed to act in", "Apps you approved once. Remove one to be asked again.", None),
    ("act", "infer"): ("Do things when I ask", "A request like “open Spotify” runs as a desktop task.", None),
    ("keys", "ask"): ("Ask about the screen", None, None),
    ("keys", "draw"): ("Circle and ask", None, None),
    ("keys", "video"): ("Check a video edit", None, None),
    ("keys", "pause"): ("Pause a walkthrough", None, None),
    ("timing", "show_seconds"): ("Answer stays at least", "Seconds after it finishes.", None),
    ("timing", "max_show_seconds"): ("Answer stays at most", "Seconds.", None),
    ("timing", "step_pace"): ("Step pace", None, None),
    ("timing", "glide_seconds"): ("Pointer glide", "Seconds between points.", None),
    ("timing", "speed"): ("Walkthrough speed", None, None),
    ("timing", "wait_for_clicks"): ("Wait for my clicks", "Steps marked to click wait until you click.", ("darwin",)),
    ("help", "mode"): ("Help mode", None, None),
    ("help", "apps"): ("Apps to watch", "Comma-separated app ids.", None),
    ("help", "muted"): ("Apps muted", "Apps where you chose “don't ask”.", None),
}


def platform():
    return "darwin" if sys.platform == "darwin" else "linux"


def _label_from_key(key):
    return key.replace("_", " ").capitalize()


def control(section, key):
    """The control kind for one setting, from its default and spec."""
    spec = settings.SETTINGS[section, key]
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
           "control": control(section, key), "value": settings.get(section, key)}
    if spec.choices:
        out["choices"] = [{"value": v, "label": text} for v, text in spec.choices]
    if spec.minimum is not None:
        out.update(min=spec.minimum, max=spec.maximum, step=spec.step, digits=spec.digits)
    return out


def pages(plat=None):
    """Every settings page with its fields. Sections no page claims get a page of their own, at the end."""
    claimed = {s for _, _, sections in PAGES for s in sections}
    extra = [(s, _label_from_key(s), [s]) for s in settings.DEFAULTS if s not in claimed]
    out = []
    for page_id, title, sections in PAGES + extra:
        fields = [f for s in sections if s in settings.DEFAULTS for k in settings.DEFAULTS[s]
                  if (s, k) not in HIDDEN and (f := field(s, k, plat)) is not None]
        if fields:
            out.append({"id": page_id, "title": title, "fields": fields})
    return out
