import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { SparkRenderer } from '@sparkjsdev/spark';
import { ARENAS, ARENA_SECONDS, KILL_MARGIN, PLAYABLE_ARENAS, PLAYER, QUALITY, RUN_SECONDS } from '../config.js';
import { LoadTracker, makeImageTexture } from '../core/assets.js';
import { Background } from './Background.js';
import { CameraRig } from './CameraRig.js';
import { CollisionWorld } from './collision.js';
import { DebugDraw } from './DebugDraw.js';
import { difficultyAt } from './difficulty.js';
import { Effects } from './Effects.js';
import { EnemyDirector } from './EnemyDirector.js';
import { FloatingPlatforms } from './FloatingPlatforms.js';
import { MainPlatform } from './MainPlatform.js';
import { Player } from './Player.js';

const DUST = { desert: 0xd8b27a, forge: 0x9a7058, neon: 0xa58ae0, forest: 0x86a85a, ice: 0xd6ecff };
const NO_INPUT = { moveX: 0, down: false, jumpHeld: false, jumpPressed: false, dashPressed: false };
const STEP = 1 / 60;

// Owns the renderer, scene and every system, and runs the state machine:
// loading -> menu -> playing <-> paused -> dying -> over | won
export class Game {
  constructor({ canvas, platform, settings, params, assets, audio, input, hud, screens, touch }) {
    Object.assign(this, { canvas, platform, settings, params, assets, audio, input, hud, screens, touch });
    this.quality = QUALITY[platform];

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: this.quality.antialias,
      powerPreference: 'high-performance',
      alpha: false,
      stencil: false,
    });
    this.renderer.setClearColor(0x07060d, 1);
    this.renderer.toneMapping = THREE.NoToneMapping;

    this.scene = new THREE.Scene();
    // Image-based light so the characters' PBR (metal/roughness) materials don't go dark.
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.environmentIntensity = 0.8;
    pmrem.dispose();
    this.rig = new CameraRig();
    this.spark = new SparkRenderer({ renderer: this.renderer, maxStdDev: this.quality.sparkStdDev });
    this.spark.renderOrder = 0;
    this.scene.add(this.spark);

    this.hemi = new THREE.HemisphereLight(0xffffff, 0x444444, 1.6);
    this.key = new THREE.DirectionalLight(0xffffff, 2.4);
    this.key.position.set(-5, 9, 12);
    this.rimLight = new THREE.DirectionalLight(0xffffff, 1.6);
    this.rimLight.position.set(7, 5, -10);
    this.scene.add(this.hemi, this.key, this.rimLight);

    this.world = new CollisionWorld();
    this.effects = new Effects(this.scene, this.quality.particles);
    this.background = new Background();
    this.scene.add(this.background.mesh);
    this.platforms = new FloatingPlatforms(this);
    this.director = new EnemyDirector(this);
    this.mainPlatform = null;
    this.player = null;
    this.debug = params.debug ? new DebugDraw(this.scene) : null;
    this.debugEl = document.getElementById('debug-stats');
    if (this.debug) this.debugEl.classList.remove('hidden');

    this.state = 'loading';
    this.elapsed = 0;
    this.arenaIndex = 0;
    this.diff = difficultyAt(0);
    this.hitstop = 0;
    this.stateT = 0;
    this.last = performance.now();
    this.fps = { frames: 0, t: 0, value: 0 };

    window.addEventListener('resize', () => this.resize());
    document.addEventListener('visibilitychange', () => {
      if (document.hidden && this.state === 'playing') this.pause();
    });
  }

  get killY() {
    return this.rig.bottomY - KILL_MARGIN;
  }

  // ---------- loading ----------
  async load(onProgress) {
    const tracker = new LoadTracker(onProgress);
    await this.assets.loadManifest();
    const def = ARENAS[0];
    const bg = this.assets.backgroundPaths(def.biome);
    const pc = this.platform === 'pc';
    const [farImg, midImg, ground, ...rest] = await Promise.all([
      this.assets.loadImage(bg.far, tracker, pc ? 1.9 : 0.1),
      this.assets.loadImage(bg.mid, tracker, pc ? 0.8 : 0.1),
      this.assets.loadGroundSplats(def.biome, tracker),
      ...def.roster.map((id) => this.assets.loadCharacter(id, tracker)),
      this.audio.preload('menu', tracker),
      this.audio.preload(def.music, tracker),
    ]);
    def.roster.forEach((id, i) => this.director.setTemplate(id, rest[i]));
    this.buildArena(0, farImg, midImg, ground);
    this.player = new Player(this);
    this.resize();
    // compile shaders up front so the first frames don't hitch
    this.renderer.compile(this.scene, this.rig.camera);
  }

  buildArena(index, farImg, midImg, ground) {
    const def = ARENAS[index];
    this.arenaIndex = index;
    this.background.setTexture(makeImageTexture(farImg, { repeatX: true }), def.bgTint);
    if (this.mainPlatform) {
      this.scene.remove(this.mainPlatform.mesh);
      this.world.remove(this.mainPlatform.surface);
      this.mainPlatform.dispose();
    }
    this.mainPlatform = new MainPlatform(midImg, makeImageTexture(midImg, { premultiply: true }));
    this.scene.add(this.mainPlatform.mesh);
    this.world.add(this.mainPlatform.surface);
    this.mainPlatform.layout(this.rig);
    this.platforms.setGround(ground.def, ground.packed, DUST[def.biome]);
    this.director.setRoster(def.roster);
    const L = def.light;
    this.hemi.color.setHex(L.sky);
    this.hemi.groundColor.setHex(L.ground);
    this.hemi.intensity = L.hemi;
    this.key.color.setHex(L.key);
    this.key.intensity = L.keyI;
    this.rimLight.color.setHex(L.rim);
    this.rimLight.intensity = L.rimI;
    this.scene.environmentIntensity = L.env ?? 0.8;
    this.hud.setArena(index, def.label);
  }

  resize() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, this.quality.maxPixelRatio));
    this.renderer.setSize(w, h, false);
    this.rig.resize(w, h);
    this.background.resize(w / h);
    this.mainPlatform?.layout(this.rig);
    const bufferH = this.renderer.getDrawingBufferSize(new THREE.Vector2()).y;
    this.effects.resize(bufferH, this.rig.camera.fov);
    this.player?.visual.resize(bufferH, this.rig.camera.fov);
    const touchOn = this.touch.enabled;
    document.getElementById('rotate-hint').classList.toggle('hidden', !(touchOn && h > w));
  }

  // ---------- state changes ----------
  enterMenu() {
    this.state = 'menu';
    this.stateT = 0;
    this.director.reset();
    this.platforms.clear();
    this.effects.clear();
    this.elapsed = 0;
    this.diff = difficultyAt(0);
    const main = this.mainPlatform.surface;
    this.player.reset(-2.2, main.heightAt(-2.2) ?? 0, main);
    this.platforms.fill(this.diff.platformTarget, this.diff.platformLifetime);
    this.hud.show(false);
    this.touch.setVisible(false);
    this.screens.show('menu');
    this.audio.setPaused(false);
    this.audio.setRate(1);
    this.audio.play('menu');
  }

  startRun() {
    this.audio.unlock();
    document.activeElement?.blur?.(); // keep Space/Enter away from menu buttons
    this.director.reset();
    this.platforms.clear();
    this.effects.clear();
    this.elapsed = Math.min(this.params.start || 0, RUN_SECONDS - 1);
    this.diff = difficultyAt(this.elapsed);
    const main = this.mainPlatform.surface;
    this.player.reset(0, main.heightAt(0) ?? 0, main);
    this.platforms.fill(this.diff.platformTarget, this.diff.platformLifetime);
    this.director.spawnTimer = 2.5;
    this.hitstop = 0;
    this.state = 'playing';
    this.stateT = 0;
    this.screens.hideAll();
    this.hud.show(true);
    this.touch.setVisible(this.touch.enabled);
    this.hud.setHealth(this.player.health, PLAYER.maxHealth);
    this.hud.setTime(RUN_SECONDS - this.elapsed);
    const def = ARENAS[this.arenaIndex];
    this.hud.announce(`ARENA ${this.arenaIndex + 1}`, `${def.label} — survive`, 2.8);
    this.hud.hint(
      this.touch.enabled
        ? 'Stick: move · JUMP (twice for an air jump) · DASH through enemies'
        : 'Move <b>A/D</b> · Jump <b>Space</b> (twice in the air) · Dash <b>Shift</b> · Drop <b>S+Space</b>',
      8,
    );
    this.audio.setPaused(false);
    this.audio.setRate(this.diff.musicRate);
    this.audio.play(def.music, { rate: this.diff.musicRate, fade: 0.8 });
    this.last = performance.now();
  }

  pause() {
    if (this.state !== 'playing') return;
    this.state = 'paused';
    this.screens.show('pause');
    this.audio.setPaused(true);
    this.touch.release();
  }

  resume() {
    if (this.state !== 'paused') return;
    this.state = 'playing';
    this.screens.hideAll();
    this.audio.setPaused(false);
    this.last = performance.now();
  }

  onAction(action) {
    this.audio.unlock();
    this.audio.sfx('ui');
    if (action === 'play' || action === 'restart') this.startRun();
    else if (action === 'resume') this.resume();
    else if (action === 'quit') this.enterMenu();
  }

  onPlayerHurt(amount) {
    this.hud.hurtFlash();
    this.rig.shake(Math.min(0.35, 0.1 + amount * 0.01), 0.3);
    this.audio.sfx('hurt');
    this.hitstop = 0.06;
  }

  onPlayerDied() {
    this.state = 'dying';
    this.stateT = 0;
    this.rig.shake(0.4, 0.5);
    this.audio.setRate(0.7);
    this.touch.setVisible(false);
  }

  gameOver() {
    this.state = 'over';
    this.hud.clearHint();
    this.screens.setGameOver(this.elapsed, this.arenaIndex, RUN_SECONDS - this.elapsed);
    this.screens.show('over');
    this.audio.play('menu', { fade: 1.5, rate: 1 });
  }

  win() {
    this.state = 'won';
    this.hud.clearHint();
    this.elapsed = RUN_SECONDS;
    this.hud.setTime(0);
    this.director.killAll();
    this.touch.setVisible(false);
    const p = this.player.body;
    this.effects.burst(p.x, p.y + 0.5, 140, { speed: 10, up: 2, color: 0x63f2ff, size: 0.3, life: 1.6, drag: 1 });
    this.screens.show('win');
    this.audio.play('menu', { fade: 2, rate: 1 });
  }

  // ---------- frame ----------
  frame() {
    const now = performance.now();
    const rdt = Math.min((now - this.last) / 1000, 1 / 20);
    this.last = now;
    const input = this.input.poll();
    this.stateT += rdt;

    switch (this.state) {
      case 'playing':
        if (input.pausePressed) this.pause();
        else this.updatePlaying(rdt, input);
        break;
      case 'paused':
        if (input.pausePressed) this.resume();
        break;
      case 'menu':
        if (input.confirmPressed || (input.jumpPressed && input.usingPad)) this.onAction('play');
        this.updateAmbient(rdt, true);
        break;
      case 'dying':
        this.updateAmbient(rdt * 0.4, false);
        if (this.stateT > 1.6) this.gameOver();
        break;
      case 'over':
      case 'won':
        if (input.confirmPressed) this.onAction('restart');
        this.updateAmbient(rdt, this.state === 'won');
        break;
      default:
        break;
    }
    if (this.state !== 'paused' && this.mainPlatform) {
      this.mainPlatform.update(rdt);
      this.effects.update(this.state === 'dying' ? rdt * 0.4 : rdt);
      this.rig.update(rdt);
      const pb = this.player?.body;
      if (pb) this.background.update(pb.x / Math.max(1, this.rig.halfW), (pb.y - 1) / 6);
    }
    this.hud.update(rdt);
    if (this.debug && this.player) this.updateDebug(rdt);
    this.renderer.render(this.scene, this.rig.camera);
  }

  updatePlaying(rdt, input) {
    this.elapsed += rdt;
    if (this.elapsed >= RUN_SECONDS) {
      this.win();
      return;
    }
    this.diff = difficultyAt(this.elapsed);
    const arena = Math.min(PLAYABLE_ARENAS - 1, Math.floor(this.elapsed / ARENA_SECONDS));
    if (arena !== this.arenaIndex) this.arenaIndex = arena; // phase 2: arena transitions start here

    this.hud.setTime(RUN_SECONDS - this.elapsed);
    this.audio.setRate(this.diff.musicRate);

    if (this.hitstop > 0) {
      this.hitstop -= rdt;
      return;
    }
    const dt = rdt * this.diff.gameSpeed;
    const n = Math.max(1, Math.ceil(dt / STEP - 1e-6));
    const h = dt / n;
    const rh = rdt / n;
    for (let i = 0; i < n; i++) {
      const inp = i === 0 ? input : { ...input, jumpPressed: false, dashPressed: false };
      this.platforms.update(h, this.diff, true);
      this.player.update(h, inp);
      this.director.update(h, rh, true);
      this.world.endFrame();
      if (this.state !== 'playing') break;
    }
    this.hud.setHealth(this.player.health, PLAYER.maxHealth);
  }

  // Menu / game over / dying: platforms and effects keep living, no new enemies.
  updateAmbient(dt, platformsSpawn) {
    const n = Math.max(1, Math.ceil(dt / STEP - 1e-6));
    const h = dt / n;
    for (let i = 0; i < n; i++) {
      this.platforms.update(h, this.diff, platformsSpawn);
      this.player.update(h, NO_INPUT);
      this.director.update(h, h, false);
      this.world.endFrame();
    }
  }

  updateDebug(rdt) {
    this.debug.update(this);
    const f = this.fps;
    f.frames++;
    f.t += rdt;
    if (f.t >= 0.5) {
      f.value = Math.round(f.frames / f.t);
      f.frames = 0;
      f.t = 0;
      const info = this.renderer.info.render;
      const d = this.diff;
      this.debugEl.textContent =
        `fps ${f.value}  calls ${info.calls}  tris ${info.triangles}\n` +
        `t ${this.elapsed.toFixed(1)}s  speed ${d.gameSpeed.toFixed(2)}  enemies ${this.director.aliveCount}/${d.maxEnemies}  spawn ${d.spawnInterval.toFixed(1)}s\n` +
        `platforms ${this.platforms.standing.length}/${d.platformTarget} life ${d.platformLifetime.toFixed(1)}s  music x${d.musicRate.toFixed(3)}  [${this.platform}]`;
    }
  }
}
