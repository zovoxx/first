import { SplatMesh } from '@sparkjsdev/spark';
import { PLATFORMS, MAIN_PLATFORM } from '../config.js';
import { clamp, easeOutCubic, rand } from '../core/math.js';
import { Surface } from './collision.js';

// Extra floating platforms: the current biome's gaussian-splat ground, scaled down. Collision is the
// manifest walk_line. They rise in at random spots, live a random time, shake for 1.5 s as a warning,
// then fall and fade out. New ones keep spawning so there is always somewhere to go.
class FloatingPlatform {
  constructor(mgr, x, y, scale, life) {
    this.mgr = mgr;
    this.x = x;
    this.y = y;
    this.scale = scale;
    this.life = life;
    this.state = 'rising';
    this.t = 0;
    this.vy = 0;
    this.halfW = 4 * scale;

    this.mesh = new SplatMesh({ packedSplats: mgr.packed });
    this.mesh.scale.setScalar(scale);
    this.mesh.position.set(x, y - PLATFORMS.riseDistance, 0);
    this.mesh.opacity = 0;
    this.mesh.visible = !mgr.game.params.nosplats;
    mgr.scene.add(this.mesh);

    this.surface = new Surface(mgr.walkLine, { owner: this });
    this.surface.scale = scale;
    this.surface.ox = x;
    this.surface.oy = y - PLATFORMS.riseDistance;
    mgr.world.add(this.surface);
  }

  get solid() {
    return this.state === 'rising' || this.state === 'solid';
  }
  // seconds until it starts falling
  get remaining() {
    if (this.state === 'rising') return this.life + PLATFORMS.shakeTime;
    if (this.state === 'solid') return this.life - this.t + PLATFORMS.shakeTime;
    if (this.state === 'shaking') return PLATFORMS.shakeTime - this.t;
    return 0;
  }

  update(dt) {
    this.t += dt;
    const m = this.mesh;
    const s = this.surface;
    switch (this.state) {
      case 'rising': {
        const k = clamp(this.t / PLATFORMS.riseTime, 0, 1);
        s.oy = this.y - PLATFORMS.riseDistance * (1 - easeOutCubic(k));
        m.opacity = k;
        if (k >= 1) this.setState('solid');
        break;
      }
      case 'solid':
        s.oy = this.y + Math.sin((this.t + this.x) * 1.3) * 0.04; // gentle bob
        if (this.t >= this.life) {
          this.setState('shaking');
          this.mgr.game.audio.sfx('crumble');
        }
        break;
      case 'shaking': {
        const k = this.t / PLATFORMS.shakeTime;
        const amp = 0.025 + 0.09 * k;
        m.position.x = this.x + (Math.random() * 2 - 1) * amp;
        m.position.y = s.oy + (Math.random() * 2 - 1) * amp * 0.6;
        m.rotation.z = (Math.random() * 2 - 1) * amp * 0.12;
        if (Math.random() < dt * 30) {
          const fx = this.mgr.game.effects;
          fx.emit(this.x + rand(-this.halfW, this.halfW) * 0.8, this.y - rand(0.2, 1.2) * this.scale * 2, rand(-0.5, 0.5), 0, -1, 0, {
            life: 0.7,
            size: 0.12,
            color: this.mgr.dustColor,
            gravity: 6,
            drag: 0.5,
          });
        }
        if (this.t >= PLATFORMS.shakeTime) this.setState('falling');
        return; // collision stays put while shaking
      }
      case 'falling': {
        this.vy += PLATFORMS.fallAccel * dt;
        s.oy -= this.vy * dt;
        m.rotation.z += dt * 0.15 * Math.sign(this.x || 1);
        m.opacity = clamp(1 - this.t / PLATFORMS.fallFadeTime, 0, 1);
        if (this.t >= PLATFORMS.fallFadeTime || s.oy < this.mgr.game.killY - 2) this.setState('dead');
        break;
      }
      default:
        return;
    }
    m.position.x = this.x;
    m.position.y = s.oy;
  }

  setState(state) {
    this.state = state;
    this.t = 0;
    if (state === 'dead') this.dispose();
  }

  dispose() {
    this.mgr.world.remove(this.surface);
    this.mgr.scene.remove(this.mesh);
    this.mesh.dispose?.();
  }
}

export class FloatingPlatforms {
  constructor(game) {
    this.game = game;
    this.scene = game.scene;
    this.world = game.world;
    this.list = [];
    this.packed = null;
    this.walkLine = null;
    this.spawnTimer = 0;
    this.dustColor = 0xd8b27a;
  }

  // groundDef = manifest ground entry, packed = PackedSplats
  setGround(groundDef, packed, dustColor = 0xd8b27a) {
    this.packed = packed;
    this.walkLine = groundDef.walk_line.map(([x, y]) => [x, y]);
    this.dustColor = dustColor;
  }

  get active() {
    return this.list.filter((p) => p.state !== 'dead');
  }
  get standing() {
    return this.list.filter((p) => p.solid);
  }

  clear() {
    for (const p of this.list) if (p.state !== 'dead') p.setState('dead');
    this.list.length = 0;
  }

  // Make every platform start its shake/fall now (arena transitions).
  collapseAll() {
    for (const p of this.list) {
      if (p.state === 'rising' || p.state === 'solid') p.setState('shaking');
    }
  }

  fill(count, lifetime) {
    for (let i = 0; i < count; i++) this.spawn(lifetime, true);
  }

  update(dt, diff, spawning = true) {
    for (const p of this.list) p.update(dt);
    this.list = this.list.filter((p) => p.state !== 'dead');
    if (!spawning || !this.packed) return;
    this.spawnTimer -= dt;
    if (this.standing.length < diff.platformTarget && this.spawnTimer <= 0) {
      if (this.spawn(diff.platformLifetime)) this.spawnTimer = rand(...PLATFORMS.respawnDelay);
      else this.spawnTimer = 0.3;
    }
  }

  // Pick a free, reachable spot. Returns the platform or null.
  spawn(lifetime, initial = false) {
    const g = this.game;
    const rig = g.rig;
    const A = rig.halfW;
    const mainHalf = MAIN_PLATFORM.width / 2;
    const yMin = PLATFORMS.minY;
    const yMax = rig.topY - PLATFORMS.maxYBelowTop;
    const player = g.player?.body;
    let best = null;
    let bestScore = -Infinity;
    for (let tries = 0; tries < 40; tries++) {
      const scale = rand(...PLATFORMS.scale);
      const halfW = 4 * scale;
      const x = rand(-A + halfW + 0.2, A - halfW - 0.2);
      const y = rand(yMin, yMax);
      // keep clear of the main platform (allowed well above it)
      if (Math.abs(x) < mainHalf + halfW + 0.4 && y < 2.6) continue;
      let ok = true;
      let nearest = Infinity;
      let reachable = false;
      const surfaces = [g.mainPlatform.surface, ...this.standing.map((p) => p.surface)];
      for (const s of surfaces) {
        const sHalf = s.halfWidth;
        const dx = Math.abs(x - s.centerX);
        const dy = y - s.topY;
        if (!s.main && dx < halfW + sHalf + 0.8 && Math.abs(dy) < 2.3) {
          ok = false;
          break;
        }
        const gap = Math.max(0, dx - halfW - sHalf);
        if (gap < 5.5 && dy < 4.0 && dy > -6) reachable = true;
        nearest = Math.min(nearest, Math.hypot(dx, dy));
      }
      if (!ok) continue;
      // never pop up inside the player
      if (player && Math.abs(player.x - x) < halfW + 0.5 && player.y > y - 2.2 && player.y < y + 1.2) continue;
      const score = (reachable ? 10 : 0) + Math.min(nearest, 8) + Math.random() * 3;
      if (score > bestScore) {
        bestScore = score;
        best = { x, y, scale };
      }
    }
    if (!best) return null;
    const life = lifetime * rand(0.75, 1.3) + (initial ? rand(0, 4) : 0);
    const p = new FloatingPlatform(this, best.x, best.y, best.scale, life);
    this.list.push(p);
    return p;
  }
}
