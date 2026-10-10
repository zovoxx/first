"""Contoo asset manifest + pipeline backup (run inside Blender on Berk's PC)."""
import os, json, glob, shutil, struct
import numpy as np

H = os.path.expanduser("~")
CONTOO = os.path.join(H, "Documents", "Contoo")
A = os.path.join(CONTOO, "Assets")
W = os.path.join(os.environ["LOCALAPPDATA"], "Temp", "claude_charpipe")
CHARS = {
    "Kaya": {"title": "Kaya, the Desert Duelist", "biome": "desert", "weapon": "kaya_dagger", "hands": ["hand.R", "hand.L"], "height_m": 1.70},
    "Brumm": {"title": "Brumm Ironbeard, the Dwarf Forgemaster", "biome": "forge", "weapon": "brumm_hammer", "hands": ["hand.R"], "height_m": 1.30},
    "Volt": {"title": "Volt, the Neon Runner", "biome": "neon", "weapon": "volt_baton", "hands": ["hand.R"], "height_m": 1.78},
    "Wren": {"title": "Wren Mossveil, the Forest Warden", "biome": "forest", "weapon": "wren_bow", "hands": ["hand.L"], "height_m": 1.95},
    "Frostine": {"title": "Lady Frostine, the Ice Sorceress", "biome": "ice", "weapon": "frostine_staff", "hands": ["hand.R"], "height_m": 1.92},
}
LOOPS = {"idle", "run"}


def _rel(p):
    """Repo-relative path. Game-ready files point to their public/assets/ copy (served by Cloudflare);
    source-only files (.ply) stay under Assets/."""
    r = os.path.relpath(p, CONTOO).replace("\\", "/")
    if r.startswith("Assets/") and not r.endswith(".ply"):
        r = "public/assets/" + r[len("Assets/"):]
    return r


def _png_size(p):
    with open(p, "rb") as f:
        b = f.read(24)
    return list(struct.unpack(">II", b[16:24])) if b[:8] == b"\x89PNG\r\n\x1a\n" else None


def _glb(p):
    data = open(p, "rb").read()
    clen = struct.unpack("<I", data[12:16])[0]
    js = json.loads(data[20:20 + clen])
    tris = 0
    lo, hi = np.full(3, 1e9), np.full(3, -1e9)
    for m in js.get("meshes", []):
        for pr in m["primitives"]:
            if "indices" in pr:
                tris += js["accessors"][pr["indices"]]["count"] // 3
            acc = js["accessors"][pr["attributes"]["POSITION"]]
            lo = np.minimum(lo, acc.get("min", lo)); hi = np.maximum(hi, acc.get("max", hi))
    anims = {}
    acc = js.get("accessors", [])
    for a in js.get("animations", []):
        t = max(acc[s["input"]].get("max", [0])[0] for s in a["samplers"])
        anims[a["name"]] = round(t + 1.0 / 30.0, 3)
    return {"MB": round(len(data) / 1e6, 2), "tris": int(tris), "anims": anims,
            "bbox_min": [round(float(v), 3) for v in lo], "bbox_max": [round(float(v), 3) for v in hi]}


def attack_hit_times():
    """Seconds into each attack clip where the weapon hand moves fastest (≈ the moment of impact)."""
    import bpy
    out = {}
    for n, d in CHARS.items():
        sc = bpy.data.scenes.get(f"C_{n}")
        if sc is None:
            continue
        rig = bpy.data.objects[f"{n}_Rig"]
        ad = rig.animation_data
        tr = [t for t in ad.nla_tracks if t.name == "attack"][0]
        for t in ad.nla_tracks:
            t.mute = t.name != "attack"
        st = tr.strips[0]
        f0, f1 = int(st.frame_start), int(st.frame_end)
        bpy.context.window.scene = sc
        pts = []
        for f in range(f0, f1 + 1):
            sc.frame_set(f)
            pts.append(np.array(rig.matrix_world @ rig.pose.bones[d["hands"][0]].tail))
        for t in ad.nla_tracks:
            t.mute = False
        sc.frame_set(1)
        v = np.linalg.norm(np.diff(np.array(pts), axis=0), axis=1)
        k = int(np.argmax(v[2:-2]) + 2)
        out[n] = round((k + 0.5) / 30.0, 3)
    return out


def build(hit_times=None):
    man = {"game": "Contoo", "version": 1,
           "conventions": {"units": "metres", "gltf_up": "+Y", "character_forward_gltf": "+Z (rotate +-90 deg about Y to face left/right)",
                           "camera": "side view 2.5D; the camera looks across the character's left-right axis",
                           "fps_animations": 30, "platforms": {"pc": "files ending _PC", "mobile": "files ending _mobile"}},
           "characters": [], "weapons": [], "grounds": [], "backgrounds": [], "music": []}
    for n, d in CHARS.items():
        cd = os.path.join(A, "characters", n)
        pc, mb = os.path.join(cd, f"{n}_PC.glb"), os.path.join(cd, f"{n}_mobile.glb")
        gp, gm = _glb(pc), _glb(mb)
        meta = {}
        try:
            meta = json.load(open(os.path.join(W, f"anim_{n}.json")))
        except Exception:
            pass
        clips = {}
        for c, dur in gp["anims"].items():
            e = {"seconds": dur, "loop": c in LOOPS}
            if c == "run" and "run_speed_mps" in meta.get("run", {}):
                e["ground_speed_mps"] = meta["run"]["run_speed_mps"]
            if c == "jump" and "airborne_peak_m" in meta.get("jump", {}):
                e["note"] = "in place: the game moves the root (Kimodo peak %.2f m)" % meta["jump"]["airborne_peak_m"]
            if c == "attack" and hit_times and n in hit_times:
                e["hit_time_s"] = hit_times[n]
            clips[c] = e
        man["characters"].append({"id": n.lower(), "name": d["title"], "home_biome": d["biome"], "height_m": d["height_m"],
                                  "files": {"pc": _rel(pc), "mobile": _rel(mb)},
                                  "triangles": {"pc": gp["tris"], "mobile": gm["tris"]}, "MB": {"pc": gp["MB"], "mobile": gm["MB"]},
                                  "weapon": {"id": d["weapon"], "attached_to": d["hands"], "note": "already inside the character GLB"},
                                  "clips": clips})
    for p in sorted(glob.glob(os.path.join(A, "weapons", "*", "*_PC.glb"))):
        wid = os.path.basename(os.path.dirname(p))
        g = _glb(p)
        man["weapons"].append({"id": wid, "files": {"pc": _rel(p), "mobile": _rel(p.replace("_PC.glb", "_mobile.glb"))},
                               "length_m": round(g["bbox_max"][1] - g["bbox_min"][1], 3), "origin": "grip", "long_axis_gltf": "+Y",
                               "triangles": {"pc": g["tris"], "mobile": _glb(p.replace("_PC.glb", "_mobile.glb"))["tris"]}})
    for b in ("desert", "forge", "neon", "forest", "ice"):
        gj = json.load(open(os.path.join(A, "floors", b, f"{b}_ground.json")))
        f = gj["files"]
        man["grounds"].append({"biome": b, "files": {k: _rel(os.path.join(A, "floors", b, v)) for k, v in f.items()},
                               "gaussians": gj.get("gaussians"), "size_m": gj.get("size_m"), "top_surface_y": gj.get("top_surface_y", 0.0),
                               "walk_line": gj.get("walk_line"), "renderer": "Gaussian splats (e.g. Spark for three.js); collider = walk_line or collider GLB"})
        bd = os.path.join(A, "backgrounds", b)
        fp, mp = os.path.join(bd, f"{b}_far_PC.png"), os.path.join(bd, f"{b}_mid_PC.png")
        man["backgrounds"].append({"biome": b,
                                   "far": {"pc": _rel(fp), "mobile": _rel(os.path.join(bd, f"{b}_far_mobile.webp")), "size_pc": _png_size(fp),
                                           "tiles_horizontally": True, "suggested_parallax": 0.15},
                                   "mid": {"pc": _rel(mp), "mobile": _rel(os.path.join(bd, f"{b}_mid_mobile.webp")), "size_pc": _png_size(mp),
                                           "tiles_horizontally": True, "has_alpha": True, "anchor": "bottom", "suggested_parallax": 0.45}})
    for t in ("menu", "combat", "boss"):
        mj = json.load(open(os.path.join(W, f"music_{t}.json")))
        e = {"track": t, "bpm": round(mj["bpm"], 2), "loop_seconds": round(mj["loop_seconds"], 3), "seamless_loop": True, "files": {}}
        for plat in ("PC", "mobile"):
            for ext in ("ogg", "mp3"):
                p = os.path.join(A, "music", f"contoo_{t}_loop_{plat}.{ext}")
                if os.path.exists(p):
                    e["files"][f"{plat.lower()}_{ext}"] = _rel(p)
        man["music"].append(e)
    out = os.path.join(CONTOO, "contoo_assets.json")
    json.dump(man, open(out, "w", encoding="utf-8"), indent=1)
    web = os.path.join(CONTOO, "public", "assets", "contoo_assets.json")   # copy the browser can fetch
    if os.path.isdir(os.path.dirname(web)):
        shutil.copyfile(out, web)
    return out, man


def backup_pipeline():
    dst = os.path.join(CONTOO, "Pipeline")
    # Scripts run flat from W (they import each other); the repo keeps them sorted by pipeline stage.
    stages = {
        "0_shared": ("comfy_pipe.py", "conto_pipe.py", "wf_bundle.json", "contoo_concepts.json"),
        "1_characters_weapons": ("char_blender.py", "conto_weapons.py", "conto_lod.py", "conto_lod2.py", "conto_lod3.py",
                                 "gc_fix_mobile.py", "*_L.json"),
        "2_floors": ("conto_grounds.py", "ground_*.json"),
        "3_animations": ("conto_anim.py", "conto_anim_bl.py", "conto_regen.py", "kimodo_ctl.py", "motions.json", "rigs.json",
                         "anim_*.json", "grip_*.json"),
        "4_music": ("conto_music.py", "music_*.json"),
        "5_backgrounds": ("conto_blender.py",),
        "6_finish": ("conto_finish.py", "conto_verify.py", "conto_manifest.py", "probe_blend.py"),
    }
    n = 0
    for stage, pats in stages.items():
        os.makedirs(os.path.join(dst, stage), exist_ok=True)
        for pat in pats:
            for f in glob.glob(os.path.join(W, pat)):
                shutil.copyfile(f, os.path.join(dst, stage, os.path.basename(f))); n += 1
    os.makedirs(os.path.join(dst, "3_animations", "kimodo"), exist_ok=True)
    for f in glob.glob(os.path.join(W, "kimodo", "*.bvh")):
        shutil.copyfile(f, os.path.join(dst, "3_animations", "kimodo", os.path.basename(f))); n += 1
    return dst, n
