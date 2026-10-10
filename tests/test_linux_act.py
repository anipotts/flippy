"""Desktop tasks on COSMIC (flippy/linux/atspi.py, act.py, borrow.py, scripts.py, mpris.py) without a desktop:
which AT-SPI app a Wayland window is, where controls are in the screenshot, the look's text from a fake tree,
menus, the media player choice, borrowing a window, and the Linux tool contract."""
import asyncio
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flippy.actions import WAYLAND, AppFrame, ApprovalPolicy, DesktopTools, RetryableActionError, app_id

LINUX = sys.platform.startswith("linux")


def _atspi():
    try:
        from flippy.linux import atspi
    except (ImportError, ValueError) as e:  # no AT-SPI typelib
        raise unittest.SkipTest(f"AT-SPI unavailable: {e}")
    return atspi


@unittest.skipUnless(LINUX, "Linux only")
class WhichApp(unittest.TestCase):
    def setUp(self):
        self.atspi = _atspi()

    def test_flatpak_id_beats_a_shared_process_name(self):
        apps = [{"pid": 10, "name": "spotify", "frames": [], "comm": "spotify", "exe": "spotify", "flatpak": ""},
                {"pid": 20, "name": "Spotify", "frames": [], "comm": "spotify", "exe": "spotify",
                 "flatpak": "com.spotify.Client"}]
        self.assertEqual(self.atspi.match_app("com.spotify.Client", "Spotify Premium", apps), 20)

    def test_the_window_title_picks_between_two_of_the_same_app(self):
        apps = [{"pid": 1, "name": "gedit", "frames": ["notes.txt - gedit"], "comm": "gedit", "exe": "gedit"},
                {"pid": 2, "name": "gedit", "frames": ["todo.txt - gedit"], "comm": "gedit", "exe": "gedit"}]
        self.assertEqual(self.atspi.match_app("gedit", "todo.txt - gedit", apps), 2)

    def test_the_desktop_files_executable_names_a_dotted_app_id(self):
        # org.gnome.Calculator's process is gnome-calculator (and /proc/comm cuts names at 15 characters)
        apps = [{"pid": 7, "name": "gnome-calculator", "frames": ["Calculator"], "comm": "gnome-calculato",
                 "exe": "gnome-calculator"}]
        self.assertEqual(self.atspi.match_app("org.gnome.Calculator", None, apps, ["gnome-calculator"]), 7)
        self.assertIsNone(self.atspi.match_app("org.gnome.Calculator", None, apps))  # no hint, no guess

    def test_a_task_typed_in_the_question_box_starts_in_the_window_before_it(self):
        # the box is a window of Flippy's own that takes the focus
        tl = lambda app, active, at: SimpleNamespace(app_id=app, activated=active, active_at=at)  # noqa: E731
        firefox, gedit, box = tl("firefox", False, 5.0), tl("gedit", False, 9.0), tl("dev.flippy.daemon", True, 10.0)
        self.assertIs(self.atspi.before_flippy([firefox, gedit, box]), gedit)
        gedit.activated, box.activated = True, False
        self.assertIs(self.atspi.before_flippy([firefox, gedit, box]), gedit)
        self.assertIsNone(self.atspi.before_flippy([box]))

    def test_nothing_matching_is_none(self):
        apps = [{"pid": 3, "name": "evolution-alarm-notify", "frames": [], "comm": "evolution-alar", "exe": ""}]
        self.assertIsNone(self.atspi.match_app("com.system76.CosmicEdit", "Untitled", apps))


@unittest.skipUnless(LINUX, "Linux only")
class Positions(unittest.TestCase):
    def setUp(self):
        self.atspi = _atspi()

    def test_gtk3_counts_from_the_surface_shadow_included(self):
        # gedit: a 630x656 window inside a surface with a 20 px shadow all round
        self.assertEqual(self.atspi.origin([(20, 20, 630, 47), (20, 67, 630, 609)], 630, 656), (20, 20))

    def test_gtk4_counts_from_the_visible_window(self):
        self.assertEqual(self.atspi.origin([(0, 0, 360, 480)], 360, 480), (0, 0))

    def test_a_server_side_title_bar_is_above_the_content(self):
        # 36 px title bar and 1 px border drawn by the compositor, which AT-SPI doesn't count
        self.assertEqual(self.atspi.origin([(0, 0, 798, 563)], 800, 600), (-1, -37))

    def test_screen_points_map_back_to_atspi_window_coordinates(self):
        target = ("gedit", 99, 5, (978, 246, 630, 656), WAYLAND)
        self.atspi._origins[(99, 5)] = (20, 20)
        frame = AppFrame("x", (315, 328), target, {}, "")  # the screenshot was sent at half size
        x, y = frame.to_logical(296, 11)                    # the Close button in the screenshot
        self.assertEqual(self.atspi.to_window(target, x, y), (20 + 592, 20 + 22))


class FakeStates:
    def __init__(self, *names):
        self.names = set(names)

    def contains(self, state):
        return state.value_nick.replace("-", "_").upper() in self.names


class Fake:
    """An AT-SPI accessible as far as the look's walk asks."""

    def __init__(self, role, name="", children=(), states=("SHOWING", "SENSITIVE", "ENABLED"), box=(0, 0, 10, 10),
                 actions=(), text="", editable=False):
        self.role, self.name, self.children, self.states = role, name, list(children), FakeStates(*states)
        self.box, self.actions, self.text, self.editable = box, list(actions), text, editable

    def get_role_name(self):
        return self.role

    def get_name(self):
        return self.name

    def get_description(self):
        return ""

    def get_state_set(self):
        return self.states

    def get_interfaces(self):
        return ["Action", "Component"] + (["EditableText", "Text"] if self.editable else [])

    def get_child_count(self):
        return len(self.children)

    def get_child_at_index(self, i):
        return self.children[i]


@unittest.skipUnless(LINUX, "Linux only")
class LookText(unittest.TestCase):
    def setUp(self):
        self.atspi = _atspi()
        a = self.atspi
        self.patches = [patch.object(a, "_extents", lambda el: el.box),
                        patch.object(a, "_actions", lambda el: [(i, n) for i, n in enumerate(el.actions)]),
                        patch.object(a, "_text", lambda el, limit=81: el.text),
                        patch.object(a, "_editable", lambda el, st=None: el.editable)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def walk(self, frame):
        elements, lines, buttons = {}, [], []
        self.atspi._walk(frame, elements, lines, buttons, lambda b: tuple(v * 2 for v in b))
        return elements, lines, buttons

    def test_controls_are_numbered_with_what_can_be_done_to_them(self):
        frame = Fake("frame", "notes - gedit", [
            Fake("push button", "Save", [Fake("label", "Save")], actions=["click"], box=(400, 0, 50, 40)),
            Fake("toggle button", "Menu", actions=["click"], box=(460, 0, 30, 40),
                 states=("SHOWING", "SENSITIVE", "ENABLED", "CHECKED")),
            Fake("text", "", text="hello", editable=True, box=(0, 40, 500, 400),
                 states=("SHOWING", "SENSITIVE", "ENABLED", "MULTI_LINE")),
            Fake("push button", "Hidden", actions=["click"], states=("SENSITIVE",)),
            Fake("push button", "Undo", actions=["click"], states=("SHOWING",)),
        ])
        elements, lines, buttons = self.walk(frame)
        self.assertEqual(lines, ["[1] button 'Save' (800,0 100x80) [press]",       # its label isn't listed again
                                 "[2] toggle button 'Menu' = 'on' (920,0 60x80) [press]",
                                 "[3] text area '' = 'hello' (0,80 1000x800) [set_text, focus]",
                                 "[4] button 'Undo' (off) (0,0 20x20) [press]"])  # hidden ones aren't listed
        self.assertEqual(buttons, ["Menu"])
        self.assertEqual(elements[1][2], "Save")

    def test_menu_bar_menus_are_listed_with_greyed_items(self):
        bar = Fake("menu bar", children=[
            Fake("menu", "File", [Fake("menu item", "New"), Fake("separator"),
                                  Fake("menu item", "Revert", states=("SHOWING",)), Fake("menu", "Recent")]),
            Fake("menu", "Edit", [Fake("menu item", "Undo")])])
        frame = Fake("frame", "LibreOffice", [Fake("panel", children=[bar])])
        self.assertEqual(self.atspi._menus(frame), "  File: New, Revert (off), Recent >\n  Edit: Undo")

    def test_no_menus_at_all_says_none(self):
        self.assertEqual(self.atspi._menus(Fake("frame")), "  (none)")

    def test_menu_titles_match_with_or_without_the_ellipsis(self):
        self.assertEqual(self.atspi._title("Save As…"), self.atspi._title("save as..."))
        self.assertEqual(self.atspi._title(" Find "), "find")


@unittest.skipUnless(LINUX, "Linux only")
class MediaPlayers(unittest.TestCase):
    def test_the_one_playing_then_a_paused_one(self):
        from flippy.linux import mpris
        p = "org.mpris.MediaPlayer2."
        self.assertEqual(mpris.choose([(p + "vlc", "Paused"), (p + "spotify", "Playing")]), p + "spotify")
        self.assertEqual(mpris.choose([(p + "vlc", "Stopped"), (p + "firefox.instance_1_9", "Paused")]),
                         p + "firefox.instance_1_9")
        self.assertEqual(mpris.choose([(p + "vlc", "Stopped")]), p + "vlc")
        self.assertIsNone(mpris.choose([]))


@unittest.skipUnless(LINUX, "Linux only")
class Scripts(unittest.TestCase):
    def test_values_are_checked_before_anything_runs(self):
        from flippy.linux import scripts
        with self.assertRaisesRegex(RetryableActionError, "spotify:"):
            scripts.run("spotify.play_uri", {"uri": "https://open.spotify.com/x"})
        with self.assertRaisesRegex(RetryableActionError, "http"):
            scripts.run("browser.open_url", {"url": "file:///etc/passwd"})
        with self.assertRaisesRegex(RetryableActionError, "needs query"):
            scripts.run("spotify.open_search", {})
        with self.assertRaisesRegex(RetryableActionError, "Choices"):
            scripts.run("notes.new_note", {"title": "x", "body": "y"})  # macOS only

    def test_a_search_is_one_escaped_uri(self):
        from flippy.linux import scripts
        with patch.object(scripts, "_open_uri") as opened:
            scripts.run("spotify.open_search", {"query": "city pop & 80s"})
        opened.assert_called_once_with("spotify:search:city%20pop%20%26%2080s", "Spotify links")

    def test_the_catalog_lists_exactly_the_linux_actions(self):
        from flippy.linux import act, scripts
        text = act.CATALOG["app_action"]["description"]
        self.assertTrue(all(name in text for name in scripts.ACTIONS))
        self.assertNotIn("notes.", text)
        self.assertNotIn("safari", text)


@unittest.skipUnless(LINUX, "Linux only")
class Borrowing(unittest.TestCase):
    """flippy/linux/borrow.py: only while the user is idle, only on that window, and their window always comes back."""

    def setUp(self):
        from flippy.linux.borrow import Borrow
        now = [0.0]
        self.clock = SimpleNamespace(monotonic=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
        self.idle = [5.0]
        self.theirs = SimpleNamespace(ext_id=1, activated=True, geometry=(0, 0, 800, 600))
        self.target = SimpleNamespace(ext_id=2, activated=False, geometry=(100, 100, 400, 300))
        self.conn = SimpleNamespace(toplevels={1: self.theirs, 2: self.target}, idle_s=lambda: self.idle[0],
                                    active=lambda: next(t for t in (self.theirs, self.target) if t.activated))

        def activate(tl):
            for t in (self.theirs, self.target):
                t.activated = t is tl
        self.conn.activate = Mock(side_effect=activate)
        self.borrow = Borrow(self.conn, self.clock)

    def test_acts_in_front_then_gives_their_window_back(self):
        seen = []
        self.borrow(self.target, lambda: seen.append(self.target.activated) or "ok", threading.Event())
        self.assertEqual(seen, [True])
        self.assertTrue(self.theirs.activated)
        self.assertEqual(self.conn.activate.call_args_list[-1].args, (self.theirs,))

    def test_never_takes_it_while_they_keep_working(self):
        self.idle[0] = 0.2
        act = Mock()
        with self.assertRaisesRegex(RetryableActionError, "kept working"):
            self.borrow(self.target, act, threading.Event())
        act.assert_not_called()
        self.conn.activate.assert_not_called()

    def test_refuses_a_spot_off_the_window_and_still_gives_it_back(self):
        act = Mock()
        with self.assertRaises(RetryableActionError):
            self.borrow(self.target, act, threading.Event(), point=(50, 50))
        act.assert_not_called()
        self.assertTrue(self.theirs.activated)

    def test_their_window_comes_back_even_when_the_input_fails(self):
        def boom():
            raise RuntimeError("virtual keyboard gone")
        with self.assertRaises(RuntimeError):
            self.borrow(self.target, boom, threading.Event())
        self.assertTrue(self.theirs.activated)

    def test_a_window_that_wont_come_forward_is_a_retry(self):
        self.conn.activate = Mock()  # the compositor ignores it
        with self.assertRaisesRegex(RetryableActionError, "forward"):
            self.borrow(self.target, Mock(), threading.Event())


class LinuxIds(unittest.TestCase):
    """flippy/actions.py: Wayland app ids (target[4] == "wayland") may be bare names; macOS ids must stay dotted."""

    def test_bare_wayland_ids_are_ids_but_not_on_macos(self):
        self.assertEqual(app_id(("firefox", 12, 3, (0, 0, 1, 1), WAYLAND)), "firefox")
        self.assertEqual(app_id(("org.gnome.TextEditor", 12, 3, (0, 0, 1, 1), WAYLAND)), "org.gnome.texteditor")
        self.assertIsNone(app_id(("firefox", 12, 3, (0, 0, 1, 1), 0)))
        self.assertIsNone(app_id(("Text Editor", 12, 3, (0, 0, 1, 1), WAYLAND)))

    def test_linux_terminals_settings_browsers_and_password_managers_always_ask(self):
        for app in ("com.system76.CosmicTerm", "org.gnome.Ptyxis", "kitty", "Alacritty", "org.wezfurlong.wezterm",
                    "com.system76.CosmicSettings", "firefox", "org.mozilla.firefox", "google-chrome", "chromium",
                    "brave-browser", "app.zen_browser.zen", "org.keepassxc.KeePassXC", "com.bitwarden.desktop",
                    "1password"):
            self.assertTrue(ApprovalPolicy.sensitive((app, 12, 3, (0, 0, 1, 1), WAYLAND)), app)
        for app in ("gedit", "org.gnome.Calculator", "com.system76.CosmicEdit", "org.gnome.Nautilus"):
            self.assertFalse(ApprovalPolicy.sensitive((app, 12, 3, (0, 0, 1, 1), WAYLAND)), app)

    def test_macos_targets_are_judged_exactly_as_before(self):
        # a Linux-only entry on a macOS target doesn't count
        self.assertFalse(ApprovalPolicy.sensitive(("com.apple.textedit", 12, 3, (0, 0, 1, 1), 0)))
        self.assertTrue(ApprovalPolicy.sensitive(("com.apple.terminal", 12, 3, (0, 0, 1, 1), 0)))


@unittest.skipUnless(LINUX, "Linux only")
class LinuxTools(unittest.IsolatedAsyncioTestCase):
    """The controller uses the platform's catalog (flippy/linux/act.py on COSMIC)."""

    async def asyncSetUp(self):
        try:
            from flippy.linux import act
        except ImportError as e:
            raise unittest.SkipTest(str(e))
        self.act = act
        target = ("gedit", 42, 3, (0, 0, 100, 100), WAYLAND)
        self.frame = AppFrame("anBn", (100, 100), target, {1: (object(), "text", "body", [], True)}, "App: gedit")
        self.done = []

        async def capture():
            return self.frame

        async def approve(name, args, shot):
            return True

        async def perform(name, args, shot, cancel):
            self.done.append((name, args))
        self.tools = DesktopTools(capture, approve, perform, approval_mode="per_app", catalog=act.CATALOG,
                                  prompt=act.PROMPT)
        await self.tools.invoke("look", {})

    async def test_shortcuts_are_ctrl_not_cmd(self):
        r = await self.tools.invoke("key", {"combo": "ctrl+s", "reason": "save"})
        self.assertFalse(r.get("is_error"))
        r = await self.tools.invoke("key", {"combo": "cmd+s", "reason": "save"})
        self.assertTrue(r.get("is_error"))

    async def test_clicks_take_no_real_pointer_choice(self):
        r = await self.tools.invoke("click", {"x": 5, "y": 5, "count": 1, "reason": "the button"})
        self.assertFalse(r.get("is_error"))
        self.assertEqual(self.done[-1][0], "click")

    async def test_the_daemon_hands_the_platforms_catalog_to_the_task(self):
        from flippy import daemon
        seen = {}

        class Tools:
            def __init__(self, *a, catalog=None, prompt=None, **kw):
                seen["catalog"], seen["prompt"] = catalog, prompt
                self.max_turns = 0
        ui = SimpleNamespace(act_catalog=self.act.CATALOG, act_prompt=self.act.PROMPT, app_look=Mock(),
                             app_preflight=Mock(), app_front=Mock(return_value=("gedit", "gedit", 42)))
        f = SimpleNamespace(busy=False, video=SimpleNamespace(recording=False), input_disabled=False, ui=ui,
                            box=Mock(), _begin_request=Mock(return_value=Mock()),
                            _run_request=Mock(side_effect=lambda req, coro, *a: coro.close()),
                            _acting=Mock(), brain=Mock())
        with patch.object(daemon, "DesktopTools", Tools), patch.object(daemon.settings, "get", return_value="per_app"):
            daemon.Flippy.act(f, "write a haiku")
        self.assertIs(seen["catalog"], self.act.CATALOG)
        self.assertTrue(seen["prompt"].startswith(self.act.PROMPT))

    async def test_any_app_shortcut_but_not_the_desktops(self):
        for combo in ("shift+a", "tab", "ctrl+shift+s", "alt+f4", "f12", "ctrl+/", "pagedown"):
            r = await self.tools.invoke("key", {"combo": combo, "reason": "x"})
            self.assertFalse(r.get("is_error"), combo)
        for combo in ("super+q", "ctrl+alt+t", "ctrl+shift+alt+z", "A", "cmd+s", "ctrl+"):
            self.tools.cancel.clear()
            self.tools.failure = None
            await self.tools.invoke("look", {})
            r = await self.tools.invoke("key", {"combo": combo, "reason": "x"})
            self.assertTrue(r.get("is_error"), combo)

    def test_every_key_offered_can_be_typed(self):
        import re
        from flippy.linux import keyboard
        pattern = self.act.CATALOG["key"]["schema"]["properties"]["combo"]["pattern"]
        for last in (*self.act.NAMED_KEYS, "a", "7", "f11", "/", "`"):
            self.assertTrue(re.fullmatch(pattern, "ctrl+shift+" + last), last)
            self.assertTrue(last in keyboard.NAMED or len(last) == 1 or last[1:].isdigit(), last)
        self.assertTrue(all(m in keyboard.MODS for m in ("ctrl", "shift", "alt")))


@unittest.skipUnless(LINUX, "Linux only")
class Cards(unittest.TestCase):
    """The overlay's notices stack: an approval card over a tip doesn't lose the tip, and neither hides the other."""

    def test_hiding_one_card_brings_back_the_one_under_it(self):
        from flippy.linux.notice import Notice, NoticeLayer
        layer = NoticeLayer()
        layer.pressed, layer.queue_draw = (None, 0.0), Mock()
        tip, approval = Notice("Tip", "x", []), Notice("Allow?", "y", [], width=480)
        layer.show_notice(tip)
        layer.show_notice(approval)
        self.assertIs(layer.notice_card, approval)
        layer.hide_notice(tip)               # the tip timed out underneath
        self.assertIs(layer.notice_card, approval)
        layer.show_notice(tip)
        layer.hide_notice(tip)
        self.assertIs(layer.notice_card, approval)
        layer.hide_notice(approval)
        self.assertIsNone(layer.notice_card)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(LINUX, "Linux only")
class RemotePointer(unittest.TestCase):
    """flippy/linux/remote.py: screen points into the monitor stream's coordinates, and the restore token stays private."""

    def test_screen_points_map_into_the_stream(self):
        from flippy.linux import remote
        rd = remote.RemoteDesktop()
        sent = []
        rd._notify = lambda method, sig, *values: sent.append((method, values))
        rd.stream = (77, (0, 0), (3840, 2160))       # the stream in device pixels, the screen at 1.5x
        rd.move(100, 200, (2560, 1440))
        self.assertEqual(sent, [("NotifyPointerMotionAbsolute", (77, 150.0, 300.0))])
        rd.scroll("up", 3)
        self.assertEqual(sent[-1], ("NotifyPointerAxisDiscrete", (remote.AXIS_VERTICAL, -3)))
        rd.scroll("right", 2)
        self.assertEqual(sent[-1], ("NotifyPointerAxisDiscrete", (remote.AXIS_HORIZONTAL, 2)))

    def test_the_restore_token_is_written_for_the_user_only(self):
        import os
        import tempfile
        from flippy.linux import remote
        with tempfile.TemporaryDirectory() as d, patch.object(remote, "TOKEN_PATH", os.path.join(d, "t")):
            remote._write_token("secret")
            self.assertEqual(os.stat(remote.TOKEN_PATH).st_mode & 0o777, 0o600)
            self.assertEqual(remote._read_token(), "secret")

    def test_a_refusal_isnt_asked_again_until_a_restart(self):
        from flippy.linux import remote
        rd = remote.RemoteDesktop()
        rd.refused = True
        with self.assertRaisesRegex(remote.Unavailable, "didn't allow"):
            rd.open()
        rd.closer.cancel()


@unittest.skipUnless(LINUX, "Linux only")
class GlassRegion(unittest.TestCase):
    """flippy/linux/blur.py: the blur region (rectangles only) covers the rounded card, lens and hand, and no more."""

    def covered(self, rects, x, y):
        return any(rx <= x < rx + rw and ry <= y < ry + rh for rx, ry, rw, rh in rects)

    def test_a_rounded_card_without_its_corners(self):
        from flippy.linux import blur
        rects = blur.strips([("round", 100, 50, 440, 120, 24)])
        self.assertTrue(self.covered(rects, 320, 110))          # the middle
        self.assertTrue(self.covered(rects, 101, 110))          # the left edge
        self.assertFalse(self.covered(rects, 101, 51))          # the rounded-off corner
        self.assertFalse(self.covered(rects, 320, 171))         # under it
        self.assertLess(len(rects), 40)                          # the straight middle is one rect

    def test_a_lens_and_a_tilted_hand_piece(self):
        from flippy.linux import blur
        lens = blur.strips([("circle", 300, 300, 22)])
        self.assertTrue(self.covered(lens, 300, 300))
        self.assertFalse(self.covered(lens, 280, 281))           # outside the circle, inside its box
        piece = blur.strips([("piece", 0, 0, 10, 40, 3, 90)])    # stood on its side: 40 wide, 10 tall
        self.assertTrue(self.covered(piece, -12, 20))
        self.assertFalse(self.covered(piece, 5, 2))
