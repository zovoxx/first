
import bpy, os, json
import numpy as np

ROOT = os.path.join(os.path.expanduser("~"), "Documents", "Contoo", "Assets")


def _std_view():
    sc = bpy.context.scene
    vs = sc.view_settings
    old = (vs.view_transform, vs.look, vs.exposure, vs.gamma)
    vs.view_transform = "Standard"; vs.look = "None"; vs.exposure = 0.0; vs.gamma = 1.0
    return old


def load_px(path):
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    a = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    bpy.data.images.remove(img)
    return a


def save_px(arr, path, fmt="PNG", quality=90, size=None):
    h, w = arr.shape[:2]
    img = bpy.data.images.new("conto_tmp", w, h, alpha=True)
    img.pixels.foreach_set(np.ascontiguousarray(arr, dtype=np.float32).ravel())
    if size:
        img.scale(int(size[0]), int(size[1]))
    img.file_format = fmt
    img.filepath_raw = path
    try:
        if fmt in ("WEBP", "JPEG"):
            img.save(filepath=path, quality=int(quality))
        else:
            img.save(filepath=path)
    finally:
        bpy.data.images.remove(img)
    return path


def _seam_path(E, lo, hi):
    """Minimum-error vertical path (image quilting). E: (h, w). Path stays in [lo, hi]."""
    h, w = E.shape
    INF = 1e18
    C = np.full((h, w), INF, dtype=np.float64)
    C[0, lo:hi + 1] = E[0, lo:hi + 1]
    back = np.zeros((h, w), dtype=np.int32)
    for y in range(1, h):
        prev = C[y - 1]
        left = np.concatenate([[INF], prev[:-1]])
        right = np.concatenate([prev[1:], [INF]])
        stack = np.stack([left, prev, right])
        k = np.argmin(stack, axis=0)
        best = stack[k, np.arange(w)]
        C[y] = best + E[y]
        C[y, :lo] = INF
        C[y, hi + 1:] = INF
        back[y] = np.arange(w) + (k - 1)
    path = np.zeros(h, dtype=np.int32)
    path[-1] = int(np.argmin(C[-1]))
    for y in range(h - 1, 0, -1):
        path[y - 1] = back[y, path[y]]
    return path


def far_layer(src, name, blend=320, feather=6):
    out = os.path.join(ROOT, "Backgrounds", name)
    os.makedirs(out, exist_ok=True)
    a = load_px(src)
    h, w = a.shape[:2]
    A = a[:, w - blend:, :3]     # end of the image (comes before the wrap)
    B = a[:, :blend, :3]         # start of the image (comes after the wrap)
    E = ((A - B) ** 2).sum(axis=2).astype(np.float64)
    path = _seam_path(E, feather + 2, blend - feather - 3)
    x = np.arange(blend)[None, :].astype(np.float32)
    t = np.clip((x - path[:, None] + feather) / (2.0 * feather), 0.0, 1.0)[..., None]
    o = a[:, : w - blend].copy()
    o[:, :blend, :3] = A * (1.0 - t) + B * t
    o[..., 3] = 1.0
    W2 = o.shape[1]
    pc = save_px(o, os.path.join(out, f"{name}_far_PC.png"), "PNG")
    mob = save_px(o, os.path.join(out, f"{name}_far_mobile.webp"), "WEBP", 82, size=(W2 // 2, h // 2))
    return {"pc": pc, "mobile": mob, "size_pc": [W2, h], "size_mobile": [W2 // 2, h // 2],
            "seam_err": round(float(E[np.arange(h), path].mean()), 5)}


def mid_layer(src_rgba, name, fade=48):
    out = os.path.join(ROOT, "Backgrounds", name)
    os.makedirs(out, exist_ok=True)
    a = load_px(src_rgba)
    h, w = a.shape[:2]
    ramp = np.ones(w, np.float32)
    ramp[:fade] = np.linspace(0.0, 1.0, fade)
    ramp[-fade:] = np.linspace(1.0, 0.0, fade)
    a[..., 3] *= ramp[None, :]
    rows = np.where(a[..., 3].max(axis=1) > 0.02)[0]      # pixel rows are bottom-up in Blender
    top = min(h, int(rows.max()) + 9) if len(rows) else h
    a = a[:top]
    h2 = a.shape[0]
    pc = save_px(a, os.path.join(out, f"{name}_mid_PC.png"), "PNG")
    mob = save_px(a, os.path.join(out, f"{name}_mid_mobile.webp"), "WEBP", 85, size=(w // 2, max(1, h2 // 2)))
    return {"pc": pc, "mobile": mob, "size_pc": [w, h2], "size_mobile": [w // 2, h2 // 2],
            "coverage": round(float((a[..., 3] > 0.5).mean()), 3)}


def composite_preview(far_png, mid_png, out_path, width=1400):
    f = load_px(far_png)
    m = load_px(mid_png)
    fh, fw = f.shape[:2]
    # tile far horizontally to cover width of mid, then crop to mid width
    mh, mw = m.shape[:2]
    reps = int(np.ceil(mw / fw))
    f2 = np.concatenate([f] * reps, axis=1)[:, :mw]
    # place mid at bottom of far
    comp = f2.copy()
    hh = min(mh, fh)
    alpha = m[:hh, :, 3:4]
    comp[:hh, :, :3] = m[:hh, :, :3] * alpha + comp[:hh, :, :3] * (1 - alpha)
    comp[..., 3] = 1.0
    s = width / comp.shape[1]
    return save_px(comp, out_path, "JPEG", 85, size=(width, int(comp.shape[0] * s)))


# ---------------------------------------------------------------- mid layers (white-key cutout + seamless tiling)

def _dilate(m, r=1):
    o = m.copy()
    for _ in range(r):
        p = o.copy()
        p[1:] |= o[:-1]; p[:-1] |= o[1:]; p[:, 1:] |= o[:, :-1]; p[:, :-1] |= o[:, 1:]
        o = p
    return o


def _maxfilter(d):
    o = d.copy()
    o[1:] = np.maximum(o[1:], d[:-1]); o[:-1] = np.maximum(o[:-1], d[1:])
    o2 = o.copy()
    o2[:, 1:] = np.maximum(o2[:, 1:], o[:, :-1]); o2[:, :-1] = np.maximum(o2[:, :-1], o[:, 1:])
    return o2


def _runs_fill(reached, low):
    """Inside every horizontal run of `low` pixels: mark the whole run if any of its pixels is reached."""
    h, w = low.shape
    fl = low.ravel()
    prev = np.zeros_like(fl)
    prev[1:] = fl[:-1]
    prev[::w] = False
    start = fl & ~prev
    rid = np.cumsum(start, dtype=np.int64)
    rid[~fl] = 0
    mark = np.zeros(int(rid.max()) + 1, bool)
    mark[np.unique(rid[reached.ravel() & fl])] = True
    mark[0] = False
    return mark[rid].reshape(h, w)


def flood(seeds, low, max_iter=400):
    """4-connected flood fill of `low` starting at `seeds` (row/column run sweeps, numpy only)."""
    r = seeds & low
    it = 0
    for it in range(max_iter):
        r2 = _runs_fill(r, low)
        r2 = np.ascontiguousarray(_runs_fill(np.ascontiguousarray(r2.T), np.ascontiguousarray(low.T)).T)
        if np.array_equal(r2, r):
            break
        r = r2
    return r, it


def key_cut(orig_path, biref_path=None, t_low=0.07):
    """Cut a game-asset strip from its plain light background.
    Background = near-background-colour pixels connected to the top/sides (plus any near-bg pixel that
    BiRefNet also calls background, which opens enclosed holes such as lattice gaps).
    Edge pixels are un-mixed against the background colour (alpha from colour distance, colour decontaminated)."""
    a = load_px(orig_path)
    h, w = a.shape[:2]
    rgb = a[..., :3]
    border = np.concatenate([rgb[-6:].reshape(-1, 3), rgb[h // 2:, :4].reshape(-1, 3), rgb[h // 2:, -4:].reshape(-1, 3)])
    bg = np.median(border, axis=0).astype(np.float32)
    d = np.abs(rgb - bg[None, None, :]).max(axis=2)
    low = d < t_low
    seeds = np.zeros_like(low)
    seeds[-1, :] = True          # top row (rows are bottom-up)
    seeds[:, 0] = True
    seeds[:, -1] = True
    if biref_path:
        ab = load_px(biref_path)[..., 3]
        seeds |= ab < 0.2
    bgm, iters = flood(seeds, low)
    alpha = (~bgm).astype(np.float32)
    near = _dilate(bgm, 1) & ~bgm
    dref = np.maximum(_maxfilter(np.where(bgm, 0.0, d).astype(np.float32)), 0.08)
    alpha[near] = np.clip(d[near] / dref[near], 0.0, 1.0)
    out = a.copy()
    al = alpha[..., None]
    C = (rgb - (1.0 - al) * bg[None, None, :]) / np.maximum(al, 0.02)
    fix = (al > 0.0) & (al < 0.999)
    out[..., :3] = np.where(fix, np.clip(C, 0.0, 1.0), rgb)
    out[..., :3] = np.where(al <= 0.0, 0.0, out[..., :3])
    out[..., 3] = alpha
    return out, {"bg": [round(float(x), 3) for x in bg], "iters": int(iters), "coverage": round(float(alpha.mean()), 3)}


def mid_layer_tile(rgba, name, blend=320, feather=5):
    """Seamless horizontal tile from an RGBA strip (min-error seam on premultiplied colour + alpha)."""
    out = os.path.join(ROOT, "Backgrounds", name)
    os.makedirs(out, exist_ok=True)
    a = rgba
    h, w = a.shape[:2]
    pm = a[..., :3] * a[..., 3:4]
    A, B = a[:, w - blend:], a[:, :blend]
    PA, PB = pm[:, w - blend:], pm[:, :blend]
    E = ((PA - PB) ** 2).sum(axis=2) + 2.0 * (A[..., 3] - B[..., 3]) ** 2
    path = _seam_path(E.astype(np.float64), feather + 2, blend - feather - 3)
    x = np.arange(blend)[None, :].astype(np.float32)
    t = np.clip((x - path[:, None] + feather) / (2.0 * feather), 0.0, 1.0)[..., None]
    P = PA * (1.0 - t) + PB * t
    al = A[..., 3:4] * (1.0 - t) + B[..., 3:4] * t
    o = a[:, : w - blend].copy()
    o[:, :blend, :3] = np.where(al > 1e-4, P / np.maximum(al, 1e-4), 0.0)
    o[:, :blend, 3:4] = al
    rows = np.where(o[..., 3].max(axis=1) > 0.02)[0]
    top = min(h, int(rows.max()) + 9) if len(rows) else h
    bot = max(0, int(rows.min()) - 2) if len(rows) else 0
    o = o[bot:top]
    h2, W2 = o.shape[:2]
    cov = (o[..., 3] > 0.5).mean(axis=1)                     # per row, bottom-up
    solid = np.where(cov > 0.85)[0]
    strip_top_from_top = int(h2 - 1 - solid.max()) if len(solid) else None
    pc = save_px(o, os.path.join(out, f"{name}_mid_PC.png"), "PNG")
    mob = save_px(o, os.path.join(out, f"{name}_mid_mobile.webp"), "WEBP", 85, size=(W2 // 2, max(1, h2 // 2)))
    return {"pc": pc, "mobile": mob, "size_pc": [W2, h2], "size_mobile": [W2 // 2, h2 // 2],
            "strip_top_px": strip_top_from_top, "touches_bottom": bool(bot == 0 and cov[0] > 0.85),
            "seam_err": round(float(E[np.arange(h), path].mean()), 5)}


def tile_preview(far_png, mid_png, out_path, tiles=2, width=1600, mark=True):
    """Far layer tiled behind `tiles` copies of the mid layer (mid anchored at the bottom); seam lines marked."""
    f = load_px(far_png)
    m = load_px(mid_png)
    fh, fw = f.shape[:2]
    mh, mw = m.shape[:2]
    Wt = mw * tiles
    f2 = np.concatenate([f] * int(np.ceil(Wt / fw) + 1), axis=1)[:, :Wt].copy()
    m2 = np.concatenate([m] * tiles, axis=1)
    hh = min(mh, fh)
    al = m2[:hh, :, 3:4]
    f2[:hh, :, :3] = m2[:hh, :, :3] * al + f2[:hh, :, :3] * (1.0 - al)
    if mark:
        for k in range(1, tiles):
            f2[-14:, k * mw - 1:k * mw + 1, :3] = [1.0, 0.0, 0.0]
        for k in range(1, int(Wt // fw) + 1):
            f2[:10, k * fw - 1:k * fw + 1, :3] = [0.0, 1.0, 1.0]
    f2[..., 3] = 1.0
    s = width / f2.shape[1]
    return save_px(f2, out_path, "JPEG", 85, size=(width, int(f2.shape[0] * s)))


# ---------------------------------------------------------------- far layers v2 (min-error seam + multi-band blend)

def _blur5(x, axis):
    k = (1.0 / 16, 4.0 / 16, 6.0 / 16, 4.0 / 16, 1.0 / 16)
    pad = [(0, 0)] * x.ndim
    pad[axis] = (2, 2)
    xp = np.pad(x, pad, mode="edge")
    n = x.shape[axis]
    out = np.zeros_like(x)
    for i, kk in enumerate(k):
        sl = [slice(None)] * x.ndim
        sl[axis] = slice(i, i + n)
        out += np.float32(kk) * xp[tuple(sl)]
    return out


def _down(x):
    return _blur5(_blur5(x, 0), 1)[::2, ::2]


def _up(x, shape):
    u = np.repeat(np.repeat(x, 2, axis=0), 2, axis=1)[:shape[0], :shape[1]]
    return _blur5(_blur5(u, 0), 1)


def _pyr_blend(A, B, M, levels=5):
    """Burt-Adelson multi-band blend: low frequencies cross-fade wide, details are cut sharply along M."""
    GA, GB, GM = [A], [B], [M]
    for _ in range(levels):
        GA.append(_down(GA[-1])); GB.append(_down(GB[-1])); GM.append(_down(GM[-1]))
    out = GA[-1] * (1.0 - GM[-1]) + GB[-1] * GM[-1]
    for i in range(levels - 1, -1, -1):
        LA = GA[i] - _up(GA[i + 1], GA[i].shape)
        LB = GB[i] - _up(GB[i + 1], GB[i].shape)
        out = _up(out, GA[i].shape) + LA * (1.0 - GM[i]) + LB * GM[i]
    return out


def far_layer_mb(src, name, blend=400, margin=90, levels=5, edge=24):
    out = os.path.join(ROOT, "Backgrounds", name)
    os.makedirs(out, exist_ok=True)
    a = load_px(src)
    h, w = a.shape[:2]
    A = a[:, w - blend:, :3].copy()
    B = a[:, :blend, :3].copy()
    E = ((A - B) ** 2).sum(axis=2).astype(np.float64)
    path = _seam_path(E, margin, blend - margin)
    x = np.arange(blend)[None, :]
    M = (x >= path[:, None]).astype(np.float32)[..., None]
    o3 = _pyr_blend(A, B, M, levels)
    r = np.clip(np.arange(blend, dtype=np.float32) / edge, 0.0, 1.0)[None, :, None]          # exact continuity at both ends
    l = np.clip((blend - 1 - np.arange(blend, dtype=np.float32)) / edge, 0.0, 1.0)[None, :, None]
    o3 = A * (1.0 - r) + o3 * r
    o3 = B * (1.0 - l) + o3 * l
    o = a[:, : w - blend].copy()
    o[:, :blend, :3] = np.clip(o3, 0.0, 1.0)
    o[..., 3] = 1.0
    W2 = o.shape[1]
    pc = save_px(o, os.path.join(out, f"{name}_far_PC.png"), "PNG")
    mob = save_px(o, os.path.join(out, f"{name}_far_mobile.webp"), "WEBP", 82, size=(W2 // 2, h // 2))
    return {"pc": pc, "mobile": mob, "size_pc": [W2, h], "size_mobile": [W2 // 2, h // 2],
            "seam_err": round(float(E[np.arange(h), path].mean()), 5), "path_range": [int(path.min()), int(path.max())]}


def _box(x, r, axis):
    """Box mean of radius r along axis (edge-padded), via cumulative sums."""
    pad = [(0, 0)] * x.ndim
    pad[axis] = (r + 1, r)
    xp = np.pad(x, pad, mode="edge").astype(np.float64)
    c = np.cumsum(xp, axis=axis)
    n = x.shape[axis]
    hi = [slice(None)] * x.ndim; hi[axis] = slice(2 * r + 1, 2 * r + 1 + n)
    lo = [slice(None)] * x.ndim; lo[axis] = slice(0, n)
    return ((c[tuple(hi)] - c[tuple(lo)]) / (2 * r + 1)).astype(np.float32)


def _gauss(x, r, axes=(0, 1)):
    for ax in axes:
        for _ in range(3):
            x = _box(x, r, ax)
    return x


def far_layer_mb2(src, name, blend=400, margin=90, levels=5, edge=24, lowr=10, dr=20):
    """Seamless far layer: min-error seam + multi-band blend + whole-width low-frequency colour ramp,
    so brightness/colour differences between the two image ends are spread across the full tile."""
    out = os.path.join(ROOT, "Backgrounds", name)
    os.makedirs(out, exist_ok=True)
    a = load_px(src)
    h, w = a.shape[:2]
    W2 = w - blend
    A = a[:, w - blend:, :3].copy()
    F = a[:, :W2, :3].copy()
    B = F[:, :blend]
    rows = np.arange(h)
    Dfield = _gauss(B - A, lowr)                                  # low-frequency difference B - A
    path = _seam_path(((A - B) ** 2).sum(axis=2).astype(np.float64), margin, blend - margin)
    for _ in range(2):
        D = _gauss(Dfield[rows, path][:, None, :], dr, axes=(0,))[:, 0, :]          # (h, 3), smooth along y
        E2 = ((A - (B - D[:, None, :])) ** 2).sum(axis=2).astype(np.float64)
        path = _seam_path(E2, margin, blend - margin)
    D = _gauss(Dfield[rows, path][:, None, :], dr, axes=(0,))[:, 0, :]
    x = np.arange(W2, dtype=np.float32)[None, :]
    p = path[:, None].astype(np.float32)
    Fc = F - D[:, None, :] * (1.0 - (x - p) / W2)[..., None]                       # B side + middle
    xa = np.arange(blend, dtype=np.float32)[None, :]
    Ac = A - D[:, None, :] * ((p - xa) / W2)[..., None]                             # A side
    Bc = Fc[:, :blend]
    M = (np.arange(blend)[None, :] >= path[:, None]).astype(np.float32)[..., None]
    o3 = _pyr_blend(Ac, Bc, M, levels)
    r = np.clip(np.arange(blend, dtype=np.float32) / edge, 0.0, 1.0)[None, :, None]
    l = np.clip((blend - 1 - np.arange(blend, dtype=np.float32)) / edge, 0.0, 1.0)[None, :, None]
    o3 = Ac * (1.0 - r) + o3 * r
    o3 = Bc * (1.0 - l) + o3 * l
    o = np.ones((h, W2, 4), np.float32)
    o[..., :3] = Fc
    o[:, :blend, :3] = o3
    o[..., :3] = np.clip(o[..., :3], 0.0, 1.0)
    pc = save_px(o, os.path.join(out, f"{name}_far_PC.png"), "PNG")
    mob = save_px(o, os.path.join(out, f"{name}_far_mobile.webp"), "WEBP", 82, size=(W2 // 2, h // 2))
    wrap_jump = float(np.abs(o[:, 0, :3] - o[:, -1, :3]).mean())
    return {"pc": pc, "mobile": mob, "size_pc": [W2, h], "size_mobile": [W2 // 2, h // 2],
            "D_max": round(float(np.abs(D).max()), 4), "path_range": [int(path.min()), int(path.max())],
            "wrap_jump": round(wrap_jump, 4)}


def far_layer_mb3(src, name, blend=400, margin=90, levels=5, edge=24, lowr=10, dr=20,
                  wide=180.0, g_lo=0.004, g_hi=0.012, save=True):
    """far_layer_mb2 + adaptive transition width: rows without vertical structure (sky, soft clouds)
    cross-fade over `wide` px, rows with vertical detail (cliffs, buildings, trunks) keep a sharp cut."""
    out = os.path.join(ROOT, "Backgrounds", name)
    os.makedirs(out, exist_ok=True)
    a = load_px(src)
    h, w = a.shape[:2]
    W2 = w - blend
    A = a[:, w - blend:, :3].copy()
    F = a[:, :W2, :3].copy()
    B = F[:, :blend]
    rows = np.arange(h)
    Dfield = _gauss(B - A, lowr)
    path = _seam_path(((A - B) ** 2).sum(axis=2).astype(np.float64), margin, blend - margin)
    for _ in range(2):
        D = _gauss(Dfield[rows, path][:, None, :], dr, axes=(0,))[:, 0, :]
        E2 = ((A - (B - D[:, None, :])) ** 2).sum(axis=2).astype(np.float64)
        path = _seam_path(E2, margin, blend - margin)
    D = _gauss(Dfield[rows, path][:, None, :], dr, axes=(0,))[:, 0, :]
    x = np.arange(W2, dtype=np.float32)[None, :]
    p = path[:, None].astype(np.float32)
    Fc = F - D[:, None, :] * (1.0 - (x - p) / W2)[..., None]
    xa = np.arange(blend, dtype=np.float32)[None, :]
    Ac = A - D[:, None, :] * ((p - xa) / W2)[..., None]
    Bc = Fc[:, :blend]
    lum = lambda c: c[..., 0] * 0.2126 + c[..., 1] * 0.7152 + c[..., 2] * 0.0722
    gx = np.abs(np.diff(lum(Ac), axis=1)).mean(axis=1) + np.abs(np.diff(lum(Bc), axis=1)).mean(axis=1)
    g = _gauss(gx[:, None].astype(np.float32), 8, axes=(0,))[:, 0] * 0.5
    s = np.clip((g_hi - g) / (g_hi - g_lo), 0.0, 1.0)
    wrow = 2.0 + s * (wide - 2.0)
    M = np.clip((xa - p) / wrow[:, None] + 0.5, 0.0, 1.0)[..., None].astype(np.float32)
    o3 = _pyr_blend(Ac, Bc, M, levels)
    r = np.clip(np.arange(blend, dtype=np.float32) / edge, 0.0, 1.0)[None, :, None]
    l = np.clip((blend - 1 - np.arange(blend, dtype=np.float32)) / edge, 0.0, 1.0)[None, :, None]
    o3 = Ac * (1.0 - r) + o3 * r
    o3 = Bc * (1.0 - l) + o3 * l
    o = np.ones((h, W2, 4), np.float32)
    o[..., :3] = Fc
    o[:, :blend, :3] = o3
    o[..., :3] = np.clip(o[..., :3], 0.0, 1.0)
    info = {"size_pc": [W2, h], "size_mobile": [W2 // 2, h // 2], "D_max": round(float(np.abs(D).max()), 4),
            "path_range": [int(path.min()), int(path.max())], "wide_rows": round(float((s > 0.5).mean()), 3),
            "g_pct": [round(float(np.percentile(g, q)), 4) for q in (10, 50, 90)]}
    if save:
        info["pc"] = save_px(o, os.path.join(out, f"{name}_far_PC.png"), "PNG")
        info["mobile"] = save_px(o, os.path.join(out, f"{name}_far_mobile.webp"), "WEBP", 82, size=(W2 // 2, h // 2))
    return o, info


def _seam_cost(E, lo, hi):
    """Minimum mean cost of a vertical 8-connected path through E restricted to columns [lo, hi]."""
    h, w = E.shape
    INF = 1e18
    c = np.full(w, INF)
    c[lo:hi + 1] = E[0, lo:hi + 1]
    for y in range(1, h):
        left = np.concatenate([[INF], c[:-1]])
        right = np.concatenate([c[1:], [INF]])
        c = np.minimum(np.minimum(left, c), right) + E[y]
        c[:lo] = INF
        c[hi + 1:] = INF
    return float(c.min()) / h


def _mid_E(a, pm, s, t, bw):
    A, B = a[:, s:s + bw], a[:, t:t + bw]
    return ((pm[:, s:s + bw] - pm[:, t:t + bw]) ** 2).sum(axis=2) + 2.0 * (A[..., 3] - B[..., 3]) ** 2


def mid_layer_tile2(rgba, name, bw=256, feather=5, search_t=448, search_e=640, step=16, drop_penalty=0.004, save=True):
    """Seamless horizontal tile from an RGBA strip. Searches which columns to join (start t, end e) so the
    seam runs through matching content (usually just the ground strip), then blends along a min-error seam."""
    out = os.path.join(ROOT, "Backgrounds", name)
    os.makedirs(out, exist_ok=True)
    a = rgba
    h, w = a.shape[:2]
    pm = a[..., :3] * a[..., 3:4]
    k = 4
    a4, pm4 = a[::k, ::k], pm[::k, ::k]
    bw4 = bw // k
    lo4, hi4 = (feather + 2) // k + 1, bw4 - (feather + 3) // k - 2
    best = None
    for t in range(0, search_t + 1, step):
        for e in range(w - search_e, w + 1, step):
            s = e - bw
            if s - t < w * 0.55:
                continue
            E4 = _mid_E(a4, pm4, s // k, t // k, bw4)
            c = _seam_cost(E4.astype(np.float64), lo4, hi4) + drop_penalty * (w - (s - t)) / 100.0
            if best is None or c < best[0]:
                best = (c, t, s)
    _, t, s = best
    E = _mid_E(a, pm, s, t, bw)
    path = _seam_path(E.astype(np.float64), feather + 2, bw - feather - 3)
    x = np.arange(bw)[None, :].astype(np.float32)
    tt = np.clip((x - path[:, None] + feather) / (2.0 * feather), 0.0, 1.0)[..., None]
    PA, PB = pm[:, s:s + bw], pm[:, t:t + bw]
    P = PA * (1.0 - tt) + PB * tt
    al = a[:, s:s + bw, 3:4] * (1.0 - tt) + a[:, t:t + bw, 3:4] * tt
    o = a[:, t:s].copy()
    o[:, :bw, :3] = np.where(al > 1e-4, P / np.maximum(al, 1e-4), 0.0)
    o[:, :bw, 3:4] = al
    rows = np.where(o[..., 3].max(axis=1) > 0.02)[0]
    top = min(h, int(rows.max()) + 9) if len(rows) else h
    bot = max(0, int(rows.min()) - 2) if len(rows) else 0
    o = o[bot:top]
    h2, W2 = o.shape[:2]
    cov = (o[..., 3] > 0.5).mean(axis=1)
    solid = np.where(cov > 0.85)[0]
    info = {"size_pc": [W2, h2], "size_mobile": [W2 // 2, h2 // 2], "cut": [int(t), int(s)],
            "strip_top_px": int(h2 - 1 - solid.max()) if len(solid) else None,
            "touches_bottom": bool(bot == 0 and cov[0] > 0.85), "touches_top": bool(top >= h and o[-1, :, 3].max() > 0.5),
            "seam_err": round(float(E[np.arange(h), path].mean()), 5)}
    if save:
        info["pc"] = save_px(o, os.path.join(out, f"{name}_mid_PC.png"), "PNG")
        info["mobile"] = save_px(o, os.path.join(out, f"{name}_mid_mobile.webp"), "WEBP", 85, size=(W2 // 2, max(1, h2 // 2)))
    return o, info
