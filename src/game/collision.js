// One-way walkable surfaces (polylines of [x, y]) + simple bodies that run, fall and land on them.
// The main platform surface comes from the image alpha; floating platforms use the manifest walk_line.

export class Surface {
  // points: [[x, y], ...] in local space, sorted by x.
  constructor(points, { main = false, droppable = !main, owner = null } = {}) {
    this.points = points;
    this.main = main;
    this.droppable = droppable;
    this.owner = owner;
    this.ox = 0;
    this.oy = 0;
    this.scale = 1;
    this.prevOy = 0;
    this.active = true;
  }

  get minX() {
    return this.ox + this.points[0][0] * this.scale;
  }
  get maxX() {
    return this.ox + this.points[this.points.length - 1][0] * this.scale;
  }
  get halfWidth() {
    return ((this.points[this.points.length - 1][0] - this.points[0][0]) * this.scale) / 2;
  }
  get centerX() {
    return (this.minX + this.maxX) / 2;
  }
  get topY() {
    return this.oy;
  }

  localHeight(lx) {
    const p = this.points;
    if (lx <= p[0][0]) return p[0][1];
    const n = p.length;
    if (lx >= p[n - 1][0]) return p[n - 1][1];
    let lo = 0;
    let hi = n - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (p[mid][0] <= lx) lo = mid;
      else hi = mid;
    }
    const [x0, y0] = p[lo];
    const [x1, y1] = p[hi];
    return y0 + ((y1 - y0) * (lx - x0)) / (x1 - x0 || 1);
  }

  contains(x, margin = 0) {
    return x >= this.minX - margin && x <= this.maxX + margin;
  }

  // World height at x, or null when x is off the surface. `margin` lets bodies stand a bit past the edge.
  heightAt(x, margin = 0, oy = this.oy) {
    if (!this.active || !this.contains(x, margin)) return null;
    return oy + this.localHeight((x - this.ox) / this.scale) * this.scale;
  }

  prevHeightAt(x, margin = 0) {
    return this.heightAt(x, margin, this.prevOy);
  }

  endFrame() {
    this.prevOy = this.oy;
  }
}

export class CollisionWorld {
  constructor() {
    this.surfaces = [];
  }
  add(s) {
    s.prevOy = s.oy;
    this.surfaces.push(s);
    return s;
  }
  remove(s) {
    s.active = false;
    const i = this.surfaces.indexOf(s);
    if (i >= 0) this.surfaces.splice(i, 1);
  }

  // Feet moved from y0 to y1 at x this step. Returns the highest surface crossed from above.
  landing(x, y0, y1, margin, ignoreDroppable = false) {
    let best = null;
    for (const s of this.surfaces) {
      if (!s.active || (ignoreDroppable && s.droppable)) continue;
      const h = s.heightAt(x, margin);
      if (h === null) continue;
      const hPrev = s.prevHeightAt(x, margin) ?? h;
      if (y0 >= hPrev - 0.03 && y1 <= h + 1e-4 && (!best || h > best.y)) best = { surface: s, y: h };
    }
    return best;
  }

  // Highest surface at or below y (for shadows, AI targeting, spawn checks).
  groundBelow(x, y, margin = 0) {
    let best = null;
    for (const s of this.surfaces) {
      if (!s.active) continue;
      const h = s.heightAt(x, margin);
      if (h === null || h > y + 0.05) continue;
      if (!best || h > best.y) best = { surface: s, y: h };
    }
    return best;
  }

  endFrame() {
    for (const s of this.surfaces) s.endFrame();
  }
}

// Axis-aligned body standing on surfaces. x = centre, y = feet.
export class Body {
  constructor(halfW, height) {
    this.halfW = halfW;
    this.height = height;
    this.x = 0;
    this.y = 0;
    this.vx = 0;
    this.vy = 0;
    this.grounded = false;
    this.ground = null;
    this.landed = false; // true on the step it touched down
    this.leftGround = false; // true on the step it walked off an edge
  }

  place(x, y, ground = null) {
    this.x = x;
    this.y = y;
    this.vx = 0;
    this.vy = 0;
    this.ground = ground;
    this.grounded = !!ground;
  }

  get edgeMargin() {
    return this.halfW * 0.5;
  }

  // Integrate one step. opts: gravity, maxFall, minX, maxX, ignoreDroppable, ceiling
  step(dt, world, opts) {
    this.landed = false;
    this.leftGround = false;
    this.x += this.vx * dt;
    if (opts.minX !== undefined && this.x < opts.minX) {
      this.x = opts.minX;
      if (this.vx < 0) this.vx = 0;
    }
    if (opts.maxX !== undefined && this.x > opts.maxX) {
      this.x = opts.maxX;
      if (this.vx > 0) this.vx = 0;
    }

    if (this.grounded) {
      const h = this.ground ? this.ground.heightAt(this.x, this.edgeMargin) : null;
      if (h === null) {
        this.grounded = false;
        this.ground = null;
        this.leftGround = true;
        if (this.vy > 0) this.vy = 0;
      } else {
        this.y = h;
        this.vy = 0;
        return;
      }
    }

    this.vy = Math.max(this.vy - opts.gravity * dt, -opts.maxFall);
    const y0 = this.y;
    this.y += this.vy * dt;
    if (opts.ceiling !== undefined && this.y + this.height > opts.ceiling && this.vy > 0) {
      this.y = opts.ceiling - this.height;
      this.vy = 0;
    }
    if (this.vy <= 0.5) {
      const hit = world.landing(this.x, y0, this.y, this.edgeMargin, opts.ignoreDroppable);
      if (hit) {
        this.y = hit.y;
        this.vy = 0;
        this.grounded = true;
        this.ground = hit.surface;
        this.landed = true;
      }
    }
  }

  overlaps(o) {
    return Math.abs(this.x - o.x) < this.halfW + o.halfW && this.y < o.y + o.height && o.y < this.y + this.height;
  }
}
