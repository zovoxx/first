import { clamp } from './math.js';

// Keyboard + gamepad + touch merged into one per-frame state.
const KEYS = {
  left: ['ArrowLeft', 'KeyA'],
  right: ['ArrowRight', 'KeyD'],
  down: ['ArrowDown', 'KeyS'],
  jump: ['Space', 'ArrowUp', 'KeyW', 'KeyZ'],
  dash: ['ShiftLeft', 'ShiftRight', 'KeyX', 'KeyJ'],
  pause: ['Escape', 'KeyP'],
  confirm: ['Enter', 'NumpadEnter'],
};

const PAD = { jump: [0], dash: [1, 2, 5, 7], pause: [9], confirm: [0, 9], left: 14, right: 15, down: 13 };
const DEADZONE = 0.25;

export class Input {
  constructor() {
    this.down = new Set();
    this.pressed = new Set(); // key codes pressed since last poll
    this.padPrev = new Map();
    this.touch = { moveX: 0, down: false, jumpHeld: false, jumpPressed: false, dashPressed: false };
    this.state = {
      moveX: 0,
      down: false,
      jumpHeld: false,
      jumpPressed: false,
      dashPressed: false,
      pausePressed: false,
      confirmPressed: false,
      usingPad: false,
    };
    const codes = new Set(Object.values(KEYS).flat());
    window.addEventListener('keydown', (e) => {
      if (codes.has(e.code)) e.preventDefault();
      if (!e.repeat) this.pressed.add(e.code);
      this.down.add(e.code);
    });
    window.addEventListener('keyup', (e) => this.down.delete(e.code));
    window.addEventListener('blur', () => this.down.clear());
  }

  any(action) {
    return KEYS[action].some((c) => this.down.has(c));
  }
  anyPressed(action) {
    return KEYS[action].some((c) => this.pressed.has(c));
  }

  poll() {
    const s = this.state;
    let moveX = (this.any('right') ? 1 : 0) - (this.any('left') ? 1 : 0);
    let down = this.any('down');
    let jumpHeld = this.any('jump');
    let jumpPressed = this.anyPressed('jump');
    let dashPressed = this.anyPressed('dash');
    let pausePressed = this.anyPressed('pause');
    let confirmPressed = this.anyPressed('confirm');

    const pads = navigator.getGamepads ? navigator.getGamepads() : [];
    for (const pad of pads) {
      if (!pad || !pad.connected) continue;
      const prev = this.padPrev.get(pad.index) || [];
      const btn = (i) => !!pad.buttons[i]?.pressed;
      const edge = (i) => btn(i) && !prev[i];
      const ax = pad.axes[0] || 0;
      const ay = pad.axes[1] || 0;
      const padX = (Math.abs(ax) > DEADZONE ? ax : 0) + (btn(PAD.right) ? 1 : 0) - (btn(PAD.left) ? 1 : 0);
      if (padX !== 0) s.usingPad = true;
      moveX += padX;
      down = down || ay > 0.6 || btn(PAD.down);
      jumpHeld = jumpHeld || PAD.jump.some(btn);
      jumpPressed = jumpPressed || PAD.jump.some(edge);
      dashPressed = dashPressed || PAD.dash.some(edge);
      pausePressed = pausePressed || PAD.pause.some(edge);
      confirmPressed = confirmPressed || PAD.confirm.some(edge);
      if (PAD.jump.some(edge) || PAD.dash.some(edge)) s.usingPad = true;
      this.padPrev.set(
        pad.index,
        pad.buttons.map((b) => b.pressed),
      );
    }

    const t = this.touch;
    moveX += t.moveX;
    down = down || t.down;
    jumpHeld = jumpHeld || t.jumpHeld;
    jumpPressed = jumpPressed || t.jumpPressed;
    dashPressed = dashPressed || t.dashPressed;
    t.jumpPressed = false;
    t.dashPressed = false;

    s.moveX = clamp(moveX, -1, 1);
    s.down = down;
    s.jumpHeld = jumpHeld;
    s.jumpPressed = jumpPressed;
    s.dashPressed = dashPressed;
    s.pausePressed = pausePressed;
    s.confirmPressed = confirmPressed;
    this.pressed.clear();
    return s;
  }
}
