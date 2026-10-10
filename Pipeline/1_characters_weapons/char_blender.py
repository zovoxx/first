"""Game-ready processing of Pixal3D character GLBs in Blender.

Stages (each called separately so no single call runs too long):
  load(glb, height)            -> import, join, orient (Z up, facing -Y), scale, feet at z=0
  landmarks(overrides)         -> find joint positions from the mesh
  build_rig()                  -> humanoid armature
  skin()                       -> voxel proxy + bone-heat weights, transferred to the real mesh
  make_mobile(tris, tex)       -> decimated copy with smaller textures
  export(outdir, name)         -> PC + mobile GLB, .blend
  preview(path, pose=False)    -> Eevee render for checking
"""
import bpy, bmesh, os, math, json
import numpy as np
from mathutils import Vector, Matrix
from mathutils.kdtree import KDTree

STATE = {}


# ---------------------------------------------------------------- helpers
def _ctx():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == "VIEW_3D":
            region = next(r for r in area.regions if r.type == "WINDOW")
            return dict(window=win, area=area, region=region, screen=win.screen)
    return dict(window=win, screen=win.screen)


def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for _ in range(3):
        for coll in (bpy.data.meshes, bpy.data.armatures, bpy.data.materials,
                     bpy.data.images, bpy.data.node_groups, bpy.data.actions,
                     bpy.data.cameras, bpy.data.lights, bpy.data.worlds):
            for b in list(coll):
                if b.users == 0:
                    coll.remove(b)
    STATE.clear()


def _verts(obj):
    me = obj.data
    co = np.empty(len(me.vertices) * 3, dtype=np.float64)
    me.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


def _surface_samples(obj, n=250000, seed=0):
    me = obj.data
    me.calc_loop_triangles()
    co = _verts(obj)
    tri = np.empty(len(me.loop_triangles) * 3, dtype=np.int64)
    me.loop_triangles.foreach_get("vertices", tri)
    tri = tri.reshape(-1, 3)
    a, b, c = co[tri[:, 0]], co[tri[:, 1]], co[tri[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(tri), size=n, p=area / area.sum())
    r1, r2 = rng.random(n), rng.random(n)
    s = np.sqrt(r1)
    return (1 - s)[:, None] * a[idx] + (s * (1 - r2))[:, None] * b[idx] + (s * r2)[:, None] * c[idx]


def _intervals(xs, gap):
    if len(xs) == 0:
        return []
    xs = np.sort(xs)
    cut = np.where(np.diff(xs) > gap)[0]
    starts = np.concatenate([[xs[0]], xs[cut + 1]])
    ends = np.concatenate([xs[cut], [xs[-1]]])
    return [(float(s), float(e)) for s, e in zip(starts, ends)]


# ---------------------------------------------------------------- stage 1
def load(glb, height, flip=False):
    clear_scene()
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb)
    new = [o for o in bpy.data.objects if o not in before]
    for o in new:
        if o.parent:
            mw = o.matrix_world.copy()
            o.parent = None
            o.matrix_world = mw
    meshes = [o for o in new if o.type == "MESH"]
    for o in new:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    for o in meshes:
        o.data.transform(o.matrix_world)
        o.matrix_world = Matrix.Identity(4)
    obj = meshes[0]
    if len(meshes) > 1:
        with bpy.context.temp_override(**_ctx(), active_object=obj, selected_editable_objects=meshes,
                                       selected_objects=meshes):
            bpy.ops.object.join()
    obj.name = "Body"
    obj.data.name = "Body"

    # merge seam-split vertices so weights/decimation see one connected surface
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6 * max(obj.dimensions))
    bm.to_mesh(obj.data)
    bm.free()

    co = _verts(obj)
    ext = co.max(0) - co.min(0)
    # up axis = largest extent among y/z after glTF import should be Z; guard anyway
    if ext[1] > ext[2] * 1.15 and ext[1] > ext[0]:
        obj.data.transform(Matrix.Rotation(math.radians(90), 4, "X"))
        co = _verts(obj)
    zmin, zmax = co[:, 2].min(), co[:, 2].max()
    H0 = zmax - zmin
    mid = co[(co[:, 2] > zmin + 0.45 * H0) & (co[:, 2] < zmin + 0.75 * H0)]
    # A-pose: lateral (arm) axis is the wide one -> make it X
    if np.ptp(mid[:, 1]) > np.ptp(mid[:, 0]):
        obj.data.transform(Matrix.Rotation(math.radians(90), 4, "Z"))
        co = _verts(obj)
    s = height / H0
    obj.data.transform(Matrix.Scale(s, 4))
    co = _verts(obj)
    torso = co[(co[:, 2] > co[:, 2].min() + 0.45 * height) & (co[:, 2] < co[:, 2].min() + 0.6 * height)]
    # center between the feet: wide armor, props and arms make the torso band unreliable
    feet = co[co[:, 2] < co[:, 2].min() + 0.08 * height]
    cx = float((feet[:, 0].min() + feet[:, 0].max()) / 2)
    tmask = np.abs(torso[:, 0] - cx) < 0.12 * height
    cy = float(np.median(torso[tmask, 1])) if tmask.sum() > 50 else float(np.median(torso[:, 1]))
    obj.data.transform(Matrix.Translation((-cx, -cy, -co[:, 2].min())))
    co = _verts(obj)
    # Pixal3D output faces +Y after glTF import; game convention here is facing -Y (Blender front view)
    if flip:
        obj.data.transform(Matrix.Rotation(math.pi, 4, "Z"))
    obj.data.update()
    STATE.update(obj=obj.name, H=height)
    co = _verts(obj)
    return {"verts": len(obj.data.vertices), "tris": sum(len(p.vertices) - 2 for p in obj.data.polygons),
            "dims": [round(v, 3) for v in obj.dimensions], "materials": [m.name for m in obj.data.materials],
            "images": [(i.name, list(i.size)) for i in bpy.data.images]}


# ---------------------------------------------------------------- stage 2
def landmarks(overrides=None):
    obj = bpy.data.objects[STATE["obj"]]
    H = STATE["H"]
    P = _surface_samples(obj)
    STATE["_P"] = P
    gap = 0.012 * H
    step = 0.01 * H
    rows = []
    for z in np.arange(0.005 * H, H, step):
        sl = P[(P[:, 2] >= z) & (P[:, 2] < z + step)]
        rows.append((z + step / 2, _intervals(sl[:, 0], gap)))

    xmax, xmin = P[:, 0].max(), P[:, 0].min()

    # crotch: scanning up from the feet, last height with two central leg intervals
    crotch = None
    for z, iv in rows:
        if z > 0.65 * H:
            break
        central = [i for i in iv if i[1] > -0.25 * H and i[0] < 0.25 * H]
        if len(central) >= 2 and any(i[1] < 0 for i in central) and any(i[0] > 0 for i in central):
            crotch = z
        elif crotch is not None and z > crotch + 0.04 * H:
            break
    crotch = crotch if crotch is not None else 0.45 * H
    crotch = float(np.clip(crotch, 0.25 * H, 0.55 * H))

    # armpit: highest height where an arm interval is separate from the torso on both sides
    armpit = None
    for z, iv in rows:
        if z < crotch:
            continue
        if len(iv) >= 3:
            torso_iv = min(iv, key=lambda i: abs((i[0] + i[1]) / 2))
            left = [i for i in iv if i[0] > torso_iv[1]]
            right = [i for i in iv if i[1] < torso_iv[0]]
            if left and right:
                armpit = z
    armpit = armpit if armpit is not None else 0.72 * H
    sl = P[np.abs(P[:, 2] - (armpit - 0.02 * H)) < step]
    iv = _intervals(sl[:, 0], gap)
    torso_iv = min(iv, key=lambda i: abs((i[0] + i[1]) / 2)) if iv else (-0.12 * H, 0.12 * H)
    half = min(abs(torso_iv[0]), abs(torso_iv[1]))

    def centroid_y(x, z, r):
        m = (np.abs(P[:, 0] - x) < r) & (np.abs(P[:, 2] - z) < r)
        return float(np.median(P[m, 1])) if m.sum() > 20 else 0.0

    def spine_y(z):
        m = (np.abs(P[:, 2] - z) < step) & (np.abs(P[:, 0]) < half * 0.6)
        return float(np.median(P[m, 1])) if m.sum() > 20 else 0.0

    # head base: narrowest slice between shoulders and top
    sh_z = armpit + 0.045 * H
    best, head_base = 1e9, H * 0.84
    for z, iv2 in rows:
        if sh_z + 0.025 * H < z < min(0.9 * H, sh_z + 0.13 * H):
            c = min(iv2, key=lambda i: abs((i[0] + i[1]) / 2)) if iv2 else None
            if c and (c[1] - c[0]) < best:
                best, head_base = c[1] - c[0], z
    neck_base = sh_z + 0.02 * H
    head_base = max(head_base, neck_base + 0.03 * H)

    L = {}
    # baggy pants / coats merge the legs low down, so never put the hips far below the armpits
    hip_z = float(np.clip(max(crotch + 0.035 * H, armpit - 0.23 * H), 0.28 * H, 0.58 * H))
    L["hips"] = (0, spine_y(hip_z), hip_z)
    L["spine"] = (0, spine_y(hip_z + 0.1 * H), hip_z + 0.1 * H)
    chest_z = (hip_z + 0.1 * H + armpit) / 2
    L["chest"] = (0, spine_y(chest_z), chest_z)
    L["neck"] = (0, spine_y(neck_base), neck_base)
    L["head"] = (0, spine_y(head_base), head_base)
    L["head_top"] = (0, spine_y(head_base), H)

    for side, sgn in (("L", 1), ("R", -1)):
        tipm = P[:, 0] * sgn > 0.95 * (xmax if sgn > 0 else -xmin)
        tip = P[tipm].mean(0)
        sh = np.array([sgn * half * 0.85, 0, sh_z])
        sh[1] = centroid_y(sh[0], sh[2], 0.04 * H)
        d = tip - sh
        hand_len = 0.09 * H
        wrist = tip - d / np.linalg.norm(d) * hand_len
        wrist[1] = centroid_y(wrist[0], wrist[2], 0.03 * H)
        elbow = (sh + wrist) / 2
        elbow[1] = centroid_y(elbow[0], elbow[2], 0.03 * H) + 0.015 * H
        L[f"clav.{side}"] = (sgn * 0.035 * H, spine_y(sh_z), sh_z)
        L[f"shoulder.{side}"] = tuple(sh)
        L[f"elbow.{side}"] = tuple(elbow)
        L[f"wrist.{side}"] = tuple(wrist)
        L[f"hand_tip.{side}"] = tuple(tip)

        below = P[np.abs(P[:, 2] - (crotch - 0.06 * H)) < step]
        legs = [i for i in _intervals(below[:, 0], gap) if (i[0] + i[1]) / 2 * sgn > 0]
        lx = (sum(legs[0]) / 2) if legs else sgn * 0.08 * H
        hip = np.array([lx, 0, hip_z - 0.01 * H])
        hip[1] = centroid_y(hip[0], hip[2], 0.05 * H)
        foot_pts = P[(P[:, 2] < 0.035 * H) & (P[:, 0] * sgn > 0)]
        ank_pts = P[(np.abs(P[:, 2] - 0.065 * H) < step) & (P[:, 0] * sgn > 0)]
        ankle = np.array([np.median(ank_pts[:, 0]), np.median(ank_pts[:, 1]), 0.065 * H]) if len(ank_pts) > 20 \
            else np.array([lx, 0, 0.065 * H])
        toe = foot_pts[np.argmin(foot_pts[:, 1])] if len(foot_pts) else ankle + np.array([0, -0.1 * H, -0.05 * H])
        toe = np.array([ankle[0] * 0.5 + toe[0] * 0.5, toe[1], 0.02 * H])
        ball = ankle + (toe - ankle) * 0.65
        ball[2] = 0.02 * H
        knee = (hip + ankle) / 2
        knee[1] = centroid_y(knee[0], knee[2], 0.03 * H) - 0.01 * H
        L[f"hip.{side}"] = tuple(hip)
        L[f"knee.{side}"] = tuple(knee)
        L[f"ankle.{side}"] = tuple(ankle)
        L[f"ball.{side}"] = tuple(ball)
        L[f"toe.{side}"] = tuple(toe)

    if overrides:
        ov = dict(overrides)
        for k in list(ov):
            if k.endswith(".L") and k[:-2] + ".R" not in ov:
                v = ov[k]
                ov[k[:-2] + ".R"] = (-v[0],) + tuple(v[1:])
        for k, v in ov.items():
            if len(v) == 2:  # (x, z): find y inside the body
                x, z = float(v[0]), float(v[1])
                y = spine_y(z) if abs(x) < 1e-6 else centroid_y(x, z, 0.04 * H)
                L[k] = (x, y, z)
            else:
                L[k] = tuple(v)
    L = {k: tuple(round(float(x), 4) for x in v) for k, v in L.items()}
    STATE["L"] = L
    return {"crotch": round(crotch / H, 3), "armpit": round(armpit / H, 3), "head_base": round(head_base / H, 3),
            "L": L}


# ---------------------------------------------------------------- stage 3
BONES = [
    # name, head, tail, parent, connected
    ("hips", "hips", "spine", None, False),
    ("spine", "spine", "chest", "hips", True),
    ("chest", "chest", "neck", "spine", True),
    ("neck", "neck", "head", "chest", True),
    ("head", "head", "head_top", "neck", True),
]
for s in ("L", "R"):
    BONES += [
        (f"shoulder.{s}", f"clav.{s}", f"shoulder.{s}", "chest", False),
        (f"upper_arm.{s}", f"shoulder.{s}", f"elbow.{s}", f"shoulder.{s}", True),
        (f"forearm.{s}", f"elbow.{s}", f"wrist.{s}", f"upper_arm.{s}", True),
        (f"hand.{s}", f"wrist.{s}", f"hand_tip.{s}", f"forearm.{s}", True),
        (f"thigh.{s}", f"hip.{s}", f"knee.{s}", "hips", False),
        (f"shin.{s}", f"knee.{s}", f"ankle.{s}", f"thigh.{s}", True),
        (f"foot.{s}", f"ankle.{s}", f"ball.{s}", f"shin.{s}", True),
        (f"toe.{s}", f"ball.{s}", f"toe.{s}", f"foot.{s}", True),
    ]


def build_rig(name="Rig"):
    L = STATE["L"]
    for o in list(bpy.data.objects):
        if o.type == "ARMATURE":
            bpy.data.objects.remove(o, do_unlink=True)
    arm = bpy.data.armatures.new(name)
    rig = bpy.data.objects.new(name, arm)
    bpy.context.scene.collection.objects.link(rig)
    arm.display_type = "STICK"
    rig.show_in_front = True
    bpy.context.view_layer.objects.active = rig
    with bpy.context.temp_override(**_ctx(), active_object=rig, object=rig):
        bpy.ops.object.mode_set(mode="EDIT")
        eb = arm.edit_bones
        for bname, h, t, parent, conn in BONES:
            b = eb.new(bname)
            b.head = Vector(L[h])
            b.tail = Vector(L[t])
            if (b.tail - b.head).length < 1e-3:
                b.tail = b.head + Vector((0, 0, 0.02))
        for bname, h, t, parent, conn in BONES:
            if parent:
                eb[bname].parent = eb[parent]
                eb[bname].use_connect = conn
        for b in eb:
            b.roll = 0.0
        # knees/elbows: roll so local X is the bend axis (consistent across sides)
        bpy.ops.armature.select_all(action="SELECT")
        bpy.ops.armature.calculate_roll(type="GLOBAL_NEG_Y")
        bpy.ops.object.mode_set(mode="OBJECT")
    STATE["rig"] = rig.name
    return {"bones": len(arm.bones)}


# ---------------------------------------------------------------- stage 4
def skin(voxel_frac=1 / 170, max_influences=4):
    obj = bpy.data.objects[STATE["obj"]]
    rig = bpy.data.objects[STATE["rig"]]
    H = STATE["H"]
    for vg in list(obj.vertex_groups):
        obj.vertex_groups.remove(vg)
    for m in list(obj.modifiers):
        obj.modifiers.remove(m)

    # watertight proxy (AI meshes have holes/internal faces that break bone heat)
    tmp = obj.copy()
    tmp.data = obj.data.copy()
    bpy.context.scene.collection.objects.link(tmp)
    rm = tmp.modifiers.new("vox", "REMESH")
    rm.mode = "VOXEL"
    rm.voxel_size = H * voxel_frac
    dg = bpy.context.evaluated_depsgraph_get()
    pmesh = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bpy.data.objects.remove(tmp, do_unlink=True)
    proxy = bpy.data.objects.new("SkinProxy", pmesh)
    bpy.context.scene.collection.objects.link(proxy)
    # keep proxy light for bone heat
    if len(pmesh.vertices) > 60000:
        dec = proxy.modifiers.new("dec", "DECIMATE")
        dec.ratio = 60000 / len(pmesh.vertices)
        dg = bpy.context.evaluated_depsgraph_get()
        m2 = bpy.data.meshes.new_from_object(proxy.evaluated_get(dg))
        proxy.modifiers.remove(dec)
        old = proxy.data
        proxy.data = m2
        bpy.data.meshes.remove(old)

    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    proxy.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    with bpy.context.temp_override(**_ctx(), active_object=rig, object=rig,
                                   selected_objects=[proxy, rig], selected_editable_objects=[proxy, rig]):
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")

    names = [b.name for b in rig.data.bones]
    gi = {g.index: names.index(g.name) for g in proxy.vertex_groups if g.name in names}
    nP = len(proxy.data.vertices)
    W = np.zeros((nP, len(names)), dtype=np.float32)
    for v in proxy.data.vertices:
        for g in v.groups:
            if g.group in gi:
                W[v.index, gi[g.group]] = g.weight
    unweighted_proxy = int((W.sum(1) < 1e-6).sum())

    kd = KDTree(nP)
    for v in proxy.data.vertices:
        kd.insert(v.co, v.index)
    kd.balance()
    co = _verts(obj)
    out = np.zeros((len(co), len(names)), dtype=np.float32)
    for i, c in enumerate(co):
        hits = kd.find_n(Vector(c), 4)
        acc = np.zeros(len(names), dtype=np.float32)
        tot = 0.0
        for _, idx, dist in hits:
            w = 1.0 / (dist + 1e-5)
            acc += W[idx] * w
            tot += w
        out[i] = acc / tot
    # fallback: anything without weights goes to the nearest bone
    heads = np.array([list(rig.data.bones[n].head_local) for n in names])
    tails = np.array([list(rig.data.bones[n].tail_local) for n in names])
    empty = np.where(out.sum(1) < 1e-4)[0]
    for i in empty:
        p = co[i]
        ab = tails - heads
        t = np.clip(((p - heads) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-9), 0, 1)
        d = np.linalg.norm(heads + ab * t[:, None] - p, axis=1)
        out[i, np.argmin(d)] = 1.0
    # limit to N influences and normalize (game engines expect <=4)
    if max_influences:
        drop = np.argsort(out, axis=1)[:, :-max_influences]
        np.put_along_axis(out, drop, 0.0, axis=1)
    out /= np.maximum(out.sum(1, keepdims=True), 1e-9)

    vgs = [obj.vertex_groups.new(name=n) for n in names]
    for j, vg in enumerate(vgs):
        idx = np.where(out[:, j] > 1e-3)[0]
        for i in idx:
            vg.add([int(i)], float(out[i, j]), "REPLACE")
    obj.parent = rig
    obj.matrix_parent_inverse = rig.matrix_world.inverted()
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = rig
    pm = proxy.data
    bpy.data.objects.remove(proxy, do_unlink=True)
    if pm.users == 0:
        bpy.data.meshes.remove(pm)
    return {"proxy_verts": nP, "proxy_unweighted": unweighted_proxy, "fallback_verts": int(len(empty)),
            "groups": len(vgs)}


# ---------------------------------------------------------------- stage 5
def _scaled_material_copy(mat, max_px, suffix):
    m2 = mat.copy()
    m2.name = mat.name + suffix
    if m2.node_tree:
        for n in m2.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image and max(n.image.size) > max_px:
                img = n.image.copy()
                img.name = n.image.name + suffix
                w, h = n.image.size
                s = max_px / max(w, h)
                img.scale(int(w * s), int(h * s))
                img.pack()
                n.image = img
    return m2


def _limit_weights(obj, max_infl=4, skip=("_keep",)):
    """Keep the strongest N bone influences per vertex and renormalize (engines expect <= 4)."""
    names = {g.index: g.name for g in obj.vertex_groups}
    groups = {g.name: g for g in obj.vertex_groups}
    for v in obj.data.vertices:
        ws = [(g.group, g.weight) for g in v.groups if names.get(g.group) not in skip and g.weight > 1e-5]
        if not ws:
            continue
        ws.sort(key=lambda t: -t[1])
        keep, drop = ws[:max_infl], ws[max_infl:]
        tot = sum(w for _, w in keep)
        for gi, _ in drop:
            groups[names[gi]].remove([v.index])
        for gi, w in keep:
            groups[names[gi]].add([v.index], w / tot, "REPLACE")


def make_mobile(target_tris=15000, max_tex=2048, protect=True):
    obj = bpy.data.objects[STATE["obj"]]
    rig = bpy.data.objects[STATE["rig"]]
    H = STATE["H"]
    for o in list(bpy.data.objects):
        if o.name.startswith("Body_mobile"):
            bpy.data.objects.remove(o, do_unlink=True)
    dup = obj.copy()
    dup.data = obj.data.copy()
    dup.name = "Body_mobile"
    bpy.context.scene.collection.objects.link(dup)
    tris = sum(len(p.vertices) - 2 for p in dup.data.polygons)
    for m in dup.modifiers:
        m.show_viewport = False
    dec = dup.modifiers.new("dec", "DECIMATE")
    dup.modifiers.move(len(dup.modifiers) - 1, 0)
    keep = None
    if protect:
        # soles and the top of the head (crowns, antlers, spikes) are thin and get eaten by collapse:
        # weight 1 + inverted group = high collapse cost there
        keep = dup.vertex_groups.new(name="_keep")
        co = _verts(dup)
        idx = np.where((co[:, 2] < 0.05 * H) | (co[:, 2] > 0.92 * H))[0]
        if len(idx):
            keep.add([int(i) for i in idx], 1.0, "REPLACE")
        dec.vertex_group = "_keep"
        dec.invert_vertex_group = True
        dec.vertex_group_factor = 1.0
    ratio = min(1.0, target_tris / tris)
    best = None
    for _ in range(4):
        dec.ratio = ratio
        dg = bpy.context.evaluated_depsgraph_get()
        me_try = bpy.data.meshes.new_from_object(dup.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
        got = sum(len(p.vertices) - 2 for p in me_try.polygons)
        if best is None or got < best[1]:
            if best:
                bpy.data.meshes.remove(best[0])
            best = (me_try, got)
        else:
            bpy.data.meshes.remove(me_try)
            break  # collapse is stuck (non-manifold areas); keep the best so far
        if got <= target_tris * 1.05 or ratio < 0.02:
            break
        ratio *= target_tris / got
    new_me = best[0]
    dup.modifiers.remove(dec)
    old = dup.data
    dup.data = new_me
    if old.users == 0:
        bpy.data.meshes.remove(old)
    if keep is not None:
        dup.vertex_groups.remove(dup.vertex_groups["_keep"])
    _limit_weights(dup, 4)
    for m in dup.modifiers:
        m.show_viewport = True
    for i, mat in enumerate(dup.data.materials):
        dup.data.materials[i] = _scaled_material_copy(mat, max_tex, "_mobile")
    dup.parent = rig
    STATE["mobile"] = dup.name
    co = _verts(dup)
    return {"tris": sum(len(p.vertices) - 2 for p in dup.data.polygons),
            "height": round(float(co[:, 2].max() - co[:, 2].min()), 3), "min_z": round(float(co[:, 2].min()), 3),
            "has_weights": any(len(v.groups) for v in dup.data.vertices[:500])}


# ---------------------------------------------------------------- stage 6
def _select_only(objs):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objs:
        o.hide_set(False)
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


def export(outdir, name):
    os.makedirs(outdir, exist_ok=True)
    rig = bpy.data.objects[STATE["rig"]]
    pc = bpy.data.objects[STATE["obj"]]
    mob = bpy.data.objects[STATE["mobile"]]
    rig.data.pose_position = "REST"
    for o in bpy.context.view_layer.objects:
        o.hide_render = False
    res = {}
    for tag, body in (("PC", pc), ("mobile", mob)):
        other = mob if body is pc else pc
        other.hide_set(True)
        _select_only([rig, body])
        path = os.path.join(outdir, f"{name}_{tag}.glb")
        with bpy.context.temp_override(**_ctx(), active_object=rig, selected_objects=[rig, body]):
            bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True,
                                      export_skins=True, export_animations=False, export_yup=True,
                                      export_apply=False,
                                      export_image_format=("JPEG" if tag == "mobile" else "AUTO"),
                                      export_jpeg_quality=88)
        other.hide_set(False)
        res[tag] = round(os.path.getsize(path) / 1e6, 2)
    rig.data.pose_position = "POSE"
    for img in bpy.data.images:
        if img.source == "FILE" and not img.packed_file:
            try:
                img.pack()
            except Exception:
                pass
    for o in list(bpy.data.objects):
        if o.name.startswith("DBG_"):
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(outdir, f"{name}.blend"), copy=True)
    return res


# ---------------------------------------------------------------- preview
def preview(path, body="pc", pose=False, angle=-30, res=900, cpu=True):
    sc = bpy.context.scene
    H = STATE["H"]
    rig = bpy.data.objects.get(STATE.get("rig", ""))
    show = bpy.data.objects[STATE["obj"] if body == "pc" else STATE["mobile"]]
    for o in bpy.data.objects:
        if o.type == "MESH":
            o.hide_render = (o is not show) and not o.name.startswith("DBG_")
    if rig:
        rig.hide_render = True
        rig.data.pose_position = "POSE"
        for pb in rig.pose.bones:
            pb.rotation_mode = "XYZ"
            pb.rotation_euler = (0, 0, 0)
        if pose:
            P = rig.pose.bones
            for s, g in (("L", 1), ("R", -1)):
                P[f"upper_arm.{s}"].rotation_euler = (math.radians(-35), 0, 0)
                P[f"forearm.{s}"].rotation_euler = (math.radians(-50), 0, 0)
            P["thigh.L"].rotation_euler = (math.radians(35), 0, 0)
            P["shin.L"].rotation_euler = (math.radians(-60), 0, 0)
            P["head"].rotation_euler = (0, math.radians(25), 0)
            P["spine"].rotation_euler = (0, math.radians(-12), 0)
    cam = bpy.data.objects.get("PrevCam")
    if not cam:
        cam = bpy.data.objects.new("PrevCam", bpy.data.cameras.new("PrevCam"))
        sc.collection.objects.link(cam)
    cam.data.lens = 50
    dist = H * 2.3
    a = math.radians(angle)
    cam.location = (dist * math.sin(a), -dist * math.cos(a), H * 0.55)
    direction = Vector((0, 0, H * 0.5)) - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam
    for nm, loc, e in (("Key", (2, -3, 4), 4.5), ("Fill", (-3, -2, 2), 2.0), ("Rim", (0, 4, 3), 3.0)):
        lo = bpy.data.objects.get("Prev" + nm)
        if not lo:
            lo = bpy.data.objects.new("Prev" + nm, bpy.data.lights.new("Prev" + nm, "SUN"))
            sc.collection.objects.link(lo)
        lo.data.energy = e
        lo.location = loc
        lo.rotation_euler = (Vector((0, 0, H * 0.5)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    if not sc.world:
        sc.world = bpy.data.worlds.new("World")
    sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.32, 0.33, 0.36, 1)
        bg.inputs[1].default_value = 0.6
    if cpu:
        sc.render.engine = "CYCLES"
        sc.cycles.device = "CPU"
        sc.cycles.samples = 24
        sc.cycles.use_denoising = True
        sc.cycles.max_bounces = 4
    else:
        try:
            sc.render.engine = "BLENDER_EEVEE_NEXT"
        except TypeError:
            sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    if rig and pose:
        for pb in rig.pose.bones:
            pb.rotation_euler = (0, 0, 0)
    return path


def jpg_b64(paths, cell=520, quality=85):
    """Side-by-side JPEG of rendered PNGs, base64 (padded so the tool saves it to a file)."""
    import base64
    tiles = []
    for p in paths:
        img = bpy.data.images.load(p, check_existing=False)
        w, h = img.size
        ch = int(cell * h / w)
        img.scale(cell, ch)
        tiles.append(np.array(img.pixels[:], dtype=np.float32).reshape(ch, cell, 4))
        bpy.data.images.remove(img)
    Hh = max(t.shape[0] for t in tiles)
    canvas = np.ones((Hh, cell * len(tiles), 4), dtype=np.float32)
    for i, t in enumerate(tiles):
        canvas[Hh - t.shape[0]:, i * cell:(i + 1) * cell] = t
    im = bpy.data.images.new("sheet", canvas.shape[1], Hh, alpha=True)
    im.pixels.foreach_set(canvas.ravel())
    sc = bpy.context.scene
    old = sc.render.image_settings.file_format
    sc.render.image_settings.file_format = "JPEG"
    sc.render.image_settings.quality = quality
    out = paths[0] + "_sheet.jpg"
    im.save_render(out, scene=sc)
    bpy.data.images.remove(im)
    sc.render.image_settings.file_format = old
    return base64.b64encode(open(out, "rb").read()).decode()


def markers(on=True, r=0.012):
    """Red spheres at joint positions + thin bone sticks, for render checks."""
    for o in list(bpy.data.objects):
        if o.name.startswith("DBG_"):
            bpy.data.objects.remove(o, do_unlink=True)
    if not on:
        return
    mat = bpy.data.materials.get("DBG_mat") or bpy.data.materials.new("DBG_mat")
    mat.use_nodes = True
    bs = mat.node_tree.nodes.get("Principled BSDF")
    bs.inputs["Base Color"].default_value = (1, 0.05, 0.05, 1)
    bs.inputs["Emission Color"].default_value = (1, 0.05, 0.05, 1)
    bs.inputs["Emission Strength"].default_value = 3.0
    L = STATE["L"]
    bm = bmesh.new()
    for k, p in L.items():
        bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r * STATE["H"] / 1.7,
                                   matrix=Matrix.Translation(p))
    for _, h, t, _, _ in BONES:
        a, b = Vector(L[h]), Vector(L[t])
        d = b - a
        if d.length < 1e-4:
            continue
        rot = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
        m = Matrix.Translation((a + b) / 2) @ rot
        bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=r * 0.35, radius2=r * 0.35,
                              depth=d.length, matrix=m)
    me = bpy.data.meshes.new("DBG_markers")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    ob = bpy.data.objects.new("DBG_markers", me)
    bpy.context.scene.collection.objects.link(ob)
    ob.show_in_front = True
    return ob.name


def run_async(fn, *a, **k):
    import traceback, time
    t0 = time.time()
    STATE["job"] = {"state": "running"}

    def _t():
        try:
            res = fn(*a, **k)
            STATE["job"] = {"state": "done", "result": res, "secs": round(time.time() - t0, 1)}
        except Exception:
            STATE["job"] = {"state": "error", "tb": traceback.format_exc()[-1500:]}
        return None
    bpy.app.timers.register(_t, first_interval=0.2)


def job():
    j = dict(STATE.get("job", {}))
    j.pop("t0", None)
    return j



def skin_auto():
    """Bone heat sometimes fails on a given voxel proxy; retry coarser until it works."""
    last = None
    for vf in (1 / 170, 1 / 120, 1 / 90):
        last = skin(voxel_frac=vf)
        last["voxel"] = round(1 / vf)
        if last["proxy_unweighted"] < 0.02 * last["proxy_verts"]:
            return last
    return last
