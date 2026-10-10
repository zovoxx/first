
"""Kimodo control for contoo: start/stop the bridge, batch generation in a background thread."""
import bpy, os, time, threading, importlib, traceback

K = {"start": None, "start_msg": "", "results": {}, "errors": {}, "busy": False, "current": None, "progress": "", "times": {}}


def _sc():
    return importlib.import_module("bl_ext.user_default.kimodo_blender_bridge.subprocess_client")


def start():
    sc = _sc()
    if sc.is_running():
        return "running"
    s = bpy.context.scene.kimodo
    py, model, off = s.python_executable, s.kimodo_model, s.use_offload
    K["start"] = None

    def _run():
        try:
            K["start"] = sc.start(py, model, use_offload=off,
                                  progress_callback=lambda m: K.__setitem__("start_msg", str(m)[-300:]))
        except Exception:
            K["start"] = (False, traceback.format_exc()[-800:])
    threading.Thread(target=_run, daemon=True).start()
    return "starting"


def stop():
    try:
        _sc().stop()
        return "stopped"
    except Exception as e:
        return str(e)


def status():
    sc = _sc()
    return {"running": sc.is_running(), "busy": K["busy"], "start": K["start"], "start_msg": K["start_msg"],
            "current": K["current"], "progress": K["progress"][-200:] if K["progress"] else "",
            "done": sorted(K["results"]), "errors": K["errors"], "times": K["times"]}


def generate_batch(jobs, tpose=True, steps=100):
    """jobs: list of (name, prompt, duration, seed); runs one after another in a background thread."""
    sc = _sc()
    K["busy"] = True

    def _run():
        for name, prompt, dur, seed in jobs:
            K["current"] = name
            t0 = time.time()
            try:
                ok, res = sc.generate_motion(prompt=prompt, duration=float(dur), seed=int(seed), output_format="bvh",
                                             constraints_json=None, diffusion_steps=steps, bvh_standard_tpose=tpose,
                                             progress_callback=lambda m: K.__setitem__("progress", str(m)))
                if ok:
                    K["results"][name] = res
                else:
                    K["errors"][name] = str(res)[-600:]
            except Exception:
                K["errors"][name] = traceback.format_exc()[-800:]
            K["times"][name] = round(time.time() - t0, 1)
        K["busy"] = False
        K["current"] = None
    threading.Thread(target=_run, daemon=True).start()
    return len(jobs)
