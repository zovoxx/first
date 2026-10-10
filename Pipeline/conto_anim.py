"""Contoo animation retargeting (numpy only): Kimodo SOMA BVH -> 21-bone Contoo rigs.

Target rigs: Blender armature space, Z up, character facing -Y, metres.
Source BVH: Y up, facing +Z, centimetres, T-pose rest (identity rotations)."""
import numpy as np

C = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])       # BVH (x,y,z) -> Blender (x,-z,y)

MAP = {   # target bone: (source joint for twist/rotation, chain start, chain end)
    "hips": ("Hips", "Hips", "Spine1"),
    "spine": ("Spine1", "Spine1", "Chest"),
    "chest": ("Chest", "Chest", "Neck1"),
    "neck": ("Neck1", "Neck1", "Head"),
    "head": ("Head", "Head", "HeadEnd"),
}
for s, S in (("L", "Left"), ("R", "Right")):
    MAP.update({
        f"shoulder.{s}": (f"{S}Shoulder", f"{S}Shoulder", f"{S}Arm"),
        f"upper_arm.{s}": (f"{S}Arm", f"{S}Arm", f"{S}ForeArm"),
        f"forearm.{s}": (f"{S}ForeArm", f"{S}ForeArm", f"{S}Hand"),
        f"hand.{s}": (f"{S}Hand", f"{S}Hand", f"{S}HandMiddle1"),
        f"thigh.{s}": (f"{S}Leg", f"{S}Leg", f"{S}Shin"),
        f"shin.{s}": (f"{S}Shin", f"{S}Shin", f"{S}Foot"),
        f"foot.{s}": (f"{S}Foot", f"{S}Foot", f"{S}ToeBase"),
        f"toe.{s}": (f"{S}ToeBase", f"{S}ToeBase", f"{S}ToeEnd"),
    })


# ------------------------------------------------------------------ BVH
def parse_bvh(text):
    lines = text.splitlines()
    joints, parents, offsets, chans = [], [], [], []
    stack, cur, i = [], None, 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith(("ROOT", "JOINT")):
            joints.append(s.split()[1]); parents.append(stack[-1] if stack else -1)
            offsets.append([0.0, 0.0, 0.0]); chans.append([])
            cur = len(joints) - 1
        elif s.startswith("End Site"):
            depth = 0
            while True:
                i += 1
                t = lines[i].strip()
                if t == "{":
                    depth += 1
                elif t == "}":
                    depth -= 1
                    if depth == 0:
                        break
        elif s.startswith("OFFSET") and cur is not None:
            offsets[cur] = [float(v) for v in s.split()[1:4]]
        elif s.startswith("CHANNELS") and cur is not None:
            chans[cur] = s.split()[2:]
        elif s == "{":
            stack.append(cur)
        elif s == "}":
            if stack:
                stack.pop()
        elif s.startswith("MOTION"):
            break
        i += 1
    nfr = int(lines[i + 1].split()[1])
    ft = float(lines[i + 2].split()[-1])
    data = np.array([[float(v) for v in ln.split()] for ln in lines[i + 3:i + 3 + nfr]])
    return {"joints": joints, "parents": np.array(parents), "offsets": np.array(offsets), "chans": chans,
            "data": data, "fps": 1.0 / ft}


def _rot(axis, ang):
    c, s = np.cos(ang), np.sin(ang)
    R = np.zeros((len(ang), 3, 3))
    a, b = {"X": (1, 2), "Y": (2, 0), "Z": (0, 1)}[axis]
    k = 3 - a - b
    R[:, k, k] = 1
    R[:, a, a] = c; R[:, a, b] = -s; R[:, b, a] = s; R[:, b, b] = c
    return R


def fk(b):
    """Global rotations (F,J,3,3) and positions (F,J,3); position channels replace the offset."""
    J, F = len(b["joints"]), len(b["data"])
    Rg, Pg = np.zeros((F, J, 3, 3)), np.zeros((F, J, 3))
    col = 0
    for j in range(J):
        R = np.tile(np.eye(3), (F, 1, 1))
        T = np.tile(b["offsets"][j], (F, 1)).astype(float)
        pos, haspos = np.zeros((F, 3)), False
        for c in b["chans"][j]:
            v = b["data"][:, col]; col += 1
            if c.endswith("position"):
                pos[:, "XYZ".index(c[0])] = v; haspos = True
            else:
                R = R @ _rot(c[0], np.radians(v))
        if haspos:
            T = pos
        p = b["parents"][j]
        if p < 0:
            Rg[:, j], Pg[:, j] = R, T
        else:
            Rg[:, j] = Rg[:, p] @ R
            Pg[:, j] = Pg[:, p] + np.einsum("fij,fj->fi", Rg[:, p], T)
    return Rg, Pg


def rest_positions(b):
    J = len(b["joints"])
    P = np.zeros((J, 3))
    for j in range(J):
        p = b["parents"][j]
        P[j] = b["offsets"][j] + (P[p] if p >= 0 else 0)
    return P


# ------------------------------------------------------------------ rotation helpers
def swing(a, b):
    """Minimal rotation matrices taking unit vectors a -> b (both (...,3))."""
    a = a / np.linalg.norm(a, axis=-1, keepdims=True)
    b = b / np.linalg.norm(b, axis=-1, keepdims=True)
    v = np.cross(a, b)
    c = np.sum(a * b, axis=-1)
    s = np.linalg.norm(v, axis=-1)
    K = np.zeros(v.shape[:-1] + (3, 3))
    K[..., 0, 1], K[..., 0, 2] = -v[..., 2], v[..., 1]
    K[..., 1, 0], K[..., 1, 2] = v[..., 2], -v[..., 0]
    K[..., 2, 0], K[..., 2, 1] = -v[..., 1], v[..., 0]
    I = np.broadcast_to(np.eye(3), K.shape)
    f = np.where(s > 1e-8, (1 - c) / np.maximum(s * s, 1e-16), 0.5)[..., None, None]
    R = I + K + K @ K * f
    # antiparallel: rotate 180 deg about any perpendicular axis
    bad = c < -0.9999
    if np.any(bad):
        ab = a[bad]
        perp = np.cross(ab, np.array([1.0, 0, 0]))
        small = np.linalg.norm(perp, axis=-1) < 1e-3
        perp[small] = np.cross(ab[small], np.array([0, 1.0, 0]))
        perp /= np.linalg.norm(perp, axis=-1, keepdims=True)
        R[bad] = 2 * perp[..., :, None] * perp[..., None, :] - np.eye(3)
    return R


def mat2quat(R):
    """(...,3,3) -> (...,4) w,x,y,z (w >= 0)."""
    m = R
    t = m[..., 0, 0] + m[..., 1, 1] + m[..., 2, 2]
    q = np.zeros(R.shape[:-2] + (4,))
    c0 = t > 0
    s = np.sqrt(np.maximum(t + 1.0, 1e-12)) * 2
    q[..., 0] = np.where(c0, 0.25 * s, 0)
    q[..., 1] = np.where(c0, (m[..., 2, 1] - m[..., 1, 2]) / s, 0)
    q[..., 2] = np.where(c0, (m[..., 0, 2] - m[..., 2, 0]) / s, 0)
    q[..., 3] = np.where(c0, (m[..., 1, 0] - m[..., 0, 1]) / s, 0)
    for i in range(3):
        j, k = (i + 1) % 3, (i + 2) % 3
        ci = (~c0) & (m[..., i, i] >= m[..., j, j]) & (m[..., i, i] >= m[..., k, k])
        if not np.any(ci):
            continue
        s2 = np.sqrt(np.maximum(1.0 + m[..., i, i] - m[..., j, j] - m[..., k, k], 1e-12)) * 2
        qw = (m[..., k, j] - m[..., j, k]) / s2
        qi = 0.25 * s2
        qj = (m[..., j, i] + m[..., i, j]) / s2
        qk = (m[..., k, i] + m[..., i, k]) / s2
        q[..., 0] = np.where(ci, qw, q[..., 0])
        q[..., 1 + i] = np.where(ci, qi, q[..., 1 + i])
        q[..., 1 + j] = np.where(ci, qj, q[..., 1 + j])
        q[..., 1 + k] = np.where(ci, qk, q[..., 1 + k])
        c0 = c0 | ci
    q /= np.linalg.norm(q, axis=-1, keepdims=True)
    return q


def quat2mat(q):
    w, x, y, z = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    R = np.zeros(q.shape[:-1] + (3, 3))
    R[..., 0, 0] = 1 - 2 * (y * y + z * z); R[..., 0, 1] = 2 * (x * y - w * z); R[..., 0, 2] = 2 * (x * z + w * y)
    R[..., 1, 0] = 2 * (x * y + w * z); R[..., 1, 1] = 1 - 2 * (x * x + z * z); R[..., 1, 2] = 2 * (y * z - w * x)
    R[..., 2, 0] = 2 * (x * z - w * y); R[..., 2, 1] = 2 * (y * z + w * x); R[..., 2, 2] = 1 - 2 * (x * x + y * y)
    return R


def slerp(q0, q1, t):
    d = np.sum(q0 * q1, axis=-1, keepdims=True)
    q1 = np.where(d < 0, -q1, q1)
    d = np.abs(d)
    th = np.arccos(np.clip(d, -1, 1))
    s = np.sin(th)
    w0 = np.where(s > 1e-6, np.sin((1 - t) * th) / np.maximum(s, 1e-12), 1 - t)
    w1 = np.where(s > 1e-6, np.sin(t * th) / np.maximum(s, 1e-12), t)
    q = w0 * q0 + w1 * q1
    return q / np.linalg.norm(q, axis=-1, keepdims=True)


def continuity(q):
    """Flip quaternion signs along the time axis (axis 0) for continuity."""
    q = q.copy()
    for f in range(1, len(q)):
        d = np.sum(q[f] * q[f - 1], axis=-1)
        q[f][d < 0] *= -1
    return q


# ------------------------------------------------------------------ retarget
def rig_from_json(rj):
    names = list(rj["bones"].keys())
    order, seen = [], set()
    while len(order) < len(names):
        for n in names:
            p = rj["bones"][n]["parent"]
            if n not in seen and (p is None or p in seen):
                order.append(n); seen.add(n)
    B = {}
    for n in order:
        d = rj["bones"][n]
        M = np.array(d["M"])
        B[n] = {"parent": d["parent"], "R": M[:3, :3], "head": np.array(d["head"]), "tail": np.array(d["tail"])}
    return order, B


def heading_fix(Rg_hips0):
    fwd = C @ Rg_hips0 @ np.array([0, 0, 1.0])
    ang = np.arctan2(fwd[0], -fwd[1])          # angle from -Y towards +X
    c, s = np.cos(-ang), np.sin(-ang)
    # rotation about Z by -ang maps fwd onto -Y
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]]), float(np.degrees(ang))


def retarget(b, rig_order, rig, loop=False, inplace=None):
    """Returns per-frame basis quaternions (F, nb, 4), hips local location (F, 3), info."""
    J = {n: i for i, n in enumerate(b["joints"])}
    Rg, Pg = fk(b)
    F = len(Rg)
    Prest = rest_positions(b)
    H, head_deg = heading_fix(Rg[0, J["Hips"]])
    HC = H @ C
    pose = {}
    for n in rig_order:
        rj, a, e = MAP[n]
        bone = rig[n]
        d_t = bone["tail"] - bone["head"]; d_t /= np.linalg.norm(d_t)
        d_s = C @ (Prest[J[e]] - Prest[J[a]]); d_s /= np.linalg.norm(d_s)
        Ralign = swing(d_t[None], d_s[None])[0]
        D = np.einsum("ij,fjk,kl->fil", HC, Rg[:, J[rj]], C.T)           # source delta in target frame
        Bp = D @ (Ralign @ bone["R"])
        cur = Bp[:, :, 1]
        des = np.einsum("ij,fj->fi", HC, Pg[:, J[e]] - Pg[:, J[a]])
        Bp = swing(cur, des) @ Bp
        pose[n] = Bp
    basis = np.zeros((F, len(rig_order), 4))
    for k, n in enumerate(rig_order):
        bone = rig[n]
        p = bone["parent"]
        if p is None:
            Rb = bone["R"].T @ pose[n]
        else:
            Rb = bone["R"].T @ rig[p]["R"] @ np.transpose(pose[p], (0, 2, 1)) @ pose[n]
        basis[:, k] = mat2quat(Rb)
    basis = continuity(basis)
    # ---- root translation
    leg_t = np.linalg.norm(rig["thigh.L"]["tail"] - rig["thigh.L"]["head"]) + np.linalg.norm(rig["shin.L"]["tail"] - rig["shin.L"]["head"])
    leg_s = 0.01 * (np.linalg.norm(Prest[J["LeftShin"]] - Prest[J["LeftLeg"]]) + np.linalg.norm(Prest[J["LeftFoot"]] - Prest[J["LeftShin"]]))
    k = leg_t / leg_s
    S = 0.01 * np.einsum("ij,fj->fi", HC, Pg[:, J["Hips"]])
    hs = 0.01 * Prest[J["Hips"]][1]
    T = np.tile(rig["hips"]["head"], (F, 1)).astype(float)
    T[:, 2] += k * (S[:, 2] - hs)
    T[:, :2] += k * (S[:, :2] - S[0, :2])
    info = {"frames": F, "fps": b["fps"], "heading_fix_deg": round(head_deg, 1), "scale_k": round(float(k), 4)}
    return basis, T, pose, info


def target_fk(rig_order, rig, basis, T):
    """Evaluate the target armature: armature-space heads/tails (F, nb, 3) for checking."""
    F = len(basis)
    Rpose, heads, tails = {}, {}, {}
    for k, n in enumerate(rig_order):
        bone = rig[n]; p = bone["parent"]
        Rb = quat2mat(basis[:, k])
        if p is None:
            Rp = bone["R"] @ Rb
            h = T
        else:
            Rrel = rig[p]["R"].T @ bone["R"]
            Rp = Rpose[p] @ Rrel @ Rb
            off = rig[p]["R"].T @ (bone["head"] - rig[p]["head"])        # head offset in parent's rest frame
            h = heads[p] + np.einsum("fij,j->fi", Rpose[p], off)
        L = np.linalg.norm(bone["tail"] - bone["head"])
        Rpose[n] = Rp
        heads[n] = h
        tails[n] = h + Rp[:, :, 1] * L
    return heads, tails, Rpose


def ground_fix(rig_order, rig, basis, T, ref_frames=(0,)):
    """Shift the root vertically so the lowest foot point touches z=0 on the reference frames."""
    heads, tails, _ = target_fk(rig_order, rig, basis, T)
    pts = [heads["foot.L"][:, 2], heads["foot.R"][:, 2], tails["toe.L"][:, 2], tails["toe.R"][:, 2]]
    low = np.min(np.stack(pts), axis=0)
    ankle_h = min(rig["foot.L"]["head"][2], rig["foot.R"]["head"][2])
    toe_h = min(rig["toe.L"]["tail"][2], rig["toe.R"]["tail"][2])
    rest_low = min(ankle_h, toe_h)                     # in rest the lowest of these sits rest_low above ground
    dz = rest_low - np.mean(low[list(ref_frames)])
    T = T.copy(); T[:, 2] += dz
    return T, float(dz)


def make_loop(basis, T, min_len, max_len=None, blend=8, w_vel=0.5):
    """Find frames i<j (j-i in [min_len, max_len]) with the most similar pose+velocity; return the cycle
    [i, j) with the last `blend` frames eased into the frames preceding i (seamless wrap)."""
    F = len(basis)
    max_len = max_len or F
    q = basis.reshape(F, -1)
    v = np.vstack([q[1:] - q[:-1], q[-1:] - q[-2:-1]])
    best = None
    for i in range(blend, F):
        for j in range(i + min_len, min(F, i + max_len + 1)):
            d = np.linalg.norm(q[i] - q[j]) + w_vel * np.linalg.norm(v[i] - v[j]) * 10
            if best is None or d < best[0]:
                best = (d, i, j)
    _, i, j = best
    L = j - i
    out = basis[i:j].copy()
    Tout = T[i:j].copy()
    for t in range(L - blend, L):
        w = (t - (L - blend) + 1) / blend
        w = w * w * (3 - 2 * w)
        src = i - L + t
        out[t] = slerp(basis[i + t], basis[src], w)
        Tout[t] = T[i + t] * (1 - w) + T[src] * w
    return continuity(out), Tout, {"loop_start": int(i), "loop_end": int(j), "len": int(L), "pose_dist": round(float(best[0]), 4)}


def inplace_xy(T, mode, rest_xy):
    """loop: remove the linear XY trend (so the cycle closes); oneshot: keep XY relative to frame 0."""
    T = T.copy()
    n = len(T)
    t = np.arange(n)
    if mode == "loop":
        for a in (0, 1):
            p = np.polyfit(t, T[:, a], 1)
            T[:, a] = T[:, a] - np.polyval(p, t) + rest_xy[a]
    return T


def _smooth_max(L, win=5, sigma=2.0):
    n = len(L)
    r = win // 2
    Lp = np.pad(L, r, mode="edge")
    M = np.array([Lp[i:i + win].max() for i in range(n)])
    k = np.exp(-0.5 * (np.arange(-3 * int(sigma), 3 * int(sigma) + 1) / sigma) ** 2)
    k /= k.sum()
    Mp = np.pad(M, len(k) // 2, mode="edge")
    return np.convolve(Mp, k, mode="valid")[:n]


def ground_clamp(rig_order, rig, basis, T, body_clear=0.10):
    """Lift the root on frames where feet would sink below their rest height or the torso/head would go
    through the floor (lying poses); smoothed so it never pops."""
    heads, tails, _ = target_fk(rig_order, rig, basis, T)
    foot_rest = min(rig["foot.L"]["head"][2], rig["toe.L"]["tail"][2], rig["foot.R"]["head"][2], rig["toe.R"]["tail"][2])
    need = [foot_rest - heads["foot.L"][:, 2], foot_rest - heads["foot.R"][:, 2],
            foot_rest - tails["toe.L"][:, 2], foot_rest - tails["toe.R"][:, 2]]
    for n in ("hips", "spine", "chest", "neck", "head"):
        need += [body_clear - heads[n][:, 2], body_clear - tails[n][:, 2]]
    for n in ("hand.L", "hand.R", "forearm.L", "forearm.R", "shin.L", "shin.R"):
        need += [0.03 - tails[n][:, 2]]
    L = np.maximum(0.0, np.max(np.stack(need), axis=0))
    Ls = _smooth_max(L)
    T = T.copy(); T[:, 2] += Ls
    return T, float(L.max())


CLIP_KIND = {"idle": "loop", "run": "loop", "jump": "jump", "dodge": "oneshot", "hit": "oneshot", "death": "oneshot"}
LOOP_LEN = {"idle": (70, 110), "run": (18, 60)}


def process_clip(bvh_text, rig_order, rig, clip):
    """Full pipeline for one clip on one rig -> (basis (F,nb,4), T (F,3) hips head in armature space, info)."""
    kind = CLIP_KIND.get(clip, "oneshot")
    b = parse_bvh(bvh_text)
    basis, T, pose, info = retarget(b, rig_order, rig)
    T, dz = ground_fix(rig_order, rig, basis, T)
    raw = T.copy()
    rest = rig["hips"]["head"]
    if kind == "loop":
        T = inplace_xy(T, "loop", rest[:2])
    else:
        T[:, :2] = rest[:2]
    if kind == "jump":
        stand = np.median(T[:6, 2])
        T[:, 2] = np.minimum(T[:, 2], stand)              # physics drives the airborne height
    T, lift = ground_clamp(rig_order, rig, basis, T)
    info.update({"kind": kind, "ground_dz": round(dz, 4), "max_lift": round(lift, 4),
                 "root_disp_xy": [round(float(v), 3) for v in (raw[-1, :2] - raw[0, :2])],
                 "duration_s": round(len(basis) / b["fps"], 3)})
    if kind == "jump":
        air = raw[:, 2] - np.median(raw[:6, 2])
        info["airborne_peak_m"] = round(float(air.max()), 3)
    if kind == "loop":
        lo, hi = LOOP_LEN[clip]
        basis, T, li = make_loop(basis, T, lo, hi, blend=6)
        info.update(li)
        info["duration_s"] = round(len(basis) / b["fps"], 3)
        if clip == "run":
            d = raw[li["loop_end"], :2] - raw[li["loop_start"], :2]
            info["run_speed_mps"] = round(float(np.linalg.norm(d) / (li["len"] / b["fps"])), 3)
    return basis, T, info
