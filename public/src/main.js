// Entry point: renderer, screens (select -> loading -> fight -> result) and the main loop.
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { SparkRenderer } from '@sparkjsdev/spark';
import { PLATFORM, TOUCH, Progress, loadGLTF, loadManifest, webPath } from './assets.js';
import { Music } from './audio.js';
import { Stage } from './stage.js';
import { Fighter, KIT, shortName } from './fighter.js';
import { Fight } from './fight.js';
import { Input } from './input.js';

const $ = (id) => document.getElementById(id);
const canvas = $('game');

// ---------- renderer & scene ----------
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(devicePixelRatio, PLATFORM === 'pc' ? 2 : 1.5));
renderer.autoClear = false;
renderer.setClearColor(0x0d0f1a);

const scene = new THREE.Scene();
scene.add(new SparkRenderer({ renderer }));
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.7;
scene.add(new THREE.HemisphereLight(0xffffff, 0x4a4a5a, 0.9));
const sun = new THREE.DirectionalLight(0xffffff, 2.2);
sun.position.set(-3, 6, 8);
scene.add(sun);

const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 200);
const cam = { x: 0, dist: 7, viewW: 7 };

// ---------- state ----------
const input = new Input(canvas, $('touch'));
let manifest = null;
let music = null;
let stage = null;
let fight = null;
let picks = null;          // { player, cpu } character defs of the current/last fight
let screen = 'boot';
const stages = new Map();

// ---------- HUD ----------
const hud = {
  ghost: [1, 1],
  health(a, b, dt) {
    [a, b].forEach((v, i) => {
      this.ghost[i] = v >= this.ghost[i] ? v : Math.max(v, this.ghost[i] - dt * 0.6);
      $(`fill${i + 1}`).style.width = `${v * 100}%`;
      $(`ghost${i + 1}`).style.width = `${this.ghost[i] * 100}%`;
    });
  },
  round(n, wins, need, final) {
    $('round').textContent = final ? 'Final' : `Round ${n}`;
    wins.forEach((w, i) => {
      $(`pips${i + 1}`).innerHTML = Array.from({ length: need }, (_, k) => `<b class="${k < w ? 'won' : ''}"></b>`).join('');
    });
  },
  timer: 0,
  banner(text, ms) {
    const el = $('banner');
    el.textContent = text;
    el.classList.add('on');
    clearTimeout(this.timer);
    this.timer = setTimeout(() => el.classList.remove('on'), ms);
  },
};

// ---------- screens ----------
function show(name) {
  screen = name;
  for (const s of document.querySelectorAll('.screen')) s.classList.toggle('on', s.id === name);
  const inFight = ['fight', 'pause', 'result'].includes(name);
  $('hud').hidden = !inFight;
  $('touch').hidden = !(TOUCH && name === 'fight');
  $('pause-btn').hidden = name !== 'fight';
  document.body.classList.toggle('fighting', inFight);
}

function unlockAudio() {
  music?.unlock();
}
addEventListener('pointerdown', unlockAudio, { capture: true });
addEventListener('keydown', unlockAudio, { capture: true });

function updateMuteButton() {
  $('mute').classList.toggle('off', !!music?.muted);
  $('mute').setAttribute('aria-label', music?.muted ? 'Unmute music' : 'Mute music');
}
$('mute').onclick = () => { music?.toggleMute(); updateMuteButton(); };
$('pause-btn').onclick = () => setPaused(true);
$('resume').onclick = () => setPaused(false);
$('quit').onclick = () => showSelect();
$('rematch').onclick = () => startFight(picks.player, picks.cpu);
$('change').onclick = () => showSelect();

function setPaused(on) {
  if (on && screen === 'fight') show('pause');
  else if (!on && screen === 'pause') show('fight');
}
document.addEventListener('visibilitychange', () => { if (document.hidden) setPaused(true); });

const farArt = (biome) => {
  const bg = manifest.backgrounds.find((b) => b.biome === biome);
  // absolute URL: relative url() in a CSS variable resolves against the stylesheet's folder
  return bg ? `url("${new URL(webPath(bg.far.mobile), location.href).href}")` : 'none';
};

function buildRoster() {
  const roster = $('roster');
  roster.innerHTML = '';
  for (const c of manifest.characters) {
    const kit = KIT[c.id];
    const [, title = ''] = c.name.split(',');
    const btn = document.createElement('button');
    btn.className = 'card';
    btn.setAttribute('role', 'listitem');
    btn.style.setProperty('--card-art', farArt(c.home_biome));
    btn.innerHTML = `
      <span class="biome">${c.home_biome}</span>
      <h2>${shortName(c)}</h2>
      <p class="title">${title.trim()}</p>
      <p class="stats">${kit?.weapon ?? c.weapon.id} · ${kit?.type === 'melee' ? 'close range' : 'ranged'}<br>${c.height_m.toFixed(2)} m tall</p>`;
    const preview = () => $('select').style.setProperty('--art', farArt(c.home_biome));
    btn.addEventListener('pointerenter', preview);
    btn.addEventListener('focus', preview);
    btn.addEventListener('click', () => {
      const others = manifest.characters.filter((o) => o.id !== c.id);
      startFight(c, others[Math.floor(Math.random() * others.length)]);
    });
    roster.appendChild(btn);
  }
  $('controls-hint').textContent = TOUCH
    ? 'Use the on-screen buttons. Best of 3 rounds against the CPU on your home stage.'
    : 'A/D or ←/→ move · W/↑/Space jump · Shift/K/↓ dodge · J/F/click attack · Esc pause. Best of 3 rounds against the CPU on your home stage.';
}

function showSelect() {
  if (fight) { fight.dispose(scene); fight = null; }
  show('select');
  music?.play('menu');
  $('roster').querySelector('.card')?.focus({ preventScroll: true });
}

// ---------- start a fight ----------
async function startFight(playerDef, cpuDef) {
  picks = { player: playerDef, cpu: cpuDef };
  if (fight) { fight.dispose(scene); fight = null; }
  const biome = playerDef.home_biome;
  $('vs').innerHTML = `<span class="p1">${shortName(playerDef)}</span> vs <span class="p2">${shortName(cpuDef)}</span><small>${biome}</small>`;
  $('progress-fill').style.width = '0%';
  $('loading-msg').textContent = 'Loading…';
  $('retry').hidden = true;
  show('loading');

  const progress = new Progress((v) => { $('progress-fill').style.width = `${Math.round(v * 100)}%`; });
  if (!stages.has(biome)) {
    stages.set(biome, new Stage(
      manifest.grounds.find((g) => g.biome === biome),
      manifest.backgrounds.find((b) => b.biome === biome),
    ));
  }
  const nextStage = stages.get(biome);
  const glb = (c) => webPath(c.files[PLATFORM === 'mobile' ? 'mobile' : 'pc']);
  let gltfs;
  try {
    [gltfs] = await Promise.all([
      Promise.all([loadGLTF(glb(playerDef), progress.part(2)), loadGLTF(glb(cpuDef), progress.part(2))]),
      nextStage.load(progress),
      music?.load('combat'),
    ]);
  } catch (err) {
    console.error(err);
    $('loading-msg').textContent = `Couldn't load the fight: ${err.message}`;
    $('retry').hidden = false;
    $('retry').onclick = () => startFight(playerDef, cpuDef);
    return;
  }
  if (screen !== 'loading') return;   // the player left while loading

  if (stage) scene.remove(stage.group);
  stage = nextStage;
  scene.add(stage.group);

  const player = new Fighter(playerDef, gltfs[0]);
  const cpu = new Fighter(cpuDef, gltfs[1]);
  scene.add(player.object, cpu.object);
  $('name1').textContent = player.name;
  $('name2').textContent = cpu.name;
  hud.ghost = [1, 1];
  cam.x = 0;
  fight = new Fight({
    scene, stage, player, cpu, hud, music,
    onOver(won) {
      $('result-title').textContent = won ? 'Victory!' : 'Defeat';
      $('result-sub').textContent = `${player.name} ${fight.wins[0]} – ${fight.wins[1]} ${cpu.name}`;
      setTimeout(() => {
        if (screen !== 'fight') return;
        show('result');
        $('rematch').focus({ preventScroll: true });
      }, 400);
    },
  });
  show('fight');
  music?.load('boss');   // warm up the final-round track
}

// ---------- camera ----------
function updateCamera(dt) {
  const [a, b] = fight.fighters;
  const targetX = Math.min(1.6, Math.max(-1.6, (a.x + b.x) / 2));
  const wantW = Math.min(9.5, Math.max(6.2, Math.abs(a.x - b.x) + 3.6));
  const tanV = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
  const forWidth = wantW / 2 / (tanV * camera.aspect);
  const forHeight = 1.8 / tanV;   // always show at least 3.6 m of height
  const wantDist = Math.min(22, Math.max(forWidth, forHeight));
  const k = 1 - Math.exp(-4 * dt);
  cam.x += (targetX - cam.x) * k;
  cam.dist += (wantDist - cam.dist) * k;
  cam.viewW = 2 * cam.dist * tanV * camera.aspect;
  const s = fight.shake * 0.06;
  camera.position.set(cam.x + (Math.random() - 0.5) * s, 1.3 + cam.dist * 0.05 + (Math.random() - 0.5) * s, cam.dist);
  camera.lookAt(cam.x, 0.85, 0);
}

function resize() {
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  const size = renderer.getSize(new THREE.Vector2());
  if (size.x !== w || size.y !== h) {
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  document.body.classList.toggle('portrait', TOUCH && h > w);
}

// ---------- main loop ----------
const timer = new THREE.Timer();
timer.connect(document);
renderer.setAnimationLoop((time) => {
  timer.update(time);
  const dt = Math.min(timer.getDelta(), 1 / 20);
  input.poll();
  const intent = input.intent();
  resize();
  renderer.clear();
  if (!fight || !stage) return;

  if (screen === 'fight') {
    if (intent.pause) setPaused(true);
    else fight.update(dt, intent);
  } else if (screen === 'pause' && intent.pause) {
    setPaused(false);
  } else if (screen === 'result') {
    fight.update(dt, {});   // keep the winner breathing behind the menu
  }
  if (!['fight', 'pause', 'result'].includes(screen)) return;

  updateCamera(dt);
  stage.updateBackground(camera.aspect, cam.x, cam.viewW);
  renderer.render(stage.bgScene, camera);
  renderer.clearDepth();
  renderer.render(scene, camera);
});

// ---------- boot ----------
(async () => {
  try {
    manifest = await loadManifest();
  } catch (err) {
    console.error(err);
    $('boot-msg').textContent = `Couldn't load the game: ${err.message}`;
    return;
  }
  music = new Music(manifest.music, PLATFORM);
  updateMuteButton();
  buildRoster();
  $('select').style.setProperty('--art', farArt(manifest.characters[0].home_biome));
  showSelect();
})();

// For debugging in the console.
window.game = { get fight() { return fight; }, get stage() { return stage; }, renderer, scene, camera };
