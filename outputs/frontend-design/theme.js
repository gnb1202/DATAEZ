/* Resolve before CSS paint. An explicit preference wins over OS appearance. */
(() => {
  const key = 'dataez-design-theme';
  const allowed = new Set(['dark', 'light', 'system']);
  const media = matchMedia('(prefers-color-scheme: dark)');
  let preference = 'dark';
  try {
    const stored = localStorage.getItem(key);
    if (allowed.has(stored)) preference = stored;
  } catch { /* The preview still works when browser storage is disabled. */ }
  const linkedTheme = new URLSearchParams(location.search).get('theme');
  if (allowed.has(linkedTheme)) preference = linkedTheme;

  function apply() {
    const resolved = preference === 'system' ? (media.matches ? 'dark' : 'light') : preference;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.dataset.themePreference = preference;
    document.documentElement.style.colorScheme = resolved;
    document.dispatchEvent(new CustomEvent('dataez-theme-change', {detail: {preference, resolved}}));
  }

  window.DataezTheme = {
    get preference() { return preference; },
    get resolved() { return document.documentElement.dataset.theme; },
    setPreference(value) {
      if (!allowed.has(value)) return;
      preference = value;
      try { localStorage.setItem(key, value); } catch { /* Session-only fallback. */ }
      if (new URLSearchParams(location.search).has('theme')) {
        try { const url = new URL(location.href); url.searchParams.set('theme', value); history.replaceState(null, '', url); } catch {}
      }
      apply();
    },
  };
  media.addEventListener('change', () => { if (preference === 'system') apply(); });
  addEventListener('storage', event => {
    if (event.key !== key && event.key !== null) return;
    preference = allowed.has(event.newValue) ? event.newValue : 'dark';
    apply();
  });
  apply();
})();
