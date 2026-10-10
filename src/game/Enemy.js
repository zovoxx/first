import * as THREE from 'three';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import { ENEMIES, ENEMY } from '../config.js';
import { angleDelta, clamp, damp, rand, smoothstep } from '../core/math.js';
import { radialTexture } from '../core/textures.js';
import { Body } from './collision.js';

const ONE_SHOT = new Set(['jump', 'dodge', 'hit', 'attack', 'death']);
const FACE = THREE.MathUtils.degToRad(ENEMY.faceAngleDeg);
const _emissive = new THREE.Color();
const _white = new THREE.Color(0xffffff);

// One enemy character: a SkeletonUtils clone of the shared GLB with its own mixer and materials.
// Uses every clip: idle, run (time-scaled to the move speed), jump (between platforms), dodge (evades a
// dash), hit (stagger), attack (damage exactly at hit_time_s), death (when removed).
export class Enemy {
  constructor(director, id, template, x, surface) {
    const g = director.game;
    this.director = director;
    this.game = g;
    this.id = id;
    this.def = ENEMIES[id];
    this.data = template.def; // manifest entry
    this.clips = this.data.clips;
    this.color = new THREE.Color(this.def.color);

    this.root = new THREE.Group();
    this.model = SkeletonUtils.clone(template.gltf.scene);
    this.materials = [];
    this.model.traverse((o) => {
      if (o.isMesh) {
        o.frustumCulled = false; // skinned meshes animate outside their bind-pose bounds
        o.material = o.material.clone();
        this.materials.push(o.material);
      }
    });
    this.root.add(this.model);
    // attack tell: a glint above the head that swells during the wind-up
    this.tell = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: radialTexture(),
        color: this.def.color,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        depthTest: false,
        transparent: true,
        opacity: 0,
      }),
    );
    this.tell.position.y = this.data.height_m + 0.3;
    this.tell.renderOrder = 25;
    this.root.add(this.tell);
    g.scene.add(this.root);

    this.mixer = new THREE.AnimationMixer(this.model);
    this.actions = {};
    for (const clip of template.gltf.animations) {
      const a = this.mixer.clipAction(clip);
      if (ONE_SHOT.has(clip.name)) {
        a.setLoop(THREE.LoopOnce, 1);
        a.clampWhenFinished = true;
      }
      this.actions[clip.name] = a;
    }
    this.current = null;

    this.body = new Body(this.def.hitW / 2, this.data.height_m);
    this.body.place(x, surface.heightAt(x, 0.3) ?? surface.topY, surface);
    this.face = g.player.body.x >= x ? 1 : -1;
    this.yaw = this.face * FACE;
    this.alive = true;
    this.removed = false;
    this.age = 0;
    this.life = g.diff.enemyLifetime * rand(0.85, 1.15);
    this.cooldown = rand(0.5, 1.0);
    this.staggerCd = 0;
    this.jumpWait = 0;
    this.reaction = rand(...ENEMY.jumpReaction);
    this.glow = 0;
    this.flash = 1;
    this.fade = 1;
    this.shadow = g.effects.makeShadow(this.def.hitW * 1.7);
    this.setState('appear');
    this.play('idle', { fade: 0 });
    this.syncVisual(0);
  }

  // ---- animation ----
  play(name, { fade = 0.15, timeScale = 1, restart = true } = {}) {
    const next = this.actions[name];
    if (!next) return;
    if (this.current === next && !restart) {
      next.setEffectiveTimeScale(timeScale);
      return;
    }
    next.reset();
    next.setEffectiveTimeScale(timeScale);
    next.setEffectiveWeight(1);
    if (fade > 0) next.fadeIn(fade);
    next.play();
    if (this.current && this.current !== next) {
      if (fade > 0) this.current.fadeOut(fade);
      else this.current.stop();
    }
    this.current = next;
  }

  loop(name, timeScale = 1) {
    this.play(name, { timeScale, restart: this.current !== this.actions[name] });
  }

  setState(state) {
    this.state = state;
    this.stateT = 0;
  }

  get speed() {
    return this.clips.run.ground_speed_mps * this.def.speedMul * this.game.diff.enemySpeed;
  }

  get canBeStaggered() {
    return this.alive && this.staggerCd <= 0 && (this.state === 'chase' || this.state === 'attack' || this.state === 'jumpPrep');
  }

  // ---- reactions ----
  onDashedThrough(dir) {
    if (!this.canBeStaggered) return;
    this.setState('stagger');
    this.play('hit', { timeScale: 1.0 / ENEMY.staggerTime, fade: 0.08 });
    this.body.vx = dir * 2.5;
    this.staggerCd = ENEMY.staggerCooldown;
    this.cooldown = Math.max(this.cooldown, 0.5);
    this.flash = 1;
    this.glow = 0;
    const b = this.body;
    this.game.effects.burst(b.x, b.y + b.height * 0.6, 14, { speed: 4, color: 0xffffff, size: 0.14, life: 0.35 });
    this.game.audio.sfx('stagger');
  }

  // The player started a dash toward us: sometimes evade with the dodge clip instead of being staggered.
  onPlayerDash(px, dir) {
    if (!this.alive || this.state !== 'chase' || !this.body.grounded) return;
    const dx = this.body.x - px;
    if (Math.sign(dx) !== dir || Math.abs(dx) > 3.5) return;
    if (Math.random() > this.game.diff.dodgeChance) return;
    this.setState('dodge');
    this.dodgeDir = dir; // move along the dash, away from the player
    this.face = -dir;
    this.play('dodge', { timeScale: 1.6, fade: 0.06 });
  }

  die() {
    if (!this.alive) return;
    this.alive = false;
    this.glow = 0;
    this.setState('dying');
    this.play('death', { timeScale: 1.15, fade: 0.12 });
    this.body.vx = 0;
  }

  // ---- main update (dt is already scaled by game speed) ----
  update(dt) {
    const g = this.game;
    const b = this.body;
    this.age += dt;
    this.stateT += dt;
    this.cooldown -= dt;
    this.staggerCd -= dt;
    if (this.alive && this.state !== 'attack') {
      this.life -= dt;
      if (this.life <= 0) this.die();
    }

    switch (this.state) {
      case 'appear':
        b.vx = 0;
        if (this.stateT >= ENEMY.appearTime) this.setState('chase');
        break;
      case 'chase':
        this.think(dt);
        break;
      case 'attack':
        this.updateAttack(dt);
        break;
      case 'jumpPrep':
        b.vx = 0;
        if (this.stateT >= 0.16) this.launch();
        break;
      case 'air':
        if (b.grounded) {
          b.vx = 0;
          this.setState('chase');
          this.play('idle', { fade: 0.2 });
        }
        break;
      case 'dodge': {
        const k = this.stateT / 0.45;
        b.vx = k < 1 ? this.dodgeDir * 4.8 * (1 - k * 0.6) : 0;
        if (b.grounded && b.ground) {
          const nx = b.x + b.vx * dt;
          if (nx < b.ground.minX + 0.3 || nx > b.ground.maxX - 0.3) b.vx = 0; // don't dodge off the edge
        }
        if (this.stateT >= 0.75) this.setState('chase');
        break;
      }
      case 'stagger':
        b.vx = damp(b.vx, 0, 8, dt);
        if (this.stateT >= ENEMY.staggerTime) this.setState('chase');
        break;
      case 'dying': {
        b.vx = 0;
        const clipTime = this.clips.death.seconds / 1.15;
        if (this.stateT > clipTime) {
          this.fade = clamp(1 - (this.stateT - clipTime) / ENEMY.deathFade, 0, 1);
          if (this.fade <= 0) this.removed = true;
        }
        break;
      }
      default:
        break;
    }

    const wasGrounded = b.grounded;
    b.step(dt, g.world, {
      gravity: ENEMY.gravity,
      maxFall: 22,
      minX: -g.rig.halfW + b.halfW,
      maxX: g.rig.halfW - b.halfW,
    });
    if (wasGrounded && !b.grounded && this.alive && this.state !== 'air') {
      // walked off / ground fell away
      this.setState('air');
      this.play('jump', { timeScale: 0.6, fade: 0.1 });
    }
    if (b.y < g.killY) {
      if (this.alive) this.die();
      this.removed = true;
    }
    this.syncVisual(dt);
    this.mixer.update(dt);
  }

  think(dt) {
    const g = this.game;
    const b = this.body;
    const player = g.player;
    if (!player.alive) {
      b.vx = 0;
      this.loop('idle');
      return;
    }
    const pb = player.body;
    const dx = pb.x - b.x;
    const dy = pb.y - b.y;
    if (Math.abs(dx) > 0.2) this.face = Math.sign(dx);
    const range = this.def.range;

    if (b.grounded && this.cooldown <= 0 && Math.abs(dx) <= range * 0.92 && dy > -0.9 && dy < 1.8) {
      this.startAttack();
      return;
    }

    const ground = b.ground;
    const target = pb.grounded ? pb.ground : g.world.groundBelow(pb.x, pb.y, 0.2)?.surface;
    if (target && ground && target !== ground) {
      this.jumpWait += dt;
      if (this.jumpWait >= this.reaction && this.tryJumpTo(target, pb.x)) return;
    } else {
      this.jumpWait = 0;
    }

    let tx = target === ground ? pb.x - Math.sign(dx || 1) * range * 0.55 : pb.x;
    if (ground) tx = clamp(tx, ground.minX + 0.35, ground.maxX - 0.35);
    const ddx = tx - b.x;
    if (Math.abs(ddx) > 0.15) {
      const speed = this.speed;
      b.vx = Math.sign(ddx) * Math.min(speed, Math.abs(ddx) / Math.max(dt, 1e-3));
      this.face = Math.sign(ddx);
      this.loop('run', this.def.speedMul * g.diff.enemySpeed);
    } else {
      b.vx = 0;
      this.loop('idle');
    }
  }

  tryJumpTo(surface, px) {
    const owner = surface.owner;
    if (owner && owner.solid === false) return false;
    const b = this.body;
    const lx = clamp(px, surface.minX + 0.4, surface.maxX - 0.4);
    const ly = surface.heightAt(lx);
    if (ly === null) return false;
    const dx = lx - b.x;
    const dy = ly - b.y;
    if (Math.abs(dx) > ENEMY.maxJumpDx || dy > ENEMY.maxJumpUp) return false;
    this.jumpPlan = { dx, dy };
    const T = clamp(0.45 + 0.07 * Math.abs(dx) + 0.06 * Math.max(0, dy), 0.55, 1.05);
    this.jumpPlan.T = T;
    this.face = Math.sign(dx) || this.face;
    this.setState('jumpPrep');
    this.play('jump', { timeScale: this.clips.jump.seconds / (T + 0.5), fade: 0.08 });
    this.jumpWait = 0;
    this.reaction = rand(...ENEMY.jumpReaction);
    return true;
  }

  launch() {
    const b = this.body;
    const { dx, dy, T } = this.jumpPlan;
    const G = ENEMY.gravity;
    b.vy = (dy + 0.5 * G * T * T) / T;
    b.vx = dx / T;
    b.grounded = false;
    b.ground = null;
    this.setState('air');
  }

  startAttack() {
    this.setState('attack');
    this.attackClock = 0;
    this.hitDone = false;
    this.attackRate = this.game.diff.attackSpeed;
    this.body.vx = 0;
    this.play('attack', { timeScale: this.attackRate, fade: 0.1 });
  }

  updateAttack(dt) {
    const g = this.game;
    const b = this.body;
    b.vx = 0;
    const hitT = this.clips.attack.hit_time_s;
    this.attackClock += dt * this.attackRate;
    // track the player during the first half of the wind-up only
    if (this.attackClock < hitT * 0.5) {
      const dx = g.player.body.x - b.x;
      if (Math.abs(dx) > 0.2) this.face = Math.sign(dx);
    }
    this.glow = this.hitDone ? Math.max(0, this.glow - dt * 4) : smoothstep(hitT * 0.3, hitT, this.attackClock);
    if (!this.hitDone && this.attackClock >= hitT) {
      this.hitDone = true;
      this.resolveHit();
    }
    if (this.attackClock >= this.clips.attack.seconds) {
      this.cooldown = g.diff.attackCooldown * rand(0.8, 1.25);
      this.setState('chase');
    }
  }

  // Damage lands exactly at the clip's hit_time_s.
  resolveHit() {
    const g = this.game;
    const b = this.body;
    const range = this.def.range;
    const x0 = b.x - this.face * 0.25;
    const x1 = b.x + this.face * range;
    const minX = Math.min(x0, x1);
    const maxX = Math.max(x0, x1);
    const pb = g.player.body;
    const hit = pb.x + pb.halfW > minX && pb.x - pb.halfW < maxX && pb.y < b.y + b.height * 1.05 && pb.y + pb.height > b.y - 0.1;
    g.effects.slash(b.x + this.face * 0.15, b.y, this.face, range, b.height, this.def.color);
    g.audio.sfx('swing');
    if (this.id === 'brumm' && b.grounded) g.effects.ring(b.x + this.face * range * 0.7, b.y, 0xffa060, { to: 1.4, life: 0.35 });
    if (hit && g.player.hurt(this.def.damage * g.diff.damageMul, b.x, this.def.knockback)) g.rig.shake(0.18, 0.25);
    this.flash = 0.5;
  }

  syncVisual(dt) {
    const g = this.game;
    const b = this.body;
    this.root.position.set(b.x, b.y, 0);
    const targetYaw = this.face * FACE;
    this.yaw += angleDelta(this.yaw, targetYaw) * (1 - Math.exp(-14 * dt));
    this.model.rotation.y = this.yaw;
    if (this.state === 'appear') {
      const k = clamp(this.stateT / ENEMY.appearTime, 0, 1);
      const s = 0.3 + 0.7 * (1 + 2.2 * Math.pow(k - 1, 3) + 1.2 * Math.pow(k - 1, 2)); // ease-out-back
      this.root.scale.setScalar(s);
    } else {
      this.root.scale.setScalar(1);
    }
    if (this.state === 'dying') this.root.position.y -= (1 - this.fade) * 0.4;

    this.flash = Math.max(0, this.flash - dt * 4);
    _emissive.copy(this.color).multiplyScalar(this.glow * 0.3).lerp(_white, this.flash * 0.6);
    this.tell.material.opacity = Math.min(1, this.glow * 1.2);
    this.tell.scale.setScalar(0.35 + this.glow * 0.75);
    const transparent = this.fade < 1;
    for (const m of this.materials) {
      m.emissive.copy(_emissive);
      if (m.transparent !== transparent) {
        m.transparent = transparent;
        m.depthWrite = !transparent;
        m.needsUpdate = true;
      }
      m.opacity = this.fade;
    }
    g.effects.placeShadow(this.shadow, g.world, b.x, b.y, this.fade);
  }

  dispose() {
    const g = this.game;
    this.mixer.stopAllAction();
    this.mixer.uncacheRoot(this.model);
    g.scene.remove(this.root);
    for (const m of this.materials) m.dispose();
    this.tell.material.dispose();
    g.effects.removeShadow(this.shadow);
  }
}
