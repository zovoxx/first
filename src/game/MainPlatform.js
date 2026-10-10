import * as THREE from 'three';
import { MAIN_PLATFORM } from '../config.js';
import { VALUE2 } from '../core/glsl.js';
import { computeWalkSurface } from './alphaSurface.js';
import { Surface } from './collision.js';

// The arena's main floating platform: the *_mid image (2D, with alpha) drawn on a plane just behind
// the gameplay plane. Its walkable top comes from the image alpha (see alphaSurface.js). It never
// shakes, falls or disappears during play; it is always at the same screen position.
export class MainPlatform {
  constructor(img, texture) {
    this.analysis = computeWalkSurface(img);
    const { width: W, height: H, median, rows } = this.analysis;
    this.width = MAIN_PLATFORM.width;
    this.mPerPx = this.width / W;
    this.heightM = H * this.mPerPx;
    this.surfaceRow = median;

    // Walkable polyline in world space: the median ground row maps to y = 0.
    const inset = MAIN_PLATFORM.edgeInset;
    const pts = [];
    for (const [u, row] of rows) {
      if (u < inset || u > 1 - inset) continue;
      pts.push([(u - 0.5) * this.width, (this.surfaceRow - row) * this.mPerPx]);
    }
    this.surface = new Surface(pts, { main: true, owner: this });

    // Plane with its local origin on the surface line.
    const geo = new THREE.PlaneGeometry(this.width, this.heightM);
    geo.translate(0, -(this.heightM / 2 - this.surfaceRow * this.mPerPx), 0);
    this.material = new THREE.ShaderMaterial({
      uniforms: {
        uMap: { value: texture },
        uTime: { value: 0 },
        uOpacity: { value: 1 },
        uSurfaceV: { value: 1 - this.surfaceRow / H },
        uWidth: { value: this.width },
        uReveal: { value: 1 }, // 0..1 (phase 2: rise / fade in)
        uBreak: { value: 0 }, // 0..1 (phase 2: break apart)
      },
      vertexShader: /* glsl */ `
        varying vec2 vUv;
        void main() {
          vUv = uv;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }`,
      fragmentShader: /* glsl */ `
        ${VALUE2}
        uniform sampler2D uMap;
        uniform float uTime;
        uniform float uOpacity;
        uniform float uSurfaceV;
        uniform float uWidth;
        uniform float uReveal;
        uniform float uBreak;
        varying vec2 vUv;
        void main() {
          vec4 c = texture2D(uMap, vUv); // premultiplied alpha
          float below = clamp((uSurfaceV - vUv.y) / max(uSurfaceV, 0.001), 0.0, 1.0);
          float n = fbm2(vec2(vUv.x * uWidth * 0.6, below * 5.0 + vUv.y * 2.0));
          // Island silhouette (metres): the ends taper inward with depth, the bottom erodes into rock crumbs.
          float side = min(vUv.x, 1.0 - vUv.x) * uWidth;
          float taper = 0.12 + below * below * 3.6 * (0.75 + n * 0.5);
          float a = smoothstep(taper, taper + 0.2, side);
          a *= 1.0 - smoothstep(0.5, 0.92, below + (n - 0.5) * 0.45);
          // break-apart (phase 2): noise threshold eats the platform
          a *= 1.0 - smoothstep(n - 0.05, n + 0.05, uBreak * 1.1 - (1.0 - below) * 0.1);
          a *= uReveal * uOpacity;
          vec3 rgb = c.rgb * mix(1.0, 0.5, smoothstep(0.05, 0.85, below));
          gl_FragColor = vec4(rgb * a, c.a * a);
        }`,
      transparent: true,
      premultipliedAlpha: true,
      depthWrite: false,
    });
    this.mesh = new THREE.Mesh(geo, this.material);
    this.mesh.renderOrder = -50;
  }

  // Place the plane behind the gameplay plane so its surface line lines up with world y = 0 on screen.
  layout(rig) {
    const z = MAIN_PLATFORM.zBack;
    rig.behind(new THREE.Vector3(0, 0, 0), z, this.mesh.position);
    this.mesh.scale.setScalar(rig.behindScale(z));
    this.mesh.rotation.x = -rig.pitch;
  }

  update(dt) {
    this.material.uniforms.uTime.value += dt;
  }

  dispose() {
    this.mesh.geometry.dispose();
    this.material.dispose();
    this.material.uniforms.uMap.value?.dispose();
  }
}
