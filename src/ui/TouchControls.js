// On-screen controls: a floating stick on the left (move; pull down = drop through), JUMP and DASH
// buttons on the right. Writes into input.touch.
export class TouchControls {
  constructor(input) {
    this.input = input;
    this.enabled = false; // decided by the Touch controls setting (see device.js)
    this.root = document.getElementById('touch');
    this.stick = document.getElementById('touch-stick');
    this.base = this.stick.querySelector('.stick-base');
    this.knob = this.stick.querySelector('.stick-knob');
    this.stickId = null;
    this.origin = { x: 0, y: 0 };
    this.radius = 52;

    this.stick.addEventListener('pointerdown', (e) => this.onStickDown(e));
    window.addEventListener('pointermove', (e) => this.onStickMove(e));
    window.addEventListener('pointerup', (e) => this.onStickUp(e));
    window.addEventListener('pointercancel', (e) => this.onStickUp(e));

    this.bindButton(document.getElementById('touch-jump'), (down) => {
      input.touch.jumpHeld = down;
      if (down) input.touch.jumpPressed = true;
    });
    this.bindButton(document.getElementById('touch-dash'), (down) => {
      if (down) input.touch.dashPressed = true;
    });
  }

  setVisible(visible) {
    this.root.classList.toggle('hidden', !visible);
    if (!visible) this.release();
  }

  bindButton(el, cb) {
    const ids = new Set();
    el.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      el.setPointerCapture?.(e.pointerId);
      ids.add(e.pointerId);
      el.classList.add('down');
      cb(true);
    });
    const up = (e) => {
      if (!ids.delete(e.pointerId)) return;
      if (ids.size === 0) {
        el.classList.remove('down');
        cb(false);
      }
    };
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
    el.addEventListener('lostpointercapture', up);
    el.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  onStickDown(e) {
    if (this.stickId !== null) return;
    e.preventDefault();
    this.stickId = e.pointerId;
    const r = this.stick.getBoundingClientRect();
    this.origin.x = e.clientX;
    this.origin.y = e.clientY;
    this.base.style.left = `${e.clientX - r.left}px`;
    this.base.style.bottom = `${r.bottom - e.clientY}px`;
    this.stick.classList.add('active');
    this.setKnob(0, 0);
  }

  onStickMove(e) {
    if (e.pointerId !== this.stickId) return;
    let dx = e.clientX - this.origin.x;
    let dy = e.clientY - this.origin.y;
    const len = Math.hypot(dx, dy);
    if (len > this.radius) {
      dx *= this.radius / len;
      dy *= this.radius / len;
    }
    this.setKnob(dx, dy);
    const nx = dx / this.radius;
    this.input.touch.moveX = Math.abs(nx) < 0.18 ? 0 : Math.max(-1, Math.min(1, nx * 1.25));
    this.input.touch.down = dy / this.radius > 0.6;
  }

  onStickUp(e) {
    if (e.pointerId !== this.stickId) return;
    this.release();
  }

  release() {
    this.stickId = null;
    this.stick.classList.remove('active');
    this.setKnob(0, 0);
    this.base.style.left = '';
    this.base.style.bottom = '';
    this.input.touch.moveX = 0;
    this.input.touch.down = false;
    this.input.touch.jumpHeld = false;
  }

  setKnob(dx, dy) {
    this.knob.style.transform = `translate(${dx}px, ${dy}px)`;
  }
}
