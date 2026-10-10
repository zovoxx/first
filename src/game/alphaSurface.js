// Walkable top surface of a 2D platform image, computed from its alpha channel.
//
// The *_mid images are a ground strip with props on top (trees, houses, pillars). Props are
// decoration, not floors, so:
//   1. find the ground band: the first rows that are opaque across >= 95% of the width,
//   2. per column, climb from just inside the band up through opaque pixels,
//   3. columns that climb far above the band are props -> dropped (plus a small dilation),
//   4. fill the gaps by interpolation, then a percentile + box filter to remove grass tufts.
// Returns rows (0 = image top) sampled across the width.

export function computeWalkSurface(img, { samples = 128, alphaThreshold = 128 } = {}) {
  const W = img.naturalWidth || img.width;
  const H = img.naturalHeight || img.height;
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(img, 0, 0);
  const data = ctx.getImageData(0, 0, W, H).data;
  const opaque = (c, r) => data[(r * W + c) * 4 + 3] >= alphaThreshold;

  // 1. ground band
  const coverage = new Float32Array(H);
  for (let r = 0; r < H; r++) {
    let n = 0;
    for (let c = 0; c < W; c++) if (opaque(c, r)) n++;
    coverage[r] = n / W;
  }
  const k = Math.max(2, Math.round(H * 0.02));
  let band = Math.round(H * 0.7);
  outer: for (let r = 0; r < H - k; r++) {
    for (let j = 0; j < k; j++) if (coverage[r + j] < 0.95) continue outer;
    band = r;
    break;
  }

  // 2-3. per-column climb
  const maxRise = Math.max(3, Math.round(H * 0.035));
  const start = Math.min(H - 1, band + Math.max(2, Math.round(H * 0.012)));
  const top = new Float32Array(W).fill(-1);
  for (let c = 0; c < W; c++) {
    if (!opaque(c, start)) continue;
    let r = start;
    while (r > 0 && opaque(c, r - 1)) r--;
    if (r < band - maxRise) continue; // a prop rising out of the ground
    top[c] = r;
  }
  const dil = Math.max(1, Math.round(W * 0.006));
  const valid = new Uint8Array(W);
  for (let c = 0; c < W; c++) {
    let ok = top[c] >= 0;
    for (let s = 1; ok && s <= dil; s++) {
      if ((c - s >= 0 && top[c - s] < 0) || (c + s < W && top[c + s] < 0)) ok = false;
    }
    valid[c] = ok ? 1 : 0;
  }

  // 4. interpolate gaps
  const filled = new Float32Array(W);
  let last = -1;
  for (let c = 0; c < W; c++) {
    if (!valid[c]) continue;
    if (last < 0) for (let j = 0; j < c; j++) filled[j] = top[c];
    else for (let j = last + 1; j < c; j++) filled[j] = top[last] + ((top[c] - top[last]) * (j - last)) / (c - last);
    filled[c] = top[c];
    last = c;
  }
  if (last < 0) filled.fill(band);
  else for (let j = last + 1; j < W; j++) filled[j] = top[last];

  // percentile (60th, i.e. slightly lower than median) then box filter
  const win = Math.max(3, Math.round(W * 0.015)) | 1;
  const half = win >> 1;
  const pct = new Float32Array(W);
  const tmp = new Float32Array(win);
  for (let c = 0; c < W; c++) {
    for (let j = 0; j < win; j++) tmp[j] = filled[Math.min(W - 1, Math.max(0, c + j - half))];
    tmp.sort();
    pct[c] = tmp[Math.floor(win * 0.6)];
  }
  const win2 = Math.max(3, Math.round(W * 0.01)) | 1;
  const half2 = win2 >> 1;
  const smooth = new Float32Array(W);
  for (let c = 0; c < W; c++) {
    let sum = 0;
    for (let j = -half2; j <= half2; j++) sum += pct[Math.min(W - 1, Math.max(0, c + j))];
    smooth[c] = sum / win2;
  }

  // resample
  const rows = [];
  for (let i = 0; i < samples; i++) {
    const u = i / (samples - 1);
    const c = Math.min(W - 1, Math.round(u * (W - 1)));
    rows.push([u, smooth[c]]);
  }
  const sorted = Array.from(smooth).sort((a, b) => a - b);
  const median = sorted[sorted.length >> 1];
  return { width: W, height: H, band, median, rows };
}
