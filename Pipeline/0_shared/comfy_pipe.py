
import json, os, time, uuid, base64, urllib.request, urllib.parse
B = "http://127.0.0.1:8188"
WORK = os.path.join(os.environ["LOCALAPPDATA"], "Temp", "claude_charpipe")
OUT = r"C:\Users\zovox\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output"
INP = r"C:\Users\zovox\AppData\Local\Comfy-Desktop\ComfyUI-Shared\input"
BUNDLE = json.load(open(os.path.join(WORK, "wf_bundle.json")))
CLIENT = "claude-charpipe"

def _get(p, t=30):
    with urllib.request.urlopen(B + p, timeout=t) as r: return json.loads(r.read())
def _post(p, obj, t=30):
    req = urllib.request.Request(B + p, data=json.dumps(obj).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=t) as r: return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode()[:3000])

def submit(wf):
    return _post("/prompt", {"prompt": wf, "client_id": CLIENT})["prompt_id"]

def check(pid):
    h = _get("/history/" + pid)
    if pid not in h:
        q = _get("/queue")
        run = [x[1] for x in q.get("queue_running", [])]
        pend = [x[1] for x in q.get("queue_pending", [])]
        return {"state": "running" if pid in run else ("pending" if pid in pend else "unknown")}
    e = h[pid]
    st = e.get("status", {})
    files = []
    for nid, o in e.get("outputs", {}).items():
        for key, items in o.items():
            if not isinstance(items, list):
                continue
            for it in items:
                if isinstance(it, dict) and it.get("type", "output") == "output" and "filename" in it:
                    files.append(os.path.join(OUT, it.get("subfolder", ""), it["filename"]))
    msgs = [m for m in st.get("messages", []) if m[0] in ("execution_error", "execution_interrupted")]
    return {"state": st.get("status_str", "?"), "files": files, "errors": msgs[:1], "raw_keys": {k: list(v.keys()) for k, v in e.get("outputs", {}).items()}}

def zimage(prompt, seed, w=896, h=1152, prefix="chars/img"):
    wf = json.loads(json.dumps(BUNDLE["z"]))
    wf["57:27"]["inputs"]["text"] = prompt
    wf["57:3"]["inputs"]["seed"] = int(seed)
    wf["57:13"]["inputs"].update(width=w, height=h)
    wf["9"]["inputs"]["filename_prefix"] = prefix
    return submit(wf)

def to3d(image_rel, prefix, seed=None, faces=40000, tex=4096):
    wf = json.loads(json.dumps(BUNDLE["d3"]))
    wf["122"]["inputs"]["image"] = image_rel
    wf["186"]["inputs"]["target_face_count"] = faces
    wf["288"]["inputs"]["value"] = tex
    wf["322"]["inputs"]["filename_prefix"] = prefix
    if seed is not None:
        for n, off in (("3", 0), ("12", 1), ("18", 2), ("23", 3)):
            wf[n]["inputs"]["seed"] = int(seed) + off
    return submit(wf)

def stage_input(src_path, name):
    import shutil
    os.makedirs(os.path.join(INP, "chars"), exist_ok=True)
    dst = os.path.join(INP, "chars", name)
    shutil.copyfile(src_path, dst)
    return "chars/" + name

def thumb(path, max_side=512, quality=80):
    import bpy
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    s = max_side / max(w, h)
    img.scale(max(1, int(w * s)), max(1, int(h * s)))
    tmp = os.path.join(WORK, "thumb_" + uuid.uuid4().hex[:8] + ".jpg")
    sc = bpy.context.scene
    old = (sc.render.image_settings.file_format, sc.render.image_settings.quality)
    sc.render.image_settings.file_format = "JPEG"; sc.render.image_settings.quality = quality
    img.save_render(tmp, scene=sc)
    sc.render.image_settings.file_format, sc.render.image_settings.quality = old
    bpy.data.images.remove(img)
    data = base64.b64encode(open(tmp, "rb").read()).decode()
    os.remove(tmp)
    return data

def free():
    try: _post("/free", {"unload_models": True, "free_memory": True})
    except Exception as e: return str(e)
    return "ok"
