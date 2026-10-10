# Contoo verification helpers (Blender side, Cycles CPU): re-import exported GLBs and render checks.
#   render_view(glb, [(clip, fraction)], out_prefix, "front"|"side")  - full-body frames of chosen clips
#   render_head(glb, out_png, view="front"|"q")                         - face close-up (PC vs mobile check)
#   render_static(glb, out_png)                                          - rest pose of a GLB without animations
#   transfer_normals(name)                                               - PC custom normals onto <Name>_Body_mobile
#   save_clean(path)                                                     - purge unused data, save the work .blend
# Use with conto_finish.enqueue(...) and conto_finish.sheet(rows, out_jpg) to build a contact sheet.
import os, math
import bpy
from mathutils import Vector
import conto_finish as cf


def _zmax(objs):
    meshes = [o for o in objs if o.type == "MESH"]
    return max((o.matrix_world @ Vector(c)).z for o in meshes for c in o.bound_box), meshes


def render_view(path, shots, out_prefix, view="front", res=(300, 420), cam_d=6.0):
    sc, cam, rig, objs, acts, info = cf.import_glb(path)
    zmax, meshes = _zmax(objs)
    cam.data.ortho_scale = max(2.6, zmax * 1.45)
    if view == "front":
        cam.location = (0.0, -cam_d, zmax * 0.5); cam.rotation_euler = (math.radians(90), 0, 0)
    else:
        cam.location = (cam_d, 0.0, zmax * 0.5); cam.rotation_euler = (math.radians(90), 0, math.radians(90))
    sc.render.resolution_x, sc.render.resolution_y = res
    files = []
    for clip, frac in shots:
        cf.set_clip(objs, acts, clip)
        act = rig.animation_data.action
        if act is None:
            continue
        a0, a1 = act.frame_range
        sc.frame_set(int(round(a0 + frac * (a1 - a0))))
        p = f"{out_prefix}_{view}_{clip}_{int(frac * 100):03d}.png"
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        files.append(p)
    tris = {o.name: sum(len(pl.vertices) - 2 for pl in o.data.polygons) for o in meshes}
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)
    return {"files": files, "tris": tris}


def render_head(path, out, res=(420, 420), view="front", frac_z=0.86, scale=0.75):
    sc, cam, rig, objs, acts, info = cf.import_glb(path)
    zmax, meshes = _zmax(objs)
    cf.set_clip(objs, acts, "idle")
    if rig.animation_data and rig.animation_data.action:
        sc.frame_set(int(rig.animation_data.action.frame_range[0]))
    cam.data.ortho_scale = scale
    if view == "front":
        cam.location = (0.0, -6.0, zmax * frac_z); cam.rotation_euler = (math.radians(90), 0, 0)
    else:
        a = math.radians(35)
        cam.location = (6.0 * math.sin(a), -6.0 * math.cos(a), zmax * frac_z); cam.rotation_euler = (math.radians(90), 0, a)
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.cycles.samples = 24
    sc.render.filepath = out
    bpy.ops.render.render(write_still=True)
    sc.cycles.samples = 12
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)
    return out


def render_static(path, out, res=(320, 420)):
    sc, cam, rig, objs, acts, info = cf.import_glb(path)
    zmax, meshes = _zmax(objs)
    cam.data.ortho_scale = max(1.6, zmax * 1.25)
    cam.location = (0.0, -6.0, zmax * 0.5); cam.rotation_euler = (math.radians(90), 0, 0)
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.filepath = out
    bpy.ops.render.render(write_still=True)
    tris = {o.name: sum(len(p.vertices) - 2 for p in o.data.polygons) for o in meshes}
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)
    return {"file": out, "tris": tris}


def transfer_normals(name):
    sc = bpy.data.scenes[f"C_{name}"]
    bpy.context.window.scene = sc
    rig = bpy.data.objects[f"{name}_Rig"]
    pc = bpy.data.objects[f"{name}_Body"]
    ob = bpy.data.objects[f"{name}_Body_mobile"]
    rig.data.pose_position = "REST"
    dt = ob.modifiers.new("DT_normals", "DATA_TRANSFER")
    dt.object = pc
    dt.use_loop_data = True
    dt.data_types_loops = {"CUSTOM_NORMAL"}
    dt.loop_mapping = "POLYINTERP_NEAREST"
    while ob.modifiers.find("DT_normals") > 0:
        with bpy.context.temp_override(object=ob, active_object=ob):
            bpy.ops.object.modifier_move_up(modifier="DT_normals")
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob], selected_editable_objects=[ob]):
        bpy.ops.object.modifier_apply(modifier="DT_normals")
    rig.data.pose_position = "POSE"
    return {"custom": ob.data.has_custom_normals}


def save_clean(path):
    vs = bpy.data.scenes.get("contoo_verify")
    if vs:
        for o in list(vs.objects):
            bpy.data.objects.remove(o, do_unlink=True)
    n = bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    bpy.ops.wm.save_as_mainfile(filepath=path, compress=True)
    return {"purged": n, "MB": round(os.path.getsize(path) / 1e6, 1)}
