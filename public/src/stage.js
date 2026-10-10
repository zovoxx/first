// A biome: gaussian-splat floor (Spark), walk line for collision, two parallax background layers.
import * as THREE from 'three';
import { SplatMesh } from '@sparkjsdev/spark';
import { PLATFORM, fetchBytes, loadGLTF, webPath } from './assets.js';

const EDGE_MARGIN = 0.4;   // keep fighters this far from the ends of the walk line

// Full-screen layer drawn in clip space: tiles horizontally, sits on the bottom edge, covers `uTop` of the height.
const VERT = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}`;
const FRAG = /* glsl */ `
uniform sampler2D map;
uniform float uRepeat;
uniform float uOffset;
uniform float uTop;
varying vec2 vUv;
void main() {
  float v = vUv.y / uTop;
  if (v > 1.0) discard;
  vec4 c = texture2D(map, vec2(vUv.x * uRepeat + uOffset, v));
  if (c.a < 0.004) discard;
  gl_FragColor = c;
  #include <colorspace_fragment>
}`;

const texLoader = new THREE.TextureLoader();
function loadTexture(url) {
  return new Promise((resolve, reject) => texLoader.load(url, (t) => {
    t.colorSpace = THREE.SRGBColorSpace;
    t.wrapS = THREE.RepeatWrapping;
    t.anisotropy = 4;
    resolve(t);
  }, undefined, () => reject(new Error(`${url}: failed to load`))));
}

class Layer {
  constructor(tex, parallax, top, order) {
    this.tex = tex;
    this.parallax = parallax;
    this.top = top;
    this.material = new THREE.ShaderMaterial({
      uniforms: { map: { value: tex }, uRepeat: { value: 1 }, uOffset: { value: 0 }, uTop: { value: top } },
      vertexShader: VERT,
      fragmentShader: FRAG,
      transparent: true,
      depthTest: false,
      depthWrite: false,
    });
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.material);
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = order;
  }

  /** aspect = screen w/h, camX = camera x in metres, viewW = metres visible across the screen at the fighters. */
  update(aspect, camX, viewW) {
    const img = this.tex.image;
    const tileW = (this.top * img.width / img.height) / aspect;   // one tile, in screen widths
    const u = this.material.uniforms;
    u.uRepeat.value = 1 / tileW;
    u.uOffset.value = (camX * this.parallax / viewW) * u.uRepeat.value;
  }
}

export class Stage {
  constructor(ground, background) {
    this.ground = ground;
    this.background = background;
    this.biome = ground.biome;
    this.walk = ground.walk_line;
    this.group = new THREE.Group();
    this.bgScene = new THREE.Scene();
    this.layers = [];
    this.loaded = null;
  }

  load(progress) {
    this.loaded ??= this._load(progress).catch((err) => { this.loaded = null; throw err; });
    return this.loaded;
  }

  async _load(progress) {
    const g = this.ground.files;
    const bg = this.background;
    const mobile = PLATFORM === 'mobile';
    const splatUrl = webPath(mobile ? g.splat_mobile : g.splat_pc);
    const onSplat = progress?.part(3);
    const onBg = progress?.part(1);
    const [bytes, far, mid] = await Promise.all([
      fetchBytes(splatUrl, onSplat),
      loadTexture(webPath(mobile ? bg.far.mobile : bg.far.pc)),
      loadTexture(webPath(mobile ? bg.mid.mobile : bg.mid.pc)),
    ]);
    onBg?.(1);

    const midTop = bg.mid.size_pc[1] / bg.far.size_pc[1];   // same pixel scale as the far layer
    this.layers = [
      new Layer(far, bg.far.suggested_parallax ?? 0.15, 1, 0),
      new Layer(mid, bg.mid.suggested_parallax ?? 0.45, midTop, 1),
    ];
    for (const l of this.layers) this.bgScene.add(l.mesh);

    try {
      const splat = new SplatMesh({ fileBytes: bytes, fileName: splatUrl.split('/').pop() });
      await splat.initialized;
      this.group.add(splat);
    } catch (err) {
      // No splat support: fall back to the collider mesh so the fight still works.
      console.warn('Splat floor failed, using the collider mesh instead', err);
      const gltf = await loadGLTF(webPath(g.collider));
      const mesh = gltf.scene.clone();
      mesh.traverse((o) => {
        if (o.isMesh) o.material = new THREE.MeshStandardMaterial({ color: 0x8b7d6b, roughness: 0.95 });
      });
      this.group.add(mesh);
    }
  }

  /** Height of the walkable surface at x (linear between walk-line points). */
  groundY(x) {
    const w = this.walk;
    if (x <= w[0][0]) return w[0][1];
    for (let i = 1; i < w.length; i++) {
      if (x <= w[i][0]) {
        const [x0, y0] = w[i - 1];
        const [x1, y1] = w[i];
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0);
      }
    }
    return w[w.length - 1][1];
  }

  get minX() { return this.walk[0][0] + EDGE_MARGIN; }
  get maxX() { return this.walk[this.walk.length - 1][0] - EDGE_MARGIN; }

  updateBackground(aspect, camX, viewW) {
    for (const l of this.layers) l.update(aspect, camX, viewW);
  }
}
