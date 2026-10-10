"""Contoo music: turn ACE-Step tracks into seamless, beat-aligned game loops (numpy + Blender's aud)."""
import os, json
import numpy as np

try:
    import aud
except ImportError:          # allows local testing of the numpy part
    aud = None


def load(path):
    s = aud.Sound(path)
    rate = int(s.specs[0])
    x = np.asarray(s.data(), dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    return x, rate


def onset_env(x, rate, hop=512, nfft=2048):
    m = x.mean(axis=1)
    n = 1 + (len(m) - nfft) // hop
    idx = np.arange(nfft)[None, :] + hop * np.arange(n)[:, None]
    win = np.hanning(nfft).astype(np.float32)
    S = np.abs(np.fft.rfft(m[idx] * win, axis=1)).astype(np.float32)
    L = np.log1p(100.0 * S)
    flux = np.maximum(L[1:] - L[:-1], 0).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    flux = flux - np.convolve(flux, np.ones(16) / 16, mode="same")       # remove slow trend
    return np.maximum(flux, 0), L, hop / rate, 0.5 * nfft / rate          # frame k is centred at k*dt + off


def beat_grid(flux, dt, bpm, off=0.0, span=0.015, nb=31, nph=64):
    """Best tempo (near bpm) and phase: maximise onset strength sampled on the beat grid."""
    best = (-1, bpm, 0.0)
    t = np.arange(len(flux)) * dt + off
    for b in np.linspace(bpm * (1 - span), bpm * (1 + span), nb):
        P = 60.0 / b
        for ph in np.linspace(0, P, nph, endpoint=False):
            k = np.arange(int((t[-1] - ph) / P))
            fr = np.round((ph + k * P - off) / dt).astype(int)
            fr = fr[(fr >= 0) & (fr < len(flux))]
            sc = flux[fr].mean()
            if sc > best[0]:
                best = (sc, b, ph)
    return {"bpm": float(best[1]), "phase_s": float(best[2]), "strength": float(best[0] / (flux.mean() + 1e-9))}


def _feat(L, dt, t0, t1, off=0.0):
    a, b = int((t0 - off) / dt), int((t1 - off) / dt)
    f = L[max(a, 0):max(b, a + 1)].mean(axis=0)
    return f / (np.linalg.norm(f) + 1e-9)


def find_loop(x, rate, bpm, beats_per_bar=4, min_bars=8, intro_bars=2, tail_s=4.0, fade_beats=1.0):
    flux, L, dt, off = onset_env(x, rate)
    g = beat_grid(flux, dt, bpm, off)
    P = 60.0 / g["bpm"]
    bar = P * beats_per_bar
    dur = len(x) / rate
    # outro detection: avoid the quiet tail / ending
    rms = np.sqrt(np.convolve((x.mean(axis=1) ** 2), np.ones(rate // 10) / (rate // 10), mode="same"))[:: rate // 10]
    med = np.median(rms)
    loud = np.where(rms > 0.5 * med)[0]
    end_ok = min(dur - tail_s, (loud[-1] / 10.0) - 1.0 if len(loud) else dur - tail_s)
    bars = g["phase_s"] + bar * np.arange(int(dur / bar) + 1)
    F = fade_beats * P
    best = None
    for i, A in enumerate(bars):
        if A < g["phase_s"] + intro_bars * bar or A - F < 0:
            continue
        for B in bars[i + min_bars:]:
            if B > end_ok:
                break
            # material that gets cross-faded: [A-F, A] vs [B-F, B]; plus what follows each point
            s1 = float(_feat(L, dt, A - F, A, off) @ _feat(L, dt, B - F, B, off))
            s2 = float(_feat(L, dt, A, A + 2 * P, off) @ _feat(L, dt, B, B + 2 * P, off))
            nb = round((B - A) / bar)
            score = 0.6 * s1 + 0.4 * s2 + 0.05 * min(1.0, (B - A) / (0.8 * dur)) + (0.02 if nb % 4 == 0 else 0.0)
            if best is None or score > best[0]:
                best = (score, A, B, s1, s2, nb)
    _, A, B, s1, s2, nb = best
    return {"A": A, "B": B, "bars": int(nb), "sim_fade": round(s1, 4), "sim_after": round(s2, 4), "grid": g, "fade_s": F, "end_ok": end_ok}


def make_loop(x, rate, A, B, F):
    a, b, f = int(round(A * rate)), int(round(B * rate)), int(round(F * rate))
    out = x[a:b].copy()
    pre = x[a - f:a]
    w = np.linspace(0.0, 1.0, f, dtype=np.float32)[:, None]
    g_in, g_out = np.sin(0.5 * np.pi * w), np.cos(0.5 * np.pi * w)
    out[-f:] = out[-f:] * g_out + pre * g_in
    pk = float(np.abs(out).max())
    gain = min(10 ** (-1.0 / 20) / max(pk, 1e-6), 4.0)            # peak -1 dBFS
    return out * gain, {"gain_db": round(20 * np.log10(gain), 2), "samples": int(len(out)),
                        "join_jump": float(np.abs(out[0] - out[-1]).max() * gain)}


def write(data, rate, path, fmt="ogg", kbps=192, mono=False):
    d = np.ascontiguousarray(data.mean(axis=1, keepdims=True) if mono else data, dtype=np.float32)
    snd = aud.Sound.buffer(d, rate)
    if fmt == "ogg":
        cont, codec = aud.CONTAINER_OGG, aud.CODEC_VORBIS
    elif fmt == "mp3":
        cont, codec = aud.CONTAINER_MP3, aud.CODEC_MP3
    else:
        cont, codec = aud.CONTAINER_WAV, aud.CODEC_PCM
    snd.write(path, rate, aud.CHANNELS_MONO if mono else aud.CHANNELS_STEREO, aud.FORMAT_S16, cont, codec, int(kbps * 1000), 0)
    return os.path.getsize(path)
