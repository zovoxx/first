
"""Run in a background Blender: replace Body_mobile in a GameCharacters .blend with the fixed LOD body
(appended from a temp library), re-export <Name>_mobile.glb (rig + mobile body, rest pose, no animation), save."""
import bpy, os, sys, json
args = sys.argv[sys.argv.index("--") + 1:]
lib, obj_name, name, outdir, report = args
rig = bpy.data.objects[f"{name}_Rig"]
old = bpy.data.objects.get("Body_mobile")
info = {}
if old is not None:
    om = old.data
    info["old_nv"] = len(om.vertices)
    bpy.data.objects.remove(old, do_unlink=True)
    if om.users == 0:
        bpy.data.meshes.remove(om)
with bpy.data.libraries.load(lib, link=False) as (src, dst):
    dst.objects = [obj_name]
new = dst.objects[0]
bpy.context.scene.collection.objects.link(new)
new.name = "Body_mobile"
new.data.name = "Body_mobile"
new.parent = rig
new.matrix_parent_inverse = rig.matrix_world.inverted()
for m in list(new.modifiers):
    new.modifiers.remove(m)
mod = new.modifiers.new("Armature", "ARMATURE")
mod.object = rig
for img in bpy.data.images:
    if img.users and img.source == "FILE" and not img.packed_file:
        try:
            img.pack()
        except Exception:
            pass
bones = {b.name for b in rig.data.bones}
info["new_nv"] = len(new.data.vertices)
info["groups_ok"] = all(g.name in bones for g in new.vertex_groups)
info["groups"] = len(new.vertex_groups)
body = bpy.data.objects["Body"]
rig.data.pose_position = "REST"
for o in bpy.context.view_layer.objects:
    o.select_set(False)
body.hide_set(True)
rig.select_set(True)
new.select_set(True)
bpy.context.view_layer.objects.active = rig
path = os.path.join(outdir, f"{name}_mobile.glb")
bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_yup=True, export_apply=False,
                          export_image_format="JPEG", export_jpeg_quality=88)
body.hide_set(False)
rig.data.pose_position = "POSE"
info["glb_MB"] = round(os.path.getsize(path) / 1e6, 2)
bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
info["blend_MB"] = round(os.path.getsize(bpy.data.filepath) / 1e6, 2)
open(report, "w").write(json.dumps(info))
