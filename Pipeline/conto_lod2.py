# Mobile LOD by texture-preserving quadric decimation of the PC body (pymeshlab, run in a separate process so
# Blender never loads it). The LOD keeps the PC UVs, so it reuses the PC texture (scaled down to 2048); skin
# weights come from the PC body (nearest-surface barycentric), then it replaces <Name>_Body_mobile.
import os, sys, json, subprocess
import numpy as np
import bpy

W = os.path.join(os.environ["LOCALAPPDATA"], "Temp", "claude_charpipe")
LIB = os.path.join(W, "pylib")

QEM = r'''
import sys, json
import pymeshlab as ml
src, dst, report, zcut, head_target, body_target = sys.argv[1:7]
zcut, head_target, body_target = float(zcut), int(head_target), int(body_target)
ms = ml.MeshSet()
ms.load_new_mesh(src)
m = ms.current_mesh()
info = {"in_faces": m.face_number(), "in_verts": m.vertex_number(), "wedge_tex": bool(m.has_wedge_tex_coord())}
kw = dict(qualitythr=0.5, extratcoordw=2.0, preserveboundary=True, boundaryweight=1.0, optimalplacement=True,
          preservenormal=True, planarquadric=False, selected=True)
# with selected=True the face target counts the selected faces only
# body below the cut gets the smaller share of the budget ...
ms.compute_selection_by_condition_per_face(condselect="(z0 < %f) && (z1 < %f) && (z2 < %f)" % (zcut, zcut, zcut))
nb = ms.current_mesh().selected_face_number()
rest = ms.current_mesh().face_number() - nb
ms.meshing_decimation_quadric_edge_collapse_with_texture(targetfacenum=min(nb, body_target), **kw)
info["body_faces"] = [nb, ms.current_mesh().face_number() - rest]
# ... the head (face, hair, crown/helmet) keeps more of its detail
ms.compute_selection_by_condition_per_face(condselect="(z0 >= %f) || (z1 >= %f) || (z2 >= %f)" % (zcut, zcut, zcut))
nh = ms.current_mesh().selected_face_number()
rest = ms.current_mesh().face_number() - nh
ms.meshing_decimation_quadric_edge_collapse_with_texture(targetfacenum=min(nh, head_target), **kw)
info["head_faces"] = [nh, ms.current_mesh().face_number() - rest]
ms.set_selection_none()
m = ms.current_mesh()
info.update(out_faces=m.face_number(), out_verts=m.vertex_number())
ms.save_current_mesh(dst)
json.dump(info, open(report, "w"))
'''


def write_obj(obj, path):
    me = obj.data
    nv, nl = len(me.vertices), len(me.loops)
    co = np.empty(nv * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    M = np.array(obj.matrix_world)
    co = co @ M[:3, :3].T + M[:3, 3]
    uv = np.empty(nl * 2); me.uv_layers.active.data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
    lv = np.empty(nl, np.int64); me.loops.foreach_get("vertex_index", lv)
    out = ["v %.6f %.6f %.6f" % tuple(c) for c in co]
    out += ["vt %.6f %.6f" % tuple(t) for t in uv]
    for p in me.polygons:
        out.append("f " + " ".join("%d/%d" % (lv[li] + 1, li + 1) for li in p.loop_indices))
    open(path, "w").write("\n".join(out) + "\n")
    return {"verts": nv, "loops": nl, "faces": len(me.polygons)}


def read_obj(path, name):
    V, T, F, FT = [], [], [], []
    for ln in open(path):
        if ln.startswith("v "):
            V.append([float(x) for x in ln.split()[1:4]])
        elif ln.startswith("vt "):
            T.append([float(x) for x in ln.split()[1:3]])
        elif ln.startswith("f "):
            f, ft = [], []
            for tok in ln.split()[1:]:
                parts = tok.split("/")
                f.append(int(parts[0]) - 1)
                ft.append(int(parts[1]) - 1 if len(parts) > 1 and parts[1] else -1)
            F.append(f); FT.append(ft)
    me = bpy.data.meshes.new(name)
    me.from_pydata(V, [], F)
    uvl = me.uv_layers.new(name="UVMap")
    flat = np.array([T[i] if i >= 0 else [0.0, 0.0] for ft in FT for i in ft], np.float32)
    uvl.data.foreach_set("uv", flat.ravel())
    me.polygons.foreach_set("use_smooth", np.ones(len(me.polygons), bool))
    me.validate(clean_customdata=False)
    me.update()
    return me


def scaled_material(mat, max_px, suffix):
    m2 = mat.copy()
    m2.name = mat.name.split(".")[0] + suffix
    done = {}
    for n in (m2.node_tree.nodes if m2.node_tree else []):
        if n.type == "TEX_IMAGE" and n.image and max(n.image.size) > max_px:
            src = n.image
            if src.name not in done:
                img = src.copy()
                img.name = src.name.split(".")[0] + suffix
                w, h = src.size
                s = max_px / max(w, h)
                img.scale(int(w * s), int(h * s))
                img.pack()
                done[src.name] = img
            n.image = done[src.name]
    return m2


def qem_mobile(name, cut_frac=0.78, head_target=6000, body_target=11000, max_tex=2048):
    # cut_frac: height fraction above which the head budget applies (dwarf heads start lower)
    import conto_lod
    sc = bpy.data.scenes[f"C_{name}"]
    bpy.context.window.scene = sc
    rig = bpy.data.objects[f"{name}_Rig"]
    pc = bpy.data.objects[f"{name}_Body"]
    src, dst, rep = (os.path.join(W, f"qem_{name}{s}") for s in ("_in.obj", "_out.obj", ".json"))
    for p in (dst, rep):
        if os.path.exists(p):
            os.remove(p)
    wi = write_obj(pc, src)
    zs = [(pc.matrix_world @ v.co).z for v in pc.data.vertices]
    zcut = min(zs) + cut_frac * (max(zs) - min(zs))
    script = os.path.join(W, "qem_run.py")
    open(script, "w").write(QEM)
    env = dict(os.environ, PYTHONPATH=LIB, PYTHONNOUSERSITE="1")
    r = subprocess.run([sys.executable, "-u", script, src, dst, rep, "%.5f" % zcut, str(head_target), str(body_target)],
                       capture_output=True, text=True, timeout=600, env=env)
    if not os.path.exists(rep):
        raise RuntimeError((r.stdout + r.stderr)[-2500:])
    info = json.load(open(rep))
    me = read_obj(dst, f"{name}_Body_mobile")
    lod = bpy.data.objects.new(f"{name}_Body_mobile_new", me)
    sc.collection.objects.link(lod)
    for m in pc.data.materials:
        me.materials.append(scaled_material(m, max_tex, "_mobile") if m else None)
    wt = conto_lod.transfer_weights(lod, pc)
    old = bpy.data.objects.get(f"{name}_Body_mobile")
    if old is not None:
        om = old.data
        bpy.data.objects.remove(old, do_unlink=True)
        if om.users == 0:
            bpy.data.meshes.remove(om)
    lod.name = f"{name}_Body_mobile"
    me.name = f"{name}_Body_mobile"
    lod.parent = rig
    lod.matrix_parent_inverse = rig.matrix_world.inverted()
    mod = lod.modifiers.new("Armature", "ARMATURE")
    mod.object = rig
    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    imgs = [[n.image.name, list(n.image.size)] for m in me.materials if m and m.node_tree
            for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]
    return {"obj_in": wi, "qem": info, "tris": tris, "verts": len(me.vertices), "weights": wt, "images": imgs}
