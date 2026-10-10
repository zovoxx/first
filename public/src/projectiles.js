// Ranged attacks: Wren's arrows (chest height) and Lady Frostine's frost wave (along the ground).
import * as THREE from 'three';

const SPEED = { arrow: 15, frost: 7 };

export class Projectiles {
  constructor(scene) {
    this.scene = scene;
    this.list = [];
    this.wood = new THREE.MeshStandardMaterial({ color: 0x8a5a2b, roughness: 0.7 });
    this.steel = new THREE.MeshStandardMaterial({ color: 0xd8dde6, metalness: 0.8, roughness: 0.3 });
    this.feather = new THREE.MeshStandardMaterial({ color: 0x3f8f4a, side: THREE.DoubleSide });
    this.ice = new THREE.MeshStandardMaterial({
      color: 0xcff4ff, emissive: 0x3aa8ff, emissiveIntensity: 0.9, roughness: 0.15, transparent: true, opacity: 0.9,
    });
    this.shaftGeo = new THREE.CylinderGeometry(0.012, 0.012, 0.8, 6).rotateZ(Math.PI / 2);
    this.tipGeo = new THREE.ConeGeometry(0.035, 0.12, 8).rotateZ(-Math.PI / 2).translate(0.45, 0, 0);
    this.featherGeo = new THREE.PlaneGeometry(0.14, 0.05).translate(-0.35, 0, 0);
    this.shardGeo = new THREE.ConeGeometry(0.09, 0.5, 6).translate(0, 0.25, 0);
  }

  makeArrow() {
    const g = new THREE.Group();
    g.add(new THREE.Mesh(this.shaftGeo, this.wood), new THREE.Mesh(this.tipGeo, this.steel));
    const f1 = new THREE.Mesh(this.featherGeo, this.feather);
    const f2 = f1.clone();
    f2.rotation.x = Math.PI / 2;
    g.add(f1, f2);
    return g;
  }

  makeFrost() {
    const g = new THREE.Group();
    const shards = [[0, 1, 0], [-0.18, 0.7, 0.25], [-0.3, 0.55, -0.2], [0.12, 0.6, -0.12]];
    for (const [x, s, tilt] of shards) {
      const m = new THREE.Mesh(this.shardGeo, this.ice);
      m.position.x = x;
      m.scale.setScalar(s);
      m.rotation.z = tilt;
      g.add(m);
    }
    return g;
  }

  spawn(kind, owner, x, y, dir, damage, range) {
    const mesh = kind === 'arrow' ? this.makeArrow() : this.makeFrost();
    mesh.rotation.y = dir > 0 ? 0 : Math.PI;
    mesh.position.set(x, y, 0);
    this.scene.add(mesh);
    this.list.push({ kind, owner, x, y, dir, damage, range, travelled: 0, mesh, done: false });
  }

  update(dt, fight) {
    for (const p of this.list) {
      const step = SPEED[p.kind] * dt;
      p.x += p.dir * step;
      p.travelled += step;
      if (p.kind === 'frost') {
        p.y = fight.stage.groundY(p.x);
        const fade = 1 - Math.max(0, (p.travelled - p.range * 0.7) / (p.range * 0.3));
        p.mesh.scale.setScalar(Math.max(0.05, fade) * (1 + 0.08 * Math.sin(p.travelled * 12)));
      }
      p.mesh.position.set(p.x, p.y, 0);

      const bottom = p.y;
      const top = p.kind === 'frost' ? p.y + 0.5 : p.y;
      for (const f of fight.fighters) {
        if (f === p.owner || f.dead || f.invulnerable) continue;
        if (Math.abs(p.x - f.x) < 0.3 && top >= f.y - 0.05 && bottom <= f.y + f.height * 0.95) {
          fight.applyHit(p.owner, f, p.damage, p.dir);
          p.done = true;
          break;
        }
      }
      if (p.travelled > p.range || Math.abs(p.x) > 7) p.done = true;
    }
    for (const p of this.list) if (p.done) this.scene.remove(p.mesh);
    this.list = this.list.filter((p) => !p.done);
  }

  /** The nearest projectile flying toward fighter f, if it is close. */
  threatTo(f) {
    return this.list.find((p) => p.owner !== f && Math.sign(f.x - p.x) === p.dir && Math.abs(f.x - p.x) < 3);
  }

  clear() {
    for (const p of this.list) this.scene.remove(p.mesh);
    this.list = [];
  }
}
