// Loading helpers: the asset list (contoo_assets.json), PC/mobile choice, GLBs with progress.
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const params = new URLSearchParams(location.search);

/** "pc" or "mobile". Override with ?q=pc or ?q=mobile. */
export const PLATFORM = (() => {
  const q = params.get('q');
  if (q === 'pc' || q === 'mobile') return q;
  const mobileUA = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const touchOnly = matchMedia('(pointer: coarse)').matches && !matchMedia('(pointer: fine)').matches;
  return mobileUA || touchOnly ? 'mobile' : 'pc';
})();

/** Show on-screen buttons. Override with ?touch=1. */
export const TOUCH = params.get('touch') === '1' || matchMedia('(pointer: coarse)').matches;

/** Paths in the asset list are repo-relative ("public/assets/..."); the site serves public/ as its root. */
export const webPath = (p) => p.replace(/^public\//, '');

export async function loadManifest() {
  const res = await fetch('assets/contoo_assets.json');
  if (!res.ok) throw new Error(`asset list: HTTP ${res.status}`);
  return res.json();
}

/** Fetch a file as an ArrayBuffer, reporting progress 0..1. */
export async function fetchBytes(url, onProgress) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  const total = Number(res.headers.get('content-length')) || 0;
  if (!res.body || !total) {
    const buf = await res.arrayBuffer();
    onProgress?.(1);
    return buf;
  }
  const reader = res.body.getReader();
  const chunks = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    got += value.length;
    onProgress?.(Math.min(1, got / total));
  }
  const out = new Uint8Array(got);
  let o = 0;
  for (const c of chunks) { out.set(c, o); o += c.length; }
  onProgress?.(1);
  return out.buffer;
}

const gltfLoader = new GLTFLoader();
const gltfCache = new Map();

export function loadGLTF(url, onProgress) {
  if (gltfCache.has(url)) {
    onProgress?.(1);
    return gltfCache.get(url);
  }
  const base = url.slice(0, url.lastIndexOf('/') + 1);
  const p = fetchBytes(url, onProgress).then((buf) => gltfLoader.parseAsync(buf, base));
  p.catch(() => gltfCache.delete(url));
  gltfCache.set(url, p);
  return p;
}

/** Combines several weighted 0..1 progress values into one. */
export class Progress {
  constructor(onChange) {
    this.parts = [];
    this.onChange = onChange;
  }
  part(weight = 1) {
    const p = { weight, value: 0 };
    this.parts.push(p);
    return (v) => { p.value = v; this.emit(); };
  }
  emit() {
    const total = this.parts.reduce((s, p) => s + p.weight, 0) || 1;
    this.onChange(this.parts.reduce((s, p) => s + p.weight * p.value, 0) / total);
  }
}
