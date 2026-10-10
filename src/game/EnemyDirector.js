import * as THREE from 'three';
import { ENEMIES, ENEMY } from '../config.js';
import { clamp, rand } from '../core/math.js';
import { beamTexture, ringTexture } from '../core/textures.js';
import { Enemy } from './Enemy.js';

// Warning marker shown before every spawn so it stays fair: a ground ring that fills up + a light beam.
class SpawnMarker {
  constructor(director, id, surface, x, duration) {
    this.director = director;
    this.id = id;
    this.surface = surface;
    this.x = x;
    this.duration = duration;
    this.t = 0;
    this.beeped = 0;
    const color = ENEMIES[id].color;
    const g = director.game;
    this.group = new THREE.Group();
    const additive = { transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, color };
    this.ring = new THREE.Mesh(new THREE.PlaneGeometry(2.2, 2.2), new THREE.MeshBasicMaterial({ ...additive, map: ringTexture() }));
    this.ring.rotation.x = -Math.PI / 2;
    this.ring.position.y = 0.04;
    this.fill = new THREE.Mesh(new THREE.CircleGeometry(0.62, 32), new THREE.MeshBasicMaterial({ ...additive, opacity: 0.35 }));
    this.fill.rotation.x = -Math.PI / 2;
    this.fill.position.y = 0.05;
    this.beam = new THREE.Mesh(new THREE.PlaneGeometry(1.0, 3.4), new THREE.MeshBasicMaterial({ ...additive, map: beamTexture(), opacity: 0 }));
    this.beam.position.y = 1.7;
    for (const m of [this.ring, this.fill, this.beam]) m.renderOrder = 14;
    this.group.add(this.ring, this.fill, this.beam);
    g.scene.add(this.group);
    this.y = surface.heightAt(x, 0.3) ?? surface.topY;
    this.group.position.set(x, this.y, 0.1);
    g.audio.sfx('warn');
  }

  get done() {
    return this.t >= this.duration;
  }

  update(dt) {
    this.t += dt;
    const k = clamp(this.t / this.duration, 0, 1);
    const h = this.surface.active ? this.surface.heightAt(this.x, 0.3) : null;
    if (h !== null) this.y = h;
    this.group.position.y = this.y;
    const pulse = 0.75 + 0.25 * Math.sin(this.t * 22);
    this.ring.material.opacity = (0.5 + 0.5 * k) * pulse;
    this.ring.scale.setScalar(1.15 - 0.25 * k);
    this.fill.scale.setScalar(Math.max(0.01, k));
    this.beam.material.opacity = k * k * 0.9 * pulse;
    this.beam.scale.x = 0.4 + 0.6 * k;
    if (this.beeped === 0 && k > 0.55) {
      this.beeped = 1;
      this.director.game.audio.sfx('warn');
    }
  }

  dispose() {
    this.director.game.scene.remove(this.group);
    this.group.traverse((o) => {
      if (o.isMesh) {
        o.geometry.dispose();
        o.material.dispose();
      }
    });
  }
}

// Decides when, what and where enemies spawn, and owns them.
export class EnemyDirector {
  constructor(game) {
    this.game = game;
    this.enemies = [];
    this.markers = [];
    this.templates = new Map();
    this.roster = [];
    this.spawnTimer = 2.5;
  }

  setTemplate(id, template) {
    this.templates.set(id, template);
  }

  setRoster(ids) {
    this.roster = ids.filter((id) => this.templates.has(id));
  }

  reset() {
    for (const e of this.enemies) e.dispose();
    for (const m of this.markers) m.dispose();
    this.enemies = [];
    this.markers = [];
    this.spawnTimer = 2.5;
  }

  killAll() {
    for (const e of this.enemies) e.die();
    for (const m of this.markers) m.dispose();
    this.markers = [];
  }

  get aliveCount() {
    let n = 0;
    for (const e of this.enemies) if (e.alive) n++;
    return n;
  }

  onPlayerDash(px, dir) {
    for (const e of this.enemies) e.onPlayerDash(px, dir);
  }

  // dt = scaled simulation time, rdt = real time (spawn warnings stay readable)
  update(dt, rdt, spawning) {
    const g = this.game;
    if (spawning && this.roster.length && g.player.alive) {
      const camping = g.player.stillTime > ENEMY.campTime;
      this.spawnTimer -= rdt * (camping ? 1.8 : 1);
      if (this.spawnTimer <= 0) {
        this.spawnTimer = g.diff.spawnInterval * rand(0.8, 1.2);
        this.trySpawn();
      }
    }

    for (let i = this.markers.length - 1; i >= 0; i--) {
      const m = this.markers[i];
      m.update(rdt);
      if (m.done) {
        this.markers.splice(i, 1);
        m.dispose();
        this.spawnFromMarker(m);
      }
    }

    for (const e of this.enemies) e.update(dt);
    this.separate();
    for (let i = this.enemies.length - 1; i >= 0; i--) {
      if (this.enemies[i].removed) {
        this.enemies[i].dispose();
        this.enemies.splice(i, 1);
      }
    }
  }

  // Keep enemies on the same ground from stacking into one blob.
  separate() {
    const list = this.enemies;
    for (let i = 0; i < list.length; i++) {
      const a = list[i];
      if (!a.alive || !a.body.grounded) continue;
      for (let j = i + 1; j < list.length; j++) {
        const b = list[j];
        if (!b.alive || b.body.ground !== a.body.ground) continue;
        const d = b.body.x - a.body.x;
        const min = (a.body.halfW + b.body.halfW) * 0.9;
        if (Math.abs(d) < min) {
          const push = (min - Math.abs(d)) * 0.5 * (d >= 0 ? 1 : -1);
          const s = a.body.ground;
          if (a.state !== 'attack') a.body.x = clamp(a.body.x - push, s.minX + 0.2, s.maxX - 0.2);
          if (b.state !== 'attack') b.body.x = clamp(b.body.x + push, s.minX + 0.2, s.maxX - 0.2);
        }
      }
    }
  }

  pickType() {
    // favour types with fewer alive so the roster stays mixed
    const weights = this.roster.map((id) => 1 / (1 + this.enemies.filter((e) => e.alive && e.id === id).length * 1.5));
    let r = Math.random() * weights.reduce((a, b) => a + b, 0);
    for (let i = 0; i < weights.length; i++) {
      r -= weights[i];
      if (r <= 0) return this.roster[i];
    }
    return this.roster[0];
  }

  trySpawn() {
    const g = this.game;
    const max = g.diff.maxEnemies;
    if (this.aliveCount + this.markers.length >= max) {
      // recycle: the farthest enemy that has been around a while leaves (death clip)
      const pb = g.player.body;
      let victim = null;
      let far = -1;
      for (const e of this.enemies) {
        if (!e.alive || e.age < 6 || e.state === 'attack') continue;
        const d = Math.abs(e.body.x - pb.x) + Math.abs(e.body.y - pb.y);
        if (d > far) {
          far = d;
          victim = e;
        }
      }
      if (!victim) return false;
      victim.die();
    }
    const spot = this.pickSpot();
    if (!spot) return false;
    const id = this.pickType();
    this.markers.push(new SpawnMarker(this, id, spot.surface, spot.x, g.diff.spawnWarning));
    return true;
  }

  // Around the player, and especially on the main platform, so standing still is never safe.
  pickSpot() {
    const g = this.game;
    const player = g.player;
    const pb = player.body;
    const main = g.mainPlatform.surface;
    const floating = g.platforms.standing.filter((p) => p.remaining > g.diff.spawnWarning + 2.5).map((p) => p.surface);
    const onMain = pb.grounded && pb.ground === main;
    const camping = player.stillTime > ENEMY.campTime;
    const order = [];
    if (onMain || Math.random() < 0.62) order.push(main);
    if (pb.ground && pb.ground !== main && floating.includes(pb.ground)) order.push(pb.ground);
    floating.sort((a, b) => Math.abs(a.centerX - pb.x) - Math.abs(b.centerX - pb.x));
    for (const s of floating) if (!order.includes(s)) order.push(s);
    if (!order.includes(main)) order.push(main);

    for (const s of order) {
      const margin = 0.45;
      if (s.maxX - s.minX < 1.4) continue;
      for (let k = 0; k < 10; k++) {
        let x;
        if (camping && k === 0 && s === pb.ground) x = pb.x; // right on top of a camper
        else x = pb.x + (Math.random() < 0.5 ? -1 : 1) * rand(1.8, 4.6);
        if (k > 6) x = rand(s.minX, s.maxX);
        x = clamp(x, s.minX + margin, s.maxX - margin);
        if (s.heightAt(x) === null) continue;
        if (!(camping && k === 0) && Math.abs(x - pb.x) < 1.3 && s === pb.ground) continue;
        let crowded = false;
        for (const e of this.enemies) if (e.alive && Math.abs(e.body.x - x) < 0.9 && e.body.ground === s) crowded = true;
        for (const m of this.markers) if (Math.abs(m.x - x) < 1.1 && m.surface === s) crowded = true;
        if (crowded) continue;
        return { surface: s, x };
      }
    }
    return null;
  }

  spawnFromMarker(m) {
    const g = this.game;
    let surface = m.surface;
    let x = m.x;
    if (!surface.active || surface.heightAt(x, 0.3) === null || surface.owner?.solid === false) {
      surface = g.mainPlatform.surface;
      x = clamp(x, surface.minX + 0.5, surface.maxX - 0.5);
    }
    const template = this.templates.get(m.id);
    if (!template) return;
    const e = new Enemy(this, m.id, template, x, surface);
    this.enemies.push(e);
    const y = e.body.y;
    const color = ENEMIES[m.id].color;
    g.effects.ring(x, y, color, { to: 2.2, life: 0.5 });
    g.effects.burst(x, y + 0.9, 26, { speed: 5, up: 1.5, color, size: 0.2, life: 0.55 });
    g.audio.sfx('spawn');
    // standing on the marker hurts: the warning was there
    const pb = g.player.body;
    if (Math.abs(pb.x - x) < ENEMY.spawnBurstRadius && pb.y > y - 0.5 && pb.y < y + 1.4) {
      g.player.hurt(ENEMY.spawnBurstDamage * g.diff.damageMul, x, 6);
    }
  }
}
