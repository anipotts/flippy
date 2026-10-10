"""Real glass on COSMIC: the compositor blurs what's behind the overlay where Flippy's glass is (the card on the
Glass and Media Player themes, the glass pointers), through ext_background_effect_v1. macOS has
NSGlassEffectView for this (flippy/mac/ui.py _place_glass); here the blur is the compositor's and the tint is
painted by the overlay (flippy/glass.py).

The request has to be made on GTK's own Wayland connection, since the overlay's wl_surface belongs to it, not on
flippy/linux/wl.py's. PyGObject doesn't hand out GTK's wl_display or wl_surface, and pywayland can't wrap a
display it didn't open, so this talks to libwayland-client and GTK through ctypes: GTK's display and surface by
their C getters, the protocol's two interfaces described by hand, and a private event queue for its one roundtrip
so GTK's own events are never dispatched from here. Everything runs on GTK's thread (the overlay's paint).

A Wayland region is a set of rectangles, so the rounded shapes become thin horizontal strips (strips()).
If the compositor doesn't offer the protocol, or anything here fails, Blur.available is False and the themes keep
their painted glass.
"""
import ctypes
import math

MANAGER = b"ext_background_effect_manager_v1"
CAPABILITY_BLUR = 1
DISPLAY_GET_REGISTRY, REGISTRY_BIND = 1, 0
COMPOSITOR_CREATE_REGION = 1
REGION_DESTROY, REGION_ADD = 0, 1
MANAGER_GET_EFFECT = 1
EFFECT_SET_BLUR_REGION = 1
ROW = 2                     # strip height for round edges, px: finer looks no different through a blur


# ---- shapes -> strips (pure)

def _round_span(x, y, w, h, r, yc):
    """The rounded rect's horizontal extent on row yc, or None."""
    if not y <= yc < y + h:
        return None
    r = min(r, w / 2, h / 2)
    d = max(y + r - yc, yc - (y + h - r), 0)
    inset = r - math.sqrt(max(r * r - d * d, 0)) if d else 0
    return x + inset, x + w - inset


def _circle_span(cx, cy, r, yc):
    d = yc - cy
    if abs(d) >= r:
        return None
    half = math.sqrt(r * r - d * d)
    return cx - half, cx + half


def _corners(x, y, w, h, rot):
    """A rect rotated by rot degrees around its center: its four corners."""
    cx, cy, a = x + w / 2, y + h / 2, math.radians(rot)
    ca, sa = math.cos(a), math.sin(a)
    return [(cx + dx * ca - dy * sa, cy + dx * sa + dy * ca)
            for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]


def _polygon_span(pts, yc):
    xs = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        if (y0 <= yc < y1) or (y1 <= yc < y0):
            xs.append(x0 + (yc - y0) * (x1 - x0) / (y1 - y0))
    return (min(xs), max(xs)) if len(xs) >= 2 else None


def strips(shapes):
    """[(x, y, w, h)] integer rects covering the shapes: ("round", x, y, w, h, r), ("circle", cx, cy, r),
    ("piece", x, y, w, h, r, rotation in degrees). Rows of ROW px; consecutive rows with the same extent merge."""
    out = []
    for kind, *v in shapes:
        if kind == "round":
            top, bottom = v[1], v[1] + v[3]
            span = lambda yc, v=v: _round_span(*v, yc)  # noqa: E731
        elif kind == "circle":
            top, bottom = v[1] - v[2], v[1] + v[2]
            span = lambda yc, v=v: _circle_span(*v, yc)  # noqa: E731
        else:
            pts = _corners(*v[:4], v[5])
            top, bottom = min(p[1] for p in pts), max(p[1] for p in pts)
            span = lambda yc, pts=pts: _polygon_span(pts, yc)  # noqa: E731
        merged = None  # the rect still growing: [x, y, w, h]
        row = math.floor(top)
        while row < bottom:
            s = span(row + ROW / 2)
            x0, x1 = (math.floor(s[0]), math.ceil(s[1])) if s else (0, 0)
            if x1 <= x0:
                merged = None
            elif merged and (merged[0], merged[0] + merged[2]) == (x0, x1):
                merged[3] += ROW
            else:
                merged = [x0, row, x1 - x0, ROW]
                out.append(merged)
            row += ROW
    return [tuple(r) for r in out]


# ---- libwayland-client through ctypes

class _Message(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p), ("signature", ctypes.c_char_p), ("types", ctypes.POINTER(ctypes.c_void_p))]


class _Interface(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p), ("version", ctypes.c_int), ("method_count", ctypes.c_int),
                ("methods", ctypes.POINTER(_Message)), ("event_count", ctypes.c_int),
                ("events", ctypes.POINTER(_Message))]


_GLOBAL = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32)
_REMOVE = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32)


class _RegistryListener(ctypes.Structure):
    _fields_ = [("global_", _GLOBAL), ("global_remove", _REMOVE)]


def _gpointer(obj):
    """A GObject's C pointer."""
    get = ctypes.pythonapi.PyCapsule_GetPointer
    get.restype, get.argtypes = ctypes.c_void_p, [ctypes.py_object, ctypes.c_char_p]
    return get(obj.__gpointer__, None)


class Blur:
    def __init__(self, display, surface):
        """display: GTK's Gdk.Display; surface: the overlay's Gdk.Surface."""
        self.available = False
        self.effect = None
        self.last = None
        try:
            self._setup(display, surface)
        except (OSError, AttributeError, ValueError) as e:
            print(f"flippy: glass: unavailable ({e})", flush=True)

    def _setup(self, display, surface):
        wl = self.wl = ctypes.CDLL("libwayland-client.so.0")
        gtk = ctypes.CDLL("libgtk-4.so.1")
        for name in ("gdk_wayland_display_get_wl_display", "gdk_wayland_surface_get_wl_surface"):
            getattr(gtk, name).restype, getattr(gtk, name).argtypes = ctypes.c_void_p, [ctypes.c_void_p]
        self.display = gtk.gdk_wayland_display_get_wl_display(_gpointer(display))
        self.surface = gtk.gdk_wayland_surface_get_wl_surface(_gpointer(surface))
        if not self.display or not self.surface:
            raise ValueError("not a Wayland display")
        wl.wl_proxy_marshal_flags.restype = ctypes.c_void_p
        wl.wl_proxy_get_version.restype, wl.wl_proxy_get_version.argtypes = ctypes.c_uint32, [ctypes.c_void_p]
        for name in ("wl_display_create_queue", "wl_proxy_create_wrapper"):
            getattr(wl, name).restype, getattr(wl, name).argtypes = ctypes.c_void_p, [ctypes.c_void_p]
        wl.wl_proxy_set_queue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        wl.wl_proxy_wrapper_destroy.argtypes = [ctypes.c_void_p]
        wl.wl_proxy_add_listener.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        wl.wl_display_roundtrip_queue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        wl.wl_display_flush.argtypes = [ctypes.c_void_p]
        self.core = {n: _Interface.in_dll(wl, f"wl_{n}_interface") for n in ("registry", "compositor", "region",
                                                                             "surface")}
        self._interfaces()

        # find the globals on a queue of our own, so GTK's events stay GTK's
        queue = wl.wl_display_create_queue(self.display)
        wrapper = wl.wl_proxy_create_wrapper(self.display)
        wl.wl_proxy_set_queue(wrapper, queue)
        registry = self._marshal(wrapper, DISPLAY_GET_REGISTRY, self.core["registry"], ctypes.c_void_p(None))
        wl.wl_proxy_wrapper_destroy(wrapper)
        found = {}

        def on_global(_data, _registry, name, interface, version):
            if interface in (MANAGER, b"wl_compositor"):
                found[interface] = (name, version)
        self._listener = _RegistryListener(_GLOBAL(on_global), _REMOVE(lambda *a: None))
        wl.wl_proxy_add_listener(registry, ctypes.addressof(self._listener), None)
        wl.wl_display_roundtrip_queue(self.display, queue)
        if MANAGER not in found or b"wl_compositor" not in found:
            raise ValueError("the compositor has no background effect")
        self.compositor = self._bind(registry, self.core["compositor"], b"wl_compositor", *found[b"wl_compositor"],
                                     want=4)
        self.manager = self._bind(registry, self.manager_iface, MANAGER, *found[MANAGER], want=1)
        self.effect = self._marshal(self.manager, MANAGER_GET_EFFECT, self.effect_iface, ctypes.c_void_p(None),
                                    ctypes.c_void_p(self.surface))
        wl.wl_display_flush(self.display)
        self.available = bool(self.effect)

    def _interfaces(self):
        """ext_background_effect_manager_v1 and ext_background_effect_surface_v1, as libwayland describes them."""
        def messages(*items):
            arr = (_Message * len(items))()
            for i, (name, sig, types) in enumerate(items):
                t = (ctypes.c_void_p * max(len(types), 1))(*[ctypes.addressof(x) if x is not None else None
                                                              for x in types])
                self._keep.append(t)
                arr[i] = _Message(name, sig, ctypes.cast(t, ctypes.POINTER(ctypes.c_void_p)))
            self._keep.append(arr)
            return arr
        self._keep = []
        self.effect_iface = _Interface(b"ext_background_effect_surface_v1", 1, 2, None, 0, None)
        self.effect_iface.methods = messages((b"destroy", b"", []), (b"set_blur_region", b"?o", [self.core["region"]]))
        self.manager_iface = _Interface(MANAGER, 1, 2, None, 1, None)
        self.manager_iface.methods = messages((b"destroy", b"", []),
                                              (b"get_background_effect", b"no", [self.effect_iface,
                                                                                 self.core["surface"]]))
        self.manager_iface.events = messages((b"capabilities", b"u", [None]))

    def _marshal(self, proxy, opcode, interface, *args, destroy=False):
        """One request; destroy: it's the object's destructor, so libwayland frees the proxy too."""
        iface = ctypes.byref(interface) if interface is not None else None
        return self.wl.wl_proxy_marshal_flags(ctypes.c_void_p(proxy), ctypes.c_uint32(opcode), iface,
                                              ctypes.c_uint32(self.wl.wl_proxy_get_version(proxy)),
                                              ctypes.c_uint32(1 if destroy else 0), *args)

    def _bind(self, registry, interface, name_bytes, name, version, want):
        version = min(version, want)
        return self.wl.wl_proxy_marshal_flags(ctypes.c_void_p(registry), ctypes.c_uint32(REGISTRY_BIND),
                                              ctypes.byref(interface), ctypes.c_uint32(version), ctypes.c_uint32(0),
                                              ctypes.c_uint32(name), ctypes.c_char_p(name_bytes),
                                              ctypes.c_uint32(version), ctypes.c_void_p(None))

    def set_shapes(self, shapes):
        """Blur behind these shapes (see strips()) from the overlay's next commit; [] for none."""
        if not self.available:
            return
        rects = strips(shapes)
        if rects == self.last:
            return
        self.last = rects
        region = None
        if rects:
            region = self._marshal(self.compositor, COMPOSITOR_CREATE_REGION, self.core["region"],
                                   ctypes.c_void_p(None))
            for x, y, w, h in rects:
                self._marshal(region, REGION_ADD, None, ctypes.c_int32(x), ctypes.c_int32(y), ctypes.c_int32(w),
                              ctypes.c_int32(h))
        self._marshal(self.effect, EFFECT_SET_BLUR_REGION, None, ctypes.c_void_p(region))
        if region:
            self._marshal(region, REGION_DESTROY, None, destroy=True)
        self.wl.wl_display_flush(self.display)
