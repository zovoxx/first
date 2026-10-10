import { PLAYER } from '../config.js';
import { approach, clamp } from '../core/math.js';
import { Body } from './collision.js';
import { WispVisual } from './WispVisual.js';

// The player: moves, jumps (plus one air jump) and dashes. No attack - it only survives.
// Dashing gives brief invulnerability and staggers enemies it passes through.
export class Player {
  constructor(game) {
    this.game = game;
    this.body = new Body(PLAYER.halfW, PLAYER.height);
    this.visual = new WispVisual(game.effects, game.quality);
    this.visual.addTo(game.scene);
    this.reset(0, 0, null);
  }

  reset(x, y, ground) {
    this.body.place(x, y, ground);
    this.health = PLAYER.maxHealth;
    this.face = 1;
    this.coyote = 0;
    this.jumpBuffer = 0;
    this.airJumps = PLAYER.airJumps;
    this.jumpCutDone = true;
    this.dashTime = 0;
    this.dashCooldown = 0;
    this.dashDir = 1;
    this.airDashUsed = false;
    this.iframes = 0;
    this.sinceHurt = 99;
    this.dropTimer = 0;
    this.dead = false;
    this.stillTime = 0;
    this.stillAnchor = x;
    this.dashHits = new Set();
    this.visual.dead = false;
  }

  get alive() {
    return !this.dead;
  }
  get dashing() {
    return this.dashTime > 0;
  }
  get invulnerable() {
    return this.iframes > 0 || this.dashTime > 0 || this.game.params.god;
  }

  update(dt, input) {
    const b = this.body;
    const g = this.game;
    if (this.dead) {
      this.visual.update(dt, this.snapshot());
      return;
    }

    this.iframes = Math.max(0, this.iframes - dt);
    this.dashCooldown = Math.max(0, this.dashCooldown - dt);
    this.dropTimer = Math.max(0, this.dropTimer - dt);
    this.jumpBuffer = Math.max(0, this.jumpBuffer - dt);
    this.coyote = b.grounded ? PLAYER.coyote : Math.max(0, this.coyote - dt);
    this.sinceHurt += dt;
    if (input.jumpPressed) this.jumpBuffer = PLAYER.jumpBuffer;
    if (input.moveX !== 0 && this.dashTime <= 0) this.face = input.moveX > 0 ? 1 : -1;

    // dash
    if (input.dashPressed && this.dashCooldown <= 0 && this.dashTime <= 0 && (b.grounded || !this.airDashUsed)) {
      this.dashDir = input.moveX !== 0 ? Math.sign(input.moveX) : this.face;
      this.face = this.dashDir;
      this.dashTime = PLAYER.dashTime;
      this.dashCooldown = PLAYER.dashCooldown;
      this.iframes = Math.max(this.iframes, PLAYER.dashIframes);
      if (!b.grounded) this.airDashUsed = true;
      this.dashHits.clear();
      this.visual.onDash(this.dashDir);
      g.director.onPlayerDash(b.x, this.dashDir);
      g.audio.sfx('dash');
    }

    let gravity = PLAYER.gravity;
    if (this.dashTime > 0) {
      this.dashTime -= dt;
      b.vx = this.dashDir * PLAYER.dashSpeed;
      b.vy = 0; // hold height during the dash
      gravity = 0;
      if (this.dashTime <= 0) b.vx *= 0.42;
    } else {
      const target = input.moveX * PLAYER.runSpeed;
      const accel = b.grounded ? PLAYER.groundAccel : PLAYER.airAccel;
      const friction = b.grounded ? PLAYER.groundFriction : PLAYER.airFriction;
      b.vx = approach(b.vx, target, (input.moveX !== 0 ? accel : friction) * dt);

      // jump / air jump / drop through
      if (this.jumpBuffer > 0) {
        if (b.grounded && input.down && b.ground?.droppable) {
          b.grounded = false;
          b.ground = null;
          this.dropTimer = 0.28;
          b.vy = -1;
          this.jumpBuffer = 0;
        } else if (b.grounded || this.coyote > 0) {
          b.vy = PLAYER.jumpSpeed;
          b.grounded = false;
          b.ground = null;
          this.coyote = 0;
          this.jumpBuffer = 0;
          this.jumpCutDone = false;
          this.visual.onJump(false);
          g.audio.sfx('jump');
        } else if (this.airJumps > 0) {
          b.vy = PLAYER.airJumpSpeed;
          this.airJumps--;
          this.jumpBuffer = 0;
          this.jumpCutDone = false;
          this.visual.onJump(true);
          g.audio.sfx('airjump');
        }
      }
      if (!this.jumpCutDone && !input.jumpHeld && b.vy > 0) {
        b.vy *= PLAYER.jumpCut;
        this.jumpCutDone = true;
      }
      if (b.vy < 0) gravity *= PLAYER.fallGravityMul;
    }

    const fallSpeed = -b.vy;
    b.step(dt, g.world, {
      gravity,
      maxFall: PLAYER.maxFall,
      minX: -g.rig.halfW + b.halfW,
      maxX: g.rig.halfW - b.halfW,
      ignoreDroppable: this.dropTimer > 0,
      ceiling: g.rig.topY - PLAYER.ceilingMargin,
    });
    if (b.landed) {
      this.airJumps = PLAYER.airJumps;
      this.airDashUsed = false;
      this.visual.onLand(fallSpeed);
      if (fallSpeed > 8) g.audio.sfx('land');
    }

    // dash through enemies -> stagger
    if (this.dashTime > 0) {
      for (const e of g.director.enemies) {
        if (!this.dashHits.has(e) && e.canBeStaggered && b.overlaps(e.body)) {
          this.dashHits.add(e);
          e.onDashedThrough(this.dashDir);
        }
      }
    }

    // standing still is tracked so spawns can punish camping
    if (Math.abs(b.x - this.stillAnchor) > 1.6) {
      this.stillAnchor = b.x;
      this.stillTime = 0;
    } else {
      this.stillTime += dt;
    }

    // regen when not hit for a while
    if (this.sinceHurt > PLAYER.regenDelay && this.health < PLAYER.maxHealth) {
      this.health = Math.min(PLAYER.maxHealth, this.health + g.diff.regenPerSec * dt);
    }

    // fell into the void
    if (b.y < g.killY) this.onFell();

    this.visual.update(dt, this.snapshot());
  }

  snapshot() {
    const b = this.body;
    const ground = b.grounded ? { y: b.y } : this.game.world.groundBelow(b.x, b.y, 0.1);
    return {
      x: b.x,
      y: b.y,
      vx: b.vx,
      vy: b.vy,
      face: this.face,
      grounded: b.grounded,
      dashing: this.dashing,
      invulnerable: this.invulnerable,
      health01: this.health / PLAYER.maxHealth,
      groundY: ground ? ground.y : null,
    };
  }

  // amount already includes difficulty scaling. fromX = attacker position (knockback direction).
  hurt(amount, fromX, knock = PLAYER.knockback) {
    if (this.dead || this.invulnerable) return false;
    this.health -= amount;
    this.sinceHurt = 0;
    this.iframes = PLAYER.hurtIframes;
    const dir = this.body.x >= fromX ? 1 : -1;
    this.body.vx = dir * knock;
    if (this.body.grounded) {
      this.body.grounded = false;
      this.body.ground = null;
    }
    this.body.vy = Math.max(this.body.vy, 5.5);
    this.dashTime = 0;
    this.visual.onHurt();
    this.game.onPlayerHurt(amount);
    if (this.health <= 0) this.die();
    return true;
  }

  onFell() {
    const g = this.game;
    if (!g.params.god) this.health -= PLAYER.fallDamage;
    this.sinceHurt = 0;
    g.onPlayerHurt(PLAYER.fallDamage);
    if (this.health <= 0) {
      this.die();
      return;
    }
    // respawn by dropping onto the main platform, away from enemies
    const main = g.mainPlatform.surface;
    let bestX = 0;
    let bestScore = -Infinity;
    for (let i = 0; i < 9; i++) {
      const x = main.minX + 1 + ((main.maxX - main.minX - 2) * i) / 8;
      let score = -Math.abs(x) * 0.15;
      for (const e of g.director.enemies) if (e.alive) score += Math.min(4, Math.abs(e.body.x - x));
      if (score > bestScore) {
        bestScore = score;
        bestX = x;
      }
    }
    const b = this.body;
    b.place(bestX, (main.heightAt(bestX) ?? 0) + 3.2, null);
    this.iframes = PLAYER.respawnIframes;
    this.airJumps = PLAYER.airJumps;
    this.airDashUsed = false;
    this.dashTime = 0;
    g.effects.burst(bestX, b.y + 0.5, 30, { speed: 5, color: 0x63f2ff, size: 0.2, life: 0.6 });
  }

  die() {
    if (this.dead) return;
    this.health = 0;
    this.dead = true;
    this.visual.onDeath();
    this.game.audio.sfx('death');
    this.game.onPlayerDied();
  }

  // AABB for hit tests
  get hitbox() {
    return this.body;
  }

  clampHealth() {
    this.health = clamp(this.health, 0, PLAYER.maxHealth);
  }
}
