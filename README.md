# first

A side-view 2.5D fighting game for the web, hosted on Cloudflare Workers (static assets).
Five fighters, five biomes, PC and mobile builds of every asset. Assets were made with the "conto" pipeline
(ComfyUI + Blender); the game code is plain JavaScript modules with three.js and Spark (gaussian-splat floors).

**Play:** pick a fighter, then a best-of-3 against the CPU on your fighter's home stage.
Keyboard: A/D or ←/→ move · W/↑/Space jump · Shift/K/↓ dodge · J/F/click attack · Esc pause.
Gamepad and on-screen touch buttons work too. Add `?q=pc` or `?q=mobile` to force an asset set.

**Run locally:** `npx wrangler dev`, or `python3 -m http.server -d public` and open http://localhost:8000.
There is no build step.

## Folders

| Path | What it is | Public? |
|---|---|---|
| `wrangler.jsonc` | Cloudflare Workers config; serves `./public` | — |
| `contoo_assets.json` | Asset list: file paths, clip lengths, hit times, walk lines, parallax, music BPM | copy in `public/assets/` |
| `public/` | **Everything here is downloadable by anyone.** Only browser files go here. | yes |
| `public/index.html` | Entry page | yes |
| `public/src/` | Game code (see below) | yes |
| `public/vendor/` | three.js 0.186.1 and Spark 2.2.0, bundled so the site needs no CDN | yes |
| `public/assets/` | Web-ready copies: characters, weapons, floors, backgrounds, music | yes |
| `Assets/` | Source/working files (incl. `Weapons.blend`, `.ply` splat sources) | no |
| `Pipeline/` | Scripts, Kimodo motions and ComfyUI workflows, by stage (`0_shared` … `6_finish`) | no |
| `docs/` | Detailed asset notes and preview images | no |

See `docs/asset_notes.txt` for characters, PC vs mobile specs and conventions.

## Game code (`public/src/`)

| File | Does |
|---|---|
| `main.js` | Renderer, screens (select → loading → fight → result), camera, main loop |
| `fight.js` | Rounds, hit resolution, hitstop, K.O. |
| `fighter.js` | One fighter: animation clips, move/jump/dodge/attack/hit/death; per-character tuning in `KIT` |
| `ai.js` | CPU opponent |
| `projectiles.js` | Wren's arrows, Lady Frostine's frost wave |
| `stage.js` | Splat floor, walk-line ground height, parallax background layers |
| `input.js` | Keyboard, mouse, gamepad, touch buttons |
| `audio.js` | Seamless music loops (menu, combat, boss for the final round) and hit sounds |
| `assets.js` | Asset list, PC/mobile choice, loading with progress |

## Rules

- Files in `public/` must be under 25 MB each (Cloudflare limit).
- Paths in `contoo_assets.json` are repo-relative; in the browser drop the `public/` prefix (`public/assets/x` → `assets/x`).
