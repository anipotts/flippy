"""Turn a record_raw.py capture into an edited demo: title card, zooms that follow the
pointer, sped-up waits, captions, transitions, outro.

The camera is driven by the daemon's event log (pointer positions, drawn marks), and
since the whole timeline is known up front it's smoothed forwards *and* backwards,
so it eases into each move slightly before the hand gets there.

Run:  python3 scripts/edit_demo.py <rawdir> [out.mp4]
"""
import bisect
import json
import math
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

RAW = sys.argv[1]
OUT = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else "demo.mp4")
SRC_W, SRC_H = 2560, 1440
W, H, FPS = 1920, 1080, 30

ZOOM_POINT = 2.3        # close-up on a single point
ZOOM_TOUR = 2.3         # close-up while the hand walks along a row
THINK_SPEED = 2.5       # fast-forward while Claude is thinking
TAIL_SPEED = 2.0        # fast-forward the last hold before things fade
SMOOTH_S = 0.45         # camera smoothing time constant
CAPTIONS = {
    "ask": "Super+Shift+Space: ask about anything on your screen",
    "tour": "Walkthroughs: the pointer moves step by step and the panel follows it",
    "draw": "Super+Alt: circle something and ask about it",
}


def font(size, bold=True):
    name = "Noto Sans:bold" if bold else "Noto Sans"
    path = subprocess.run(["fc-match", name, "-f", "%{file}"], capture_output=True, text=True).stdout
    return ImageFont.truetype(path, size)


F_TITLE, F_SUB, F_SMALL, F_CAP, F_BADGE = font(132), font(44, False), font(30, False), font(38), font(30)

# ---------- load capture ----------
frames = sorted((float(f[:-4]), os.path.join(RAW, "frames", f))
                for f in os.listdir(os.path.join(RAW, "frames")) if f.endswith(".jpg"))
frame_t = [t for t, _ in frames]
events = [json.loads(line) for line in open(os.path.join(RAW, "events.jsonl"))]
marks = json.load(open(os.path.join(RAW, "marks.json")))


def ev_after(name, t, before=math.inf):
    for e in events:
        if e["ev"] == name and t <= e["t"] < before:
            return e
    return None


# ---------- scenes and speed ramps (source time ranges) ----------
scenes = []
for i, m in enumerate(marks):
    nxt = marks[i + 1]["t"] if i + 1 < len(marks) else math.inf
    cleared = ev_after("cleared", m["t"], nxt)
    end = cleared["t"] + 0.3 if cleared else min(nxt, frame_t[-1])
    start = m["t"] - 0.4
    think = ev_after("thinking", m["t"], end)
    first_pt = ev_after("point", m["t"], end)
    done = ev_after("answer_done", m["t"], end)
    pieces = []  # (src0, src1, speed)
    cur = start
    if think and first_pt:
        pieces += [(cur, think["t"], 1.0), (think["t"], first_pt["t"] - 0.15, THINK_SPEED)]
        cur = first_pt["t"] - 0.15
    if done:
        hold_end = done["t"] + 3.0
        pieces += [(cur, hold_end, 1.0), (hold_end, end, TAIL_SPEED)]
    else:
        pieces.append((cur, end, 1.0))
    scenes.append({"name": m["scene"], "start": start, "end": end, "pieces": [p for p in pieces if p[1] > p[0]],
                   "first_point": first_pt["t"] if first_pt else None})


# ---------- camera targets (source time -> cx, cy, zoom) ----------
def camera_target(t):
    wide = (SRC_W / 2, SRC_H / 2, 1.0)
    drawn = [e for e in events if e["ev"] == "drawn"]
    # while drawing / typing the draw question: frame the marked area
    for d in drawn:
        ds = ev_after("draw_start", d["t"] - 30, d["t"] + 0.01)
        th = ev_after("thinking", d["t"])
        if ds and ds["t"] - 0.2 <= t < (th["t"] if th else d["t"] + 5):
            bw, bh = d["x1"] - d["x0"], d["y1"] - d["y0"]
            z = min(SRC_W / (bw * 1.9), SRC_H / (bh * 5.0), 2.6)
            return ((d["x0"] + d["x1"]) / 2, (d["y0"] + d["y1"]) / 2 + 80 / z, max(z, 1.0))
    pts = [e for e in events if e["ev"] == "point" and e["t"] <= t]
    if not pts:
        return wide
    p = pts[-1]
    done = ev_after("answer_done", p["t"])
    cleared = ev_after("cleared", p["t"])
    if (done and t > done["t"] + 2.5) or (cleared and t >= cleared["t"]):
        return wide
    # is this point part of a multi-step walkthrough? (another point within the same answer)
    same = [e for e in events if e["ev"] == "point" and (not done or e["t"] <= done["t"] + 0.01)
            and (not cleared or e["t"] < cleared["t"]) and abs(e["t"] - p["t"]) < 40]
    z = ZOOM_TOUR if len(same) > 1 else ZOOM_POINT
    # frame the hand plus the card riding next to it
    cy = p["y"] + (-90 if p["y"] > SRC_H / 2 else 110)
    cx = p["x"] + 170
    return cx, cy, z


def clamp_cam(cx, cy, z):
    vw, vh = SRC_W / z, SRC_H / z
    cx = min(max(cx, vw / 2), SRC_W - vw / 2)
    cy = min(max(cy, vh / 2), SRC_H - vh / 2)
    return cx, cy, z


# ---------- output timeline ----------
TITLE_S, OUTRO_S, XFADE_S = 3.2, 3.6, 0.45
timeline = []  # per output frame: ("title", k) | ("src", src_t, speed, scene_idx, scene_frac) | ("outro", k)
for k in range(int(TITLE_S * FPS)):
    timeline.append(("title", k / FPS))
for si, sc in enumerate(scenes):
    for (a, b, sp) in sc["pieces"]:
        t = a
        while t < b:
            timeline.append(("src", t, sp, si))
            t += sp / FPS
for k in range(int(OUTRO_S * FPS)):
    timeline.append(("outro", k / FPS))

# camera: targets per frame, then zero-phase exponential smoothing (zoom in log space)
cams = []
for item in timeline:
    if item[0] == "src":
        cx, cy, z = camera_target(item[1])
        cams.append([cx, cy, math.log(z)])
    else:
        cams.append([SRC_W / 2, SRC_H / 2, 0.0])
alpha = 1 - math.exp(-1 / (SMOOTH_S * FPS))
for rng in (range(1, len(cams)), range(len(cams) - 2, -1, -1)):
    prev = None
    for i in rng:
        j = i - 1 if rng.step == 1 else i + 1
        for c in range(3):
            cams[i][c] = cams[j][c] + alpha * (cams[i][c] - cams[j][c])


# ---------- drawing helpers ----------
def text_center(d, y, s, f, fill):
    w = d.textlength(s, font=f)
    d.text(((W - w) / 2, y), s, font=f, fill=fill)


def title_frame(t, outro=False):
    im = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(im)
    for y in range(H):  # deep blue -> near black gradient
        k = y / H
        d.line([(0, y), (W, y)], fill=(int(14 + 10 * (1 - k)), int(18 + 16 * (1 - k)), int(32 + 30 * (1 - k))))
    a = min(t / 0.6, 1.0)
    rise = int(30 * (1 - a) ** 2)
    fg = tuple(int(c * a) for c in (242, 244, 250))
    accent = tuple(int(c * a) for c in (138, 184, 255))
    dim = tuple(int(c * a) for c in (150, 158, 175))
    if not outro:
        text_center(d, 330 + rise, "Flippy", F_TITLE, fg)
        text_center(d, 510 + rise, "an AI tutor that can see your Linux screen", F_SUB, accent)
        text_center(d, 600 + rise, "Pop!_OS · COSMIC · Wayland · powered by Claude", F_SMALL, dim)
    else:
        text_center(d, 380 + rise, "Flippy", font(96), fg)
        text_center(d, 520 + rise, "Python · GTK4 + layer-shell · Claude Agent SDK", F_SUB, accent)
        text_center(d, 600 + rise, "ask · point · walk through · circle", F_SMALL, dim)
    return im


_cache = {"path": None, "im": None}


def source_frame(t):
    i = max(bisect.bisect_right(frame_t, t) - 1, 0)
    path = frames[i][1]
    if _cache["path"] != path:
        _cache["path"], _cache["im"] = path, Image.open(path).convert("RGB")
    return _cache["im"]


def pill(d, x, y, s, f, pad=(26, 14), fill=(16, 16, 20, 225), fg=(245, 245, 250, 255), radius=18):
    w = d.textlength(s, font=f)
    asc, desc = f.getmetrics()
    box = (x, y, x + w + 2 * pad[0], y + asc + desc + 2 * pad[1])
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=(90, 160, 255, 160), width=2)
    d.text((x + pad[0], y + pad[1]), s, font=f, fill=fg)
    return box


def render_src(idx, item):
    _, t, speed, si = item
    cx, cy, lz = cams[idx]
    cx, cy, z = clamp_cam(cx, cy, math.exp(lz))
    vw, vh = SRC_W / z, SRC_H / z
    src = source_frame(t)
    im = src.transform((W, H), Image.EXTENT, (cx - vw / 2, cy - vh / 2, cx + vw / 2, cy + vh / 2), Image.BILINEAR)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    sc = scenes[si]
    # caption: from scene start until a little after the first point
    cap_end = (sc["first_point"] or sc["end"]) + 1.5
    if t < cap_end:
        a = min((t - sc["start"]) / 0.4, (cap_end - t) / 0.4, 1.0)
        if a > 0:
            s = CAPTIONS.get(sc["name"], "")
            tw = d.textlength(s, font=F_CAP)
            box_y = H - 150
            pill(d, (W - tw) / 2 - 30, box_y, s, F_CAP, pad=(30, 18),
                 fill=(16, 16, 20, int(225 * a)), fg=(245, 245, 250, int(255 * a)))
    if speed > 1.01:
        pill(d, W - 190, 40, f"{speed:g}×  ▶▶", F_BADGE, pad=(20, 10))
    im = Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB")
    # dip-to-black at scene edges
    edge = min(t - sc["start"], sc["end"] - t) / max(speed, 1)
    if edge < XFADE_S:
        im = Image.blend(Image.new("RGB", (W, H)), im, max(edge / XFADE_S, 0))
    return im


def main():
    if os.environ.get("DRY"):  # print the camera path instead of rendering
        for idx in range(0, len(timeline), 15):
            it = timeline[idx]
            if it[0] == "src":
                cx, cy, z = clamp_cam(cams[idx][0], cams[idx][1], math.exp(cams[idx][2]))
                print(f"out {idx / FPS:6.1f}s src {it[1] - frame_t[0]:6.1f}s scene {scenes[it[3]]['name']:5s} "
                      f"cam ({cx:6.0f},{cy:6.0f}) z {z:.2f}")
        return
    print(f"{len(timeline)} frames ({len(timeline) / FPS:.1f}s), {len(scenes)} scenes", flush=True)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
                           "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", OUT],
                          stdin=subprocess.PIPE)
    n_title = int(TITLE_S * FPS)
    for idx, item in enumerate(timeline):
        if item[0] == "title":
            im = title_frame(item[1])
            fade_out = (n_title - idx) / (XFADE_S * FPS)
            if fade_out < 1:
                im = Image.blend(Image.new("RGB", (W, H)), im, max(fade_out, 0))
        elif item[0] == "outro":
            im = title_frame(item[1], outro=True)
            remain = OUTRO_S - item[1]
            if remain < 0.5:
                im = Image.blend(Image.new("RGB", (W, H)), im, max(remain / 0.5, 0))
        else:
            im = render_src(idx, item)
        ff.stdin.write(im.tobytes())
        if idx % 150 == 0:
            print(f"  {idx}/{len(timeline)}", flush=True)
    ff.stdin.close()
    ff.wait()
    print(f"saved {OUT}")


main()
