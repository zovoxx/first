
import bpy, json, sys
out = {"scenes": [s.name for s in bpy.data.scenes], "objects": {}}
for o in bpy.data.objects:
    e = {"type": o.type, "parent": o.parent.name if o.parent else None, "users_scene": [s.name for s in o.users_scene]}
    if o.type == "MESH":
        e.update(nv=len(o.data.vertices), vg=len(o.vertex_groups), mods=[[m.type, getattr(getattr(m, "object", None), "name", None)] for m in o.modifiers],
                 mats=[m.name if m else None for m in o.data.materials])
    if o.type == "ARMATURE":
        e.update(bones=[b.name for b in o.data.bones])
    out["objects"][o.name] = e
open(sys.argv[-1], "w").write(json.dumps(out))
