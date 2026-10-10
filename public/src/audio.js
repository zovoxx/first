// Seamless music loops (Web Audio) plus a few synthesized hit sounds.
import { webPath } from './assets.js';

const VOLUME = 0.5;
const MUTE_KEY = 'muted';

export class Music {
  constructor(tracks, platform) {
    this.tracks = tracks;
    this.platform = platform;
    this.ctx = null;
    this.cache = new Map();
    this.current = null;
    this.wanted = null;
    this.oggFirst = new Audio().canPlayType('audio/ogg; codecs="vorbis"') !== '';
    try { this.muted = localStorage.getItem(MUTE_KEY) === '1'; } catch { this.muted = false; }
  }

  /** Browsers only allow audio after a user gesture: call this from one. */
  unlock() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      this.ctx = new AC();
      this.master = this.ctx.createGain();
      this.master.gain.value = this.muted ? 0 : VOLUME;
      this.master.connect(this.ctx.destination);
      if (this.wanted) this.play(this.wanted);
    }
    if (this.ctx.state === 'suspended') this.ctx.resume();
  }

  urls(name) {
    const t = this.tracks.find((x) => x.track === name);
    if (!t) return [];
    const f = t.files;
    const p = this.platform;
    const order = this.oggFirst ? [f[`${p}_ogg`], f[`${p}_mp3`]] : [f[`${p}_mp3`], f[`${p}_ogg`]];
    return order.filter(Boolean).map(webPath);
  }

  load(name) {
    if (!this.ctx) return Promise.resolve(null);
    if (!this.cache.has(name)) {
      this.cache.set(name, (async () => {
        for (const url of this.urls(name)) {
          try {
            const res = await fetch(url);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return await this.ctx.decodeAudioData(await res.arrayBuffer());
          } catch (err) {
            console.warn('music', url, err);
          }
        }
        return null;
      })());
    }
    return this.cache.get(name);
  }

  async play(name) {
    this.wanted = name;
    if (!this.ctx || this.current?.name === name) return;
    const buffer = await this.load(name);
    if (!buffer || this.wanted !== name || this.current?.name === name) return;
    const ctx = this.ctx;
    const loopSeconds = this.tracks.find((x) => x.track === name)?.loop_seconds;
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.loop = true;
    if (loopSeconds && loopSeconds < buffer.duration) src.loopEnd = loopSeconds;
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0, ctx.currentTime);
    gain.gain.linearRampToValueAtTime(1, ctx.currentTime + 0.8);
    src.connect(gain).connect(this.master);
    src.start();
    this.fadeOutCurrent(0.6);
    this.current = { name, src, gain };
  }

  fadeOutCurrent(seconds) {
    const c = this.current;
    if (!c) return;
    const t = this.ctx.currentTime;
    c.gain.gain.cancelScheduledValues(t);
    c.gain.gain.setValueAtTime(c.gain.gain.value, t);
    c.gain.gain.linearRampToValueAtTime(0, t + seconds);
    c.src.stop(t + seconds + 0.05);
    this.current = null;
  }

  toggleMute() {
    this.muted = !this.muted;
    try { localStorage.setItem(MUTE_KEY, this.muted ? '1' : '0'); } catch { /* private mode */ }
    if (this.master) this.master.gain.value = this.muted ? 0 : VOLUME;
    return this.muted;
  }

  /** Short synthesized effects: "hit", "swing", "ko". */
  sfx(kind) {
    const ctx = this.ctx;
    if (!ctx || this.muted) return;
    const t = ctx.currentTime;
    const out = ctx.createGain();
    out.connect(ctx.destination);
    if (kind === 'swing') {
      noise(ctx, out, t, 0.18, 1800, 'bandpass');
      out.gain.setValueAtTime(0.0001, t);
      out.gain.exponentialRampToValueAtTime(0.18, t + 0.05);
      out.gain.exponentialRampToValueAtTime(0.0001, t + 0.18);
      return;
    }
    const heavy = kind === 'ko';
    noise(ctx, out, t, heavy ? 0.45 : 0.2, heavy ? 900 : 1400, 'lowpass');
    const osc = ctx.createOscillator();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(heavy ? 140 : 190, t);
    osc.frequency.exponentialRampToValueAtTime(45, t + (heavy ? 0.4 : 0.18));
    osc.connect(out);
    osc.start(t);
    osc.stop(t + 0.5);
    out.gain.setValueAtTime(heavy ? 0.6 : 0.45, t);
    out.gain.exponentialRampToValueAtTime(0.0001, t + (heavy ? 0.5 : 0.22));
  }
}

function noise(ctx, dest, t, seconds, freq, type) {
  const len = Math.ceil(ctx.sampleRate * seconds);
  const buf = ctx.createBuffer(1, len, ctx.sampleRate);
  const d = buf.getChannelData(0);
  for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / len);
  const src = ctx.createBufferSource();
  src.buffer = buf;
  const f = ctx.createBiquadFilter();
  f.type = type;
  f.frequency.value = freq;
  src.connect(f).connect(dest);
  src.start(t);
}
