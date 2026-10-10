// One fighter: model + animation clips + movement/combat state machine.
// Clip lengths, run speed and attack hit time come from contoo_assets.json; the numbers below are game feel.
import * as THREE from 'three';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';

export const MAX_HP = 100;
export const GRAVITY = 22.7;

// The jump clip crouches until ~0.55 s, is in the air until ~1.2 s, then lands. These numbers line the
// physics up with it: 7.4 m/s at 22.7 m/s² gives 0.65 s in the air and a 1.2 m peak.
const JUMP_VELOCITY = 7.4;
const JUMP_CLIP_START = 0.3;   // skip part of the crouch so the jump feels responsive
const JUMP_TAKEOFF = 0.25;     // seconds after the start (clip time 0.55)
const JUMP_AIR_HOLD = 1.1;     // hold this clip time while still airborne
const JUMP_LAND = 1.15;        // clip time where the landing starts
const LAND_TIME = 0.28;

const RUN_SCALE = 1.5;         // run faster than the clip's ground speed, clip sped up to match (no foot sliding)
const AIR_CONTROL = 0.8;
const ATTACK_SPEED = 1.2;
const DODGE_SPEED = 1.6;
const DODGE_TIME = 1.2 / DODGE_SPEED;
const DODGE_IFRAMES = 0.5;
const DODGE_DISTANCE = 2.4;
const DODGE_COOLDOWN = 0.35;
const HIT_STUN = 0.45;
const KNOCKBACK = 3.2;
const FACE_YAW = Math.PI / 2 - 0.3;   // side-on, turned a little toward the camera

/** Per-character combat tuning (weapons from the asset notes). */
export const KIT = {
  kaya: { weapon: 'Two daggers', type: 'melee', range: 1.15, damage: 15 },
  brumm: { weapon: 'Hammer', type: 'melee', range: 1.45, damage: 22 },
  volt: { weapon: 'Baton', type: 'melee', range: 1.35, damage: 14 },
  wren: { weapon: 'Bow', type: 'arrow', range: 7.5, damage: 13 },
  frostine: { weapon: 'Ice staff', type: 'frost', range: 4.5, damage: 15 },
};

export const shortName = (def) => def.name.split(',')[0];

let shadowTexture = null;
function blobShadow() {
  if (!shadowTexture) {
    const c = document.createElement('canvas');
    c.width = c.height = 64;
    const g = c.getContext('2d');
    const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grd.addColorStop(0, 'rgba(0,0,0,0.6)');
    grd.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = grd;
    g.fillRect(0, 0, 64, 64);
    shadowTexture = new THREE.CanvasTexture(c);
  }
  const m = new THREE.Mesh(
    new THREE.PlaneGeometry(1, 1),
    new THREE.MeshBasicMaterial({ map: shadowTexture, transparent: true, depthWrite: false }),
  );
  m.rotation.x = -Math.PI / 2;
  m.renderOrder = 2;
  return m;
}

export class Fighter {
  constructor(def, gltf) {
    this.def = def;
    this.kit = KIT[def.id] ?? KIT.kaya;
    this.name = shortName(def);
    this.height = def.height_m;

    this.object = new THREE.Group();
    this.body = new THREE.Group();
    this.model = SkeletonUtils.clone(gltf.scene);
    this.materials = [];
    this.model.traverse((o) => {
      if (!o.isMesh) return;
      o.frustumCulled = false;   // skinned bounds don't follow the animation
      o.material = o.material.clone();
      if (o.material.emissive) this.materials.push({ m: o.material, base: o.material.emissive.clone() });
    });
    this.body.add(this.model);
    this.shadow = blobShadow();
    this.object.add(this.body, this.shadow);

    this.mixer = new THREE.AnimationMixer(this.model);
    this.actions = {};
    for (const clip of gltf.animations) {
      const action = this.mixer.clipAction(clip);
      const loop = def.clips[clip.name]?.loop ?? false;
      action.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, Infinity);
      action.clampWhenFinished = !loop;
      this.actions[clip.name] = action;
    }

    this.runSpeed = (def.clips.run?.ground_speed_mps ?? 2.2) * RUN_SCALE;
    const atk = def.clips.attack;
    this.attackTime = atk.seconds / ATTACK_SPEED;
    this.hitTime = (atk.hit_time_s ?? atk.seconds * 0.6) / ATTACK_SPEED;
  }

  reset(x, facing, groundY) {
    Object.assign(this, {
      x, y: groundY, vx: 0, vy: 0, facing, hp: MAX_HP, state: 'idle', t: 0,
      airborne: false, jumpPhase: null, hitDone: false, flash: 0, dodgeDir: facing,
    });
    this.yaw = facing * FACE_YAW;
    this.cool = { attack: 0, dodge: 0 };
    this.buf = { attack: 0, jump: 0, dodge: 0 };
    this.mixer.stopAllAction();
    this.current = null;
    this.play('idle', 0);
    this.sync(0, groundY);
  }

  get dead() { return this.state === 'dead'; }
  get invulnerable() { return this.state === 'dodge' && this.t < DODGE_IFRAMES; }
  get canAct() { return this.state === 'idle' || this.state === 'run'; }

  play(name, fade = 0.15, { time = 0, timeScale = 1 } = {}) {
    const next = this.actions[name];
    if (!next) return;
    const prev = this.current;
    next.reset();
    next.time = time;
    next.timeScale = timeScale;
    next.play();
    if (prev && prev !== next) {
      if (fade > 0) next.crossFadeFrom(prev, fade, false);
      else prev.stop();
    }
    this.current = next;
  }

  /** input = { move: -1..1, jump, dodge, attack } (buttons true on the frame they are pressed). */
  update(dt, input, foe, fight) {
    this.t += dt;
    this.cool.attack -= dt;
    this.cool.dodge -= dt;
    for (const k in this.buf) this.buf[k] = input[k] ? 0.2 : Math.max(0, this.buf[k] - dt);

    switch (this.state) {
      case 'idle':
      case 'run': this.updateGround(dt, input, foe); break;
      case 'attack': this.updateAttack(input, foe, fight); break;
      case 'jump': this.updateJump(dt, input, foe, fight.stage); break;
      case 'dodge': this.updateDodge(dt); break;
      case 'hit':
      case 'dead': this.updateHit(dt); break;
    }

    // Vertical: stick to the walk line, except in the air (jump handles its own air phase).
    const g = fight.stage.groundY(this.x);
    if (this.state === 'jump') return;
    if (this.airborne) {
      this.vy -= GRAVITY * dt;
      this.y += this.vy * dt;
      if (this.y <= g && this.vy <= 0) { this.y = g; this.vy = 0; this.airborne = false; }
    } else {
      this.y = g;
    }
  }

  faceFoe(foe) {
    if (!foe.dead) this.facing = Math.sign(foe.x - this.x) || this.facing;
  }

  updateGround(dt, input, foe) {
    const move = input.move ?? 0;
    if (this.buf.attack && this.cool.attack <= 0) return this.startAttack(foe);
    if (this.buf.dodge && this.cool.dodge <= 0) return this.startDodge(move || this.facing);
    if (this.buf.jump) return this.startJump();
    if (Math.abs(move) > 0.15) {
      this.x += move * this.runSpeed * dt;
      this.facing = Math.sign(move);
      const ts = RUN_SCALE * Math.abs(move);
      if (this.state !== 'run') { this.state = 'run'; this.play('run', 0.15, { timeScale: ts }); }
      else this.current.timeScale = ts;
    } else {
      this.faceFoe(foe);
      if (this.state !== 'idle') { this.state = 'idle'; this.play('idle', 0.2); }
    }
  }

  toIdle(fade = 0.2) {
    this.state = 'idle';
    this.t = 0;
    this.play('idle', fade);
  }

  startAttack(foe) {
    this.faceFoe(foe);
    this.state = 'attack';
    this.t = 0;
    this.hitDone = false;
    this.buf.attack = 0;
    this.play('attack', 0.08, { timeScale: ATTACK_SPEED });
  }

  updateAttack(input, foe, fight) {
    if (!this.hitDone && this.t >= this.hitTime) {
      this.hitDone = true;
      fight.attackLands(this);
    }
    // After the hit you may cancel the recovery into a dodge.
    if (this.hitDone && this.t > this.hitTime + 0.15 && this.buf.dodge && this.cool.dodge <= 0) {
      return this.startDodge(input.move || -this.facing);
    }
    if (this.t >= this.attackTime - 0.15) {
      this.cool.attack = 0.12;
      this.toIdle();
    }
  }

  startJump() {
    this.state = 'jump';
    this.t = 0;
    this.jumpPhase = 'crouch';
    this.buf.jump = 0;
    this.play('jump', 0.08, { time: JUMP_CLIP_START });
  }

  updateJump(dt, input, foe, stage) {
    const move = input.move ?? 0;
    const ground = stage.groundY(this.x);
    if (this.jumpPhase === 'crouch') {
      this.y = ground;
      if (this.t >= JUMP_TAKEOFF) {
        this.jumpPhase = 'air';
        this.vy = JUMP_VELOCITY;
        this.airborne = true;
      }
      return;
    }
    if (this.jumpPhase === 'air') {
      this.x += move * this.runSpeed * AIR_CONTROL * dt;
      if (Math.abs(move) > 0.15) this.facing = Math.sign(move);
      this.vy -= GRAVITY * dt;
      this.y += this.vy * dt;
      if (this.current.time > JUMP_AIR_HOLD) this.current.time = JUMP_AIR_HOLD;
      const g = stage.groundY(this.x);
      if (this.y <= g && this.vy < 0) {
        this.y = g;
        this.vy = 0;
        this.airborne = false;
        this.jumpPhase = 'land';
        this.t = 0;
        this.current.time = Math.max(this.current.time, JUMP_LAND);
      }
      return;
    }
    // landing
    this.y = ground;
    if (this.buf.attack && this.cool.attack <= 0) return this.startAttack(foe);
    if (Math.abs(move) > 0.15 || this.t >= LAND_TIME) this.toIdle(0.15);
  }

  startDodge(dir) {
    this.dodgeDir = Math.sign(dir) || this.facing;
    this.facing = this.dodgeDir;
    this.state = 'dodge';
    this.t = 0;
    this.buf.dodge = 0;
    this.cool.dodge = DODGE_TIME + DODGE_COOLDOWN;
    this.play('dodge', 0.06, { timeScale: DODGE_SPEED });
  }

  updateDodge(dt) {
    const p = this.t / DODGE_TIME;
    if (p > 0.12 && p < 0.7) this.x += this.dodgeDir * (DODGE_DISTANCE / (0.58 * DODGE_TIME)) * dt;
    if (this.t >= DODGE_TIME) this.toIdle(0.15);
  }

  /** dir = direction from the attacker to this fighter. Returns false if it didn't count. */
  takeHit(damage, dir) {
    if (this.dead) return false;
    this.hp = Math.max(0, this.hp - damage);
    this.flash = 1;
    this.t = 0;
    this.vx = dir * KNOCKBACK;
    this.jumpPhase = null;
    if (this.hp <= 0) {
      this.state = 'dead';
      this.facing = -dir || this.facing;   // face the attacker, so the backward fall goes away from them
      this.vx = dir * 1.5;
      this.play('death', 0.08);
    } else {
      this.state = 'hit';
      this.play('hit', 0.05);
    }
    return true;
  }

  updateHit(dt) {
    this.x += this.vx * dt;
    this.vx *= Math.exp(-7 * dt);
    if (this.state === 'hit' && this.t >= HIT_STUN) this.toIdle(0.2);
  }

  /** Apply position/rotation/flash to the 3D objects and advance the animation. */
  sync(dt, groundY) {
    const target = this.facing * FACE_YAW;
    this.yaw += (target - this.yaw) * (1 - Math.exp(-14 * dt));
    this.body.rotation.y = this.yaw;
    this.body.position.set(this.x, this.y, 0);

    const lift = Math.max(0, this.y - groundY);
    const s = (0.45 + this.height * 0.3) / (1 + lift * 0.8);
    this.shadow.position.set(this.x, groundY + 0.02, 0.05);
    this.shadow.scale.set(s * 1.4, s * 0.8, 1);
    this.shadow.material.opacity = 1 / (1 + lift);

    if (this.flash > 0) this.flash = Math.max(0, this.flash - dt * 4);
    for (const { m, base } of this.materials) {
      m.emissive.setRGB(base.r + this.flash * 0.9, base.g + this.flash * 0.15, base.b + this.flash * 0.1);
    }
    this.mixer.update(dt);
  }
}
