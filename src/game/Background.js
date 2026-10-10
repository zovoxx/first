import * as THREE from 'three';

// The arena's main background (*_far image): a full-screen quad, cover-fit, with a little parallax
// from the player position. Two texture slots + `mix` so phase 2 can animate arena transitions.
export class Background {
  constructor() {
    this.material = new THREE.ShaderMaterial({
      uniforms: {
        uMapA: { value: null },
        uMapB: { value: null },
        uAspectA: { value: 1.84 },
        uAspectB: { value: 1.84 },
        uScreenAspect: { value: 16 / 9 },
        uOffset: { value: new THREE.Vector2() },
        uMix: { value: 0 },
        uTintA: { value: new THREE.Vector3() },
        uTintB: { value: new THREE.Vector3() },
        uFade: { value: 1 },
      },
      vertexShader: /* glsl */ `
        varying vec2 vUv;
        void main() {
          vUv = uv;
          gl_Position = vec4(position.xy, 0.9999, 1.0);
        }`,
      fragmentShader: /* glsl */ `
        uniform sampler2D uMapA;
        uniform sampler2D uMapB;
        uniform float uAspectA;
        uniform float uAspectB;
        uniform float uScreenAspect;
        uniform vec2 uOffset;
        uniform float uMix;
        uniform vec3 uTintA;
        uniform vec3 uTintB;
        uniform float uFade;
        varying vec2 vUv;
        vec2 coverUv(vec2 uv, float imgAspect) {
          vec2 s = uScreenAspect > imgAspect ? vec2(1.0, imgAspect / uScreenAspect) : vec2(uScreenAspect / imgAspect, 1.0);
          s *= 0.94; // a little zoom leaves room for parallax
          return (uv - 0.5) * s + 0.5 + uOffset;
        }
        void main() {
          vec3 a = texture2D(uMapA, coverUv(vUv, uAspectA)).rgb;
          a = mix(a, uTintA, 0.18);
          vec3 c = a;
          if (uMix > 0.0) {
            vec3 b = texture2D(uMapB, coverUv(vUv, uAspectB)).rgb;
            b = mix(b, uTintB, 0.18);
            c = mix(a, b, uMix);
          }
          float vig = smoothstep(1.25, 0.3, length((vUv - 0.5) * vec2(1.5, 1.1)));
          c *= mix(0.62, 1.0, vig) * uFade;
          gl_FragColor = vec4(c, 1.0);
        }`,
      depthTest: false,
      depthWrite: false,
    });
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.material);
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = -1000;
  }

  setTexture(tex, tint = [0, 0, 0]) {
    const u = this.material.uniforms;
    u.uMapA.value = tex;
    u.uAspectA.value = tex.image.width / tex.image.height;
    u.uTintA.value.set(...tint);
    u.uMix.value = 0;
  }

  resize(aspect) {
    this.material.uniforms.uScreenAspect.value = aspect;
  }

  // Gentle parallax: px/py in -1..1 (player position relative to the arena).
  update(px, py) {
    const o = this.material.uniforms.uOffset.value;
    o.x += (px * 0.02 - o.x) * 0.05;
    o.y += (py * 0.012 - o.y) * 0.05;
  }
}
