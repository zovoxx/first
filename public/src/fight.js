// A best-of-3 fight between the player and the CPU on one stage.
import { MAX_HP } from './fighter.js';
import { Brain } from './ai.js';
import { Projectiles } from './projectiles.js';

const ROUNDS_TO_WIN = 2;
const START_X = 1.8;
const MIN_GAP = 0.55;
const NO_INPUT = { move: 0 };

export class Fight {
  constructor({ scene, stage, player, cpu, hud, music, onOver }) {
    this.stage = stage;
    this.player = player;
    this.cpu = cpu;
    this.fighters = [player, cpu];
    this.hud = hud;
    this.music = music;
    this.onOver = onOver;
    this.brain = new Brain(cpu, player, this);
    this.projectiles = new Projectiles(scene);
    this.wins = [0, 0];
    this.round = 0;
    this.shake = 0;
    this.startRound();
  }

  get finalRound() {
    return this.wins[0] === ROUNDS_TO_WIN - 1 && this.wins[1] === ROUNDS_TO_WIN - 1;
  }

  startRound() {
    this.round++;
    this.projectiles.clear();
    this.player.reset(-START_X, 1, this.stage.groundY(-START_X));
    this.cpu.reset(START_X, -1, this.stage.groundY(START_X));
    this.brain.next = 0.6;
    this.phase = 'intro';
    this.phaseT = 0;
    this.slowmo = 1;
    this.hitstop = 0;
    this.hud.round(this.round, this.wins, ROUNDS_TO_WIN, this.finalRound);
    this.hud.banner(this.finalRound ? 'Final round' : `Round ${this.round}`, 1100);
    this.music.play(this.finalRound ? 'boss' : 'combat');
  }

  update(rawDt, input) {
    let dt = rawDt * this.slowmo;
    if (this.hitstop > 0) {   // freeze the action for a moment when a hit lands
      this.hitstop -= rawDt;
      dt *= 0.05;
    }
    this.phaseT += rawDt;

    let pIn = NO_INPUT;
    let cIn = NO_INPUT;
    if (this.phase === 'intro' && this.phaseT > 1.3) {
      this.phase = 'fight';
      this.hud.banner('Fight!', 650);
    } else if (this.phase === 'fight') {
      pIn = input;
      cIn = this.brain.think(dt);
    }

    this.player.update(dt, pIn, this.cpu, this);
    this.cpu.update(dt, cIn, this.player, this);
    this.projectiles.update(dt, this);
    this.separate();
    for (const f of this.fighters) f.sync(dt, this.stage.groundY(f.x));
    this.hud.health(this.player.hp / MAX_HP, this.cpu.hp / MAX_HP, rawDt);
    this.shake = Math.max(0, this.shake - rawDt * 2.5);

    if (this.phase === 'fight' && (this.player.dead || this.cpu.dead)) {
      this.phase = 'ko';
      this.phaseT = 0;
      this.slowmo = 0.4;
      this.music.sfx('ko');
      this.hud.banner('K.O.', 1500);
    } else if (this.phase === 'ko') {
      if (this.phaseT > 1.0) this.slowmo = 1;
      if (this.phaseT > 3.0) this.endRound();
    }
  }

  endRound() {
    const p = this.player.dead;
    const c = this.cpu.dead;
    if (c && !p) this.wins[0]++;
    if (p && !c) this.wins[1]++;   // a double K.O. scores nothing
    this.hud.round(this.round, this.wins, ROUNDS_TO_WIN, false);
    if (this.wins.some((w) => w >= ROUNDS_TO_WIN)) {
      this.phase = 'over';
      this.onOver(this.wins[0] >= ROUNDS_TO_WIN);
    } else {
      this.startRound();
    }
  }

  /** Called by a fighter at the attack's hit time (from contoo_assets.json). */
  attackLands(a) {
    const foe = a === this.player ? this.cpu : this.player;
    const k = a.kit;
    this.music.sfx('swing');
    if (k.type === 'arrow') {
      this.projectiles.spawn('arrow', a, a.x + a.facing * 0.35, a.y + a.height * 0.62, a.facing, k.damage, k.range);
    } else if (k.type === 'frost') {
      this.projectiles.spawn('frost', a, a.x + a.facing * 0.6, this.stage.groundY(a.x), a.facing, k.damage, k.range);
    } else {
      const reach = (foe.x - a.x) * a.facing;
      if (reach > -0.3 && reach < k.range && Math.abs(foe.y - a.y) < 1.1 && !foe.invulnerable) {
        this.applyHit(a, foe, k.damage, a.facing);
      }
    }
  }

  applyHit(attacker, target, damage, dir) {
    if (!target.takeHit(damage, dir)) return;
    this.hitstop = 0.07;
    this.shake = Math.min(1, this.shake + 0.5);
    if (!target.dead) this.music.sfx('hit');
  }

  /** Fighters can't stand inside each other (unless one is dodging or jumping over), and stay on the floor. */
  separate() {
    const [a, b] = this.fighters;
    const passing = a.state === 'dodge' || b.state === 'dodge' || a.dead || b.dead || Math.abs(a.y - b.y) > 0.9;
    const d = b.x - a.x;
    if (!passing && Math.abs(d) < MIN_GAP) {
      const push = ((MIN_GAP - Math.abs(d)) / 2) * (Math.sign(d) || 1);
      a.x -= push;
      b.x += push;
    }
    for (const f of this.fighters) f.x = Math.min(this.stage.maxX, Math.max(this.stage.minX, f.x));
  }

  dispose(scene) {
    this.projectiles.clear();
    for (const f of this.fighters) scene.remove(f.object);
  }
}
