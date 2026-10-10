// WebAudio music (seamless loops with playbackRate ramp) + tiny synthesized SFX.

export function preferredMusicFormat() {
  const a = document.createElement('audio');
  return a.canPlayType('audio/ogg; codecs="vorbis"') ? 'ogg' : 'mp3';
}

export class AudioSystem {
  constructor(assets, settings) {
    this.assets = assets;
    this.settings = settings;
    this.format = preferredMusicFormat();
    const Ctx = window.AudioContext || window.webkitAudioContext;
    this.ctx = Ctx ? new Ctx() : null;
    this.buffers = new Map();
    this.current = null; // { track, source, gain }
    this.rate = 1;
    this.paused = false;
    if (this.ctx) {
      this.musicGain = this.ctx.createGain();
      this.sfxGain = this.ctx.createGain();
      this.musicGain.connect(this.ctx.destination);
      this.sfxGain.connect(this.ctx.destination);
      this.applyVolumes();
      this.noiseBuffer = this.makeNoise();
    }
    this.wantTrack = null;
  }

  applyVolumes() {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    this.musicGain.gain.setTargetAtTime(this.paused ? this.settings.music * 0.35 : this.settings.music, t, 0.05);
    this.sfxGain.gain.setTargetAtTime(this.settings.sfx, t, 0.05);
  }

  // Must be called from a user gesture (browsers block audio before one).
  unlock() {
    if (this.ctx && this.ctx.state === 'suspended') this.ctx.resume();
  }

  async preload(track, tracker) {
    if (!this.ctx || this.buffers.has(track)) return;
    const { bytes, def } = await this.assets.loadMusicBytes(track, this.format, tracker);
    // decodeAudioData detaches the buffer, so pass a copy (the bytes stay cached for retries).
    const buffer = await this.ctx.decodeAudioData(bytes.slice(0));
    this.buffers.set(track, { buffer, def });
  }

  play(track, { fade = 1.2, rate = this.rate } = {}) {
    if (!this.ctx) return;
    this.wantTrack = track;
    if (this.current?.track === track) return;
    const entry = this.buffers.get(track);
    if (!entry) {
      this.preload(track).then(() => {
        if (this.wantTrack === track) this.play(track, { fade, rate });
      });
      return;
    }
    const now = this.ctx.currentTime;
    const source = this.ctx.createBufferSource();
    source.buffer = entry.buffer;
    source.loop = true;
    const loopLen = entry.def.loop_seconds;
    source.loopStart = 0;
    source.loopEnd = Math.min(loopLen, entry.buffer.duration);
    source.playbackRate.value = rate;
    const gain = this.ctx.createGain();
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(1, now + fade);
    source.connect(gain).connect(this.musicGain);
    source.start(now);
    this.stopCurrent(fade);
    this.current = { track, source, gain };
    this.rate = rate;
  }

  stopCurrent(fade = 0.8) {
    if (!this.current) return;
    const { source, gain } = this.current;
    const now = this.ctx.currentTime;
    gain.gain.cancelScheduledValues(now);
    gain.gain.setValueAtTime(Math.max(gain.gain.value, 0.0001), now);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + fade);
    source.stop(now + fade + 0.05);
    this.current = null;
  }

  stop(fade = 0.8) {
    this.wantTrack = null;
    if (this.ctx) this.stopCurrent(fade);
  }

  // Music speeds up with the game (1.0 -> 1.2). The small pitch rise is intended.
  setRate(rate) {
    this.rate = rate;
    if (this.current) this.current.source.playbackRate.setTargetAtTime(rate, this.ctx.currentTime, 0.3);
  }

  setPaused(paused) {
    this.paused = paused;
    this.applyVolumes();
  }

  // ---- SFX (synthesized, no asset files needed) ----
  makeNoise() {
    const len = this.ctx.sampleRate * 0.6;
    const buf = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    return buf;
  }

  tone({ type = 'sine', f0 = 440, f1 = f0, dur = 0.15, vol = 0.3, delay = 0 }) {
    const c = this.ctx;
    const t = c.currentTime + delay;
    const o = c.createOscillator();
    const g = c.createGain();
    o.type = type;
    o.frequency.setValueAtTime(f0, t);
    o.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t + dur);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(vol, t + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(this.sfxGain);
    o.start(t);
    o.stop(t + dur + 0.02);
  }

  noise({ dur = 0.2, vol = 0.3, f0 = 1200, f1 = 400, q = 1, type = 'bandpass', delay = 0 }) {
    const c = this.ctx;
    const t = c.currentTime + delay;
    const s = c.createBufferSource();
    s.buffer = this.noiseBuffer;
    const f = c.createBiquadFilter();
    f.type = type;
    f.Q.value = q;
    f.frequency.setValueAtTime(f0, t);
    f.frequency.exponentialRampToValueAtTime(Math.max(30, f1), t + dur);
    const g = c.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(vol, t + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    s.connect(f).connect(g).connect(this.sfxGain);
    s.start(t);
    s.stop(t + dur + 0.02);
  }

  sfx(name) {
    if (!this.ctx || this.ctx.state !== 'running') return;
    switch (name) {
      case 'jump':
        this.tone({ type: 'sine', f0: 320, f1: 720, dur: 0.14, vol: 0.18 });
        break;
      case 'airjump':
        this.tone({ type: 'triangle', f0: 520, f1: 1100, dur: 0.16, vol: 0.16 });
        break;
      case 'dash':
        this.noise({ dur: 0.22, vol: 0.28, f0: 2600, f1: 500, q: 0.8 });
        this.tone({ type: 'sine', f0: 900, f1: 300, dur: 0.18, vol: 0.08 });
        break;
      case 'land':
        this.noise({ dur: 0.08, vol: 0.1, f0: 500, f1: 150, q: 0.7, type: 'lowpass' });
        break;
      case 'hurt':
        this.tone({ type: 'sawtooth', f0: 220, f1: 70, dur: 0.3, vol: 0.2 });
        this.noise({ dur: 0.18, vol: 0.25, f0: 1500, f1: 300, q: 0.6 });
        break;
      case 'warn':
        this.tone({ type: 'square', f0: 660, f1: 660, dur: 0.07, vol: 0.06 });
        this.tone({ type: 'square', f0: 880, f1: 880, dur: 0.07, vol: 0.06, delay: 0.09 });
        break;
      case 'spawn':
        this.noise({ dur: 0.35, vol: 0.22, f0: 300, f1: 2400, q: 1.2 });
        break;
      case 'swing':
        this.noise({ dur: 0.16, vol: 0.16, f0: 3000, f1: 900, q: 1.5 });
        break;
      case 'stagger':
        this.tone({ type: 'triangle', f0: 900, f1: 380, dur: 0.16, vol: 0.14 });
        break;
      case 'crumble':
        this.noise({ dur: 0.6, vol: 0.12, f0: 400, f1: 90, q: 0.5, type: 'lowpass' });
        break;
      case 'death':
        this.tone({ type: 'sine', f0: 600, f1: 60, dur: 0.9, vol: 0.25 });
        this.noise({ dur: 0.8, vol: 0.2, f0: 2000, f1: 100, q: 0.5 });
        break;
      case 'ui':
        this.tone({ type: 'sine', f0: 740, f1: 990, dur: 0.08, vol: 0.12 });
        break;
      default:
        break;
    }
  }
}
