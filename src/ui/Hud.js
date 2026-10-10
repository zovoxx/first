import { formatClock } from '../core/math.js';

const $ = (id) => document.getElementById(id);

export class Hud {
  constructor() {
    this.root = $('hud');
    this.timer = $('hud-timer');
    this.arenaNum = $('hud-arena-num');
    this.arenaName = $('hud-arena-name');
    this.healthFill = $('hud-health-fill');
    this.healthText = $('hud-health-text');
    this.announceEl = $('hud-announce');
    this.hintEl = $('hud-hint');
    this.hurtEl = $('hurt-flash');
    this.lastClock = '';
    this.lastHealth = -1;
    this.hintTimer = 0;
  }

  show(visible) {
    this.root.classList.toggle('hidden', !visible);
  }

  setTime(remaining) {
    const text = formatClock(remaining);
    if (text !== this.lastClock) {
      this.lastClock = text;
      this.timer.textContent = text;
      this.timer.classList.toggle('final', remaining <= 60);
    }
  }

  setArena(index, label) {
    this.arenaNum.textContent = `ARENA ${index + 1}`;
    this.arenaName.textContent = label;
  }

  setHealth(health, max) {
    const h = Math.max(0, Math.ceil(health));
    if (h === this.lastHealth) return;
    this.lastHealth = h;
    this.healthFill.style.transform = `scaleX(${Math.max(0, health / max)})`;
    this.healthFill.classList.toggle('low', health / max < 0.3);
    this.healthText.textContent = String(h);
  }

  announce(title, sub = '', duration = 2.6) {
    const el = this.announceEl;
    el.querySelector('.title').textContent = title;
    el.querySelector('.sub').textContent = sub;
    el.style.setProperty('--dur', `${duration}s`);
    el.classList.remove('show');
    void el.offsetWidth; // restart the CSS animation
    el.classList.add('show');
  }

  hint(text, duration = 6) {
    this.hintEl.innerHTML = text;
    this.hintEl.classList.add('show');
    this.hintTimer = duration;
  }

  clearHint() {
    this.hintTimer = 0;
    this.hintEl.classList.remove('show');
  }

  hurtFlash() {
    this.hurtEl.classList.remove('show');
    void this.hurtEl.offsetWidth;
    this.hurtEl.classList.add('show');
  }

  update(dt) {
    if (this.hintTimer > 0) {
      this.hintTimer -= dt;
      if (this.hintTimer <= 0) this.hintEl.classList.remove('show');
    }
  }
}
