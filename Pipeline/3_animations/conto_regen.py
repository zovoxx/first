"""Regenerate one Kimodo clip for all Contoo characters: score candidate BVHs, retarget the best one onto
every rig and replace that clip's NLA track (weapon tracks are refreshed by conto_finish.fix_death_weapon)."""
import os, json
import numpy as np
import bpy

W = os.path.join(os.environ["LOCALAPPDATA"], "Temp", "claude_charpipe")
CHARS = ("Kaya", "Brumm", "Volt", "Wren", "Frostine")


def analyse_fall(path):
    """How a death take falls, in the BVH frame (Y up). back = 1 means the body ends lying straight
    behind where the character was facing (best for a side-view camera); side = sideways share."""
    import conto_anim as ca
    b = ca.parse_bvh(open(path, encoding="utf-8").read())
    Rg, Pg = ca.fk(b)
    J = {n: i for i, n in enumerate(b["joints"])}
    f0 = Rg[0, J["Hips"]] @ np.array([0.0, 0.0, 1.0])
    f0[1] = 0.0
    f0 /= np.linalg.norm(f0)
    side_ax = np.cross([0.0, 1.0, 0.0], f0)
    hips, head = Pg[:, J["Hips"]], Pg[:, J["Head"]]
    v = head[-1] - hips[-1]
    v[1] = 0.0
    L = np.linalg.norm(v) + 1e-9
    tail = Pg[-12:, :, :]
    still = float(np.abs(np.diff(tail, axis=0)).max())          # cm per frame at the end
    return {"back": round(float(v @ -f0 / L), 3), "side": round(float(abs(v @ side_ax) / L), 3),
            "head_end_cm": round(float(head[-1, 1]), 1), "hips_end_cm": round(float(hips[-1, 1]), 1),
            "still_cm": round(still, 2), "frames": int(len(Pg)), "fps": round(float(b["fps"]), 2)}


def pick_best(results):
    """results: {name: (path, analysis)} -> best name: lying, still, falling backward."""
    best, score_best = None, -1e9
    for name, (path, a) in results.items():
        lying = a["head_end_cm"] < 35
        s = 2.0 * a["back"] - 1.0 * a["side"] - 0.02 * a["still_cm"] + (1.0 if lying else -3.0)
        if s > score_best:
            best, score_best = name, s
    return best, round(score_best, 3)


def replace_clip(name, clip, bvh_path):
    import conto_anim as ca
    import conto_anim_bl as cab
    rigs = json.load(open(os.path.join(W, "rigs.json")))
    order, rig = ca.rig_from_json(rigs[name])
    basis, T, info = ca.process_clip(open(bvh_path, encoding="utf-8").read(), order, rig, clip)
    sc = bpy.data.scenes[f"C_{name}"]
    bpy.context.window.scene = sc
    rob = bpy.data.objects[f"{name}_Rig"]
    old = [t for t in rob.animation_data.nla_tracks if t.name == clip]
    old_len = int(old[0].strips[0].frame_end) if old else None
    act = cab.write_action(rob, f"{name}_{clip}", order, basis, T)
    cab.push_nla(rob, act, clip)
    # keep each anim json up to date
    p = os.path.join(W, f"anim_{name}.json")
    try:
        meta = json.load(open(p))
    except Exception:
        meta = {}
    meta[clip] = info
    json.dump(meta, open(p, "w"), indent=1)
    return {"frames": int(len(basis)), "old_frames": old_len, "info": {k: info[k] for k in ("duration_s", "max_lift", "ground_dz")}}
