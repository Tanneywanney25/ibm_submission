/* T17: address search with autocomplete, shared by the nav, the landing hero
 * and the building page. Suggestions come from NYC Planning GeoSearch
 * (a public city service; the query string is the only thing sent, and nothing
 * typed is logged with identifying info). Building-level only: a suggestion is
 * the tax lot's street address and BBL, never an apartment.
 *
 * Markup: <form data-ha-search class="ha-search"> with one <input> and
 * optionally a .ha-search-status element. Selecting a suggestion navigates to
 * /building?bbl=…; plain Enter navigates to /building?q=… so the building
 * page's own lookup (and its geocoder-down / BBL fallbacks) takes over.
 * A page can intercept instead: the form dispatches cancelable "ha-search"
 * ({bbl, label}) and "ha-search-query" ({q}) events before navigating.
 */
(() => {
  'use strict';
  const GEOSEARCH = 'https://geosearch.planninglabs.nyc/v2/autocomplete';
  const MIN_CHARS = 3, DEBOUNCE_MS = 250, MAX_ITEMS = 6;
  let nextId = 0;

  function attach(form) {
    const input = form.querySelector('input');
    if (!input) return;
    const id = 'ha-search-' + (++nextId);
    const box = document.createElement('div');
    box.className = 'ha-search-box';
    input.parentNode.insertBefore(box, input);
    box.appendChild(input);
    const list = document.createElement('ul');
    list.id = id + '-list';
    list.className = 'ha-search-list';
    list.hidden = true;
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', 'Address suggestions');
    box.appendChild(list);
    const status = form.querySelector('.ha-search-status');
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-controls', list.id);
    input.setAttribute('autocomplete', 'off');
    input.setAttribute('spellcheck', 'false');

    let items = [], active = -1, timer = null, abort = null, searchSeq = 0;

    const say = text => { if (status) status.textContent = text || ''; };
    function close() {
      items = []; active = -1;
      list.hidden = true; list.innerHTML = '';
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
    }
    function render() {
      list.innerHTML = '';
      items.forEach((item, i) => {
        const li = document.createElement('li');
        li.id = id + '-opt-' + i;
        li.setAttribute('role', 'option');
        li.setAttribute('aria-selected', String(i === active));
        li.className = i === active ? 'active' : '';
        const name = document.createElement('b');
        name.textContent = item.name;
        li.appendChild(name);
        if (item.locality) {
          const where = document.createElement('small');
          where.textContent = ' ' + item.locality;
          li.appendChild(where);
        }
        // mousedown so the choice lands before the input's blur closes the list
        li.addEventListener('mousedown', event => { event.preventDefault(); select(item); });
        li.addEventListener('mousemove', () => { if (active !== i) { active = i; mark(); } });
        list.appendChild(li);
      });
      list.hidden = !items.length;
      input.setAttribute('aria-expanded', String(!!items.length));
      mark();
    }
    function mark() {
      [...list.children].forEach((li, i) => {
        li.className = i === active ? 'active' : '';
        li.setAttribute('aria-selected', String(i === active));
      });
      if (active >= 0) {
        input.setAttribute('aria-activedescendant', id + '-opt-' + active);
        const li = list.children[active];
        if (li && li.scrollIntoView) li.scrollIntoView({block: 'nearest'});
      } else input.removeAttribute('aria-activedescendant');
    }
    function select(item) {
      close();
      input.value = item.label;
      say('');
      const event = new CustomEvent('ha-search', {cancelable: true, detail: {bbl: item.bbl, label: item.label}});
      if (form.dispatchEvent(event)) window.location.assign('/building?bbl=' + encodeURIComponent(item.bbl));
    }
    function submitQuery() {
      const q = input.value.trim();
      close();
      if (!q) { say('Type a street address or a 10-digit BBL.'); return; }
      const event = new CustomEvent('ha-search-query', {cancelable: true, detail: {q}});
      if (!form.dispatchEvent(event)) return;
      window.location.assign(/^[1-5]\d{9}$/.test(q)
        ? '/building?bbl=' + encodeURIComponent(q)
        : '/building?q=' + encodeURIComponent(q));
    }
    async function suggest() {
      const q = input.value.trim();
      if (q.length < MIN_CHARS || /^\d{10}$/.test(q)) { close(); say(''); return; }
      if (abort) abort.abort();
      abort = new AbortController();
      const seq = ++searchSeq;
      let features;
      try {
        const r = await fetch(GEOSEARCH + '?text=' + encodeURIComponent(q), {signal: abort.signal});
        if (!r.ok) throw new Error();
        features = (await r.json()).features || [];
      } catch (error) {
        if (error && error.name === 'AbortError') return;
        if (seq !== searchSeq) return;
        close();
        say('Suggestions are unavailable right now — press Enter to search, or type the 10-digit BBL.');
        return;
      }
      if (seq !== searchSeq) return;
      const seen = new Set();
      items = [];
      for (const f of features) {
        const p = f && f.properties || {};
        const bbl = String(((p.addendum || {}).pad || {}).bbl || '');
        if (!/^[1-5]\d{9}$/.test(bbl) || seen.has(bbl)) continue;
        seen.add(bbl);
        const label = String(p.label || p.name || '').replace(/, USA$/, '');
        items.push({bbl, label, name: p.name || label,
                    locality: [p.borough, p.postalcode].filter(Boolean).join(' ')});
        if (items.length >= MAX_ITEMS) break;
      }
      active = -1;
      say(items.length ? '' : 'No NYC address matches yet — keep typing, or press Enter to search.');
      render();
    }

    input.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(suggest, DEBOUNCE_MS);
    });
    input.addEventListener('keydown', event => {
      if (event.key === 'ArrowDown' && items.length) {
        event.preventDefault(); active = (active + 1) % items.length; mark();
      } else if (event.key === 'ArrowUp' && items.length) {
        event.preventDefault(); active = (active - 1 + items.length) % items.length; mark();
      } else if (event.key === 'Enter' && active >= 0 && items[active]) {
        event.preventDefault(); select(items[active]);
      } else if (event.key === 'Escape') {
        close();
      }
    });
    input.addEventListener('blur', () => setTimeout(close, 120));
    form.addEventListener('submit', event => { event.preventDefault(); submitQuery(); });
  }

  function init() { document.querySelectorAll('form[data-ha-search]').forEach(attach); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
