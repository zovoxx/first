"""Contoo grounds: make TripoSplat gaussian splats game-ready (Y-up metres, top surface at y=0, centred),
plus a collision polyline and a collider mesh. Works on SPZ v2 / 3DGS PLY (SH degree 0)."""
import os, gzip, struct, json
import numpy as np

C0 = 0.28209479177387814


# ------------------------------------------------------------------ IO
def read_ply(path):
    data = open(path, "rb").read()
    end = data.index(b"end_header\n") + len(b"end_header\n")
    header = data[:end].decode("ascii", "replace")
    props, n = [], 0
    for line in header.splitlines():
        if line.startswith("element vertex"):
            n = int(line.split()[-1])
        if line.startswith("property"):
            _, t, name = line.split()
            props.append((name, t))
    assert all(t in ("float", "float32") for _, t in props), props
    dt = np.dtype([(nm, "<f4") for nm, _ in props])
    return np.frombuffer(data, dtype=dt, count=n, offset=end).copy()


def write_ply(path, arr):
    names = arr.dtype.names
    head = "ply\nformat binary_little_endian 1.0\nelement vertex %d\n" % len(arr)
    head += "".join("property float %s\n" % nm for nm in names) + "end_header\n"
    with open(path, "wb") as f:
        f.write(head.encode("ascii"))
        f.write(np.ascontiguousarray(arr).tobytes())
    return path


def read_spz(path):
    raw = gzip.decompress(open(path, "rb").read())
    magic, version, n, shdeg, fbits, flags, res = struct.unpack("<IIIBBBB", raw[:16])
    assert magic == 0x5053474E and version == 2, (hex(magic), version)
    off = 16
    pos = np.frombuffer(raw, np.uint8, n * 9, off).reshape(n, 3, 3).astype(np.int32); off += n * 9
    v = pos[..., 0] | (pos[..., 1] << 8) | (pos[..., 2] << 16)
    v = np.where(v & 0x800000, v - (1 << 24), v)
    P = v.astype(np.float64) / (1 << fbits)
    alpha = np.frombuffer(raw, np.uint8, n, off).copy(); off += n
    col = np.frombuffer(raw, np.uint8, n * 3, off).reshape(n, 3).copy(); off += n * 3
    scl = np.frombuffer(raw, np.uint8, n * 3, off).reshape(n, 3).copy(); off += n * 3
    rot = np.frombuffer(raw, np.uint8, n * 3, off).reshape(n, 3).copy(); off += n * 3
    rest = raw[off:]
    return {"n": n, "shdeg": shdeg, "fbits": fbits, "flags": flags}, P, alpha, col, scl, rot, rest


def write_spz(path, hdr, P, alpha, col, scl, rot, rest):
    n = len(P)
    fb = hdr["fbits"]
    v = np.round(P * (1 << fb)).astype(np.int64)
    assert np.abs(v).max() < (1 << 23), "position out of 24-bit range"
    v = v & 0xFFFFFF
    pos = np.stack([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF], axis=-1).astype(np.uint8)
    body = struct.pack("<IIIBBBB", 0x5053474E, 2, n, hdr["shdeg"], fb, hdr["flags"], 0)
    body += pos.tobytes() + alpha.tobytes() + col.tobytes() + scl.tobytes() + rot.tobytes() + rest
    with open(path, "wb") as f:
        f.write(gzip.compress(body, compresslevel=9))
    return path


# ------------------------------------------------------------------ maths
def qmul(a, b):
    aw, ax, ay, az = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bw, bx, by, bz = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return np.stack([aw * bw - ax * bx - ay * by - az * bz,
                     aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw], axis=-1)


Q_FLIP = np.array([0.0, 1.0, 0.0, 0.0])        # 180 deg about X: (x, y, z) -> (x, -y, -z)
R_FLIP = np.diag([1.0, -1.0, -1.0])


def spz_rot_decode(rot):
    xyz = rot.astype(np.float64) / 127.5 - 1.0
    w = np.sqrt(np.clip(1.0 - (xyz ** 2).sum(axis=1), 0.0, 1.0))
    return np.concatenate([w[:, None], xyz], axis=1)


def spz_rot_encode(q):
    q = q / np.linalg.norm(q, axis=1, keepdims=True)
    q = np.where(q[:, :1] < 0, -q, q)
    return np.clip(np.round(q[:, 1:] * 127.5 + 127.5), 0, 255).astype(np.uint8)


def _medfilt(v, k=5):
    r = k // 2
    vp = np.pad(v, r, mode="edge")
    return np.array([np.median(vp[i:i + k]) for i in range(len(v))])


def _dp_simplify(pts, eps):
    pts = np.asarray(pts, float)
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    ab = b - a
    L = np.hypot(*ab) or 1e-9
    d = np.abs(ab[0] * (pts[:, 1] - a[1]) - ab[1] * (pts[:, 0] - a[0])) / L
    i = int(np.argmax(d))
    if d[i] > eps:
        return np.vstack([_dp_simplify(pts[:i + 1], eps)[:-1], _dp_simplify(pts[i:], eps)])
    return np.vstack([a, b])


# ------------------------------------------------------------------ analysis + export
def analyse(ply_arr, length=8.0, bins=48):
    P = np.stack([ply_arr["x"], ply_arr["y"], ply_arr["z"]], axis=1).astype(np.float64)
    op = 1.0 / (1.0 + np.exp(-ply_arr["opacity"].astype(np.float64)))
    x0, x1 = np.percentile(P[:, 0], [1, 99])
    z0, z1 = np.percentile(P[:, 2], [2, 98])
    cx, cz = 0.5 * (x0 + x1), 0.5 * (z0 + z1)
    s = length / (x1 - x0)
    band = (np.abs(P[:, 2] - cz) < 0.25 * (z1 - z0)) & (op > 0.3)
    edges = np.linspace(x0, x1, bins + 1)
    tops, xs = [], []
    for i in range(bins):
        m = band & (P[:, 0] >= edges[i]) & (P[:, 0] < edges[i + 1])
        if m.sum() < 30:
            tops.append(np.nan)
        else:
            tops.append(np.percentile(P[m, 1], 12))       # native y points DOWN: low y = top surface
        xs.append(0.5 * (edges[i] + edges[i + 1]))
    tops = np.array(tops); xs = np.array(xs)
    ok = ~np.isnan(tops)
    tf = tops.copy()
    tf[ok] = _medfilt(tops[ok], 5)
    y_top = float(np.median(tf[ok]))
    t = np.array([-s * cx, s * y_top, s * cz])              # p_game = s * R_FLIP @ p + t
    poly = np.stack([s * (xs[ok] - cx), -s * (tf[ok] - y_top)], axis=1)
    # extend to the walkable ends of the platform (first/last bin edges)
    first, last = np.where(ok)[0][[0, -1]]
    poly = np.vstack([[s * (edges[first] - cx), poly[0, 1]], poly, [s * (edges[last + 1] - cx), poly[-1, 1]]])
    poly = _dp_simplify(poly, 0.02)
    G = (s * (R_FLIP @ P.T)).T + t
    lo, hi = np.percentile(G, 1, axis=0), np.percentile(G, 99, axis=0)
    return {"scale": float(s), "translation": t.tolist(), "rotation_euler_deg": [180.0, 0.0, 0.0],
            "poly": poly.tolist(), "bbox_game": [lo.tolist(), hi.tolist()],
            "native_center": [float(cx), float(y_top), float(cz)]}


def transform_ply(arr, s, t):
    o = arr.copy()
    P = np.stack([arr["x"], arr["y"], arr["z"]], axis=1).astype(np.float64)
    G = (s * (R_FLIP @ P.T)).T + np.asarray(t)
    o["x"], o["y"], o["z"] = G[:, 0], G[:, 1], G[:, 2]
    for k in ("scale_0", "scale_1", "scale_2"):
        o[k] = arr[k] + np.float32(np.log(s))
    q = np.stack([arr["rot_0"], arr["rot_1"], arr["rot_2"], arr["rot_3"]], axis=1).astype(np.float64)
    q2 = qmul(np.broadcast_to(Q_FLIP, q.shape), q)
    for i in range(4):
        o["rot_%d" % i] = q2[:, i]
    return o


def transform_spz(src, dst, s, t):
    hdr, P, alpha, col, scl, rot, rest = read_spz(src)
    G = (s * (R_FLIP @ P.T)).T + np.asarray(t)
    scl2 = np.clip(np.round(scl.astype(np.float64) + 16.0 * np.log(s)), 0, 255).astype(np.uint8)
    q = spz_rot_decode(rot)
    rot2 = spz_rot_encode(qmul(np.broadcast_to(Q_FLIP, q.shape), q))
    write_spz(dst, hdr, G, alpha, col, scl2, rot2, rest)
    return {"n": int(hdr["n"]), "bytes": os.path.getsize(dst), "scale_clipped": int(((scl.astype(np.float64) + 16 * np.log(s)) > 255).sum())}


def side_view(ply_game, poly, out_png_path, save_fn, W=1000, H=420, margin=0.6):
    """Orthographic side view (game X right, Y up) of the transformed splat + collision polyline in red."""
    P = np.stack([ply_game["x"], ply_game["y"], ply_game["z"]], axis=1)
    col = np.clip(0.5 + C0 * np.stack([ply_game["f_dc_0"], ply_game["f_dc_1"], ply_game["f_dc_2"]], axis=1), 0, 1)
    xmin, xmax = P[:, 0].min() - margin, P[:, 0].max() + margin
    ymin, ymax = P[:, 1].min() - margin, P[:, 1].max() + margin + 1.0
    sc = min(W / (xmax - xmin), H / (ymax - ymin))
    img = np.zeros((H, W, 4), np.float32)
    img[..., :3] = 0.18; img[..., 3] = 1.0
    order = np.argsort(-P[:, 2])                   # far (negative z is away from a +z camera) first... draw far->near
    order = np.argsort(P[:, 2])
    px = ((P[order, 0] - xmin) * sc).astype(int)
    py = ((P[order, 1] - ymin) * sc).astype(int)    # rows bottom-up (Blender pixel order)
    okm = (px >= 0) & (px < W - 1) & (py >= 0) & (py < H - 1)
    for dx in (0, 1):
        for dy in (0, 1):
            img[py[okm] + dy, px[okm] + dx, :3] = col[order][okm]
    pl = np.asarray(poly)
    for i in range(len(pl) - 1):
        for u in np.linspace(0, 1, 200):
            x = pl[i, 0] * (1 - u) + pl[i + 1, 0] * u
            y = pl[i, 1] * (1 - u) + pl[i + 1, 1] * u
            cx_, cy_ = int((x - xmin) * sc), int((y - ymin) * sc)
            if 0 <= cx_ < W and 1 <= cy_ < H - 1:
                img[cy_ - 1:cy_ + 1, cx_, :3] = [1.0, 0.1, 0.1]
    # 1 m ruler + a 1.7 m character-height marker at x=0
    x0p = int((0 - xmin) * sc)
    y0p = int((0 - ymin) * sc)
    img[y0p:y0p + int(1.7 * sc), max(0, x0p - 1):x0p + 1, :3] = [0.2, 0.9, 1.0]
    return save_fn(img, out_png_path, "PNG")
