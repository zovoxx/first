"""Contoo weapons: Pixal3D GLB -> oriented, scaled, grip-centred, PC + mobile GLBs."""
import os, json, math
import numpy as np
import bpy, bmesh
from mathutils import Matrix, Vector

ROOT = os.path.join(os.path.expanduser("~"), "Documents", "Contoo", "Assets")


def use_scene(name, reset=False):
    sc = bpy.data.scenes.get(name)
    if sc is not None and reset:
        for o in list(sc.objects):
            bpy.data.objects.remove(o, do_unlink=True)
    if sc is None:
        sc = bpy.data.scenes.new(name)
    bpy.context.window.scene = sc
    return sc


def _tri_samples(obj):
    """Area-weighted triangle centroids in world space: (centroids, areas)."""
    me = obj.data
    me.calc_loop_triangles()
    n = len(me.loop_triangles)
    co = np.empty(len(me.vertices) * 3, np.float64)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    M = np.array(obj.matrix_world)
    co = co @ M[:3, :3].T + M[:3, 3]
    tri = np.empty(n * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", tri)
    tri = tri.reshape(-1, 3)
    a, b, c = co[tri[:, 0]], co[tri[:, 1]], co[tri[:, 2]]
    cen = (a + b + c) / 3.0
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    return cen, area, co


def import_glb(path, name):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    for o in new:
        o.select_set(False)
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    for o in new:
        if o is not obj and o.name in bpy.data.objects and o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    obj.parent = None
    obj.matrix_world = obj.matrix_world.copy()
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.name = name
    obj.data.name = name
    return obj


def _apply_matrix(obj, M):
    obj.data.transform(M)
    obj.data.update()


def profile(obj, n=24):
    """Width / mass profile along local Z (after alignment)."""
    cen, area, co = _tri_samples(obj)
    z0, z1 = co[:, 2].min(), co[:, 2].max()
    edges = np.linspace(z0, z1, n + 1)
    idx = np.clip(np.searchsorted(edges, cen[:, 2]) - 1, 0, n - 1)
    mass = np.bincount(idx, weights=area, minlength=n)
    width = np.zeros(n)
    for i in range(n):
        m = idx == i
        if m.sum() > 3:
            width[i] = np.percentile(np.hypot(cen[m, 0], cen[m, 1]), 95)
    return edges, mass, width


def align(obj, rule, flip=None, spin_deg=0.0):
    """PCA align: main axis -> +Z, second axis -> +X, centred at the bbox centre.
    rule decides which end is up (the business end):
      'head_heavy' : the heavier end is the head (hammer, staff)
      'guard_low'  : the widest slice (guard) belongs to the lower half (dagger, sword)
      'bulge_x'    : symmetric (bow): +X points to the side the limbs bulge toward
      'none'       : keep PCA sign (use flip to correct)."""
    cen, area, co = _tri_samples(obj)
    c = (cen * area[:, None]).sum(0) / area.sum()
    X = (cen - c) * np.sqrt(area / area.sum())[:, None]
    U, S, Vt = np.linalg.svd(X, full_matrices=False)
    a1, a2 = Vt[0], Vt[1]
    a3 = np.cross(a1, a2)
    R = np.stack([a2, a3, a1])               # rows: new X, Y, Z
    M = Matrix.Identity(4)
    for i in range(3):
        for j in range(3):
            M[i][j] = R[i, j]
    T = Matrix.Translation(Vector((-c[0], -c[1], -c[2])))
    _apply_matrix(obj, M @ T)
    edges, mass, width = profile(obj)
    n = len(mass)
    do_flip = False
    if rule == "head_heavy":
        lo, hi = mass[: n // 3].sum(), mass[-(n // 3):].sum()
        do_flip = lo > hi
    elif rule == "guard_low":
        do_flip = int(np.argmax(width)) > n // 2
    if flip is not None:
        do_flip = do_flip != bool(flip)
    if do_flip:
        _apply_matrix(obj, Matrix.Rotation(math.pi, 4, "X"))   # z -> -z, y -> -y
    if rule == "bulge_x":
        # bow: the grip (mid height) must sit on the +X side of the limb tips (string on -X)
        cen2, area2, co2 = _tri_samples(obj)
        z0, z1 = co2[:, 2].min(), co2[:, 2].max()
        Lz = z1 - z0
        mid = np.abs(cen2[:, 2] - 0.5 * (z0 + z1)) < 0.05 * Lz
        tips = (cen2[:, 2] < z0 + 0.05 * Lz) | (cen2[:, 2] > z1 - 0.05 * Lz)
        if np.average(cen2[mid, 0], weights=area2[mid]) < np.average(cen2[tips, 0], weights=area2[tips]):
            _apply_matrix(obj, Matrix.Rotation(math.pi, 4, "Z"))
    if spin_deg:
        _apply_matrix(obj, Matrix.Rotation(math.radians(spin_deg), 4, "Z"))
    edges, mass, width = profile(obj)
    return {"sv": [round(float(s), 4) for s in S], "flipped": bool(do_flip),
            "mass": [round(float(m / mass.sum()), 3) for m in mass], "width": [round(float(w), 3) for w in width]}


def finalize(obj, length, grip_frac):
    """Uniform scale to `length` along Z, origin at the grip (fraction from the bottom end), axis-centred."""
    cen, area, co = _tri_samples(obj)
    z0, z1 = co[:, 2].min(), co[:, 2].max()
    s = length / (z1 - z0)
    _apply_matrix(obj, Matrix.Scale(s, 4))
    z0, z1 = z0 * s, z1 * s
    gz = z0 + grip_frac * (z1 - z0)
    cen, area, co = _tri_samples(obj)
    band = np.abs(cen[:, 2] - gz) < 0.03 * (z1 - z0)
    if band.sum() < 10:
        band = np.abs(cen[:, 2] - gz) < 0.08 * (z1 - z0)
    gx = float(np.average(cen[band, 0], weights=area[band]))
    gy = float(np.average(cen[band, 1], weights=area[band]))
    _apply_matrix(obj, Matrix.Translation(Vector((-gx, -gy, -gz))))
    obj.location = (0, 0, 0)
    cen, area, co = _tri_samples(obj)
    return {"scale": round(float(s), 4), "bbox": [np.round(co.min(0), 3).tolist(), np.round(co.max(0), 3).tolist()],
            "grip_radius": round(float(np.percentile(np.hypot(cen[band, 0], cen[band, 1]), 90)), 4)}


def _scaled_material_copy(mat, max_px, suffix):
    m2 = mat.copy()
    m2.name = mat.name + suffix
    if m2.node_tree:
        for nd in m2.node_tree.nodes:
            if nd.type == "TEX_IMAGE" and nd.image and max(nd.image.size) > max_px:
                img = nd.image.copy()
                img.name = (nd.image.name or "tex") + suffix
                w, h = nd.image.size
                s = max_px / max(w, h)
                img.scale(int(w * s), int(h * s))
                img.pack()
                nd.image = img
    return m2


def limit_textures(obj, max_px, suffix):
    for i, mat in enumerate(obj.data.materials):
        if mat is not None:
            obj.data.materials[i] = _scaled_material_copy(mat, max_px, suffix)


def decimated_copy(obj, target_tris, name):
    dup = obj.copy()
    dup.data = obj.data.copy()
    dup.name = name
    dup.data.name = name
    bpy.context.scene.collection.objects.link(dup)
    tris = sum(len(p.vertices) - 2 for p in dup.data.polygons)
    if target_tris < tris:
        dec = dup.modifiers.new("dec", "DECIMATE")
        ratio = target_tris / tris
        for _ in range(4):
            dec.ratio = ratio
            dg = bpy.context.evaluated_depsgraph_get()
            me = bpy.data.meshes.new_from_object(dup.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
            got = sum(len(p.vertices) - 2 for p in me.polygons)
            if got <= target_tris * 1.06 or ratio < 0.02:
                break
            bpy.data.meshes.remove(me)
            ratio *= target_tris / got
        dup.modifiers.remove(dec)
        old = dup.data
        dup.data = me
        if old.users == 0:
            bpy.data.meshes.remove(old)
        me.name = name
    return dup


def tri_count(obj):
    return sum(len(p.vertices) - 2 for p in obj.data.polygons)


def export_glb(obj, path, mobile=False):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, use_active_scene=True,
                              export_animations=False, export_skins=False, export_morph=False, export_apply=True,
                              export_yup=True, export_image_format=("JPEG" if mobile else "AUTO"),
                              export_jpeg_quality=85)
    return os.path.getsize(path)


def save_scene_blend(scene, path):
    bpy.data.libraries.write(path, {scene}, fake_user=True, compress=True)
    return os.path.getsize(path)


# ---------------------------------------------------------------- previews (Cycles CPU only)
def _preview_world():
    w = bpy.data.worlds.get("contoo_preview_world") or bpy.data.worlds.new("contoo_preview_world")
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.42, 0.42, 0.44, 1.0)
    bg.inputs[1].default_value = 1.0
    return w


def render_views(objs, path, res=420, views=("front", "side"), samples=24):
    """Orthographic Cycles-CPU renders of each object (front = from -Y, side = from +X), saved side by side."""
    sc = bpy.context.scene
    sc.world = _preview_world()
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = False
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "Standard"
    cam_d = bpy.data.cameras.get("pv_cam") or bpy.data.cameras.new("pv_cam")
    cam_d.type = "ORTHO"
    cam = bpy.data.objects.get("pv_cam") or bpy.data.objects.new("pv_cam", cam_d)
    if cam.name not in sc.collection.objects:
        sc.collection.objects.link(cam)
    sun_d = bpy.data.lights.get("pv_sun") or bpy.data.lights.new("pv_sun", "SUN")
    sun_d.energy = 3.5
    sun = bpy.data.objects.get("pv_sun") or bpy.data.objects.new("pv_sun", sun_d)
    if sun.name not in sc.collection.objects:
        sc.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(-40))
    sc.camera = cam
    hidden = {o.name: o.hide_render for o in sc.objects}
    tiles = []
    try:
        for ob in objs:
            for o in sc.objects:
                if o.type == "MESH":
                    o.hide_render = o is not ob
            cen, area, co = _tri_samples(ob)
            lo, hi = co.min(0), co.max(0)
            mid = 0.5 * (lo + hi)
            size = float((hi - lo).max()) * 1.1
            cam_d.ortho_scale = size
            for v in views:
                if v == "front":
                    cam.location = (mid[0], mid[1] - 5, mid[2])
                    cam.rotation_euler = (math.radians(90), 0, 0)
                else:
                    cam.location = (mid[0] + 5, mid[1], mid[2])
                    cam.rotation_euler = (math.radians(90), 0, math.radians(90))
                tmp = path + f".{ob.name}.{v}.png"
                sc.render.filepath = tmp
                bpy.ops.render.render(write_still=True)
                tiles.append(tmp)
    finally:
        for nm, hr in hidden.items():
            if nm in sc.objects:
                sc.objects[nm].hide_render = hr
    return tiles
