// Device detection + persistent settings.

const SETTINGS_KEY = 'wisp.settings.v1';

const DEFAULTS = {
  quality: 'auto', // 'auto' | 'pc' | 'mobile'  -> which asset set to load
  touch: 'auto', // 'auto' | 'on' | 'off'      -> on-screen controls
  music: 0.7,
  sfx: 0.8,
};

export function isMobileDevice() {
  const ua = navigator.userAgent || '';
  if (navigator.userAgentData && typeof navigator.userAgentData.mobile === 'boolean' && navigator.userAgentData.mobile) return true;
  if (/Android|iPhone|iPad|iPod|Mobile|Silk|Kindle|Opera Mini|IEMobile/i.test(ua)) return true;
  // iPadOS reports itself as a Mac.
  if (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1) return true;
  return false;
}

export function hasTouch() {
  return 'ontouchstart' in window || navigator.maxTouchPoints > 0;
}

export function loadSettings() {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') || {};
  } catch {
    saved = {};
  }
  return { ...DEFAULTS, ...saved };
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    /* private mode etc. */
  }
}

// URL parameters for testing: ?quality=pc|mobile ?debug=1 ?start=<seconds> ?god=1 ?play=1
// ?nosplats=1 hides the splat meshes (collision stays) - for software-GL test browsers.
export function urlParams() {
  const p = new URLSearchParams(location.search);
  return {
    quality: p.get('quality'),
    debug: p.has('debug'),
    start: p.has('start') ? Math.max(0, parseFloat(p.get('start')) || 0) : 0,
    god: p.has('god'),
    play: p.has('play'),
    nosplats: p.has('nosplats'),
  };
}

// 'pc' or 'mobile': which asset files to load.
export function resolvePlatform(settings, params) {
  const forced = params.quality === 'pc' || params.quality === 'mobile' ? params.quality : null;
  if (forced) return forced;
  if (settings.quality === 'pc' || settings.quality === 'mobile') return settings.quality;
  return isMobileDevice() ? 'mobile' : 'pc';
}

export function touchEnabled(settings) {
  if (settings.touch === 'on') return true;
  if (settings.touch === 'off') return false;
  return isMobileDevice() || (hasTouch() && !matchMedia('(pointer: fine)').matches);
}
