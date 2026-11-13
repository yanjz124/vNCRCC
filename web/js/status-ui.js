// NAS-status-style UI layer: masthead clocks, live notice strip, view switch
// (List / Tile / Map), intrusion tiles, Zulu toggle and the mobile menu.
//
// This is the first piece of app.js being split into ES modules. It does not
// touch app.js internals: it listens for the `vncrcc:data` event app.js
// dispatches after every refresh. Strings in that payload are already
// HTML-escaped at the JSON boundary, so they can go into innerHTML as-is.

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode etc. */ } },
};

// ---------------------------------------------------------------- time -----
let zulu = store.get('vncrcc.zulu', '1') === '1';
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const pad = (n) => String(n).padStart(2, '0');

function fmtDateTime(ms) {
  if (!ms || !isFinite(ms)) return '—';
  const d = new Date(ms);
  if (zulu) {
    return `${MONTHS[d.getUTCMonth()]} ${pad(d.getUTCDate())}, ${d.getUTCFullYear()} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}Z`;
  }
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit', timeZoneName: 'short' });
}

function fmtShort(ms) {
  if (!ms || !isFinite(ms)) return '—';
  const d = new Date(ms);
  if (zulu) return `${pad(d.getUTCDate())}/${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}Z`;
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' });
}

function ago(ms) {
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 90) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

function parseVatsimTs(v) {
  if (!v) return 0;
  const s = String(v);
  if (/^\d{14}$/.test(s)) {
    return Date.parse(`${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T${s.slice(8, 10)}:${s.slice(10, 12)}:${s.slice(12, 14)}Z`);
  }
  const t = Date.parse(s);
  return isNaN(t) ? 0 : t;
}

function tickClocks() {
  const updatedMs = parseVatsimTs(window.vatsimUpdateTimestamp);
  const upd = $('#hdr-updated');
  const cur = $('#hdr-current');
  if (upd) {
    upd.querySelector('span').textContent = updatedMs ? fmtDateTime(updatedMs) : 'connecting…';
    const age = updatedMs ? Date.now() - updatedMs : 0;
    upd.dataset.state = !updatedMs ? 'offline' : age > 120000 ? 'stale' : age > 60000 ? 'lagging' : 'live';
  }
  if (cur) cur.querySelector('span').textContent = fmtDateTime(Date.now());
}

function initZulu() {
  const btn = $('#zulu-toggle');
  const sync = () => {
    btn.setAttribute('aria-pressed', String(zulu));
    $('#zulu-label').textContent = zulu ? 'Zulu' : 'Local';
  };
  btn.addEventListener('click', () => {
    zulu = !zulu;
    store.set('vncrcc.zulu', zulu ? '1' : '0');
    sync();
    tickClocks();
    if (lastData) render(lastData);
  });
  sync();
}

// ---------------------------------------------------------------- theme ----
// Preference cycles Auto (follow OS) -> Light -> Dark. The inline <head>
// script applied it before first paint; app.js listens for `vncrcc:theme` to
// swap the basemap.
const THEMES = ['auto', 'light', 'dark'];
const darkMq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

function applyTheme(pref) {
  const root = document.documentElement;
  const resolved = pref === 'dark' || (pref === 'auto' && darkMq?.matches) ? 'dark' : 'light';
  const changed = root.dataset.resolvedTheme !== resolved;
  root.dataset.theme = pref;
  root.dataset.resolvedTheme = resolved;
  $('#theme-label').textContent = pref === 'auto' ? 'Auto' : pref === 'dark' ? 'Dark' : 'Light';
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = resolved === 'dark' ? '#0a2a52' : '#0b3d78';
  if (changed) window.dispatchEvent(new Event('vncrcc:theme'));
}

function initTheme() {
  let pref = store.get('vncrcc.theme', 'auto');
  if (!THEMES.includes(pref)) pref = 'auto';
  applyTheme(pref);
  $('#theme-toggle').addEventListener('click', () => {
    pref = THEMES[(THEMES.indexOf(pref) + 1) % THEMES.length];
    store.set('vncrcc.theme', pref);
    applyTheme(pref);
  });
  darkMq?.addEventListener?.('change', () => { if (pref === 'auto') applyTheme('auto'); });
}

// ---------------------------------------------------------------- views ----
const VIEWS = ['list', 'tile', 'map'];

function setView(view, { persist = true } = {}) {
  if (!VIEWS.includes(view)) view = 'tile';
  document.body.dataset.view = view;
  $$('.view-switch button').forEach((b) => {
    const on = b.dataset.view === view;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', String(on));
  });
  if (persist) store.set('vncrcc.view', view);
  // Map sizes change between views; app.js re-fits Leaflet on resize.
  requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
}

function initViews() {
  $$('.view-switch button').forEach((b) => b.addEventListener('click', () => setView(b.dataset.view)));
  setView(store.get('vncrcc.view', 'tile'), { persist: false });
}

// ---------------------------------------------------------------- nav ------
function initNav() {
  const toggle = $('#nav-toggle');
  const nav = $('#site-nav');
  toggle.addEventListener('click', () => {
    const open = nav.classList.toggle('open');
    toggle.setAttribute('aria-expanded', String(open));
  });
  $$('#site-nav a').forEach((a) => a.addEventListener('click', () => {
    nav.classList.remove('open');
    toggle.setAttribute('aria-expanded', 'false');
    // Sections hidden in the current view would be unreachable; switch to List.
    const target = document.querySelector(a.getAttribute('href'));
    if (target && target.offsetParent === null) setView('list');
  }));
}

// ---------------------------------------------------------------- tiles ----
const fp = (x) => x?.flight_plan || {};
const acType = (x) => fp(x).aircraft_faa || fp(x).aircraft_short || '';
const route = (x) => {
  const dep = fp(x).departure || '';
  const arr = fp(x).arrival || '';
  return dep || arr ? `${dep || '—'} → ${arr || '—'}` : '';
};
const isVso = (x) => (typeof window.vncrccIsVso === 'function' ? window.vncrccIsVso(x) : false);
const vsoTag = (x) => (isVso(x) ? ' <span class="vso-tag">VSOA</span>' : '');
const zoneLabel = (x) => ((x.zones && x.zones.length) ? x.zones.join(', ') : 'P-56');

function eventTile(evt) {
  const recMs = Number(evt.recorded_at) * 1000;
  const exitMs = Number(evt.exit_confirmed_at) * 1000;
  const dur = exitMs && recMs && exitMs > recMs ? Math.max(1, Math.round((exitMs - recMs) / 60000)) : null;
  const key = `${evt.cid ?? ''}:${evt.recorded_at ?? ''}`;
  const meta = [acType(evt), route(evt)].filter(Boolean).join(' · ');
  return `
    <article class="tile">
      <header class="tile-head">
        <h3 class="tile-ident">${evt.callsign || 'UNKNOWN'}${vsoTag(evt)}</h3>
        ${evt.track_points || evt.pre_positions ? `<button class="tile-link" data-event-key="${key}">${expanded.has(key) ? 'Hide Track' : 'View Track'}</button>` : ''}
      </header>
      <div class="tile-row">
        <span class="tile-label">${zoneLabel(evt)} Entry</span>
        <span class="tile-time" title="${ago(recMs)}">${fmtShort(recMs)}${dur ? ` &middot; ${dur} min` : ''}</span>
      </div>
      ${meta ? `<p class="tile-body">${meta}</p>` : ''}
    </article>`;
}

function activeTile(ci) {
  const alt = Math.round(Number(ci.altitude) || 0);
  const gs = Math.round(Number(ci.groundspeed) || 0);
  const meta = [acType(ci), route(ci)].filter(Boolean).join(' · ');
  return `
    <article class="tile tile-active">
      <header class="tile-head">
        <h3 class="tile-ident">${ci.callsign || 'UNKNOWN'}${vsoTag(ci)}</h3>
        <button class="tile-link" data-active-cid="${ci.cid ?? ''}">${expanded.has(`p56-current:${ci.cid}`) ? 'Hide Path' : 'Show Path'}</button>
      </header>
      <div class="tile-row">
        <span class="tile-label">${zoneLabel(ci)} &mdash; Inside Now</span>
        <span class="tile-time">${alt.toLocaleString()} ft &middot; ${gs} kt</span>
      </div>
      ${meta ? `<p class="tile-body">${meta}</p>` : ''}
    </article>`;
}

let logLimit = 12;
let lastData = null;
let expanded = new Set();
// app.js persists which rows are expanded (and so which tracks are drawn).
function loadExpanded() {
  try { expanded = new Set(JSON.parse(localStorage.getItem('vncrcc.expandedFP') || '[]')); } catch { expanded = new Set(); }
}

function fillTiles(container, html) {
  container.innerHTML = html || `<p class="tiles-empty">${container.dataset.empty || 'Nothing to show.'}</p>`;
}

function renderNotice(d) {
  const notice = $('#notice');
  const text = $('#notice-text');
  const active = d.currentInside || [];
  if (active.length) {
    notice.classList.add('notice-alert');
    const names = active.slice(0, 3).map((c) => `<strong>${c.callsign || 'UNKNOWN'}</strong>`).join(', ');
    text.innerHTML = `ACTIVE P-56 ENTR${active.length > 1 ? 'IES' : 'Y'}: ${names}${active.length > 3 ? ` +${active.length - 3} more` : ''}`;
    return;
  }
  notice.classList.remove('notice-alert');
  const last = (d.events || []).reduce((a, e) => (Number(e.recorded_at) > Number(a?.recorded_at || 0) ? e : a), null);
  const traffic = `${d.sfraCount} in SFRA &middot; ${d.frzCount} in FRZ`;
  text.innerHTML = last
    ? `No active P-56 entries &middot; ${traffic} &middot; last entry <strong>${last.callsign || 'UNKNOWN'}</strong> ${ago(Number(last.recorded_at) * 1000)}`
    : `No active P-56 entries &middot; ${traffic}`;
}

function render(d) {
  lastData = d;
  loadExpanded();
  renderNotice(d);
  fillTiles($('#active-tiles'), (d.currentInside || []).map(activeTile).join(''));
  const events = (d.events || []).slice().sort((a, b) => Number(b.recorded_at || 0) - Number(a.recorded_at || 0));
  fillTiles($('#log-tiles'), events.slice(0, logLimit).map(eventTile).join(''));
  const more = $('#log-more');
  more.hidden = events.length <= logLimit;
  more.textContent = `Show more (${events.length - logLimit} older)`;
}

function initTiles() {
  $('#log-more').addEventListener('click', () => {
    logLimit += 24;
    if (lastData) render(lastData);
  });
  // Delegate to the existing table rows so expand/track logic stays in one place.
  document.addEventListener('click', (ev) => {
    const btn = ev.target.closest('.tile-link');
    if (!btn) return;
    let row = null;
    if (btn.dataset.eventKey) row = document.querySelector(`#p56-events-tbody tr[data-fp-key="${CSS.escape(btn.dataset.eventKey)}"]`);
    if (btn.dataset.activeCid) row = document.querySelector(`#p56-tbody tr[data-fp-key="${CSS.escape('p56-current:' + btn.dataset.activeCid)}"]`);
    if (!row) return;
    row.click();
    const open = row.nextElementSibling?.classList.contains('show');
    btn.textContent = btn.dataset.eventKey ? (open ? 'Hide Track' : 'View Track') : (open ? 'Hide Path' : 'Show Path');
    if (open) $('#maps-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

// ---------------------------------------------------------------- boot -----
initTheme();
initZulu();
initViews();
initNav();
initTiles();
tickClocks();
setInterval(tickClocks, 1000);
window.addEventListener('vncrcc:data', (e) => render(e.detail));
if (window.__vncrccLastData) render(window.__vncrccLastData);
