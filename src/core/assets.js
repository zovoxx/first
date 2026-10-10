import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { PackedSplats } from '@sparkjsdev/spark';
import { MANIFEST_PATH } from '../config.js';

const BASE = import.meta.env.BASE_URL;

// Weighted progress over many parallel downloads.
export class LoadTracker {
  constructor(onProgress) {
    this.items = [];
    this.onProgress = onProgress || (() => {});
  }
  add(weight = 1) {
    const item = { weight, done: 0 };
    this.items.push(item);
    this.emit();
    return (fraction) => {
      item.done = Math.max(item.done, Math.min(1, fraction));
      this.emit();
    };
  }
  emit() {
    let total = 0;
    let done = 0;
    for (const it of this.items) {
      total += it.weight;
      done += it.weight * it.done;
    }
    this.onProgress(total > 0 ? done / total : 0);
  }
}

async function fetchBytes(url, onProgress) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${url}`);
  const total = Number(res.headers.get('content-length')) || 0;
  if (!res.body || !total) {
    const buf = await res.arrayBuffer();
    onProgress?.(1);
    return buf;
  }
  const reader = res.body.getReader();
  const out = new Uint8Array(total);
  let received = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (received + value.length > out.length) {
      // content-length lied (e.g. compressed transfer); fall back to growing.
      const grown = new Uint8Array(Math.max(out.length * 2, received + value.length));
      grown.set(out.subarray(0, received));
      return finishGrowing(reader, grown, received, value, onProgress);
    }
    out.set(value, received);
    received += value.length;
    onProgress?.(received / total);
  }
  onProgress?.(1);
  return out.buffer.slice(0, received);
}

async function finishGrowing(reader, buf, received, first, onProgress) {
  let out = buf;
  const push = (chunk) => {
    if (received + chunk.length > out.length) {
      const grown = new Uint8Array(Math.max(out.length * 2, received + chunk.length));
      grown.set(out.subarray(0, received));
      out = grown;
    }
    out.set(chunk, received);
    received += chunk.length;
  };
  push(first);
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    push(value);
  }
  onProgress?.(1);
  return out.buffer.slice(0, received);
}

// Loads everything through contoo_assets.json. `platform` is 'pc' or 'mobile'.
export class Assets {
  constructor(platform) {
    this.platform = platform;
    this.manifest = null;
    this.cache = new Map();
    this.gltfLoader = new GLTFLoader();
  }

  url(path) {
    return BASE + path;
  }

  async loadManifest() {
    const res = await fetch(this.url(MANIFEST_PATH));
    if (!res.ok) throw new Error(`Cannot load ${MANIFEST_PATH}`);
    this.manifest = await res.json();
    return this.manifest;
  }

  character(id) {
    return this.manifest.characters.find((c) => c.id === id);
  }
  ground(biome) {
    return this.manifest.grounds.find((g) => g.biome === biome);
  }
  background(biome) {
    return this.manifest.backgrounds.find((b) => b.biome === biome);
  }
  musicTrack(track) {
    return this.manifest.music.find((m) => m.track === track);
  }

  memo(key, fn, progress) {
    if (!this.cache.has(key)) {
      const p = fn().catch((err) => {
        this.cache.delete(key);
        throw err;
      });
      this.cache.set(key, p);
    }
    return this.cache.get(key).then((r) => {
      progress?.(1);
      return r;
    });
  }

  // Character GLB -> { gltf, def } (def = manifest entry with clips/hit times).
  loadCharacter(id, tracker) {
    const def = this.character(id);
    const path = def.files[this.platform];
    const progress = tracker?.add(def.MB?.[this.platform] ?? 4);
    return this.memo(path, async () => {
      const buf = await fetchBytes(this.url(path), progress);
      const gltf = await this.gltfLoader.parseAsync(buf, this.url(path.slice(0, path.lastIndexOf('/') + 1)));
      return { gltf, def };
    }, progress);
  }

  // Gaussian-splat ground for a biome -> PackedSplats (shared by every platform instance).
  loadGroundSplats(biome, tracker) {
    const def = this.ground(biome);
    const path = def.files[this.platform === 'pc' ? 'splat_pc' : 'splat_mobile'];
    const progress = tracker?.add(this.platform === 'pc' ? 3.2 : 0.9);
    return this.memo(path, async () => {
      const buf = await fetchBytes(this.url(path), progress);
      const packed = new PackedSplats({ fileBytes: new Uint8Array(buf), fileName: path.split('/').pop() });
      await packed.initialized;
      return { packed, def };
    }, progress);
  }

  // Image with pixel access (used for the main platform alpha + textures).
  loadImage(path, tracker, weight = 1) {
    const progress = tracker?.add(weight);
    return this.memo(path, async () => {
      const buf = await fetchBytes(this.url(path), progress);
      const type = path.endsWith('.webp') ? 'image/webp' : 'image/png';
      const blobUrl = URL.createObjectURL(new Blob([buf], { type }));
      const img = new Image();
      img.src = blobUrl;
      await img.decode();
      URL.revokeObjectURL(blobUrl);
      return img;
    }, progress);
  }

  backgroundPaths(biome) {
    const bg = this.background(biome);
    return { far: bg.far[this.platform], mid: bg.mid[this.platform], def: bg };
  }

  // Raw bytes of a music loop (decoded later by the audio context).
  loadMusicBytes(track, format, tracker) {
    const def = this.musicTrack(track);
    const path = def.files[`${this.platform}_${format}`];
    const progress = tracker?.add(this.platform === 'pc' ? 2.3 : 1.1);
    return this.memo(path, async () => ({ bytes: await fetchBytes(this.url(path), progress), def }), progress);
  }
}

export function makeImageTexture(img, { premultiply = false, repeatX = false } = {}) {
  const tex = new THREE.Texture(img);
  // 2D art is used as-is (no sRGB decode); the art shaders write the colours straight out.
  tex.colorSpace = THREE.NoColorSpace;
  tex.premultiplyAlpha = premultiply;
  tex.wrapS = repeatX ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.anisotropy = 4;
  tex.needsUpdate = true;
  return tex;
}
