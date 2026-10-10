import './styles.css';
import { Assets } from './core/assets.js';
import { AudioSystem } from './core/audio.js';
import { loadSettings, resolvePlatform, saveSettings, touchEnabled, urlParams } from './core/device.js';
import { Input } from './core/input.js';
import { Game } from './game/Game.js';
import { Hud } from './ui/Hud.js';
import { Screens } from './ui/Screens.js';
import { TouchControls } from './ui/TouchControls.js';

function hasWebGL2() {
  try {
    return !!document.createElement('canvas').getContext('webgl2');
  } catch {
    return false;
  }
}

async function boot() {
  const params = urlParams();
  const settings = loadSettings();
  const platform = resolvePlatform(settings, params); // 'pc' | 'mobile' asset set
  const assets = new Assets(platform);
  const audio = new AudioSystem(assets, settings);
  const input = new Input();
  const touch = new TouchControls(input);
  touch.enabled = touchEnabled(settings);
  const hud = new Hud();

  let game = null;
  const screens = new Screens({
    settings,
    platform,
    touch: touch.enabled,
    onAction: (action) => game?.onAction(action),
    onSettingsChanged: (what) => {
      saveSettings(settings);
      if (what === 'volume') audio.applyVolumes();
      if (what === 'touch') {
        touch.enabled = touchEnabled(settings);
        screens.setControlsHelp(touch.enabled);
        game?.resize();
      }
    },
  });

  // Browsers only start audio after a user gesture.
  const unlock = () => audio.unlock();
  window.addEventListener('pointerdown', unlock);
  window.addEventListener('keydown', unlock);

  if (!hasWebGL2()) {
    screens.showError('This game needs WebGL 2. Please use a recent Chrome, Edge, Firefox or Safari.');
    return;
  }

  game = new Game({ canvas: document.getElementById('game'), platform, settings, params, assets, audio, input, hud, screens, touch });
  window.__game = game; // handy for debugging from the console
  const label = platform === 'pc' ? 'PC' : 'mobile';
  await game.load((f) => screens.setProgress(f, `Loading ${label} assets… ${Math.round(f * 100)}%`));
  game.renderer.setAnimationLoop(() => game.frame());
  if (params.play) game.startRun();
  else game.enterMenu();
}

const showFatal = (msg) => {
  const el = document.getElementById('error-box');
  if (!el) return;
  el.textContent = String(msg);
  el.classList.remove('hidden');
};
window.addEventListener('error', (e) => showFatal(e.message || e.error));
window.addEventListener('unhandledrejection', (e) => showFatal(e.reason?.stack || e.reason));

boot().catch((err) => {
  console.error(err);
  showFatal(err?.stack || err);
});
