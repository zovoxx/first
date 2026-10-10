import * as THREE from 'three';

// ?debug=1 : collision surfaces (green), hitboxes (cyan player / orange enemies), kill line (red).
export class DebugDraw {
  constructor(scene, maxSegments = 4096) {
    this.max = maxSegments;
    this.positions = new Float32Array(maxSegments * 6);
    this.colors = new Float32Array(maxSegments * 6);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(this.positions, 3).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute('color', new THREE.BufferAttribute(this.colors, 3).setUsage(THREE.DynamicDrawUsage));
    this.lines = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ vertexColors: true, depthTest: false, transparent: true }));
    this.lines.frustumCulled = false;
    this.lines.renderOrder = 1000;
    scene.add(this.lines);
    this.n = 0;
  }

  seg(x0, y0, x1, y1, c) {
    if (this.n >= this.max) return;
    const i = this.n * 6;
    this.positions.set([x0, y0, 0.5, x1, y1, 0.5], i);
    this.colors.set([c.r, c.g, c.b, c.r, c.g, c.b], i);
    this.n++;
  }

  box(x, y, halfW, h, c) {
    this.seg(x - halfW, y, x + halfW, y, c);
    this.seg(x + halfW, y, x + halfW, y + h, c);
    this.seg(x + halfW, y + h, x - halfW, y + h, c);
    this.seg(x - halfW, y + h, x - halfW, y, c);
  }

  update(game) {
    this.n = 0;
    const green = new THREE.Color(0x30ff80);
    const yellow = new THREE.Color(0xffe040);
    const cyan = new THREE.Color(0x40e8ff);
    const orange = new THREE.Color(0xff9a40);
    const red = new THREE.Color(0xff3040);
    for (const s of game.world.surfaces) {
      const c = s.main ? green : yellow;
      const p = s.points;
      for (let i = 0; i < p.length - 1; i++) {
        this.seg(s.ox + p[i][0] * s.scale, s.oy + p[i][1] * s.scale, s.ox + p[i + 1][0] * s.scale, s.oy + p[i + 1][1] * s.scale, c);
      }
    }
    const pb = game.player.body;
    this.box(pb.x, pb.y, pb.halfW, pb.height, cyan);
    for (const e of game.director.enemies) {
      const b = e.body;
      this.box(b.x, b.y, b.halfW, b.height, orange);
      if (e.state === 'attack') this.seg(b.x, b.y + b.height * 0.5, b.x + e.face * e.def.range, b.y + b.height * 0.5, red);
    }
    this.seg(-game.rig.halfW, game.killY, game.rig.halfW, game.killY, red);
    this.seg(-game.rig.halfW, game.rig.bottomY + 0.05, -game.rig.halfW, game.rig.topY, red);
    this.seg(game.rig.halfW, game.rig.bottomY + 0.05, game.rig.halfW, game.rig.topY, red);
    const g = this.lines.geometry;
    g.setDrawRange(0, this.n * 2);
    g.attributes.position.needsUpdate = true;
    g.attributes.color.needsUpdate = true;
  }
}
