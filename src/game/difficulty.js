import { RUN_SECONDS, ARENA_SECONDS, ARENAS } from '../config.js';
import { clamp, lerp } from '../core/math.js';

// Continuous difficulty ramp over the whole 20 minutes. Everything is a function of elapsed
// time so it rises smoothly inside an arena, not only at arena changes. The boss arena (5)
// adds a flat bump on top.
export function difficultyAt(elapsed) {
  const t = clamp(elapsed / RUN_SECONDS, 0, 1);
  const arena = Math.min(ARENAS.length - 1, Math.floor(elapsed / ARENA_SECONDS));
  const boss = arena === ARENAS.length - 1 ? 1 : 0;
  return {
    t,
    arena,
    gameSpeed: 1 + 0.15 * t, // global simulation speed
    enemySpeed: 1 + 0.65 * t + 0.1 * boss,
    attackSpeed: 1 + 0.5 * t + 0.1 * boss, // attack clip time scale
    attackCooldown: lerp(1.5, 0.45, t),
    spawnInterval: lerp(6.0, 1.4, Math.pow(t, 0.85)),
    maxEnemies: Math.round(lerp(3, 9, t)) + boss,
    spawnWarning: lerp(1.25, 0.75, t),
    enemyLifetime: lerp(28, 20, t),
    dodgeChance: lerp(0.15, 0.5, t),
    platformLifetime: lerp(15, 5.5, t),
    platformTarget: t < 0.5 ? 5 : 4,
    damageMul: 1 + 0.6 * t + 0.15 * boss,
    regenPerSec: lerp(4, 1.2, t),
    musicRate: 1 + 0.2 * t, // 1.0 -> 1.2
  };
}
