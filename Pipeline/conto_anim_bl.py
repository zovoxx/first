"""Blender side of the Contoo animation step: write retargeted clips as actions/NLA tracks,
attach weapons to hand bones, export game GLBs (PC + mobile)."""
import os, json, math
import numpy as np
import bpy
from mathutils import Matrix, Vector
from bpy_extras import anim_utils

ROOT = os.path.join(os.path.expanduser("~"), "Documents", "Contoo", "Assets")


def rig_json(rig):
    bones = {}
    for b in rig.data.bones:
        bones[b.name] = {"parent": b.parent.name if b.parent else None, "head": list(b.head_local), "tail": list(b.tail_local),
                         "M": [list(r) for r in b.matrix_local]}
    return {"bones": bones}


def write_action(rig, name, order, basis, T, frame_start=1):
    F = len(basis)
    old = bpy.data.actions.get(name)
    if old:
        bpy.data.actions.remove(old)
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    ad = rig.animation_data or rig.animation_data_create()
    ad.action = act
    slot = ad.action_slot
    if slot is None:
        slot = act.slots.new(id_type="OBJECT", name=rig.name)
        ad.action_slot = slot
    cbag = anim_utils.action_ensure_channelbag_for_slot(act, slot)
    frames = np.arange(F, dtype=np.float32) + frame_start

    def put(dp, idx, vals, group):
        fc = cbag.fcurves.new(dp, index=idx)
        try:
            grp = cbag.groups.get(group) or cbag.groups.new(group)
            fc.group = grp
        except Exception:
            pass
        fc.keyframe_points.add(F)
        co = np.empty(2 * F, np.float32)
        co[0::2] = frames
        co[1::2] = vals
        fc.keyframe_points.foreach_set("co", co)
        fc.update()

    for k, bn in enumerate(order):
        rig.pose.bones[bn].rotation_mode = "QUATERNION"
        for i in range(4):
            put(f'pose.bones["{bn}"].rotation_quaternion', i, basis[:, k, i], bn)
    hb = rig.data.bones["hips"]
    R = np.array(hb.matrix_local)[:3, :3]
    loc = (np.asarray(T) - np.array(hb.head_local)) @ R
    for i in range(3):
        put('pose.bones["hips"].location', i, loc[:, i], "hips")
    act.frame_range = (frame_start, frame_start + F - 1)
    return act


def push_nla(rig, act, track_name):
    ad = rig.animation_data
    for tr in list(ad.nla_tracks):
        if tr.name == track_name:
            ad.nla_tracks.remove(tr)
    tr = ad.nla_tracks.new()
    tr.name = track_name
    st = tr.strips.new(track_name, int(act.frame_range[0]), act)
    if hasattr(st, "action_slot") and st.action_slot is None and len(act.slots):
        st.action_slot = act.slots[0]
    ad.action = None
    return tr


def clear_anim(rig):
    ad = rig.animation_data
    if ad:
        ad.action = None
        for tr in list(ad.nla_tracks):
            ad.nla_tracks.remove(tr)
    for pb in rig.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
        pb.scale = (1, 1, 1)


def weapon_rest_matrix(rig, bone_name, style, grip_frac=0.42, palm_off=0.018):
    """World matrix of the weapon (grip origin, local +Z = long axis) when the rig is in rest pose.
    style 'fist': long axis forward (-Y) perpendicular to the hand; local +X along the fingers.
    style 'staff': long axis back up along the forearm (opposite the fingers), local +X forward."""
    b = rig.data.bones[bone_name]
    M = rig.matrix_world @ b.matrix_local
    head = M.translation.copy()
    yh = (M.to_3x3() @ Vector((0, 1, 0))).normalized()
    fwd = Vector((0, -1, 0))
    if style == "staff":
        z = -yh
        x = (fwd - fwd.dot(z) * z).normalized()
    else:
        z = (fwd - fwd.dot(yh) * yh).normalized()
        x = (yh - yh.dot(z) * z).normalized()
    y = z.cross(x)
    side = 1.0 if head.x > 0 else -1.0
    palm = Vector((-side, 0, 0))                          # palms face the body in the A-pose
    palm = (palm - palm.dot(yh) * yh).normalized()
    pos = head + yh * (b.length * grip_frac) + palm * palm_off
    R = Matrix((x, y, z)).transposed()
    W = R.to_4x4()
    W.translation = pos
    return W


def attach_weapon(rig, bone_name, wobj, style, **kw):
    pp = rig.data.pose_position
    rig.data.pose_position = "REST"
    bpy.context.view_layer.update()
    W = weapon_rest_matrix(rig, bone_name, style, **kw)
    wobj.parent = rig
    wobj.parent_type = "BONE"
    wobj.parent_bone = bone_name
    pb = rig.pose.bones[bone_name]
    P = rig.matrix_world @ pb.matrix @ Matrix.Translation((0, rig.data.bones[bone_name].length, 0))
    wobj.matrix_parent_inverse = Matrix.Identity(4)
    wobj.matrix_basis = P.inverted() @ W
    rig.data.pose_position = pp
    bpy.context.view_layer.update()
    return W


def export_character(rig, meshes, path, mobile=False):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    rig.select_set(True)
    for m in meshes:
        m.hide_set(False)
        m.select_set(True)
    bpy.context.view_layer.objects.active = rig
    rig.data.pose_position = "POSE"
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, use_active_scene=True,
                              export_skins=True, export_animations=True, export_animation_mode="NLA_TRACKS",
                              export_anim_slide_to_zero=True, export_force_sampling=True, export_frame_step=1,
                              export_reset_pose_bones=True, export_optimize_animation_size=False,
                              export_def_bones=False, export_morph=False, export_yup=True, export_apply=False,
                              export_image_format="JPEG", export_jpeg_quality=(85 if mobile else 92))
    return os.path.getsize(path)


def glb_summary(path):
    import struct
    data = open(path, "rb").read()
    clen = struct.unpack("<I", data[12:16])[0]
    js = json.loads(data[20:20 + clen])
    acc = js.get("accessors", [])
    anims = []
    for a in js.get("animations", []):
        t = 0.0
        for s in a.get("samplers", []):
            mx = acc[s["input"]].get("max", [0])[0]
            t = max(t, mx)
        anims.append([a.get("name"), round(t, 3), len(a.get("channels", []))])
    return {"MB": round(len(data) / 1e6, 2), "scenes": len(js.get("scenes", [])), "nodes": len(js.get("nodes", [])),
            "meshes": [m.get("name") for m in js.get("meshes", [])], "skins": len(js.get("skins", [])),
            "animations": anims, "images": len(js.get("images", []))}


# ---------------------------------------------------------------- grip optimisation
def hand_frames(rig, bone, samples):
    """World 3x3 rotation of a pose bone for (track, frame) samples (other NLA tracks muted)."""
    sc = bpy.context.scene
    ad = rig.animation_data
    out = []
    for track, frame in samples:
        for tr in ad.nla_tracks:
            tr.mute = tr.name != track
        sc.frame_set(frame)
        M = rig.matrix_world @ rig.pose.bones[bone].matrix
        out.append(np.array(M.to_3x3()))
    for tr in ad.nla_tracks:
        tr.mute = False
    sc.frame_set(1)
    return out


def peak_frame(rig, bone, track, axis=(0, -1, 0)):
    """Frame of `track` where the bone tail reaches furthest along `axis` (e.g. the punch/thrust peak)."""
    sc = bpy.context.scene
    ad = rig.animation_data
    for tr in ad.nla_tracks:
        tr.mute = tr.name != track
    st = [s for tr in ad.nla_tracks if tr.name == track for s in tr.strips][0]
    best = None
    a = Vector(axis)
    for f in range(int(st.frame_start), int(st.frame_end) + 1):
        sc.frame_set(f)
        t = rig.matrix_world @ rig.pose.bones[bone].tail
        v = t.dot(a)
        if best is None or v > best[0]:
            best = (v, f)
    for tr in ad.nla_tracks:
        tr.mute = False
    sc.frame_set(1)
    return best[1]


def best_grip(rig, bone, goals, n=2500, nroll=36):
    """goals: list of dicts {track, frame, w, z: world vec or None, z_abs: bool, x: world vec or None, wx}.
    Returns 3x3 R (columns = weapon X, Y, Z axes expressed in the bone's local frame)."""
    Ms = hand_frames(rig, bone, [(g["track"], g["frame"]) for g in goals])
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = np.pi * (1 + 5 ** 0.5) * i
    Z = np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], axis=1)
    ref = np.where(np.abs(Z[:, 2:3]) < 0.9, np.array([[0, 0, 1.0]]), np.array([[1.0, 0, 0]]))
    U = np.cross(Z, ref); U /= np.linalg.norm(U, axis=1, keepdims=True)
    V = np.cross(Z, U)
    best = (-1e9, None)
    for r in np.linspace(0, 2 * np.pi, nroll, endpoint=False):
        X = np.cos(r) * U + np.sin(r) * V
        score = np.zeros(n)
        for g, M in zip(goals, Ms):
            if g.get("z") is not None:
                zw = Z @ M.T
                d = zw @ np.asarray(g["z"], float) / np.linalg.norm(g["z"])
                score += g.get("w", 1.0) * (np.abs(d) if g.get("z_abs") else d)
            if g.get("x") is not None:
                xw = X @ M.T
                score += g.get("wx", 1.0) * (xw @ np.asarray(g["x"], float) / np.linalg.norm(g["x"]))
        k = int(np.argmax(score))
        if score[k] > best[0]:
            best = (float(score[k]), (X[k], np.cross(Z[k], X[k]), Z[k]))
    X, Y, Zv = best[1]
    return np.stack([X, Y, Zv], axis=1), best[0]


def attach_weapon_local(rig, bone_name, wobj, R_local, grip_frac=0.42, palm_off=0.018):
    """Parent wobj to the bone with weapon axes R_local (in the bone's local frame) and the grip in the palm."""
    pp = rig.data.pose_position
    rig.data.pose_position = "REST"
    bpy.context.view_layer.update()
    b = rig.data.bones[bone_name]
    M = rig.matrix_world @ b.matrix_local
    head = M.translation.copy()
    yh = (M.to_3x3() @ Vector((0, 1, 0))).normalized()
    side = 1.0 if head.x > 0 else -1.0
    palm = Vector((-side, 0, 0))
    palm = (palm - palm.dot(yh) * yh).normalized()
    pos = head + yh * (b.length * grip_frac) + palm * palm_off
    Rw = M.to_3x3() @ Matrix([list(r) for r in R_local])
    Wm = Rw.to_4x4()
    Wm.translation = pos
    wobj.parent = rig
    wobj.parent_type = "BONE"
    wobj.parent_bone = bone_name
    pb = rig.pose.bones[bone_name]
    P = rig.matrix_world @ pb.matrix @ Matrix.Translation((0, b.length, 0))
    wobj.matrix_parent_inverse = Matrix.Identity(4)
    wobj.matrix_basis = P.inverted() @ Wm
    rig.data.pose_position = pp
    bpy.context.view_layer.update()
    return Wm


# ---------------------------------------------------------------- per-clip weapon orientation
def axes_local(rig, bone_name, style):
    """Weapon axes in the bone's local frame for a named rest-pose style ('fist' or 'staff')."""
    W = weapon_rest_matrix(rig, bone_name, style)
    b = rig.data.bones[bone_name]
    M = (rig.matrix_world @ b.matrix_local).to_3x3()
    return np.array(M.transposed() @ W.to_3x3())


def _smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def weapon_clip_anim(rig, wobj, bone_name, R_default, R_attack=None, attack_track="attack", peak=None,
                     grip_frac=0.42, palm_off=0.018):
    """Give the weapon its own per-clip rotation in the hand (one NLA track per rig track, same names):
    R_default everywhere, easing into R_attack around the attack peak and back out."""
    from mathutils import Quaternion
    attach_weapon_local(rig, bone_name, wobj, R_default, grip_frac, palm_off)
    loc = wobj.matrix_basis.to_translation()
    q0 = Matrix([list(r) for r in R_default]).to_quaternion()
    q1 = Matrix([list(r) for r in R_attack]).to_quaternion() if R_attack is not None else None
    wobj.rotation_mode = "QUATERNION"
    ad = wobj.animation_data or wobj.animation_data_create()
    for tr in list(ad.nla_tracks):
        ad.nla_tracks.remove(tr)
    for tr in rig.animation_data.nla_tracks:
        st = tr.strips[0]
        f0, f1 = int(st.frame_start), int(st.frame_end)
        F = f1 - f0 + 1
        name = f"{wobj.name}_{tr.name}"
        old = bpy.data.actions.get(name)
        if old:
            bpy.data.actions.remove(old)
        act = bpy.data.actions.new(name)
        act.use_fake_user = True
        ad.action = act
        slot = ad.action_slot
        if slot is None:
            slot = act.slots.new(id_type="OBJECT", name=wobj.name)
            ad.action_slot = slot
        cbag = anim_utils.action_ensure_channelbag_for_slot(act, slot)
        fr = np.arange(f0, f1 + 1, dtype=np.float32)
        quats = []
        for f in range(f0, f1 + 1):
            w = 0.0
            if q1 is not None and tr.name == attack_track and peak:
                t = (f - f0) / max(1, F - 1)
                tp = (peak - f0) / max(1, F - 1)
                rise = _smooth(t / max(1e-3, 0.6 * tp))
                fall = 1.0 - _smooth((t - (tp + 0.3 * (1 - tp))) / max(1e-3, 0.7 * (1 - tp)))
                w = min(rise, fall)
            q = q0.slerp(q1, w) if w > 0 else q0
            quats.append([q.w, q.x, q.y, q.z])
        quats = np.array(quats)
        for i in range(1, len(quats)):
            if np.dot(quats[i], quats[i - 1]) < 0:
                quats[i] *= -1
        for i in range(4):
            fc = cbag.fcurves.new("rotation_quaternion", index=i)
            fc.keyframe_points.add(F)
            co = np.empty(2 * F, np.float32); co[0::2] = fr; co[1::2] = quats[:, i]
            fc.keyframe_points.foreach_set("co", co); fc.update()
        for i in range(3):
            fc = cbag.fcurves.new("location", index=i)
            fc.keyframe_points.add(F)
            co = np.empty(2 * F, np.float32); co[0::2] = fr; co[1::2] = loc[i]
            fc.keyframe_points.foreach_set("co", co); fc.update()
        act.frame_range = (f0, f1)
        ntr = ad.nla_tracks.new()
        ntr.name = tr.name
        s = ntr.strips.new(tr.name, f0, act)
        if hasattr(s, "action_slot") and s.action_slot is None and len(act.slots):
            s.action_slot = act.slots[0]
        ad.action = None
    return len(ad.nla_tracks)


def weapon_clip_anim_world(rig, wobj, bone_name, R_world, R_attack=None, attack_track="attack", peak=None,
                           grip_frac=0.42, palm_off=0.018):
    """Like weapon_clip_anim, but outside the attack the weapon keeps a fixed WORLD orientation R_world
    (e.g. a staff held upright) while staying gripped in the palm; in the attack it eases into the rigid
    hand grip R_attack (bone-local) around the peak."""
    sc = bpy.context.scene
    attach_weapon_local(rig, bone_name, wobj, np.eye(3), grip_frac, palm_off)
    loc = wobj.matrix_basis.to_translation()
    q1 = Matrix([list(r) for r in R_attack]).to_quaternion() if R_attack is not None else None
    Rw = Matrix([list(r) for r in R_world])
    wobj.rotation_mode = "QUATERNION"
    ad = wobj.animation_data or wobj.animation_data_create()
    for tr in list(ad.nla_tracks):
        ad.nla_tracks.remove(tr)
    rad = rig.animation_data
    tracks = [(tr.name, int(tr.strips[0].frame_start), int(tr.strips[0].frame_end)) for tr in rad.nla_tracks]
    for tname, f0, f1 in tracks:
        for tr in rad.nla_tracks:
            tr.mute = tr.name != tname
        F = f1 - f0 + 1
        quats = []
        for f in range(f0, f1 + 1):
            sc.frame_set(f)
            Mh = (rig.matrix_world @ rig.pose.bones[bone_name].matrix).to_3x3()
            qd = (Mh.transposed() @ Rw).to_quaternion()
            w = 0.0
            if q1 is not None and tname == attack_track and peak:
                t = (f - f0) / max(1, F - 1)
                tp = (peak - f0) / max(1, F - 1)
                rise = _smooth(t / max(1e-3, 0.6 * tp))
                fall = 1.0 - _smooth((t - (tp + 0.3 * (1 - tp))) / max(1e-3, 0.7 * (1 - tp)))
                w = min(rise, fall)
            q = qd.slerp(q1, w) if w > 0 else qd
            quats.append([q.w, q.x, q.y, q.z])
        quats = np.array(quats)
        for i in range(1, len(quats)):
            if np.dot(quats[i], quats[i - 1]) < 0:
                quats[i] *= -1
        name = f"{wobj.name}_{tname}"
        old = bpy.data.actions.get(name)
        if old:
            bpy.data.actions.remove(old)
        act = bpy.data.actions.new(name)
        act.use_fake_user = True
        ad.action = act
        slot = ad.action_slot
        if slot is None:
            slot = act.slots.new(id_type="OBJECT", name=wobj.name)
            ad.action_slot = slot
        cbag = anim_utils.action_ensure_channelbag_for_slot(act, slot)
        fr = np.arange(f0, f1 + 1, dtype=np.float32)
        for i in range(4):
            fc = cbag.fcurves.new("rotation_quaternion", index=i)
            fc.keyframe_points.add(F)
            co = np.empty(2 * F, np.float32); co[0::2] = fr; co[1::2] = quats[:, i]
            fc.keyframe_points.foreach_set("co", co); fc.update()
        for i in range(3):
            fc = cbag.fcurves.new("location", index=i)
            fc.keyframe_points.add(F)
            co = np.empty(2 * F, np.float32); co[0::2] = fr; co[1::2] = loc[i]
            fc.keyframe_points.foreach_set("co", co); fc.update()
        act.frame_range = (f0, f1)
        ntr = ad.nla_tracks.new()
        ntr.name = tname
        s = ntr.strips.new(tname, f0, act)
        if hasattr(s, "action_slot") and s.action_slot is None and len(act.slots):
            s.action_slot = act.slots[0]
        ad.action = None
    for tr in rad.nla_tracks:
        tr.mute = False
    sc.frame_set(1)
    return len(ad.nla_tracks)
