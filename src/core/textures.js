import * as THREE from 'three';

// Small procedural textures shared by effects.
const cache = new Map();

function canvasTexture(key, size, draw) {
  if (cache.has(key)) return cache.get(key);
  const c = document.createElement('canvas');
  c.width = size.w ?? size;
  c.height = size.h ?? size;
  draw(c.getContext('2d'), c.width, c.height);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.NoColorSpace;
  cache.set(key, tex);
  return tex;
}

// White radial falloff (alpha in all channels) - glows, shadows, motes.
export function radialTexture() {
  return canvasTexture('radial', 128, (g, w, h) => {
    const grd = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
    grd.addColorStop(0, 'rgba(255,255,255,1)');
    grd.addColorStop(0.25, 'rgba(255,255,255,0.75)');
    grd.addColorStop(0.6, 'rgba(255,255,255,0.22)');
    grd.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grd;
    g.fillRect(0, 0, w, h);
  });
}

// Vertical beam: bright at the bottom, fading up, soft sides.
export function beamTexture() {
  return canvasTexture('beam', { w: 64, h: 256 }, (g, w, h) => {
    const img = g.createImageData(w, h);
    for (let y = 0; y < h; y++) {
      const v = 1 - y / (h - 1); // 1 at bottom
      for (let x = 0; x < w; x++) {
        const u = Math.abs(x / (w - 1) - 0.5) * 2;
        const a = Math.pow(v, 1.6) * Math.pow(Math.max(0, 1 - u * u), 1.5);
        const i = ((h - 1 - y) * w + x) * 4;
        img.data[i] = img.data[i + 1] = img.data[i + 2] = 255;
        img.data[i + 3] = Math.round(a * 255);
      }
    }
    g.putImageData(img, 0, 0);
  });
}

// Soft ring for ground markers.
export function ringTexture() {
  return canvasTexture('ring', 128, (g, w, h) => {
    const grd = g.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w / 2);
    grd.addColorStop(0, 'rgba(255,255,255,0.12)');
    grd.addColorStop(0.62, 'rgba(255,255,255,0.18)');
    grd.addColorStop(0.8, 'rgba(255,255,255,1)');
    grd.addColorStop(0.9, 'rgba(255,255,255,0.35)');
    grd.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grd;
    g.fillRect(0, 0, w, h);
  });
}
