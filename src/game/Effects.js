import * as THREE from 'three';
import { radialTexture, ringTexture } from '../core/textures.js';
import { rand } from '../core/math.js';

const _color = new THREE.Color();

// One pooled additive particle system for every burst/trail, plus short-lived meshes (rings, slashes)
// and blob shadows.
export class Effects {
  constructor(scene, maxParticles) {
    this.scene = scene;
    this.max = maxParticles;
    const n = maxParticles;
    this.pos = new Float32Array(n * 3);
    this.col = new Float32Array(n * 3);
    this.alpha = new Float32Array(n);
    this.size = new Float32Array(n);
    this.vel = new Float32Array(n * 3);
    this.life = new Float32Array(n);
    this.maxLife = new Float32Array(n);
    this.size0 = new Float32Array(n);
    this.size1 = new Float32Array(n);
    this.grav = new Float32Array(n);
    this.drag = new Float32Array(n);
    this.cursor = 0;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(this.pos, 3).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute('color', new THREE.BufferAttribute(this.col, 3).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute('aAlpha', new THREE.BufferAttribute(this.alpha, 1).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute('aSize', new THREE.BufferAttribute(this.size, 1).setUsage(THREE.DynamicDrawUsage));
    this.uniforms = { uScale: { value: 500 }, uMap: { value: radialTexture() } };
    this.points = new THREE.Points(
      geo,
      new THREE.ShaderMaterial({
        uniforms: this.uniforms,
        vertexShader: /* glsl */ `
          attribute float aAlpha;
          attribute float aSize;
          attribute vec3 color;
          uniform float uScale;
          varying vec3 vColor;
          varying float vAlpha;
          void main() {
            vec4 mv = modelViewMatrix * vec4(position, 1.0);
            gl_PointSize = aAlpha > 0.0 ? aSize * uScale / -mv.z : 0.0;
            gl_Position = projectionMatrix * mv;
            vColor = color;
            vAlpha = aAlpha;
          }`,
        fragmentShader: /* glsl */ `
          uniform sampler2D uMap;
          varying vec3 vColor;
          varying float vAlpha;
          void main() {
            float a = texture2D(uMap, gl_PointCoord).a * vAlpha;
            gl_FragColor = vec4(vColor, a);
            #include <colorspace_fragment>
          }`,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    );
    this.points.frustumCulled = false;
    this.points.renderOrder = 20;
    scene.add(this.points);
    this.transients = [];
  }

  // Pixels per world metre at distance 1 (for gl_PointSize).
  resize(heightPx, fovDeg) {
    this.uniforms.uScale.value = heightPx / (2 * Math.tan(THREE.MathUtils.degToRad(fovDeg) / 2));
  }

  emit(x, y, z, vx, vy, vz, { life = 0.6, size = 0.25, sizeEnd = 0, color = 0xffffff, gravity = 0, drag = 1.5 } = {}) {
    const i = this.cursor;
    this.cursor = (this.cursor + 1) % this.max;
    this.pos[i * 3] = x;
    this.pos[i * 3 + 1] = y;
    this.pos[i * 3 + 2] = z;
    this.vel[i * 3] = vx;
    this.vel[i * 3 + 1] = vy;
    this.vel[i * 3 + 2] = vz;
    _color.set(color);
    this.col[i * 3] = _color.r;
    this.col[i * 3 + 1] = _color.g;
    this.col[i * 3 + 2] = _color.b;
    this.life[i] = life;
    this.maxLife[i] = life;
    this.size0[i] = size;
    this.size1[i] = sizeEnd;
    this.grav[i] = gravity;
    this.drag[i] = drag;
    this.alpha[i] = 1;
    this.size[i] = size;
  }

  burst(x, y, count, { speed = 4, up = 0, spreadZ = 0.5, ...opts } = {}) {
    for (let k = 0; k < count; k++) {
      const a = Math.random() * Math.PI * 2;
      const s = speed * (0.3 + Math.random() * 0.7);
      this.emit(x, y, rand(-0.1, 0.1), Math.cos(a) * s, Math.sin(a) * s + up, rand(-spreadZ, spreadZ), {
        ...opts,
        life: (opts.life ?? 0.6) * rand(0.6, 1.2),
      });
    }
  }

  // Expanding flat ring on the ground (spawn bursts, landings).
  ring(x, y, color, { from = 0.2, to = 1.6, life = 0.45, opacity = 0.9 } = {}) {
    const mat = new THREE.MeshBasicMaterial({
      map: ringTexture(),
      color,
      transparent: true,
      opacity,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set(x, y + 0.03, 0);
    mesh.renderOrder = 15;
    this.addTransient(mesh, life, (t) => {
      const r = from + (to - from) * (1 - Math.pow(1 - t, 2));
      mesh.scale.set(r, r, 1);
      mat.opacity = opacity * (1 - t);
    });
  }

  // Crescent flash showing an attack's hit area.
  slash(x, y, dir, range, height, color) {
    const geo = new THREE.RingGeometry(range * 0.55, range, 24, 1, -Math.PI / 2, Math.PI);
    const mat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.85,
      depthWrite: false,
      side: THREE.DoubleSide,
      blending: THREE.AdditiveBlending,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(x, y + height * 0.5, 0.3);
    mesh.scale.set(dir, (height * 0.6) / range, 1);
    mesh.renderOrder = 16;
    this.addTransient(mesh, 0.2, (t) => {
      mat.opacity = 0.85 * (1 - t);
      mesh.scale.x = dir * (1 + t * 0.15);
    });
  }

  addTransient(mesh, life, update) {
    this.scene.add(mesh);
    this.transients.push({ mesh, life, t: 0, update });
    update(0);
  }

  // Soft blob shadow for a character (black, alpha falloff).
  makeShadow(width = 1.1) {
    const mat = new THREE.MeshBasicMaterial({
      color: 0x000000,
      map: radialTexture(), // white rgb * black colour = black; the texture alpha gives the falloff
      transparent: true,
      opacity: 0.5,
      depthWrite: false,
    });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), mat);
    mesh.rotation.x = -Math.PI / 2;
    mesh.scale.set(width, width * 0.8, 1);
    mesh.renderOrder = 5;
    mesh.userData.width = width;
    this.scene.add(mesh);
    return mesh;
  }

  // Put a shadow on the ground under (x, y). `world` = CollisionWorld.
  placeShadow(shadow, world, x, y, strength = 1) {
    const g = world.groundBelow(x, y + 0.05, 0.1);
    if (!g) {
      shadow.visible = false;
      return;
    }
    const h = y - g.y;
    const k = Math.max(0, 1 - h / 6);
    shadow.visible = k > 0.02;
    shadow.position.set(x, g.y + 0.02, 0.05);
    const w = shadow.userData.width * (0.55 + 0.45 * k);
    shadow.scale.set(w, w * 0.8, 1);
    shadow.material.opacity = 0.5 * k * strength;
  }

  removeShadow(shadow) {
    this.scene.remove(shadow);
    shadow.geometry.dispose();
    shadow.material.dispose();
  }

  update(dt) {
    const n = this.max;
    for (let i = 0; i < n; i++) {
      if (this.life[i] <= 0) {
        if (this.alpha[i] !== 0) this.alpha[i] = 0;
        continue;
      }
      this.life[i] -= dt;
      const t = 1 - Math.max(0, this.life[i]) / this.maxLife[i];
      const d = Math.exp(-this.drag[i] * dt);
      const j = i * 3;
      this.vel[j] *= d;
      this.vel[j + 1] = this.vel[j + 1] * d - this.grav[i] * dt;
      this.vel[j + 2] *= d;
      this.pos[j] += this.vel[j] * dt;
      this.pos[j + 1] += this.vel[j + 1] * dt;
      this.pos[j + 2] += this.vel[j + 2] * dt;
      this.size[i] = this.size0[i] + (this.size1[i] - this.size0[i]) * t;
      this.alpha[i] = this.life[i] > 0 ? 1 - t * t : 0;
    }
    const g = this.points.geometry;
    g.attributes.position.needsUpdate = true;
    g.attributes.color.needsUpdate = true;
    g.attributes.aAlpha.needsUpdate = true;
    g.attributes.aSize.needsUpdate = true;

    for (let k = this.transients.length - 1; k >= 0; k--) {
      const tr = this.transients[k];
      tr.t += dt;
      const t = Math.min(1, tr.t / tr.life);
      tr.update(t);
      if (t >= 1) {
        this.scene.remove(tr.mesh);
        tr.mesh.geometry.dispose();
        tr.mesh.material.dispose();
        this.transients.splice(k, 1);
      }
    }
  }

  clear() {
    this.life.fill(0);
    this.alpha.fill(0);
    for (const tr of this.transients) {
      this.scene.remove(tr.mesh);
      tr.mesh.geometry.dispose();
      tr.mesh.material.dispose();
    }
    this.transients.length = 0;
  }
}
