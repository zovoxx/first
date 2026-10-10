"""Mobile LOD from a second Pixal3D run (same seed, fewer faces): align it to the PC body, transfer the
skin weights from the PC body (nearest-surface barycentric), and swap it in as <Name>_Body_mobile."""
import os, math
import numpy as np
import bpy, bmesh
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree


def _co(obj):
    me = obj.data
    a = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get("co", a)
    return a.reshape(-1, 3)


def import_lod(glb):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    for o in meshes:
        o.data.transform(o.matrix_world)
        o.parent = None
        o.matrix_world = Matrix.Identity(4)
    for o in new:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    obj = meshes[0]
    if len(meshes) > 1:
        with bpy.context.temp_override(active_object=obj, selected_editable_objects=meshes, selected_objects=meshes):
            bpy.ops.object.join()
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6 * max(obj.dimensions))
    bm.to_mesh(obj.data)
    bm.free()
    return obj


def _umeyama(src, dst, scale=True):
    mu_s, mu_d = src.mean(0), dst.mean(0)
    S, D = src - mu_s, dst - mu_d
    C = D.T @ S / len(src)
    U, s, Vt = np.linalg.svd(C)
    d = np.sign(np.linalg.det(U @ Vt))
    Dm = np.diag([1, 1, d])
    R = U @ Dm @ Vt
    c = (s * np.diag(Dm)).sum() / (S ** 2).sum() * len(src) if scale else 1.0
    t = mu_d - c * R @ mu_s
    return c, R, t


def _yaw(deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _surface_bvh(obj):
    me = obj.data
    me.calc_loop_triangles()
    mw = obj.matrix_world
    verts = [mw @ v.co for v in me.vertices]
    tris = [tuple(t.vertices) for t in me.loop_triangles]
    return BVHTree.FromPolygons(verts, tris, all_triangles=True)


def _icp(P, M, idx, bvh, iters):
    err = None
    for _ in range(iters):
        src = P[idx]
        dst = np.array([bvh.find_nearest(Vector(p))[0] for p in src])
        d = np.linalg.norm(src - dst, axis=1)
        keep = d < np.percentile(d, 90)
        c, R, t = _umeyama(src[keep], dst[keep])
        P = (c * (R @ P.T)).T + t
        step = np.eye(4); step[:3, :3] = c * R; step[:3, 3] = t
        M = step @ M
        err = float(d[keep].mean())
    return P, M, err


def align_to(lod, ref, iters=25, n=6000):
    """Coarse: height + base centre for 4 start yaws (the PC body may have been turned 90/180 deg when it was
    built); ICP (rigid + uniform scale) against the reference body SURFACE; keep the best start."""
    P0 = _co(lod)
    Q = np.array([list(ref.matrix_world @ Vector(v)) for v in _co(ref)])
    bvh = _surface_bvh(ref)
    s0 = (Q[:, 2].max() - Q[:, 2].min()) / (P0[:, 2].max() - P0[:, 2].min())
    cQ = np.array([np.median(Q[:, 0]), np.median(Q[:, 1]), Q[:, 2].min()])
    rng = np.random.default_rng(0)
    idx = rng.choice(len(P0), size=min(n, len(P0)), replace=False)
    tries = []
    for yaw in (0, 90, 180, 270):
        A = s0 * _yaw(yaw)
        P = (A @ P0.T).T
        cP = np.array([np.median(P[:, 0]), np.median(P[:, 1]), P[:, 2].min()])
        P = P - cP + cQ
        M = np.eye(4); M[:3, :3] = A; M[:3, 3] = cQ - cP
        P, M, err = _icp(P, M, idx, bvh, 8)
        tries.append((err, yaw, P, M))
    tries.sort(key=lambda t: t[0])
    err0, yaw, P, M = tries[0]
    P, M, err = _icp(P, M, idx, bvh, iters)
    lod.data.transform(Matrix(M.tolist()))
    lod.data.update()
    P2 = _co(lod)
    d = np.array([bvh.find_nearest(Vector(p))[3] for p in P2[idx]])
    return {"yaw_start": yaw, "yaw_errs_mm": {t[1]: round(1000 * t[0], 1) for t in tries},
            "scale": round(float(np.cbrt(abs(np.linalg.det(M[:3, :3])))), 4),
            "mean_mm": round(1000 * float(d.mean()), 2), "p95_mm": round(1000 * float(np.percentile(d, 95)), 2),
            "max_mm": round(1000 * float(d.max()), 1), "icp_err_mm": round(1000 * err, 2)}


def transfer_weights(dst, src, max_infl=4):
    """Barycentric weights from the nearest point on the source surface (source rest geometry)."""
    names = [g.name for g in src.vertex_groups]
    gi = {g.index: k for k, g in enumerate(src.vertex_groups)}
    Wsrc = np.zeros((len(src.data.vertices), len(names)), np.float32)
    for v in src.data.vertices:
        for g in v.groups:
            if g.group in gi:
                Wsrc[v.index, gi[g.group]] = g.weight
    me = src.data
    me.calc_loop_triangles()
    verts = [v.co.copy() for v in me.vertices]
    tris = [tuple(t.vertices) for t in me.loop_triangles]
    bvh = BVHTree.FromPolygons(verts, tris, all_triangles=True)
    co = _co(dst)
    Wd = np.zeros((len(co), len(names)), np.float32)
    far = 0
    for i, c in enumerate(co):
        loc, nrm, ti, dist = bvh.find_nearest(Vector(c))
        if ti is None:
            continue
        a, b, cc = tris[ti]
        A, B, Cv = np.array(verts[a]), np.array(verts[b]), np.array(verts[cc])
        p = np.array(loc)
        v0, v1, v2 = B - A, Cv - A, p - A
        d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
        d20, d21 = v2 @ v0, v2 @ v1
        den = d00 * d11 - d01 * d01
        if abs(den) < 1e-14:
            w = np.array([1.0, 0.0, 0.0])
        else:
            vv = (d11 * d20 - d01 * d21) / den
            ww = (d00 * d21 - d01 * d20) / den
            w = np.clip(np.array([1 - vv - ww, vv, ww]), 0, 1)
            w /= max(w.sum(), 1e-9)
        Wd[i] = w[0] * Wsrc[a] + w[1] * Wsrc[b] + w[2] * Wsrc[cc]
        if dist > 0.02:
            far += 1
    if max_infl:
        drop = np.argsort(Wd, axis=1)[:, :-max_infl]
        np.put_along_axis(Wd, drop, 0.0, axis=1)
    Wd /= np.maximum(Wd.sum(1, keepdims=True), 1e-9)
    for g in list(dst.vertex_groups):
        dst.vertex_groups.remove(g)
    vgs = [dst.vertex_groups.new(name=n) for n in names]
    for j, vg in enumerate(vgs):
        for i in np.where(Wd[:, j] > 1e-3)[0]:
            vg.add([int(i)], float(Wd[i, j]), "REPLACE")
    return {"verts": int(len(co)), "far_2cm": int(far), "groups": len(vgs)}


def swap_mobile(name, lod_glb):
    sc = bpy.data.scenes[f"C_{name}"]
    bpy.context.window.scene = sc
    rig = bpy.data.objects[f"{name}_Rig"]
    pc = bpy.data.objects[f"{name}_Body"]
    old = bpy.data.objects.get(f"{name}_Body_mobile")
    rig.data.pose_position = "REST"
    lod = import_lod(lod_glb)
    for c in list(lod.users_collection):
        c.objects.unlink(lod)
    sc.collection.objects.link(lod)
    fit = align_to(lod, pc)
    wt = transfer_weights(lod, pc)
    tris = sum(len(p.vertices) - 2 for p in lod.data.polygons)
    if old is not None:
        old.name = f"{name}_Body_mobile_OLD"
        old_mesh = old.data
        bpy.data.objects.remove(old, do_unlink=True)
        if old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
    lod.name = f"{name}_Body_mobile"
    lod.data.name = f"{name}_Body_mobile"
    for m in lod.data.materials:
        if m:
            m.name = f"{name}_mobile_mat"
    lod.parent = rig
    lod.matrix_parent_inverse = rig.matrix_world.inverted()
    mod = lod.modifiers.new("Armature", "ARMATURE")
    mod.object = rig
    for img in bpy.data.images:
        if img.users and not img.packed_file and img.source == "FILE":
            try:
                img.pack()
            except Exception:
                pass
    rig.data.pose_position = "POSE"
    imgs = []
    for m in lod.data.materials:
        if m and m.node_tree:
            imgs += [[n.image.name, list(n.image.size)] for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]
    return {"fit": fit, "weights": wt, "tris": tris, "images": imgs}
