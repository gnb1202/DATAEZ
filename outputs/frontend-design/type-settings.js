/* Preview controls. Spoqa Han Sans Neo is also the application's chosen UI font. */
(() => {
  const key = 'dataez-design-typography-v2';
  const fonts = {
    pretendard: {name: 'Pretendard', family: '"Pretendard Variable", "Noto Sans KR", sans-serif', face: 'Pretendard Variable'},
    suit: {name: 'SUIT', family: '"SUIT Variable", "Noto Sans KR", sans-serif', face: 'SUIT Variable'},
    noto: {name: 'Noto Sans KR', family: '"Noto Sans KR", sans-serif', face: 'Noto Sans KR', fixedDigits: true},
    wanted: {name: 'Wanted Sans', family: '"Wanted Sans Variable", "Noto Sans KR", sans-serif', face: 'Wanted Sans Variable'},
    spoqa: {name: 'Spoqa Han Sans Neo', family: '"Spoqa Han Sans Neo", "Noto Sans KR", sans-serif', face: 'Spoqa Han Sans Neo', fixedDigits: true, weights: [400, 500, 700], emphasis: 700}
  };
  const defaults = Object.freeze({font: 'spoqa', size: 15, weight: 400, tracking: -0.015, leading: 1.7, amount: 32, tabular: true});
  const number = (n, min, max, fallback) => typeof n === 'number' && Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback;
  function normalize(raw) {
    const value = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
    const font = Object.hasOwn(fonts, value.font) ? value.font : defaults.font;
    const supported = fonts[font].weights;
    let weight = number(value.weight, 400, supported ? 700 : 600, defaults.weight);
    if (supported) weight = supported.reduce((best, candidate) => Math.abs(candidate - weight) < Math.abs(best - weight) ? candidate : best);
    return {
      font,
      size: number(value.size, 13, 18, defaults.size),
      weight,
      tracking: number(value.tracking, -0.04, 0.01, defaults.tracking),
      leading: number(value.leading, 1.4, 1.9, defaults.leading),
      amount: number(value.amount, 26, 40, defaults.amount),
      tabular: fonts[font].fixedDigits ? true : typeof value.tabular === 'boolean' ? value.tabular : defaults.tabular
    };
  }
  function read() {
    // The URL also allows the preview to work when localStorage is unavailable.
    try {
      const raw = new URLSearchParams(location.search).get('type');
      if (raw) return normalize(JSON.parse(raw));
    } catch {}
    try {
      const raw = localStorage.getItem(key);
      if (raw) return normalize(JSON.parse(raw));
      const previous = localStorage.getItem('dataez-design-typography-v1');
      if (previous) {
        const migrated = normalize({...JSON.parse(previous), font: defaults.font});
        localStorage.setItem(key, JSON.stringify(migrated));
        return migrated;
      }
    } catch { /* The chosen default also works without browser storage. */ }
    return {...defaults};
  }
  function applyTo(element, raw) {
    const s = normalize(raw);
    const variables = {'family': fonts[s.font].family, 'size': `${s.size}px`, 'weight': s.weight,
      'tracking': `${s.tracking}em`, 'leading': s.leading, 'amount': `${s.amount}px`, 'emphasis': fonts[s.font].emphasis || 600,
      'numerals': s.tabular ? 'lining-nums tabular-nums' : 'lining-nums proportional-nums'};
    Object.entries(variables).forEach(([name, value]) => element.style.setProperty(`--type-${name}`, value));
    element.dataset.font = s.font;
    return s;
  }
  function save(raw) {
    const settings = normalize(raw);
    let persisted = false;
    try { localStorage.setItem(key, JSON.stringify(settings)); persisted = true; } catch {}
    document.dispatchEvent(new CustomEvent('dataez-type-change', {detail: settings}));
    return {settings, persisted};
  }
  function css(raw) {
    const s = normalize(raw);
    return `/* DATA:EZ typography draft. Load fonts.css and keep fonts/ alongside it. */\n:root {\n  --font-ui: ${fonts[s.font].family};\n  --text-body: ${s.size}px;\n  --weight-body: ${s.weight};\n  --tracking-body: ${s.tracking}em;\n  --leading-body: ${s.leading};\n  --text-amount: ${s.amount}px;\n}\nbody {\n  font-family: var(--font-ui);\n  font-size: var(--text-body);\n  font-weight: var(--weight-body);\n  letter-spacing: var(--tracking-body);\n  line-height: var(--leading-body);\n}\nbutton, input, select, textarea { font: inherit; }\n.numeric {\n  font-variant-numeric: lining-nums ${s.tabular ? 'tabular-nums' : 'proportional-nums'};\n  font-kerning: none;\n  letter-spacing: 0;\n}\n.amount { font-size: var(--text-amount); font-weight: ${fonts[s.font].emphasis || 600}; }\n`;
  }
  const current = read();
  window.DataezType = {key, fonts, defaults, normalize, read, applyTo, save, css};
  if (document.documentElement.dataset.typePreview === 'workspace' && current) {
    applyTo(document.documentElement, current);
  }
  addEventListener('storage', event => {
    if (event.key !== key || document.documentElement.dataset.typePreview !== 'workspace') return;
    const current = read();
    if (current) {
      applyTo(document.documentElement, current);
      document.dispatchEvent(new CustomEvent('dataez-type-change', {detail: current}));
    }
  });
})();
