import { formatClock } from '../core/math.js';
import { GAME_TITLE } from '../config.js';

const SCREENS = ['loading', 'menu', 'settings', 'pause', 'over', 'win'];

// DOM menus: loading, start menu, settings, pause, game over, win.
export class Screens {
  constructor({ onAction, settings, onSettingsChanged, platform, touch }) {
    this.onAction = onAction;
    this.settings = settings;
    this.onSettingsChanged = onSettingsChanged;
    this.current = 'loading';
    this.settingsReturn = 'menu';
    this.els = Object.fromEntries(SCREENS.map((s) => [s, document.getElementById(`screen-${s}`)]));
    document.title = GAME_TITLE;
    for (const el of document.querySelectorAll('.logo')) el.textContent = GAME_TITLE;

    document.getElementById('ui').addEventListener('click', (e) => {
      const btn = e.target.closest('[data-action]');
      if (!btn) return;
      const action = btn.dataset.action;
      if (action === 'settings' || action === 'pause-settings') {
        this.settingsReturn = action === 'settings' ? 'menu' : 'pause';
        this.show('settings');
      } else if (action === 'settings-back') {
        this.show(this.settingsReturn);
      } else {
        this.onAction(action);
      }
    });

    // settings controls
    const q = document.getElementById('set-quality');
    const t = document.getElementById('set-touch');
    const m = document.getElementById('set-music');
    const s = document.getElementById('set-sfx');
    const note = document.getElementById('set-quality-note');
    q.value = settings.quality;
    t.value = settings.touch;
    m.value = settings.music;
    s.value = settings.sfx;
    const loadedLabel = platform === 'pc' ? 'PC' : 'mobile';
    note.textContent = `Currently loaded: ${loadedLabel} assets.`;
    q.addEventListener('change', () => {
      settings.quality = q.value;
      onSettingsChanged('quality');
      note.innerHTML = `Currently loaded: ${loadedLabel} assets. <a href="#" id="reload-link" style="color:var(--cyan)">Reload to apply</a>`;
      document.getElementById('reload-link').addEventListener('click', (e) => {
        e.preventDefault();
        location.reload();
      });
    });
    t.addEventListener('change', () => {
      settings.touch = t.value;
      onSettingsChanged('touch');
    });
    m.addEventListener('input', () => {
      settings.music = parseFloat(m.value);
      onSettingsChanged('volume');
    });
    s.addEventListener('input', () => {
      settings.sfx = parseFloat(s.value);
      onSettingsChanged('volume');
    });

    this.setControlsHelp(touch);
  }

  setControlsHelp(touch) {
    const el = document.getElementById('controls-help');
    el.innerHTML = touch
      ? 'Left thumb: move (pull down + JUMP to drop through)<br>JUMP twice for an air jump · DASH passes through enemies'
      : '<kbd>A</kbd><kbd>D</kbd> / <kbd>←</kbd><kbd>→</kbd> move · <kbd>Space</kbd> jump (twice in the air) · <kbd>Shift</kbd> dash · <kbd>S</kbd>+<kbd>Space</kbd> drop · <kbd>Esc</kbd> pause<br>Gamepad: stick move · A jump · B/X/RB dash · Start pause';
  }

  show(name) {
    this.current = name;
    for (const [key, el] of Object.entries(this.els)) el.classList.toggle('hidden', key !== name);
    const first = this.els[name]?.querySelector('.btn.primary');
    if (first && matchMedia('(pointer: fine)').matches) first.focus({ preventScroll: true });
  }

  hideAll() {
    this.current = null;
    for (const el of Object.values(this.els)) el.classList.add('hidden');
  }

  setProgress(fraction, text) {
    document.getElementById('load-fill').style.width = `${Math.round(fraction * 100)}%`;
    if (text) document.getElementById('load-text').textContent = text;
  }

  setGameOver(elapsed, arenaIndex, remaining) {
    document.getElementById('over-time').textContent = formatClock(elapsed);
    document.getElementById('over-arena').textContent = `${arenaIndex + 1} / 5`;
    document.getElementById('over-left').textContent = formatClock(remaining);
  }

  showError(message) {
    const el = document.getElementById('error-box');
    el.textContent = message;
    el.classList.remove('hidden');
  }
}
