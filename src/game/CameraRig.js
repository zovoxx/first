import * as THREE from 'three';
import { VIEW } from '../config.js';

// Fixed side-view camera framing the arena. The main platform surface (world y = 0) always sits at the
// same fraction of the screen height. Narrow screens show more height instead of cutting the sides.
export class CameraRig {
  constructor() {
    this.camera = new THREE.PerspectiveCamera(VIEW.fovDeg, 16 / 9, 1, 600);
    this.pitch = THREE.MathUtils.degToRad(VIEW.pitchDeg);
    this.target = new THREE.Vector3();
    this.base = new THREE.Vector3();
    this.shakeAmp = 0;
    this.shakeTime = 0;
    this.viewW = 24;
    this.viewH = VIEW.height;
    this.halfW = 12;
    this.distance = 40;
  }

  resize(w, h) {
    const aspect = w / Math.max(1, h);
    let viewH = h < VIEW.compactBelowPx ? VIEW.heightCompact : VIEW.height;
    if (viewH * aspect < VIEW.minWidth) viewH = VIEW.minWidth / aspect;
    this.viewH = viewH;
    this.viewW = viewH * aspect;
    this.halfW = Math.min(this.viewW / 2 - 0.35, VIEW.maxHalfWidth);
    const fov = THREE.MathUtils.degToRad(VIEW.fovDeg);
    this.distance = viewH / 2 / Math.tan(fov / 2);
    const centerY = (0.5 - VIEW.surfaceScreenFrac) * viewH;
    this.target.set(0, centerY, 0);
    this.base.set(0, centerY + Math.sin(this.pitch) * this.distance, Math.cos(this.pitch) * this.distance);
    this.camera.aspect = aspect;
    this.camera.near = Math.max(1, this.distance - 60);
    this.camera.far = this.distance + 400;
    this.camera.updateProjectionMatrix();
    this.apply(0, 0);
  }

  get bottomY() {
    return this.target.y - this.viewH / 2;
  }
  get topY() {
    return this.target.y + this.viewH / 2;
  }

  shake(amount, time = 0.25) {
    this.shakeAmp = Math.max(this.shakeAmp, amount);
    this.shakeTime = Math.max(this.shakeTime, time);
  }

  apply(ox, oy) {
    this.camera.position.set(this.base.x + ox, this.base.y + oy, this.base.z);
    this.camera.lookAt(this.target.x + ox, this.target.y + oy, this.target.z);
  }

  update(dt) {
    if (this.shakeTime > 0) {
      this.shakeTime -= dt;
      const a = this.shakeAmp * Math.max(0, Math.min(1, this.shakeTime / 0.25));
      this.apply((Math.random() * 2 - 1) * a, (Math.random() * 2 - 1) * a);
      if (this.shakeTime <= 0) {
        this.shakeAmp = 0;
        this.apply(0, 0);
      }
    }
  }

  // Point on the line from the camera through `worldPoint`, pushed `zBack` further away. Lets a
  // plane drawn behind the gameplay plane line up on screen with gameplay coordinates.
  behind(worldPoint, zBack, out = new THREE.Vector3()) {
    const dir = new THREE.Vector3().copy(worldPoint).sub(this.base);
    const len = dir.length();
    const k = (len + zBack) / len;
    return out.copy(this.base).addScaledVector(dir, k);
  }

  // Scale factor that keeps an object drawn zBack further away the same size on screen.
  behindScale(zBack) {
    return (this.distance + zBack) / this.distance;
  }
}
