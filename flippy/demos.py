"""Scripted previews/recording. dispatch returns (handled, result); never approves actions."""
import math
import sys
from . import loop, settings, tips, watch
NOT_HERE = "not available on this platform yet (see docs/linux-port.md)"

def dispatch(host, cmd, event, log):
    if cmd.startswith('demo-type '):
        host.demo_type(cmd[len('demo-type '):])
    elif cmd.startswith('demo-draw '):
        parts = cmd.split(maxsplit=5)
        host.demo_draw(*map(float, parts[1:5]), then_ask=parts[5] if len(parts) > 5 else None)
    elif cmd.startswith('demo-pointer'):
        host.demo_pointer(cmd[len('demo-pointer'):].strip() or 'Sunset')
    elif cmd == 'preview':
        host.preview()
    elif cmd.startswith('demo-point '):
        x, y, rest = cmd.split(maxsplit=3)[1:]
        label, _, text = rest.partition('|')
        host.demo_point(float(x), float(y), label, text or label)
    elif cmd == 'demo-tutorial':
        host.preview(tutorial=True)
    elif cmd.startswith('demo-user-click '):
        x, y = map(float, cmd.split()[1:3])
        host._on_user_click(x, y)
    elif cmd.startswith('demo-nudge'):
        parts = cmd.split(maxsplit=2)
        reason = parts[1] if len(parts) > 1 else 'stalled'
        offer = watch.Offer('demo', parts[2] if len(parts) > 2 else 'Ableton Live', reason)
        if not hasattr(host.ui, 'show_nudge'):
            return (True, NOT_HERE)
        host.ui.show_nudge(offer, lambda: host._nudge_help(offer), lambda: log('nudge: not now'), lambda: log('nudge: mute'))
    elif cmd.startswith('shot '):
        if not hasattr(host.ui, 'screenshot_to'):
            return (True, NOT_HERE)
        host.ui.screenshot_to(cmd[5:].strip())
    elif cmd.startswith('record '):
        if not hasattr(host.ui, 'start_recording'):
            return (True, NOT_HERE)
        parts = cmd.split(maxsplit=2)
        if parts[1] == 'start' and len(parts) == 3:
            host.ui.start_recording(parts[2])
            event('record_start', path=parts[2])
        else:
            host.ui.stop_recording()
            event('record_stop')
    elif cmd.startswith('mark '):
        event('mark', name=cmd[5:].strip())
    elif cmd == 'demo-update':
        if not hasattr(host.ui, 'show_update'):
            return (True, NOT_HERE)
        rel = {'version': '0.3', 'name': 'Flippy 0.3', 'url': 'https://github.com/kap-il/flippy/releases', 'notes': 'Tutorials that make the music under them.'}
        host.ui.show_update(rel, install=lambda: log('demo update: install'), later=lambda: None)
    elif cmd.startswith('nudge '):
        if not hasattr(host.ui, 'press_nudge'):
            return (True, NOT_HERE)
        return (True, 'ok' if host.ui.press_nudge(cmd[6:].strip()) else 'no such button')
    elif cmd.startswith('demo-tip'):
        if not hasattr(host.ui, 'show_tip'):
            return (True, NOT_HERE)
        parts = cmd.split(maxsplit=1)
        deck = tips.Deck.load(parts[1]) if len(parts) > 1 else None
        tip = deck.next_tip() if deck else None
        if tip:
            host._show_tip(deck, tip)
        else:
            host._show_tip(tips.Deck('demo', 'Ableton Live'), {'text': 'Hold ⌘ while dragging a clip to duplicate it instead of moving it.', 'level': 1, 'state': 'new'})
    else:
        return False, None
    return True, "ok"

def demo_point(host, x, y, label, text):
    """A one-step answer pointing at (x, y): same spot every time, so a theme/pointer montage lines up."""
    if host.busy:
        return
    host.gen += 1
    host._stop_playback()
    host._cancel_fade()
    host.overlay.clear()
    host.tutorial = False
    W, H = host.ui.screen_size()
    sc = host._scale()
    shot = (int(W * sc), int(H * sc))
    host._start_playback(host.gen, shot, shot)
    host.play.finish(f'{text} [POINT:{int(x * sc)},{int(y * sc)}:{label}]')

def preview(host, tutorial=False):
    """Fake 3-step walkthrough so theme/pointer/timing changes can be seen in place.
        tutorial: the first step is a ":click" step that waits for them to click it."""
    if host.busy:
        return
    host.gen += 1
    host._stop_playback()
    host._cancel_fade()
    host.overlay.clear()
    W, H = host.ui.screen_size()
    sc = host._scale()
    if sys.platform == 'darwin':
        spots, first = ([(22, 12, 'Apple menu'), (W - 70, 12, 'Clock'), (W // 2, H - 40, 'Dock')], 'the Apple menu')
    else:
        spots, first = ([(70, 14, 'Workspaces'), (W // 2, 14, 'Clock'), (W // 2, H - 40, 'Dock')], 'the workspaces button')
    host.tutorial = tutorial
    if tutorial:
        spots = [(22, 12, 'Apple menu:click'), (W // 2, H - 40, 'Dock')]
        texts = ('Click the Apple menu to open it', "Nice. That's how tutorials wait for you, then go on")
        raw = ' '.join((f'{txt} [POINT:{int(x * sc)},{int(y * sc)}:{lbl}].' for (x, y, lbl), txt in zip(spots, texts)))
        shot = (int(W * sc), int(H * sc))
        host._start_playback(host.gen, shot, shot)
        host.play.finish(raw)
        return
    raw = ' '.join((f'{txt} [POINT:{int(x * sc)},{int(y * sc)}:{lbl}].' for (x, y, lbl), txt in zip(spots, (f'This is a preview of how answers look: the pointer starts at {first}', 'then glides to the clock while the panel follows it', 'and ends on the dock, one step per thing it explains'))))
    shot = (int(W * sc), int(H * sc))
    host._start_playback(host.gen, shot, shot)
    host.play.finish(raw)

def demo_type(host, text, delay_ms=65, *, event):
    if not host.box.visible:
        host.open_box()
    if not text:
        return
    state = {'i': 0}

    def step():
        if not host.box.visible:
            return False
        state['i'] += 1
        host.box.set_text(text[:state['i']])
        event('typed', ch=text[state['i'] - 1])
        if state['i'] >= len(text):
            loop.timeout_add(450, lambda: host.box.visible and host.box.activate() and False)
            return False
        return True
    loop.timeout_add(500, lambda: loop.timeout_add(delay_ms, step) and False)

def demo_draw(host, cx, cy, rx, ry, then_ask=None, duration_ms=900):
    host.start_draw()
    host.overlay.strokes = [[]]
    n = duration_ms // 16
    state = {'i': 0}

    def step():
        if not host.overlay.drawing or not host.overlay.strokes:
            return False
        a = 2 * math.pi * 1.08 * state['i'] / n - math.pi / 2
        host.overlay.strokes[-1].append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
        host.overlay.queue_draw()
        state['i'] += 1
        if state['i'] > n:
            host._draw_done()
            if then_ask:
                host.demo_type(then_ask)
            return False
        return True
    loop.timeout_add(600, lambda: loop.timeout_add(16, step) and False)

def demo_pointer(host, name):

    def saved(value):
        settings.set('look', 'pointer', value)
        loop.timeout_add(500, lambda: host.preview() and False)
    host.ui.demo_pointer(name, saved)
