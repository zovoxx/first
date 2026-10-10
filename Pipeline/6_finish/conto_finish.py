"""Contoo finishing helpers (Blender side).

- A small job queue that runs one job per timer tick, so long work never blocks the MCP bridge.
- fix_death_weapon: world-upright weapons (bow, staff) tip over and lie flat while the character dies,
  instead of standing upright next to the body.
- export_char: PC + mobile GLBs (rig + body + weapon, all NLA clips) for one character scene.
- verify_glb / render_glb_frames: re-import an exported GLB and render side-view frames of chosen clips.
"""
import os, json, math, time, traceback
import numpy as np
import bpy
from mathutils import Matrix, Vector, Quaternion
from bpy_extras import anim_utils

W = os.path.join(os.environ["LOCALAPPDATA"], "Temp", "claude_charpipe")
ROOT = os.path.join(os.path.expanduser("~"), "Documents", "Contoo", "Assets")
Q = {"jobs": [], "done": [], "errors": [], "busy": False}


# ------------------------------------------------------------------ job queue
def _tick():
    if not Q["jobs"]:
        Q["busy"] = False
        return None
    name, fn, a, k = Q["jobs"].pop(0)
    t0 = time.time()
    try:
        res = fn(*a, **k)
        Q["done"].append([name, round(time.time() - t0, 1), res])
    except Exception:
        Q["errors"].append([name, traceback.format_exc()[-1500:]])
    return 0.05


def enqueue(name, fn, *a, **k):
    Q["jobs"].append((name, fn, a, k))
    if not bpy.app.timers.is_registered(_tick):
        Q["busy"] = True
        bpy.app.timers.register(_tick, first_interval=0.1)


def status(full=False):
    done = Q["done"] if full else [[d[0], d[1]] for d in Q["done"]]
    return {"busy": bool(Q["jobs"]) or bpy.app.timers.is_registered(_tick), "pending": [j[0] for j in Q["jobs"]],
            "done": done, "errors": Q["errors"]}


def result_of(name):
    for d in reversed(Q["done"]):
        if d[0] == name:
            return d[2]
    return None


# ------------------------------------------------------------------ NLA helpers
def _tracks(obj):
    ad = obj.animation_data
    return list(ad.nla_tracks) if ad else []


def solo(objs, track):
    for o in objs:
        for tr in _tracks(o):
            tr.mute = tr.name != track


def unsolo(objs):
    for o in objs:
        for tr in _tracks(o):
            tr.mute = False


def track_range(obj, track):
    tr = [t for t in _tracks(obj) if t.name == track][0]
    st = tr.strips[0]
    return int(st.frame_start), int(st.frame_end)


def _rot_about(axis, ang):
    return Matrix.Rotation(ang, 3, Vector(axis).normalized())


# ------------------------------------------------------------------ weapon death fall
def fix_death_weapon(scene_name, rig_name, weapon_names, bone, track="death", ref_track="idle", ref_frame=10):
    """Rebuild the weapon rotation keys of `track`: start in the weapon's world-upright orientation and,
    following the fall of the hips, tip over (direction = body direction at the end) and roll flat."""
    sc = bpy.data.scenes[scene_name]
    bpy.context.window.scene = sc
    rig = bpy.data.objects[rig_name]
    weps = [bpy.data.objects[n] for n in weapon_names]
    pb = rig.pose.bones[bone]
    # 1) upright world orientation, read from the weapon in the reference clip
    solo([rig] + weps, ref_track)
    r0, _ = track_range(rig, ref_track)
    sc.frame_set(r0 + ref_frame)
    Rw_up = weps[0].matrix_world.to_3x3().normalized()
    # 2) sample the death clip
    solo([rig] + weps, track)
    f0, f1 = track_range(rig, track)
    Mh, hips, head = [], [], []
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        Mh.append((rig.matrix_world @ pb.matrix).to_3x3().normalized())
        hips.append(np.array(rig.matrix_world @ rig.pose.bones["hips"].head))
        head.append(np.array(rig.matrix_world @ rig.pose.bones["head"].tail))
    hips, head = np.array(hips), np.array(head)
    h = hips[:, 2]
    drop = max(1e-4, h[0] - h.min())
    w = np.clip((h[0] - h) / drop, 0.0, 1.0)
    w = np.maximum.accumulate(w)
    w = w * w * (3.0 - 2.0 * w)
    # 3) flat end orientation: tip the long axis (+Z) toward the body direction, then roll X horizontal
    d = head[-1] - hips[-1]
    d[2] = 0.0
    d = d / np.linalg.norm(d) if np.linalg.norm(d) > 1e-4 else np.array([0.0, 1.0, 0.0])
    dv = Vector(d)
    z_up = Rw_up.col[2].copy()
    R_tip = z_up.rotation_difference(dv).to_matrix() @ Rw_up
    X = R_tip.col[0]
    up = Vector((0, 0, 1))
    a, b = X.dot(up), dv.cross(X).dot(up)
    phi = math.atan2(-a, b) if abs(b) > 1e-6 or abs(a) > 1e-6 else 0.0
    phi2 = phi + math.pi if phi < 0 else phi - math.pi
    if abs(phi2) < abs(phi):
        phi = phi2
    R_flat = _rot_about(dv, phi) @ R_tip
    q_up, q_flat = Rw_up.to_quaternion(), R_flat.to_quaternion()
    # 4) basis quaternions relative to the hand bone, written into each weapon's track action
    quats = []
    for i in range(len(Mh)):
        Rw = q_up.slerp(q_flat, float(w[i])).to_matrix()
        q = (Mh[i].transposed() @ Rw).to_quaternion()
        quats.append([q.w, q.x, q.y, q.z])
    quats = np.array(quats)
    for i in range(1, len(quats)):
        if np.dot(quats[i], quats[i - 1]) < 0:
            quats[i] *= -1
    frames = np.arange(f0, f1 + 1, dtype=np.float32)
    written = []
    for wo in weps:
        tr = [t for t in _tracks(wo) if t.name == track][0]
        st = tr.strips[0]
        act = st.action
        slot = getattr(st, "action_slot", None) or (act.slots[0] if len(act.slots) else None)
        cbag = anim_utils.action_ensure_channelbag_for_slot(act, slot)
        for fc in list(cbag.fcurves):
            if fc.data_path == "rotation_quaternion":
                cbag.fcurves.remove(fc)
        for k in range(4):
            fc = cbag.fcurves.new("rotation_quaternion", index=k)
            fc.keyframe_points.add(len(frames))
            co = np.empty(2 * len(frames), np.float32)
            co[0::2] = frames
            co[1::2] = quats[:, k]
            fc.keyframe_points.foreach_set("co", co)
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"
            fc.update()
        written.append(wo.name)
    unsolo([rig] + weps)
    sc.frame_set(1)
    return {"frames": [f0, f1], "fall_dir": [round(float(v), 3) for v in d], "phi_deg": round(math.degrees(phi), 1),
            "w_end": round(float(w[-1]), 3), "written": written}


# ------------------------------------------------------------------ exports
def export_char(name, out_root=None):
    import conto_anim_bl as cab
    out_root = out_root or os.path.join(ROOT, "characters")
    sc = bpy.data.scenes[f"C_{name}"]
    bpy.context.window.scene = sc
    rig = bpy.data.objects[f"{name}_Rig"]
    meshes = [o for o in sc.objects if o.type == "MESH"]
    pc = [o for o in meshes if not o.name.endswith("_mobile")]
    mob = [o for o in meshes if o.name.endswith("_mobile")]
    unsolo([rig] + meshes)
    rig.data.pose_position = "POSE"
    od = os.path.join(out_root, name)
    os.makedirs(od, exist_ok=True)
    res = {}
    for tag, objs in (("PC", pc), ("mobile", mob)):
        others = [o for o in meshes if o not in objs]
        for o in others:
            o.hide_set(True)
        for o in objs:
            o.hide_set(False)
        p = os.path.join(od, f"{name}_{tag}.glb")
        cab.export_character(rig, objs, p, mobile=(tag == "mobile"))
        res[tag] = cab.glb_summary(p)
        for o in others:
            o.hide_set(False)
    return res


# ------------------------------------------------------------------ verification renders
def _verify_scene():
    sc = bpy.data.scenes.get("contoo_verify") or bpy.data.scenes.new("contoo_verify")
    bpy.context.window.scene = sc
    for o in list(sc.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 12
    sc.cycles.use_denoising = False
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "Standard"
    w = bpy.data.worlds.get("contoo_verify_world") or bpy.data.worlds.new("contoo_verify_world")
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.55, 0.56, 0.6, 1.0)
    bg.inputs[1].default_value = 1.0
    sc.world = w
    cam_d = bpy.data.cameras.get("vf_cam") or bpy.data.cameras.new("vf_cam")
    cam_d.type = "ORTHO"
    cam = bpy.data.objects.new("vf_cam", cam_d)
    sc.collection.objects.link(cam)
    sun_d = bpy.data.lights.get("vf_sun") or bpy.data.lights.new("vf_sun", "SUN")
    sun_d.energy = 3.0
    sun = bpy.data.objects.new("vf_sun", sun_d)
    sc.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(55), math.radians(15), math.radians(60))
    sc.camera = cam
    return sc, cam


def import_glb(path):
    sc, cam = _verify_scene()
    before_o, before_a = set(bpy.data.objects), set(bpy.data.actions)
    bpy.ops.import_scene.gltf(filepath=path)
    objs = [o for o in bpy.data.objects if o not in before_o]
    acts = [a for a in bpy.data.actions if a not in before_a]
    rig = next(o for o in objs if o.type == "ARMATURE")
    info = {"objects": [[o.name, o.type, (o.parent.name + ":" + o.parent_bone) if o.parent and o.parent_bone else (o.parent.name if o.parent else None)] for o in objs],
            "actions": sorted(a.name for a in acts)}
    for o in objs:
        ad = o.animation_data
        if ad:
            info.setdefault("anim", {})[o.name] = {"action": ad.action.name if ad.action else None,
                                                   "tracks": [[t.name, [s.action.name for s in t.strips if s.action]] for t in ad.nla_tracks]}
    return sc, cam, rig, objs, acts, info


def _clip_actions(objs, acts, clip):
    """For every animated object, the imported action belonging to glTF animation `clip` (+ its slot)."""
    pick = {}
    for o in objs:
        ad = o.animation_data
        cands = []
        if ad:
            for t in ad.nla_tracks:
                for s in t.strips:
                    if s.action:
                        cands.append((t.name, s.action, getattr(s, "action_slot", None)))
            if ad.action:
                cands.append((ad.action.name, ad.action, getattr(ad, "action_slot", None)))
        for tname, act, slot in cands:
            base = act.name.split(".")[0]
            if tname == clip or base == clip or base.startswith(clip + "_") or act.name == clip:
                pick[o.name] = (act, slot)
                break
    return pick


def set_clip(objs, acts, clip):
    pick = _clip_actions(objs, acts, clip)
    for o in objs:
        ad = o.animation_data
        if not ad:
            continue
        for t in ad.nla_tracks:
            t.mute = True
        if o.name in pick:
            act, slot = pick[o.name]
            ad.action = act
            if slot is not None:
                try:
                    ad.action_slot = slot
                except Exception:
                    pass
        else:
            ad.action = None
    return {k: v[0].name for k, v in pick.items()}


def render_glb_frames(path, shots, out_prefix, res=(300, 420), ortho=2.6, cam_x=6.0, height=None):
    """shots: list of (clip, frame_fraction). Side view (camera on +X looking at -X, character faces left)."""
    sc, cam, rig, objs, acts, info = import_glb(path)
    meshes = [o for o in objs if o.type == "MESH"]
    zmax = max((o.matrix_world @ Vector(c)).z for o in meshes for c in o.bound_box)
    H = height or zmax
    cam.data.ortho_scale = max(ortho, H * 1.45)
    cam.location = (cam_x, 0.0, H * 0.5)
    cam.rotation_euler = (math.radians(90), 0, math.radians(90))
    sc.render.resolution_x, sc.render.resolution_y = res
    files = []
    used = {}
    for clip, frac in shots:
        used[clip] = set_clip(objs, acts, clip)
        act = rig.animation_data.action
        if act is None:
            continue
        a0, a1 = act.frame_range
        f = int(round(a0 + frac * (a1 - a0)))
        sc.frame_set(f)
        p = f"{out_prefix}_{clip}_{int(frac * 100):03d}.png"
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        files.append(p)
    info["used"] = used
    info["files"] = files
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)
    return info


def sheet(rows, out_path, cell_h=260, quality=86, label_px=0):
    """rows: list of lists of PNG paths -> one JPEG grid; returns base64."""
    import base64
    imgs = []
    for row in rows:
        r = []
        for p in row:
            im = bpy.data.images.load(p, check_existing=False)
            w, h = im.size
            cw = int(round(w * cell_h / h))
            im.scale(cw, cell_h)
            r.append(np.array(im.pixels[:], np.float32).reshape(cell_h, cw, 4))
            bpy.data.images.remove(im)
        imgs.append(r)
    width = max(sum(t.shape[1] for t in r) for r in imgs)
    canvas = np.ones((cell_h * len(imgs), width, 4), np.float32)
    canvas[..., :3] = 0.5
    for i, r in enumerate(imgs):
        y0 = (len(imgs) - 1 - i) * cell_h          # Blender pixel rows are bottom-up
        x = 0
        for t in r:
            canvas[y0:y0 + cell_h, x:x + t.shape[1]] = t
            x += t.shape[1]
    out = bpy.data.images.new("vsheet", width, canvas.shape[0], alpha=True)
    out.pixels.foreach_set(canvas.ravel())
    sc = bpy.context.scene
    fmt = sc.render.image_settings.file_format
    sc.render.image_settings.file_format = "JPEG"
    sc.render.image_settings.quality = quality
    out.save_render(out_path, scene=sc)
    sc.render.image_settings.file_format = fmt
    bpy.data.images.remove(out)
    return base64.b64encode(open(out_path, "rb").read()).decode()
