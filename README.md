# Contoo

A side-view 2.5D fighting game for the web, hosted on Cloudflare Workers (static assets).
The game assets were made with the "conto" pipeline (ComfyUI + Blender). Game code comes next.

## Folders

| Path | What it is | Public? |
|---|---|---|
| `wrangler.jsonc` | Cloudflare Workers config; serves `./public` | — |
| `contoo_assets.json` | Asset list: file paths, clip lengths, hit times, walk lines, parallax, music BPM | copy in `public/assets/` |
| `public/` | **Everything here is downloadable by anyone.** Only browser files go here. | yes |
| `public/index.html` | Entry page | yes |
| `public/src/` | Game code (later) | yes |
| `public/assets/` | Web-ready copies: characters, weapons, floors, backgrounds, music | yes |
| `Assets/` | Source/working files (incl. `Weapons.blend`, `.ply` splat sources) | no |
| `Pipeline/` | Scripts, Kimodo motions and ComfyUI workflows, by stage (`0_shared` … `6_finish`) | no |
| `docs/` | Detailed asset notes and preview images | no |

See `docs/asset_notes.txt` for characters, PC vs mobile specs and conventions.

## Rules

- Files in `public/` must be under 25 MB each (Cloudflare limit).
- Paths in `contoo_assets.json` are repo-relative; in the browser drop the `public/` prefix (`public/assets/x` → `/assets/x`).
