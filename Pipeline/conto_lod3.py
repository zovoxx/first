# Mobile LOD for PC bodies whose topology will not decimate cleanly (Pixal3D meshes with hundreds of tiny
# tunnels / non-manifold edges): voxel remesh -> quadric decimation with a head budget (pymeshlab, separate
# process) -> Smart UV -> bake base colour, ORM and normal map from the PC body (Cycles CPU, selected to active)
# -> PC skin weights -> replaces <Name>_Body_mobile.
import os, sys, json, math, subprocess
import numpy as np
import bpy, bmesh

W = os.path.join(os.environ["LOCALAPPDATA"], "Temp", "claude_charpipe")
LIB = os.path.join(W, "pylib")

QEM_PLAIN = r'''
import sys, json
import pymeshlab as ml
src, dst, report, zcut, head_target, body_target = sys.argv[1:7]
zcut, head_target, body_target = float(zcut), int(head_target), int(body_target)
ms = ml.MeshSet()
ms.load_new_mesh(src)
ms.meshing_remove_duplicate_vertices()
info = {"in_faces": ms.current_mesh().face_number()}
kw = dict(qualitythr=0.4, preserveboundary=True, preservenormal=True, preservetopology=False, optimalplacement=True,
          planarquadric=True, autoclean=True, selected=True)
ms.compute_selection_by_condition_per_face(condselect="(z0 < %f) && (z1 < %f) && (z2 < %f)" % (zcut, zcut, zcut))
nb = ms.current_mesh().selected_face_number()
ms.meshing_decimation_quadric_edge_collapse(targetfacenum=min(nb, body_target), **kw)
ms.compute_selection_by_condition_per_face(condselect="(z0 >= %f) || (z1 >= %f) || (z2 >= %f)" % (zcut, zcut, zcut))
nh = ms.current_mesh().selected_face_number()
ms.meshing_decimation_quadric_edge_collapse(targetfacenum=min(nh, head_target), **kw)
ms.set_selection_none()
# a last light pass over everything evens out the seam between the two budgets
ms.meshing_decimation_quadric_edge_collapse(targetfacenum=int(ms.current_mesh().face_number() * 0.97), qualitythr=0.4,
    preserveboundary=True, preservenormal=True, optimalplacement=True, planarquadric=True, autoclean=True)
m = ms.current_mesh()
info.update(body=nb, head=nh, out_faces=m.face_number(), out_verts=m.vertex_number())
ms.save_current_mesh(dst)
json.dump(info, open(report, "w"))
'''


def _ctx():
    win = bpy.context.window_manager.windows[0]
    for area in win.screen.areas:
        if area.type == "VIEW_3D":
            region = next(r for r in area.regions if r.type == "WINDOW")
            return dict(window=win, area=area, region=region, screen=win.screen)
    return dict(window=win, screen=win.screen)


def _write_obj_plain(me, path):
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    out = ["v %.6f %.6f %.6f" % tuple(c) for c in co]
    me.calc_loop_triangles()
    tv = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get("vertices", tv)
    out += ["f %d %d %d" % (a + 1, b + 1, c + 1) for a, b, c in tv.reshape(-1, 3)]
    open(path, "w").write("\n".join(out) + "\n")


def _read_obj_plain(path, name):
    V, F = [], []
    for ln in open(path):
        if ln.startswith("v "):
            V.append([float(x) for x in ln.split()[1:4]])
        elif ln.startswith("f "):
            F.append([int(t.split("/")[0]) - 1 for t in ln.split()[1:]])
    me = bpy.data.meshes.new(name)
    me.from_pydata(V, [], F)
    me.validate()
    me.polygons.foreach_set("use_smooth", np.ones(len(me.polygons), bool))
    me.update()
    return me


def remesh_decimate(name, voxel, cut_frac, head_target, body_target):
    sc = bpy.data.scenes[f"C_{name}"]
    pc = bpy.data.objects[f"{name}_Body"]
    tmp_me = pc.data.copy()
    tmp = bpy.data.objects.new(f"{name}_vox_tmp", tmp_me)
    sc.collection.objects.link(tmp)
    tmp.matrix_world = pc.matrix_world.copy()
    r = tmp.modifiers.new("vox", "REMESH")
    r.mode = "VOXEL"
    r.voxel_size = voxel
    r.adaptivity = 0.0
    dg = bpy.context.evaluated_depsgraph_get()
    vox = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg), depsgraph=dg)
    vox.transform(tmp.matrix_world)
    bpy.data.objects.remove(tmp, do_unlink=True)
    bpy.data.meshes.remove(tmp_me)
    nvox = len(vox.polygons)
    zs = np.empty(len(vox.vertices) * 3); vox.vertices.foreach_get("co", zs); zs = zs.reshape(-1, 3)[:, 2]
    zcut = float(zs.min() + cut_frac * (zs.max() - zs.min()))
    src, dst, rep = (os.path.join(W, f"lod3_{name}{s}") for s in ("_in.obj", "_out.obj", ".json"))
    for p in (dst, rep):
        if os.path.exists(p):
            os.remove(p)
    _write_obj_plain(vox, src)
    bpy.data.meshes.remove(vox)
    script = os.path.join(W, "qem_plain_run.py")
    open(script, "w").write(QEM_PLAIN)
    env = dict(os.environ, PYTHONPATH=LIB, PYTHONNOUSERSITE="1")
    res = subprocess.run([sys.executable, "-u", script, src, dst, rep, "%.5f" % zcut, str(head_target), str(body_target)],
                         capture_output=True, text=True, timeout=900, env=env)
    if not os.path.exists(rep):
        raise RuntimeError((res.stdout + res.stderr)[-2500:])
    info = json.load(open(rep))
    info["voxel_faces"] = nvox
    me = _read_obj_plain(dst, f"{name}_Body_mobile")
    return me, info


def smart_uv(obj, margin=0.004):
    ctx = _ctx()
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    with bpy.context.temp_override(**ctx, active_object=obj, object=obj, selected_objects=[obj], selected_editable_objects=[obj]):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=margin, area_weight=0.0,
                                 correct_aspect=True, scale_to_bounds=False)
        bpy.ops.object.mode_set(mode="OBJECT")


def _emit_material(img, name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img
    em = nt.nodes.new("ShaderNodeEmission"); em.inputs["Strength"].default_value = 1.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(tex.outputs["Color"], em.inputs["Color"])
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return m


def _pc_images(mat):
    base = orm = nrm = None
    for l in mat.node_tree.links:
        fn, tn = l.from_node, l.to_node
        if fn.type != "TEX_IMAGE" or not fn.image:
            continue
        if tn.type == "BSDF_PRINCIPLED" and l.to_socket.name == "Base Color":
            base = fn.image
        elif tn.type == "SEPARATE_COLOR":
            orm = fn.image
        elif tn.type == "NORMAL_MAP":
            nrm = fn.image
    return base, orm, nrm


def bake_maps(name, pc, lod, tex=2048, extrusion=0.015, ray=0.05, samples=4):
    sc = bpy.context.window.scene
    pc_mat = pc.data.materials[0]
    base_src, orm_src, nrm_src = _pc_images(pc_mat)
    imgs = {}
    for key, cs in (("base", "sRGB"), ("orm", "Non-Color"), ("nrm", "Non-Color")):
        nm = f"{name}_mobile_{key}"
        old = bpy.data.images.get(nm)
        if old is not None:
            bpy.data.images.remove(old)
        im = bpy.data.images.new(nm, tex, tex, alpha=False, float_buffer=False)
        im.colorspace_settings.name = cs
        imgs[key] = im
    # the LOD material = copy of the PC material with the baked images swapped in
    mat = pc_mat.copy()
    mat.name = f"{name}_mobile_mat"
    swap = {base_src.name: imgs["base"], orm_src.name: imgs["orm"], nrm_src.name: imgs["nrm"]}
    for n in mat.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image and n.image.name in swap:
            n.image = swap[n.image.name]
    lod.data.materials.clear()
    lod.data.materials.append(mat)
    # source = PC body copy with object-level material slots
    src = pc.copy()
    sc.collection.objects.link(src)
    src.material_slots[0].link = "OBJECT"
    store = (sc.render.engine, sc.cycles.device, sc.cycles.samples)
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    bk = sc.render.bake
    bk.use_selected_to_active = True
    bk.cage_extrusion = extrusion
    bk.max_ray_distance = ray
    bk.margin = 8
    bk.margin_type = "EXTEND"
    bk.use_clear = True
    bk.target = "IMAGE_TEXTURES"
    ctx = _ctx()
    times = {}
    import time
    for key, btype, src_mat in (("base", "EMIT", _emit_material(base_src, "_bake_base")),
                                ("orm", "EMIT", _emit_material(orm_src, "_bake_orm")),
                                ("nrm", "NORMAL", pc_mat)):
        src.material_slots[0].material = src_mat
        node = next(n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image == imgs[key])
        for n in mat.node_tree.nodes:
            n.select = False
        node.select = True
        mat.node_tree.nodes.active = node
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        src.select_set(True)
        lod.select_set(True)
        bpy.context.view_layer.objects.active = lod
        t0 = time.time()
        with bpy.context.temp_override(**ctx, active_object=lod, object=lod, selected_objects=[src, lod],
                                       selected_editable_objects=[src, lod]):
            if btype == "NORMAL":
                bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", use_selected_to_active=True,
                                    cage_extrusion=extrusion, max_ray_distance=ray, margin=8)
            else:
                bpy.ops.object.bake(type="EMIT", use_selected_to_active=True, cage_extrusion=extrusion,
                                    max_ray_distance=ray, margin=8)
        times[key] = round(time.time() - t0, 1)
        if src_mat is not pc_mat:
            bpy.data.materials.remove(src_mat)
    bpy.data.objects.remove(src, do_unlink=True)
    for im in imgs.values():
        im.pack()
    sc.render.engine, sc.cycles.device, sc.cycles.samples = store
    return {"bake_s": times, "images": [im.name for im in imgs.values()]}


def make_mobile(name, voxel=0.006, cut_frac=0.78, head_target=6000, body_target=10000, tex=2048):
    import conto_lod
    sc = bpy.data.scenes[f"C_{name}"]
    bpy.context.window.scene = sc
    rig = bpy.data.objects[f"{name}_Rig"]
    pc = bpy.data.objects[f"{name}_Body"]
    rig.data.pose_position = "REST"
    me, info = remesh_decimate(name, voxel, cut_frac, head_target, body_target)
    lod = bpy.data.objects.new(f"{name}_Body_mobile_new", me)
    sc.collection.objects.link(lod)
    smart_uv(lod)
    bk = bake_maps(name, pc, lod, tex=tex)
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
    rig.data.pose_position = "POSE"
    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    return {"remesh_qem": info, "tris": tris, "verts": len(me.vertices), "bake": bk, "weights": wt}
