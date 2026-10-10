import * as THREE from 'three';
import { SIMPLEX3 } from '../core/glsl.js';
import { radialTexture } from '../core/textures.js';
import { clamp, damp } from '../core/math.js';

const CORE_CENTER = 0.49; // centre of the 0.98 m tall hitbox
const RADIUS = new THREE.Vector3(0.3, 0.4, 0.3);
const CORE_COLOR = new THREE.Color(0x63f2ff);
const RIM_COLOR = new THREE.Color(0xb48cff);
const HURT_CORE = new THREE.Color(0xff5a7a);
const HURT_RIM = new THREE.Color(0xffc06a);

// The player creature: no real body - a shifting, flame-like glow made of a noise-displaced shader
// blob, a bright nucleus showing which way it faces, orbiting motes and a halo. The core fills the
// hitbox (0.62 x 0.98 m) so what you see is what can be hit.
export class WispVisual {
  constructor(effects, quality) {
    this.effects = effects;
    this.root = new THREE.Group();
    this.root.position.z = 0.35; // a touch in front of enemies so it always reads
    this.core = new THREE.Group();
    this.core.position.y = CORE_CENTER;
    this.root.add(this.core);

    this.uniforms = {
      uTime: { value: 0 },
      uVel: { value: new THREE.Vector2() },
      uSquash: { value: 0 },
      uRadius: { value: RADIUS.clone() },
      uCore: { value: CORE_COLOR.clone() },
      uRim: { value: RIM_COLOR.clone() },
      uFlash: { value: 0 },
      uOpacity: { value: 1 },
      uWobble: { value: 1 },
    };
    const coreMat = new THREE.ShaderMaterial({
      uniforms: this.uniforms,
      vertexShader: /* glsl */ `
        ${SIMPLEX3}
        uniform float uTime;
        uniform vec2 uVel;
        uniform float uSquash;
        uniform vec3 uRadius;
        uniform float uWobble;
        varying vec3 vN;
        varying vec3 vV;
        varying float vNoise;
        varying float vY;
        void main() {
          vec3 n0 = normalize(position);
          float up = n0.y;
          float n1 = snoise(n0 * 1.6 + vec3(0.0, -uTime * 1.4, uTime * 0.5));
          float n2 = snoise(n0 * 3.4 + vec3(uTime * 0.9, -uTime * 2.2, 0.0));
          vec3 p = n0 * uRadius;
          // flame tip: the top is drawn up and flickers
          p.y += max(0.0, up) * max(0.0, up) * (0.16 + 0.07 * n2);
          // shifting surface
          p += n0 * (n1 * 0.06 + n2 * 0.025) * uWobble;
          // squash (land) / stretch (jump)
          p.x *= 1.0 - uSquash * 0.45;
          p.z *= 1.0 - uSquash * 0.45;
          p.y *= 1.0 + uSquash;
          // the upper part trails behind the motion
          vec2 lag = clamp(uVel * 0.016, vec2(-0.45), vec2(0.45));
          p.xy -= lag * smoothstep(-0.4, 1.0, up);
          vNoise = n1;
          vY = up;
          vec4 wp = modelMatrix * vec4(p, 1.0);
          vN = normalize(mat3(modelMatrix) * n0);
          vV = normalize(cameraPosition - wp.xyz);
          gl_Position = projectionMatrix * viewMatrix * wp;
        }`,
      fragmentShader: /* glsl */ `
        uniform vec3 uCore;
        uniform vec3 uRim;
        uniform float uTime;
        uniform float uFlash;
        uniform float uOpacity;
        varying vec3 vN;
        varying vec3 vV;
        varying float vNoise;
        varying float vY;
        void main() {
          float ndv = clamp(dot(normalize(vN), normalize(vV)), 0.0, 1.0);
          float fres = pow(1.0 - ndv, 2.0);
          float hot = pow(ndv, 4.0);
          float bands = 0.5 + 0.5 * sin(vNoise * 7.0 - uTime * 5.0 + vY * 5.0);
          vec3 col = mix(uCore, uRim, fres);
          col += vec3(0.9, 1.0, 1.0) * hot * 0.6;
          col += uRim * bands * 0.22 * (1.0 - hot);
          col = mix(col, vec3(1.0), uFlash);
          float a = (0.82 + 0.18 * fres) * uOpacity;
          gl_FragColor = vec4(col, a);
          #include <colorspace_fragment>
        }`,
      transparent: true,
      depthWrite: false,
    });
    const seg = quality.wispSegments;
    this.coreMesh = new THREE.Mesh(new THREE.IcosahedronGeometry(1, seg), coreMat);
    this.coreMesh.renderOrder = 31;
    this.core.add(this.coreMesh);

    // nucleus: shows the facing direction
    this.nucleus = new THREE.Mesh(
      new THREE.SphereGeometry(0.075, 16, 12),
      new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, depthWrite: false }),
    );
    this.nucleus.renderOrder = 32;
    this.core.add(this.nucleus);
    this.nucleusGlow = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: radialTexture(),
        color: 0xbff8ff,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        transparent: true,
        opacity: 0.9,
      }),
    );
    this.nucleusGlow.scale.setScalar(0.42);
    this.nucleusGlow.renderOrder = 33;
    this.core.add(this.nucleusGlow);

    // halo
    this.halo = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: radialTexture(),
        color: CORE_COLOR,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        transparent: true,
        opacity: 0.5,
      }),
    );
    this.halo.scale.setScalar(2.1);
    this.halo.renderOrder = 30;
    this.core.add(this.halo);

    // orbiting motes (animated entirely in the vertex shader)
    const count = quality.motes;
    const seeds = new Float32Array(count * 4);
    for (let i = 0; i < seeds.length; i++) seeds[i] = Math.random();
    const mg = new THREE.BufferGeometry();
    mg.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3));
    mg.setAttribute('aSeed', new THREE.BufferAttribute(seeds, 4));
    this.moteUniforms = {
      uTime: this.uniforms.uTime,
      uVel: this.uniforms.uVel,
      uScale: { value: 500 },
      uSpread: { value: 1 },
      uColorA: { value: CORE_COLOR.clone() },
      uColorB: { value: RIM_COLOR.clone() },
      uMap: { value: radialTexture() },
      uOpacity: this.uniforms.uOpacity,
    };
    this.motes = new THREE.Points(
      mg,
      new THREE.ShaderMaterial({
        uniforms: this.moteUniforms,
        vertexShader: /* glsl */ `
          attribute vec4 aSeed;
          uniform float uTime;
          uniform vec2 uVel;
          uniform float uScale;
          uniform float uSpread;
          varying float vA;
          varying float vMix;
          void main() {
            float dir = aSeed.y > 0.5 ? 1.0 : -1.0;
            float ang = uTime * mix(1.0, 3.0, aSeed.x) * dir + aSeed.z * 6.2831;
            float r = mix(0.36, 0.78, aSeed.w) * uSpread;
            float tilt = (aSeed.x - 0.5) * 2.6;
            vec3 p = vec3(cos(ang) * r, sin(ang) * r * 0.9 * cos(tilt), sin(ang) * r * sin(tilt));
            p.y += sin(uTime * 1.7 + aSeed.w * 10.0) * 0.08 + 0.05;
            p.xy -= clamp(uVel * (0.02 + 0.05 * aSeed.w), vec2(-1.4), vec2(1.4));
            vec4 mv = modelViewMatrix * vec4(p, 1.0);
            gl_PointSize = mix(0.07, 0.17, aSeed.y) * uScale / -mv.z;
            gl_Position = projectionMatrix * mv;
            vA = 0.55 + 0.45 * sin(uTime * 4.0 + aSeed.z * 20.0);
            vMix = aSeed.x;
          }`,
        fragmentShader: /* glsl */ `
          uniform sampler2D uMap;
          uniform vec3 uColorA;
          uniform vec3 uColorB;
          uniform float uOpacity;
          varying float vA;
          varying float vMix;
          void main() {
            float a = texture2D(uMap, gl_PointCoord).a * vA * uOpacity;
            gl_FragColor = vec4(mix(uColorA, uColorB, vMix) + 0.25, a);
            #include <colorspace_fragment>
          }`,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    );
    this.motes.frustumCulled = false;
    this.motes.renderOrder = 34;
    this.core.add(this.motes);

    // light pooled on the ground below
    this.groundGlow = new THREE.Mesh(
      new THREE.PlaneGeometry(1, 1),
      new THREE.MeshBasicMaterial({
        map: radialTexture(),
        color: CORE_COLOR,
        transparent: true,
        opacity: 0.5,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      }),
    );
    this.groundGlow.rotation.x = -Math.PI / 2;
    this.groundGlow.renderOrder = 6;

    this.squash = 0;
    this.squashVel = 0;
    this.flash = 0;
    this.trailT = 0;
    this.face = 1;
    this.noseX = 0.11;
    this.dead = false;
  }

  addTo(scene) {
    scene.add(this.root);
    scene.add(this.groundGlow);
  }

  resize(heightPx, fovDeg) {
    this.moteUniforms.uScale.value = heightPx / (2 * Math.tan(THREE.MathUtils.degToRad(fovDeg) / 2));
  }

  onJump(air) {
    this.squashVel += air ? 2.8 : 3.5;
    const p = this.root.position;
    this.effects.burst(p.x, p.y + 0.1, air ? 14 : 8, {
      speed: air ? 3.5 : 2.5,
      color: air ? 0xc8a8ff : 0x8af5ff,
      size: 0.16,
      life: 0.4,
      drag: 3,
    });
  }

  onLand(impact) {
    this.squashVel -= clamp(impact * 0.22, 0.6, 4);
    const p = this.root.position;
    if (impact > 6) this.effects.burst(p.x, p.y + 0.05, 8, { speed: 2.4, up: 0.6, color: 0x8af5ff, size: 0.13, life: 0.35, drag: 4 });
  }

  onDash(dir) {
    const p = this.root.position;
    for (let i = 0; i < 16; i++) {
      this.effects.emit(p.x, p.y + CORE_CENTER + (Math.random() - 0.5) * 0.6, 0.3, -dir * (2 + Math.random() * 5), (Math.random() - 0.5) * 2, 0, {
        life: 0.35,
        size: 0.22,
        color: i % 2 ? 0xb48cff : 0x63f2ff,
        drag: 5,
      });
    }
  }

  onHurt() {
    this.flash = 1;
    const p = this.root.position;
    this.effects.burst(p.x, p.y + CORE_CENTER, 22, { speed: 6, color: 0xff6a8a, size: 0.18, life: 0.5, drag: 3 });
  }

  onDeath() {
    this.dead = true;
    const p = this.root.position;
    this.effects.burst(p.x, p.y + CORE_CENTER, 90, { speed: 9, color: 0x63f2ff, size: 0.28, life: 1.1, drag: 1.5 });
    this.effects.burst(p.x, p.y + CORE_CENTER, 50, { speed: 5, color: 0xb48cff, size: 0.22, life: 1.4, drag: 1.2 });
  }

  // s: player snapshot { x, y, vx, vy, face, grounded, dashing, invulnerable, health01, groundY }
  update(dt, s) {
    const u = this.uniforms;
    u.uTime.value += dt;
    this.root.position.x = s.x;
    this.root.position.y = s.y;
    u.uVel.value.set(damp(u.uVel.value.x, s.vx, 12, dt), damp(u.uVel.value.y, s.vy, 12, dt));

    // squash spring
    this.squashVel += (-this.squash * 140 - this.squashVel * 11) * dt;
    this.squash = clamp(this.squash + this.squashVel * dt, -0.35, 0.45);
    let squash = this.squash;
    if (s.dashing) squash = -0.3; // flatten into the dash
    u.uSquash.value = squash;

    // facing: the nucleus slides to the front
    this.face = s.face;
    this.noseX = damp(this.noseX, s.face * 0.12, 14, dt);
    this.nucleus.position.set(this.noseX, 0.08, 0.26);
    this.nucleusGlow.position.copy(this.nucleus.position);

    // colours: low health shifts toward red and pulses faster
    const danger = clamp(1 - s.health01 / 0.45, 0, 1);
    const pulse = danger > 0 ? 0.5 + 0.5 * Math.sin(u.uTime.value * (6 + danger * 8)) : 0;
    u.uCore.value.copy(CORE_COLOR).lerp(HURT_CORE, danger * (0.5 + 0.5 * pulse));
    u.uRim.value.copy(RIM_COLOR).lerp(HURT_RIM, danger * 0.6);
    this.halo.material.color.copy(u.uCore.value);
    this.groundGlow.material.color.copy(u.uCore.value);
    this.halo.material.opacity = 0.42 + 0.1 * Math.sin(u.uTime.value * 3) + (s.dashing ? 0.25 : 0);

    this.flash = Math.max(0, this.flash - dt * 5);
    u.uFlash.value = this.flash;
    u.uOpacity.value = this.dead ? 0 : s.invulnerable && !s.dashing ? (Math.floor(u.uTime.value * 16) % 2 ? 0.35 : 0.9) : 1;
    this.root.visible = !this.dead;

    // trail while moving fast
    const speed = Math.hypot(s.vx, s.vy);
    this.trailT -= dt;
    if (!this.dead && speed > 3 && this.trailT <= 0) {
      this.trailT = s.dashing ? 0.012 : 0.05;
      this.effects.emit(
        s.x + (Math.random() - 0.5) * 0.3,
        s.y + CORE_CENTER + (Math.random() - 0.5) * 0.45,
        0.3,
        -s.vx * 0.08 + (Math.random() - 0.5) * 0.4,
        -s.vy * 0.08 + 0.3 + Math.random() * 0.4,
        0,
        { life: s.dashing ? 0.3 : 0.45, size: s.dashing ? 0.36 : 0.2, sizeEnd: 0.02, color: Math.random() < 0.5 ? 0x63f2ff : 0xb48cff, drag: 2 },
      );
    }

    // ground light
    if (s.groundY !== null && !this.dead) {
      const h = s.y - s.groundY;
      const k = clamp(1 - h / 5, 0, 1);
      this.groundGlow.visible = k > 0.02;
      this.groundGlow.position.set(s.x, s.groundY + 0.025, 0.3);
      const w = 1.6 * (0.6 + 0.4 * k);
      this.groundGlow.scale.set(w, w * 0.7, 1);
      this.groundGlow.material.opacity = 0.55 * k;
    } else {
      this.groundGlow.visible = false;
    }
  }
}
