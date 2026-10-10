// Keyboard, mouse, gamepad and on-screen touch buttons -> one intent per frame.
const KEYS = {
  ArrowLeft: 'left', KeyA: 'left',
  ArrowRight: 'right', KeyD: 'right',
  ArrowUp: 'jump', KeyW: 'jump', Space: 'jump',
  KeyJ: 'attack', KeyF: 'attack',
  ShiftLeft: 'dodge', ShiftRight: 'dodge', KeyK: 'dodge', KeyS: 'dodge', ArrowDown: 'dodge',
  Escape: 'pause', KeyP: 'pause',
};
// Standard gamepad layout: A jump, B dodge, X attack, RB dodge, Start pause.
const PAD = { 0: 'jump', 1: 'dodge', 2: 'attack', 5: 'dodge', 9: 'pause' };

export class Input {
  constructor(canvas, touchRoot) {
    this.held = new Set();
    this.edges = new Set();
    this.padPrev = {};
    this.padMove = 0;

    addEventListener('keydown', (e) => {
      const act = KEYS[e.code];
      if (!act) return;
      if ((e.code === 'Space' || e.code === 'Enter') && e.target.closest?.('button')) return;
      e.preventDefault();
      if (!e.repeat) this.edges.add(act);
      this.held.add(act);
    });
    addEventListener('keyup', (e) => {
      const act = KEYS[e.code];
      if (act) this.held.delete(act);
    });
    addEventListener('blur', () => this.held.clear());

    canvas.addEventListener('pointerdown', (e) => {
      if (e.pointerType === 'mouse' && e.button === 0) this.edges.add('attack');
    });

    for (const btn of touchRoot.querySelectorAll('[data-act]')) {
      const act = btn.dataset.act;
      const key = `touch-${act}`;
      btn.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        btn.setPointerCapture(e.pointerId);
        this.held.add(key);
        this.edges.add(act);
        btn.classList.add('down');
      });
      const up = () => { this.held.delete(key); btn.classList.remove('down'); };
      btn.addEventListener('pointerup', up);
      btn.addEventListener('pointercancel', up);
      btn.addEventListener('lostpointercapture', up);
      btn.addEventListener('contextmenu', (e) => e.preventDefault());
    }
  }

  poll() {
    this.padMove = 0;
    const gp = [...(navigator.getGamepads?.() ?? [])].find(Boolean);
    if (!gp) return;
    const ax = gp.axes[0] ?? 0;
    if (Math.abs(ax) > 0.25) this.padMove = ax;
    if (gp.buttons[14]?.pressed) this.padMove = -1;
    if (gp.buttons[15]?.pressed) this.padMove = 1;
    for (const [i, act] of Object.entries(PAD)) {
      const down = !!gp.buttons[i]?.pressed;
      if (down && !this.padPrev[i]) this.edges.add(act);
      this.padPrev[i] = down;
    }
  }

  has(act) {
    return this.held.has(act) || this.held.has(`touch-${act}`);
  }

  /** { move, jump, dodge, attack, pause } - buttons are true only on the frame they were pressed. */
  intent() {
    let move = (this.has('right') ? 1 : 0) - (this.has('left') ? 1 : 0);
    if (!move) move = this.padMove;
    const out = {
      move,
      jump: this.edges.has('jump'),
      dodge: this.edges.has('dodge'),
      attack: this.edges.has('attack'),
      pause: this.edges.has('pause'),
    };
    this.edges.clear();
    return out;
  }
}
