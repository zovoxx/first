# CLAUDE.md — side-view survival browser game

Working title **WISP** (placeholder, set in `src/config.js` → `GAME_TITLE`). Note: "Contoo" is *not* the
game's name — it is the owner's word for "coding the game after the conto asset pipeline". The manifest
file is still called `contoo_assets.json`.

## Hard rules

- **Never move or rename anything under `Assets/`** and never edit `contoo_assets.json` paths — the game
  loads every file through the manifest. `README.txt` documents the assets.
- **Ignore `Pipeline/`** (the asset-making tools). Don't import from it, don't ship it.
- Every asset exists as `_PC` and `_mobile`. Load `_PC` on desktop and `_mobile` on phones/tablets
  (auto-detected, overridable in Settings and with `?quality=pc|mobile`).
- Keep all gameplay numbers in `src/config.js` (and the curves in `src/game/difficulty.js`).
- Cloudflare Pages: max 25 MiB per file. The build copies only runtime assets and fails if one is bigger.

## Commands

```bash
npm install
npm run dev       # Vite dev server; serves Assets/ straight from the repo root
npm run build     # -> dist/ (bundle + copies the manifest-referenced runtime assets)
npm run preview   # serve dist/
```

Cloudflare Pages: build command `npm run build`, output directory `dist`. `public/_headers` sets caching.

### Test URL parameters
`?quality=pc|mobile` force asset set · `?debug=1` collision lines, hitboxes, fps/difficulty readout ·
`?play=1` skip the menu · `?start=<seconds>` start the run at that elapsed time (e.g. `?start=900`) ·
`?god=1` no damage · `?nosplats=1` hide splat meshes (collision stays).

Headless Chromium (SwiftShader) renders the splats at ~7 s/frame, so use `?nosplats=1` for automated
gameplay checks, and the new headless mode (`channel: 'chromium'`) for screenshots — the old headless
shell times out on screenshots. `window.__game` is exposed; a fast no-render simulation can call
`__game.updatePlaying(1/60, input)` in a loop (see the phase-1 notes below).

## Tech

- Plain **three.js** (r186) + `GLTFLoader` + `SkeletonUtils` for the character `.glb` files.
- **Spark** (`@sparkjsdev/spark` 2.x) for the gaussian-splat `.spz` grounds. Spark 2 needs a
  `SparkRenderer` added to the scene. One `PackedSplats` per biome is shared by all platform `SplatMesh`es.
  Spark has **no orthographic camera support** → we use a narrow-FOV perspective camera.
- **Vite** build, plain ES modules (no TypeScript, no framework). DOM overlay for UI.
- WebAudio for music (seamless `loopEnd = loop_seconds`, `playbackRate` ramp) and synthesized SFX.

## Game design (full)

**Player.** A strange creature — not human or animal, a figure without a real body. Made in code (no
asset): a glowing, shifting, flame-like blob (noise-displaced shader), a bright nucleus that shows the
facing direction, orbiting motes, halo and trails. Readable from the side; the core fills the hitbox
(0.62 × 0.98 m). It can **move, jump (+1 air jump), dash** (brief invulnerability; dashing through an
enemy staggers it). It has **no attack** — it only survives. Down + jump drops through floating platforms.

**Goal.** Stay alive until a **20:00 countdown** reaches 0. Health 100, regenerates slowly after a few
seconds without damage. Falling into the void costs 25 HP and respawns you on the main platform.
The game must always get harder and faster and always force the player to keep moving.

**Arenas and timeline** (exactly 4 minutes each):

| Time | Arena | Biome | Enemies |
|---|---|---|---|
| 00:00–04:00 | 1 | desert | Kaya, Brumm |
| 04:00–08:00 | 2 | forge | + Volt |
| 08:00–12:00 | 3 | neon | + Wren |
| 12:00–16:00 | 4 | forest | + Frostine |
| 16:00–20:00 | 5 | ice | all 5, strongest versions (boss music) |

Each arena = its `Assets/Backgrounds/<biome>` folder: the big `*_far` image is the arena's main background
(full-screen, cover-fit, slight parallax); the small `*_mid` image is the **main floating platform**. The
main platform is the only platform that never shakes, falls or disappears; it is always at the same screen
position. Its walkable top is computed from the image **alpha** (props like trees/houses are ignored, see
`alphaSurface.js`). At exactly 4:00, 8:00, 12:00 and 16:00 an animated transition plays: the old
background and main platform break apart / sink / fade while the new ones rise / fade in. The player must
not die because of the transition (kept safely on the platform during it).

**Random platforms.** The current arena's biome ground (`Assets/Grounds/<biome>` `.spz`, collision from
the manifest `walk_line`), scaled to ~3–4 m. They appear and disappear at random positions/times. Before a
platform falls it shakes for ~1.5 s, then falls and fades out. New ones keep spawning so there is always
somewhere to go.

**Enemies** = the 5 characters. They spawn around the player and especially on the main platform, so
standing still is never safe; a warning marker (ground ring + beam in the enemy's colour) shows before
each spawn, and standing on it when it bursts hurts. Each enemy uses its `.glb` clips: idle, run (time-
scaled to move speed so feet don't slide), jump (to reach other platforms), dodge (evades a dash), hit
(stagger), attack (damage exactly at the manifest `hit_time_s`), death (whenever an enemy is removed).
Enemies face left/right by rotating around Y (they face +Z in the file; we use ±72° so a bit of the face
shows). Abilities unlock progressively: each enemy starts with a basic attack and gains one new ability
per arena, built from the clips + code effects, announced on screen. Ideas: Kaya dash-slash and spin,
Brumm hammer ground-pound shockwave, Volt teleport-dash and electric trail, Wren arrows and arrow rain,
Frostine ice spikes and slowing ice zones.

**Difficulty.** Everything ramps continuously over the 20 minutes (not just at arena changes): enemy
speed, attack rate, spawn rate, max enemies, platform fall rate, damage, overall game speed (1.0→1.15).
Music speeds up with it: combat loop in arenas 1–4, boss loop in arena 5, `playbackRate` 1.0→1.2
(slight pitch rise is fine). Menu loop on the menu.

**UI.** 20:00 countdown always visible, arena number, player health, short announcements. Start menu,
settings (asset quality, touch controls, volumes), pause, game over (time survived, arena reached), win
screen at 00:00.

**Platforms/input.** Keyboard + gamepad on PC, on-screen touch controls on mobile (floating stick left,
JUMP/DASH right). 60 fps target on PC, smooth on mid-range phones.

## Phases

1. **Done** — project setup, manifest loading (PC/mobile), side-view camera, player creature + movement,
   main platform with alpha collision, Arena 1 (desert) with Kaya + Brumm basic AI, spawn warnings,
   random shaking/falling splat platforms, countdown, HUD, menus, touch/gamepad, music + rate ramp.
2. **Arenas 2–5 + transitions** — load next arena in the background before each 4:00 mark; transition
   animation (Background has two texture slots + `uMix`; MainPlatform shader has `uReveal`/`uBreak`);
   keep the player safe during it; collapse old splat platforms, spawn new biome ones; Volt, Wren, Frostine
   basic attacks; boss loop at 16:00; `PLAYABLE_ARENAS` → 5.
3. **Abilities** — one new ability per enemy per arena (clips + code effects), unlock table, on-screen
   announcements, projectiles/zones/shockwaves, status effects (slow).
4. **Polish + ship** — difficulty tuning over a full 20-minute run, juice (hit-stop, screen shake, sounds),
   pickups if needed, performance pass on real phones (dynamic resolution, splat counts), main platform
   underside art, accessibility, Cloudflare Pages deploy.

## Project structure

```
index.html              DOM: canvas, HUD, touch controls, screens
vite.config.js          base './', copies runtime assets into dist/ (25 MiB check)
public/_headers         Cloudflare Pages cache headers
src/main.js             boot: settings, platform choice, systems, Game, render loop
src/config.js           ALL tunables: arenas/timeline, view, player, enemies, platforms, quality presets
src/styles.css          UI styles
src/core/
  assets.js             Assets (manifest lookups, GLB/SPZ/image/music loading with progress), LoadTracker
  audio.js              AudioSystem: music loops (crossfade, rate), synthesized SFX
  device.js             mobile detection, settings (localStorage), URL params
  input.js              keyboard + gamepad + touch -> one per-frame state
  math.js glsl.js textures.js   helpers, shared GLSL noise, procedural textures
src/game/
  Game.js               renderer/scene/lights, state machine, frame loop (fixed 60 Hz substeps)
  CameraRig.js          side-view camera framing + shake; `behind()` helper for planes behind z=0
  difficulty.js         difficultyAt(elapsed) -> all ramped values
  collision.js          Surface (one-way polyline), CollisionWorld, Body (run/fall/land)
  alphaSurface.js       walkable surface from the *_mid image alpha
  Background.js         full-screen far background (cover-fit, parallax, 2 slots for transitions)
  MainPlatform.js       *_mid image plane + island-shaped edge erosion + Surface
  FloatingPlatforms.js  splat platforms: rise, live, shake 1.5 s, fall + fade; placement
  Player.js             movement/jump/dash/health/respawn
  WispVisual.js         the creature's look (shaders, motes, halo, ground glow)
  Enemy.js              one enemy: clone, mixer, AI state machine, attacks at hit_time_s
  EnemyDirector.js      spawn timing/placement, warning markers, recycling, separation
  Effects.js            pooled additive particles, rings, slash arcs, blob shadows
  DebugDraw.js          ?debug=1 overlay
src/ui/                 Hud.js, Screens.js, TouchControls.js
```

## Conventions / how things fit

- World units = metres, +Y up, gameplay on the **z = 0 plane** (X/Y only). Main platform surface = y 0.
- Camera: vertical FOV 20°, pitched down 7° so splat tops read. Visible height 12 m (10.5 m on short
  screens); the surface sits at 35% of screen height. Arena walls = visible half width (max 15 m).
  Kill line = 1.5 m below the screen.
- Draw order (renderOrder): far background −1000 (full-screen quad, opaque pass) → characters (opaque) →
  main platform −50 (plane at z −1.2, scaled/offset via `rig.behind()` so its surface still lines up with
  y 0) → splats 0 → shadows 5 → glows/rings 6–16 → particles 20 → wisp 30–34 (z +0.35).
- 2D art textures use `NoColorSpace` and are written straight out; custom shaders that use `THREE.Color`
  include `<colorspace_fragment>`. Characters use PBR + a RoomEnvironment env map + 3 lights per arena.
- Collision: all platforms are one-way (land from above, jump up through). Floating platforms are
  droppable, the main one is not. Grounded bodies follow their surface each step (moving platforms carry).
- Simulation: `dt = realDt * diff.gameSpeed`, split into ≤1/60 s substeps. The countdown uses real time.
  Spawn warnings use real time too (fairness).
- Enemy AI states: appear → chase ⇄ attack / jumpPrep → air / dodge / stagger → dying (death clip, fade).
  Enemies have a lifetime; at the enemy cap the farthest old enemy leaves (death clip) to make room.
  Camping (staying within ~1.6 m for 3.5 s) speeds up spawns and drops one right on the player.
- Main platform alpha surface: first rows ≥95% opaque = ground band; per column climb up through opaque
  pixels; columns rising >3.5% of the image height above the band are props (dropped + dilated);
  interpolate, 60th-percentile + box filter. Median row → y 0. Verified on all 5 `_mid` images.

## Phase-1 verification notes

- `npm run build` passes; runtime assets ~104 MiB, all files < 25 MiB.
- Headless runs: menu, gameplay, PC 1600×900, phone landscape with touch controls; 4-minute and
  late-game (`?start=1000`) bot simulations with no errors, bounded scene size, 2–5 standing platforms,
  enemies jumping between platforms, staggers/dodges/attacks all firing.

## Open questions for the owner

- Final game name (currently "WISP").
