// Every gameplay tunable lives here. Units: metres, seconds, m/s.

export const GAME_TITLE = 'WISP'; // working title, rename freely

export const MANIFEST_PATH = 'contoo_assets.json';

export const RUN_SECONDS = 20 * 60; // the countdown
export const ARENA_SECONDS = 4 * 60; // each arena lasts exactly this long

// Arena timeline. `roster` = enemy ids that can spawn in that arena (ids from the manifest).
// Phase 1 only plays arena 1; arenas 2-5 and the transitions come in phase 2.
export const ARENAS = [
  {
    biome: 'desert',
    label: 'Desert',
    roster: ['kaya', 'brumm'],
    music: 'combat',
    light: { sky: 0xfff1dc, ground: 0x6b4a2e, hemi: 1.7, key: 0xffe2b8, keyI: 2.4, rim: 0xffb070, rimI: 1.6 },
    bgTint: [0.09, 0.05, 0.06],
  },
  {
    biome: 'forge',
    label: 'Forge',
    roster: ['kaya', 'brumm', 'volt'],
    music: 'combat',
    light: { sky: 0xffd9b0, ground: 0x3a2418, hemi: 1.5, key: 0xffc890, keyI: 2.4, rim: 0xff6a2a, rimI: 2.0 },
    bgTint: [0.08, 0.04, 0.03],
  },
  {
    biome: 'neon',
    label: 'Neon',
    roster: ['kaya', 'brumm', 'volt', 'wren'],
    music: 'combat',
    light: { sky: 0xd8d0ff, ground: 0x2a1840, hemi: 1.5, key: 0xe6e0ff, keyI: 2.2, rim: 0x41f0ff, rimI: 2.2 },
    bgTint: [0.05, 0.03, 0.1],
  },
  {
    biome: 'forest',
    label: 'Forest',
    roster: ['kaya', 'brumm', 'volt', 'wren', 'frostine'],
    music: 'combat',
    light: { sky: 0xeaffe0, ground: 0x2c3a1c, hemi: 1.6, key: 0xfff4d0, keyI: 2.3, rim: 0x9dff7a, rimI: 1.6 },
    bgTint: [0.03, 0.06, 0.03],
  },
  {
    biome: 'ice',
    label: 'Ice',
    roster: ['kaya', 'brumm', 'volt', 'wren', 'frostine'],
    music: 'boss',
    light: { sky: 0xe4f4ff, ground: 0x2a3550, hemi: 1.7, key: 0xf0f8ff, keyI: 2.4, rim: 0x9fd8ff, rimI: 2.0 },
    bgTint: [0.03, 0.05, 0.09],
  },
];

// Arenas that are implemented in the current build (phase 1 = desert only).
export const PLAYABLE_ARENAS = 1;

// Side-view camera. Spark has no orthographic support, so a narrow-FOV perspective camera is used.
export const VIEW = {
  fovDeg: 20, // vertical FOV
  pitchDeg: 7, // looks slightly down so the tops of the splat grounds read
  height: 12, // world metres visible vertically on 16:9 or wider screens
  heightCompact: 10.5, // short screens (phones in landscape) get a closer camera
  compactBelowPx: 520, // CSS pixel height under which the compact view is used
  minWidth: 19.5, // narrower screens show more height instead of less width
  maxHalfWidth: 15, // arena walls never further than this from the centre
  surfaceScreenFrac: 0.35, // main platform surface sits at 35% of the screen height from the bottom
};

// The main floating platform = the arena's *_mid image. Always the same screen position.
export const MAIN_PLATFORM = {
  width: 12, // metres
  zBack: 1.2, // drawn this far behind the gameplay plane (z = 0) so characters are in front
  edgeInset: 0.02, // fraction of the image width trimmed from each end of the walkable surface
};

export const PLAYER = {
  maxHealth: 100,
  halfW: 0.31,
  height: 0.98,
  runSpeed: 7.2,
  groundAccel: 75,
  airAccel: 42,
  groundFriction: 65,
  airFriction: 9,
  gravity: 34,
  fallGravityMul: 1.3,
  maxFall: 24,
  jumpSpeed: 13.2,
  jumpCut: 0.5, // vy multiplier when jump is released early
  airJumps: 1,
  airJumpSpeed: 11.5,
  coyote: 0.1,
  jumpBuffer: 0.13,
  dashSpeed: 21,
  dashTime: 0.16,
  dashCooldown: 0.5,
  dashIframes: 0.22,
  hurtIframes: 0.9,
  knockback: 7,
  regenDelay: 3.5,
  fallDamage: 25,
  respawnIframes: 2.0,
  ceilingMargin: 0.8, // soft ceiling below the top of the screen
};

// Enemy definitions. Clip data (lengths, hit_time_s, run speed) comes from the manifest.
// speedMul scales the manifest ground_speed_mps; the run clip is time-scaled to match so feet don't slide.
export const ENEMIES = {
  kaya: { color: 0xffb347, damage: 12, range: 1.35, hitW: 0.7, speedMul: 1.35, knockback: 6.5 },
  brumm: { color: 0xff6a2a, damage: 18, range: 1.55, hitW: 0.85, speedMul: 1.55, knockback: 9.5 },
  volt: { color: 0x41f0ff, damage: 10, range: 1.45, hitW: 0.7, speedMul: 1.3, knockback: 6 },
  wren: { color: 0x7ddc5a, damage: 11, range: 1.55, hitW: 0.7, speedMul: 1.2, knockback: 6 },
  frostine: { color: 0x9fd8ff, damage: 13, range: 1.6, hitW: 0.7, speedMul: 1.15, knockback: 6.5 },
};

export const ENEMY = {
  faceAngleDeg: 72, // yaw used for left/right (90 = pure profile; a bit less shows some of the face)
  gravity: 26,
  maxJumpUp: 4.2,
  maxJumpDx: 7.5,
  jumpReaction: [0.35, 0.65],
  appearTime: 0.45,
  staggerTime: 0.7,
  staggerCooldown: 2.2,
  deathFade: 0.7,
  campTime: 3.5, // standing within ~1.6 m this long counts as camping: spawns speed up and land on you
  spawnBurstRadius: 0.95,
  spawnBurstDamage: 8,
};

export const PLATFORMS = {
  scale: [0.36, 0.48], // splat grounds are 8 m wide; this makes 2.9-3.8 m platforms
  shakeTime: 1.5, // warning before a platform falls
  riseTime: 0.9,
  riseDistance: 1.6,
  fallAccel: 14,
  fallFadeTime: 1.1,
  minY: -2.6,
  maxYBelowTop: 3.7, // keep platforms this far below the top of the screen
  respawnDelay: [0.4, 1.2],
};

export const KILL_MARGIN = 1.5; // below the bottom of the screen = fell into the void

// Quality presets, picked by device (or the Quality setting).
export const QUALITY = {
  pc: { antialias: true, maxPixelRatio: 2, particles: 1600, wispSegments: 5, motes: 46, sparkStdDev: Math.sqrt(8) },
  mobile: { antialias: false, maxPixelRatio: 1.5, particles: 700, wispSegments: 3, motes: 26, sparkStdDev: Math.sqrt(6) },
};
