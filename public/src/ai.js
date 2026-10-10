// The CPU opponent: re-decides a few times per second, so it reacts but can be outplayed.
export class Brain {
  constructor(me, foe, fight) {
    this.me = me;
    this.foe = foe;
    this.fight = fight;
    this.move = 0;
    this.next = 0.6;
    this.attackWait = 0.8;
  }

  think(dt) {
    const out = { move: this.move, jump: false, dodge: false, attack: false };
    const { me, foe } = this;
    this.next -= dt;
    this.attackWait -= dt;
    if (!me.canAct || foe.dead) { this.move = 0; return { ...out, move: 0 }; }
    if (this.next > 0) return out;
    this.next = 0.16 + Math.random() * 0.22;

    const dx = foe.x - me.x;
    const dist = Math.abs(dx);
    const dir = Math.sign(dx) || 1;
    const k = me.kit;
    const stage = this.fight.stage;
    const nearWall = (d) => (d < 0 ? me.x - stage.minX : stage.maxX - me.x) < 0.6;

    // Defend: a swing that is about to land, or a projectile flying in.
    const swing = foe.state === 'attack' && !foe.hitDone && foe.kit.type === 'melee' && dist < foe.kit.range + 0.5;
    const shot = this.fight.projectiles.threatTo(me);
    if ((swing || shot) && Math.random() < 0.45) {
      if (shot && Math.random() < 0.5) return { ...out, jump: true };
      const away = nearWall(-dir) ? dir : -dir;
      return { ...out, dodge: true, move: away };
    }

    if (k.type === 'melee') {
      if (dist > k.range * 0.85) this.move = dir;
      else if (this.attackWait <= 0) {
        this.move = 0;
        this.attackWait = 0.5 + Math.random() * 1.1;
        return { ...out, move: 0, attack: true };
      } else {
        this.move = Math.random() < 0.2 && !nearWall(-dir) ? -dir : 0;
      }
    } else {
      const ideal = k.type === 'arrow' ? 4.5 : 3;
      if (dist < 1.6) {
        if (nearWall(-dir) || Math.random() < 0.3) return { ...out, dodge: true, move: dir };   // roll past
        this.move = -dir;
      } else if (dist > k.range * 0.9) {
        this.move = dir;
      } else if (this.attackWait <= 0) {
        this.move = 0;
        this.attackWait = 0.9 + Math.random() * 1.2;
        return { ...out, move: 0, attack: true };
      } else {
        this.move = dist < ideal - 0.5 && !nearWall(-dir) ? -dir : dist > ideal + 0.5 ? dir : 0;
      }
    }

    if (Math.random() < 0.04) out.jump = true;
    out.move = this.move;
    return out;
  }
}
