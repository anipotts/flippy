"""Cut a record_reel.py capture into a 45 s reel: no captions, no title card.

The look lives in STYLE (palette, grade, grain, chromatic aberration, floating-screen frame,
beat pump...). The cut lives in SHOTS: long continuous shots with eased camera moves, smoothed
speed ramps through the waits, and crossfades between them.

Override any STYLE key without editing the file:
  python scripts/edit_reel.py <rawdir> out.mp4 --set grain=0.0 --set palette='["#ff3d7f","#00e0ff"]'
  python scripts/edit_reel.py <rawdir> out.mp4 --music my_track.wav --set bpm=124
  python scripts/edit_reel.py <rawdir> out.mp4 --style my_look.json   # JSON dict of STYLE keys
  python scripts/edit_reel.py <rawdir> out.mp4 --retake <retakedir>        # shots with raw="retake"
"""
import argparse
import bisect
import json
import math
import os
import subprocess
import sys
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(__file__))
import reel_music  # noqa: E402

STYLE = {
    "bpm": 120,
    "fps": 30,
    "size": [1920, 1080],
    "palette": ["#ff6b5a", "#7b5cff", "#2de2b4", "#ffd166"],  # backdrop blobs behind the floating screen
    "backdrop_dark": "#07060d",
    "frame_scale": 0.78,      # screen size when fully "framed" (floating card over the backdrop)
    "corner": 26,             # px, rounded corners of the floating screen
    "shadow": 0.6,
    "grade_contrast": 1.08,
    "grade_saturation": 1.12,
    "grade_lift": [0.015, 0.0, 0.035],   # shadows tint (r, g, b)
    "grade_gain": [1.04, 1.0, 0.96],     # highlights tint
    "vignette": 0.25,
    "grain": 0.012,           # fine luma grain, full resolution
    "aberration": 0.0006,     # resting radial RGB split (fraction of frame)
    "cut_aberration": 0.0,    # extra split right after a shot change
    "punch": 0.0,             # zoom punch on a shot change
    "pump": 0.0035,           # zoom bump on every kick after the drop
    "speed_smooth": 0.3,      # s, how gently fast-forwards ramp in and out
    "flash_at": [4.0],        # seconds: soft white flash hits
    "flash": 0.35,
    "fade_in": 0.6,
    "fade_out": 1.2,
}
SRC_W, SRC_H = 2560, 1440
T0 = 1791234000.0  # capture-relative times below are seconds after this

# A shot is `secs` of output. `time`: [(out_s, src_s)] -- source seconds (after T0) at output seconds into
# the shot; between keys it plays linearly and the speed changes are smoothed, so fast-forwards ramp in/out.
# `cam`: [(u, cx, cy, zoom)] in source pixels, u = 0..1 through the shot. `frame`: [(u, framed 0..1, yaw, pitch)].
# `xf`: crossfade (s) from the previous shot.
WIDE = (SRC_W / 2, SRC_H / 2, 1.0)
THEMES = {"midnight": 874.65, "y2k": 879.30, "glass": 883.91, "terminal": 888.52, "cosmic": 893.13}
POINTERS = [897.75, 901.36, 904.98, 908.58, 912.19]


def shot(secs, time, cam, frame=((0, 0, 0, 0),), xf=0.35, raw="main", tag=None):
    """raw: which capture ("main" = positional rawdir, "retake" = --retake dir)."""
    return {"secs": secs, "time": time, "cam": cam, "frame": frame, "xf": xf, "raw": raw, "tag": tag}


SHOTS = [
    # intro: close on the render, easing back out to the floating desktop
    shot(4.0, [(0, 800.0), (4, 804.0)],
         [(0, 1060, 640, 2.6), (0.4, 1030, 620, 2.8), (1, *WIDE)],
         frame=[(0, 0, 0, 0), (0.45, 0, 0, 0), (1, 1, -8, 3)], xf=0),
    # ask in Blender: box -> answer -> pointer walks Halo -> Material tab
    shot(9.0, [(0, 762.0), (2.8, 765.0), (3.7, 767.6), (5.5, 769.6), (8.3, 773.3), (9, 774.1)],
         [(0, 1400, 450, 1.5), (0.2, 1560, 300, 2.2), (0.36, 1600, 300, 2.2), (0.46, 2030, 330, 2.1),
          (0.6, 2040, 340, 2.2), (0.68, 1960, 780, 2.1), (0.9, 1950, 800, 2.3), (1, 1700, 650, 1.6)]),
    # walkthrough (y2k): Render menu -> Render tab
    shot(7.0, [(0, 7838.2), (2.3, 7841.4), (2.9, 7843.8), (4.6, 7845.9), (7, 7848.8)],
         [(0, 1280, 300, 1.6), (0.22, 1280, 150, 2.4), (0.34, 1100, 160, 2.0), (0.44, 380, 190, 2.3),
          (0.6, 380, 195, 2.4), (0.72, 1880, 540, 2.2), (1, 1890, 545, 2.45)], raw="retake"),
    # draw your own pointer: outline, fill, highlights, sparkles, tip, save
    shot(5.5, [(0, 7854.8), (5.5, 7860.1)],
         [(0, 1280, 560, 1.5), (0.25, 1110, 480, 2.3), (0.85, 1100, 470, 2.45), (1, 1180, 500, 2.2)],
         raw="retake", xf=0.5),
    # ...and it's the pointer now
    shot(2.5, [(0, 7861.0), (2.5, 7864.4)],
         [(0, 300, 150, 3.8), (0.55, 300, 150, 4.0), (0.85, 1420, 150, 3.6), (1, 1440, 150, 3.7)],
         raw="retake"),
    # themes: same framing, so only the skin changes
    *[shot(1.4, [(0, THEMES[k] + 1.0), (1.4, THEMES[k] + 2.4)], [(0, 480, 230, 2.4), (1, 480, 230, 2.5)], xf=0.3,
           tag="montage")
      for k in ["glass", "terminal", "cosmic", "y2k", "midnight"]],
    # circle-and-ask on the Hokusai print (terminal)
    shot(7.0, [(0, 923.4), (2.2, 925.6), (3.6, 927.5), (4.3, 932.1), (7, 935.6)],
         [(0, 1100, 700, 1.15), (0.23, 480, 420, 1.9), (0.5, 600, 420, 1.7), (0.62, 660, 480, 2.2),
          (1, 660, 485, 2.5)], xf=0.5),
    # settings, then out
    shot(3.0, [(0, 942.0), (3, 945.0)], [(0, 1523, 615, 1.4), (1, 1523, 615, 1.6)],
         frame=[(0, 1, 8, -2), (1, 0.6, 3, 0)], xf=0.5),
]


# ---------------- helpers ----------------
def hexrgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)


def smooth(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * u * (u * (6 * u - 15) + 10)


def interp(keys, u):
    """Keyframes [(u, *vals)] with smootherstep easing between them."""
    keys = list(keys)
    if u <= keys[0][0]:
        return keys[0][1:]
    for a, b in zip(keys, keys[1:]):
        if u <= b[0]:
            k = smooth((u - a[0]) / max(b[0] - a[0], 1e-6))
            return tuple(x + (y - x) * k for x, y in zip(a[1:], b[1:]))
    return keys[-1][1:]


def perspective_coeffs(dst, src):
    """Coefficients for Image.transform(PERSPECTIVE) mapping output points dst -> input points src."""
    m = []
    for (x, y), (u, v) in zip(dst, src):
        m.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        m.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    return np.linalg.solve(np.array(m, float), np.array(src, float).reshape(8))


# ---------------- timeline ----------------
def time_map(sh, fps, smooth_s):
    """Output seconds -> source seconds, piecewise linear between keys, speed smoothed with a gaussian."""
    keys = sh["time"]
    pad = sh["secs"] + 1.0  # extra so a crossfade into the next shot can keep playing this one
    step = 1 / (fps * 4)
    ts = np.arange(-1.0, pad + step, step)
    ko = np.array([k[0] for k in keys], float)
    ks = np.array([k[1] for k in keys], float)
    src = np.interp(ts, ko, ks)
    v0 = (ks[1] - ks[0]) / (ko[1] - ko[0])
    v1 = (ks[-1] - ks[-2]) / (ko[-1] - ko[-2])
    src = np.where(ts < ko[0], ks[0] + (ts - ko[0]) * v0, src)
    src = np.where(ts > ko[-1], ks[-1] + (ts - ko[-1]) * v1, src)
    if smooth_s > 0:
        k = np.arange(-3 * smooth_s, 3 * smooth_s + step, step)
        g = np.exp(-0.5 * (k / smooth_s) ** 2)
        g /= g.sum()
        n = len(g) // 2
        src = np.convolve(np.pad(src, n, mode="reflect", reflect_type="odd"), g, "valid")
    return ts, src


def build(style):
    fps = style["fps"]
    timeline, t_out, starts = [], 0.0, []
    for si, sh in enumerate(SHOTS):
        dur = sh["secs"]
        starts.append(t_out)
        n = round((t_out + dur) * fps) - round(t_out * fps)
        for k in range(n):
            timeline.append((si, (k + 0.5) / fps, t_out + k / fps))
        t_out += dur
    maps = [time_map(sh, fps, style["speed_smooth"]) for sh in SHOTS]
    return timeline, t_out, maps


# ---------------- worker state ----------------
G = {}


def init_worker(raws, style):
    G["frames"] = {}
    for key, raw in raws.items():
        frames = sorted((float(f[:-4]), os.path.join(raw, "frames", f))
                        for f in os.listdir(os.path.join(raw, "frames")) if f.endswith(".jpg"))
        G["frames"][key] = ([t for t, _ in frames], [p for _, p in frames])
    W, H = style["size"]
    G.update(style=style, cache={},
             W=W, H=H, rng=np.random.default_rng())
    G["timeline"], _, G["maps"] = build(style)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
    G["vignette"] = (1 - style["vignette"] * smooth_np(r)).astype(np.float32)[..., None]
    G["palette"] = [hexrgb(c) for c in style["palette"]]
    G["dark"] = hexrgb(style["backdrop_dark"])
    G["lift"] = np.array(style["grade_lift"], np.float32)
    G["gain"] = np.array(style["grade_gain"], np.float32)
    # rounded-rect alpha for the floating screen
    s = 2
    m = Image.new("L", (W * s, H * s), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, W * s - 1, H * s - 1), radius=style["corner"] * s / style["frame_scale"],
                                        fill=255)
    G["mask"] = m.resize((W, H), Image.LANCZOS)


def smooth_np(u):
    u = np.clip(u, 0, 1)
    return u * u * (3 - 2 * u)


def source(t, raw):
    frame_t, frame_p = G["frames"][raw]
    i = max(bisect.bisect_right(frame_t, T0 + t) - 1, 0)
    c = G["cache"]
    if (raw, i) not in c:
        if len(c) > 6:
            c.clear()
        c[raw, i] = Image.open(frame_p[i]).convert("RGB")
    return c[raw, i]


def backdrop(t):
    """Slowly drifting colour blobs on a dark base (computed small, upscaled)."""
    w, h = 192, 108
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.broadcast_to(G["dark"], (h, w, 3)).copy()
    for i, col in enumerate(G["palette"]):
        cx = w * (0.5 + 0.38 * math.sin(t * 0.23 + i * 1.9))
        cy = h * (0.5 + 0.36 * math.cos(t * 0.19 + i * 2.6))
        rad = w * (0.32 + 0.06 * math.sin(t * 0.5 + i))
        g = np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * rad ** 2))[..., None]
        img += col * g * 0.55
    im = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
    return im.resize((G["W"], G["H"]), Image.BICUBIC).filter(ImageFilter.GaussianBlur(6))


def camera_view(sh, u, extra_zoom):
    cx, cy, z = interp(sh["cam"], u)
    z = max(z * extra_zoom, 1.0)
    vw, vh = SRC_W / z, SRC_H / z
    cx = min(max(cx, vw / 2), SRC_W - vw / 2)
    cy = min(max(cy, vh / 2), SRC_H - vh / 2)
    return cx - vw / 2, cy - vh / 2, cx + vw / 2, cy + vh / 2


def render_screen(sh, u, src_t, extra_zoom):
    return source(src_t, sh["raw"]).transform((G["W"], G["H"]), Image.EXTENT, camera_view(sh, u, extra_zoom), Image.BICUBIC)


def compose(screen, framed, yaw, pitch, t):
    """Place the screen as a floating, tilted card over the backdrop (framed 0 = full bleed)."""
    if framed <= 0.001:
        return screen
    st = G["style"]
    W, H = G["W"], G["H"]
    s = 1 - (1 - st["frame_scale"]) * min(framed, 1.0)
    if framed > 1:  # shrink further away (outro)
        s *= 1 - 0.45 * (framed - 1)
    yaw, pitch = math.radians(yaw), math.radians(pitch)
    f = 2.2 * W
    pts = []
    for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        X, Y, Z = x * W / 2 * s, y * H / 2 * s, 0.0
        X, Z = X * math.cos(yaw) + Z * math.sin(yaw), -X * math.sin(yaw) + Z * math.cos(yaw)
        Y, Z = Y * math.cos(pitch) - Z * math.sin(pitch), Y * math.sin(pitch) + Z * math.cos(pitch)
        k = f / (f + Z)
        pts.append((W / 2 + X * k, H / 2 + Y * k))
    coeffs = perspective_coeffs(pts, [(0, 0), (W, 0), (W, H), (0, H)])
    warped = screen.transform((W, H), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    mask = G["mask"].transform((W, H), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    bg = backdrop(t)
    # soft shadow, computed at quarter size
    sm = mask.resize((W // 4, H // 4)).filter(ImageFilter.GaussianBlur(12))
    sm = sm.transform(sm.size, Image.AFFINE, (1, 0, 0, 0, 1, -10)).resize((W, H), Image.BILINEAR)
    shadow = Image.new("RGB", (W, H), (0, 0, 0))
    bg = Image.composite(shadow, bg, sm.point(lambda v: int(v * st["shadow"])))
    return Image.composite(warped, bg, mask)


def aberrate(arr, k):
    """Radial RGB split: scale red out and blue in by k."""
    if k < 1e-4:
        return arr
    H, W = arr.shape[:2]
    out = arr.copy()
    for ch, sgn in ((0, 1), (2, -1)):
        z = 1 + sgn * k
        im = Image.fromarray(arr[..., ch])
        cw, chh = W / z, H / z
        out[..., ch] = np.asarray(im.transform((W, H), Image.EXTENT, ((W - cw) / 2, (H - chh) / 2, (W + cw) / 2,
                                                                    (H + chh) / 2), Image.BILINEAR))
    return out


def shot_image(si, lt, t):
    """Shot si at lt seconds into it (lt may run past its end during a crossfade)."""
    st = G["style"]
    sh = SHOTS[si]
    ts, src = G["maps"][si]
    src_t = float(np.interp(lt, ts, src))
    u = min(max(lt / sh["secs"], 0.0), 1.0)
    beat = 60.0 / st["bpm"]
    punch = st["punch"] * math.exp(-lt / 0.12) if si > 0 else 0.0
    pump = st["pump"] * math.exp(-((t % beat) / beat) * 6) if 4.0 <= t < TOTAL - 3.0 else 0.0
    framed, yaw, pitch = interp(sh["frame"], u)
    zoom = 1 + punch + pump
    im = compose(render_screen(sh, u, src_t, zoom if framed < 0.5 else 1.0), framed, yaw, pitch, t)
    if framed >= 0.5 and zoom > 1.0005:  # punch the whole composition when the screen is floating
        W, H = G["W"], G["H"]
        cw, chh = W / zoom, H / zoom
        im = im.transform((W, H), Image.EXTENT, ((W - cw) / 2, (H - chh) / 2, (W + cw) / 2, (H + chh) / 2),
                          Image.BILINEAR)
    return im


def render(idx):
    st = G["style"]
    si, lt, t = G["timeline"][idx]
    sh = SHOTS[si]
    since_cut = lt
    im = shot_image(si, lt, t)
    if si > 0 and lt < sh["xf"]:  # crossfade from the previous shot, which keeps playing
        prev = SHOTS[si - 1]
        k = smooth(lt / sh["xf"])
        im = Image.blend(shot_image(si - 1, prev["secs"] + lt, t), im, k)
    arr = np.asarray(im)
    ca = st["aberration"] + (st["cut_aberration"] * math.exp(-since_cut / 0.1) if si > 0 else 0)
    arr = aberrate(arr, ca)
    x = arr.astype(np.float32) / 255
    # grade: contrast, saturation, lift/gain
    x = (x - 0.5) * st["grade_contrast"] + 0.5
    lum = x @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    x = lum[..., None] + (x - lum[..., None]) * st["grade_saturation"]
    x = G["lift"] * (1 - x) + x * G["gain"]
    x *= G["vignette"]
    for fa in st["flash_at"]:
        if 0 <= t - fa < 0.35:
            x += (1 - (t - fa) / 0.35) ** 2 * st["flash"]
    if st["grain"] > 0:
        H, W = x.shape[:2]
        g = G["rng"].standard_normal((H, W), dtype=np.float32)
        x += g[..., None] * st["grain"] * (0.5 + 0.5 * (1 - lum[..., None]))
    total = TOTAL
    fade = min(t / st["fade_in"] if st["fade_in"] else 1, (total - t) / st["fade_out"] if st["fade_out"] else 1, 1)
    x *= max(fade, 0) ** 1.5
    return (np.clip(x, 0, 1) * 255).astype(np.uint8).tobytes()


TOTAL = 0.0


def main():
    global TOTAL
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("out", nargs="?", default="reel.mp4")
    ap.add_argument("--retake", help="second capture (record_reel.py <dir> retake) for shots with raw='retake'")
    ap.add_argument("--music", help="wav/mp3 to use instead of the generated track")
    ap.add_argument("--style", help="JSON file of STYLE overrides")
    ap.add_argument("--set", action="append", default=[], help="key=value (JSON value) STYLE override")
    ap.add_argument("--preview", action="store_true", help="half-res, quick")
    ap.add_argument("--jobs", type=int, default=max(os.cpu_count() - 2, 1))
    args = ap.parse_args()
    style = dict(STYLE)
    if args.style:
        style.update(json.load(open(args.style)))
    for kv in args.set:
        k, v = kv.split("=", 1)
        try:
            style[k] = json.loads(v)
        except json.JSONDecodeError:
            style[k] = v
    if args.preview:
        style["size"] = [style["size"][0] // 2, style["size"][1] // 2]
        style["corner"] = style["corner"] // 2
    timeline, TOTAL, _ = build(style)
    W, H = style["size"]
    out = os.path.abspath(args.out)
    music = args.music
    if not music:
        music = out.rsplit(".", 1)[0] + ".music.wav"
        beat = 60.0 / style["bpm"]
        # sections follow the cut: drums in after the intro, arps under the montages, out on the settings shot
        starts = np.cumsum([0] + [sh["secs"] for sh in SHOTS])
        tagged = [i for i, sh in enumerate(SHOTS) if sh["tag"] == "montage"]
        montage = (starts[tagged[0]], starts[tagged[-1] + 1])
        reel_music.write_wav(music, reel_music.render(style["bpm"], TOTAL, drop=starts[1], montage=tuple(montage),
                                                      outro=starts[-2]))
    print(f"{len(timeline)} frames, {TOTAL:.1f}s, {len(SHOTS)} shots", flush=True)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                           "-r", str(style["fps"]), "-i", "-", "-i", music, "-map", "0:v", "-map", "1:a",
                           "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
                           "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", out],
                          stdin=subprocess.PIPE)
    with Pool(args.jobs, initializer=init_worker, initargs=({"main": args.raw, **({"retake": args.retake} if args.retake else {})}, style)) as pool:
        for i, frame in enumerate(pool.imap(render, range(len(timeline)), chunksize=4)):
            ff.stdin.write(frame)
            if i % 150 == 0:
                print(f"  {i}/{len(timeline)}", flush=True)
    ff.stdin.close()
    ff.wait()
    if not args.music:
        os.unlink(music)
    print("saved", out)


if __name__ == "__main__":
    main()
