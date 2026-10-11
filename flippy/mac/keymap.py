"""Key codes for typing text, character by character. No AppKit or Carbon here, so it imports anywhere (the
gesture tests run the macOS typing code on Linux too)."""

# US-layout key codes for typed punctuation: (code, shifted). Apps that read key codes (terminals, games, some
# shortcuts) see the real key instead of "a".
TYPE_KEYS = {"-": (27, False), "=": (24, False), "[": (33, False), "]": (30, False), "\\": (42, False),
             ";": (41, False), "'": (39, False), "`": (50, False), "\n": (36, False), "\t": (48, False),
             "!": (18, True), "@": (19, True), "#": (20, True), "$": (21, True), "%": (23, True), "^": (22, True),
             "&": (26, True), "*": (28, True), "(": (25, True), ")": (29, True), "_": (27, True), "+": (24, True),
             "{": (33, True), "}": (30, True), "|": (42, True), ":": (41, True), '"': (39, True), "<": (43, True),
             ">": (47, True), "?": (44, True), "~": (50, True)}
UNMAPPED_KEY = 0x0A  # the ISO section key, absent on ANSI keyboards: for characters with no key (é, emoji)


def type_key(ch, keys):
    """(key code, shifted) to type one character. keys: hotkeys.KEYS (letters, digits, space...)."""
    if ch in TYPE_KEYS:
        return TYPE_KEYS[ch]
    code = keys.get("space" if ch == " " else ch.lower())
    if code is None:
        return UNMAPPED_KEY, False
    return code, ch.isupper()
