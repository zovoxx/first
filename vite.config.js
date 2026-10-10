import { defineConfig } from 'vite';
import fs from 'node:fs';
import path from 'node:path';

const MANIFEST = 'contoo_assets.json';
const MAX_FILE_BYTES = 25 * 1024 * 1024; // Cloudflare Pages per-file limit

// The game loads only these manifest entries at runtime (no .ply sources, colliders, previews,
// stand-alone weapons or .blend files).
function runtimeAssetPaths(manifest) {
  const out = new Set();
  for (const c of manifest.characters) Object.values(c.files).forEach((p) => out.add(p));
  for (const g of manifest.grounds) [g.files.splat_pc, g.files.splat_mobile].forEach((p) => out.add(p));
  for (const b of manifest.backgrounds) [b.far.pc, b.far.mobile, b.mid.pc, b.mid.mobile].forEach((p) => out.add(p));
  for (const m of manifest.music) Object.values(m.files).forEach((p) => out.add(p));
  return [...out];
}

// Assets stay where they are in the repo (the manifest paths depend on it). In dev Vite serves them
// from the project root; on build they are copied into dist/ with the same relative paths.
function copyGameAssets() {
  let root;
  let outDir;
  return {
    name: 'copy-game-assets',
    apply: 'build',
    configResolved(cfg) {
      root = cfg.root;
      outDir = path.resolve(cfg.root, cfg.build.outDir);
    },
    closeBundle() {
      const manifest = JSON.parse(fs.readFileSync(path.join(root, MANIFEST), 'utf8'));
      const files = [MANIFEST, ...runtimeAssetPaths(manifest)];
      let total = 0;
      for (const rel of files) {
        const src = path.join(root, rel);
        const dst = path.join(outDir, rel);
        const size = fs.statSync(src).size;
        if (size > MAX_FILE_BYTES) throw new Error(`${rel} is ${(size / 1048576).toFixed(1)} MiB (> 25 MiB Cloudflare Pages limit)`);
        fs.mkdirSync(path.dirname(dst), { recursive: true });
        fs.copyFileSync(src, dst);
        total += size;
      }
      console.log(`copy-game-assets: ${files.length} files, ${(total / 1048576).toFixed(1)} MiB`);
    },
  };
}

export default defineConfig({
  base: './',
  plugins: [copyGameAssets()],
  build: {
    target: 'es2022',
    chunkSizeWarningLimit: 3500, // Spark ships its WASM inline
  },
  server: {
    host: true,
    watch: { ignored: ['**/Assets/**', '**/Pipeline/**'] },
  },
});
