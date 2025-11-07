// Simple dashboard app that queries the API endpoints and renders lists + map.
(function(){
  const API_ROOT = window.location.origin + '/api/v1';
  const DCA = [38.8514403, -77.0377214];
  const DEFAULT_RANGE_NM = 100;
  const REFRESH = 15000;

  const el = id => document.getElementById(id);
  const params = new URLSearchParams(window.location.search);
  // The plane PNG default orientation points straight up (north). If you need to tweak
  // how the nose aligns with `heading`, adjust this offset. Positive rotates clockwise.
  const PLANE_ROTATION_OFFSET = 0; // degrees

  // affiliation defaults
  const DEFAULT_AFF = ["vusaf","vuscg","usnv"];

  // initialize inputs from URL
  el('vso-range').value = params.get('vso_range') || DEFAULT_RANGE_NM;
  // load any provided vso_aff as comma-separated and add as checkboxes
  const providedAff = (params.get('vso_aff') || '').split(',').map(s=>s.trim()).filter(Boolean);

  // map setup - dark tiles
  // create maps without default zoom control (remove zoom +/- control)
  const p56Map = L.map('p56-map', { zoomControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false, boxZoom: false, keyboard: false });
  // SFRA map: zoom ~9 shows a bit wider view (slightly zoomed out from 40nm)
  const sfraMap = L.map('sfra-map', { zoomControl: false }).setView(DCA, 9);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',{maxZoom:19,attribution:''}).addTo(p56Map);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',{maxZoom:19,attribution:''}).addTo(sfraMap);

  // layers - create separate overlay objects for each map since Leaflet doesn't allow sharing
  const overlays = {
    p56: { sfra: null, frz: null, p56: null },
    sfra: { sfra: null, frz: null, p56: null }
  };
  // Per-category marker groups so we can toggle colored aircraft from the legend.
  const categories = ['frz','p56','sfra','ground','air'];
  const p56MarkerGroups = {};
  const sfraMarkerGroups = {};
  categories.forEach(cat => {
    p56MarkerGroups[cat] = L.layerGroup();
    sfraMarkerGroups[cat] = L.layerGroup();
    p56Map.addLayer(p56MarkerGroups[cat]);
    sfraMap.addLayer(sfraMarkerGroups[cat]);
  });
  const p56PathLayer = L.layerGroup();
  const sfraPathLayer = L.layerGroup();
  p56Map.addLayer(p56PathLayer);
  sfraMap.addLayer(sfraPathLayer);

  // icon sizing
  const ICON_SIZE = 32; // px, slightly larger than before

  // caches
  const elevCache = {};

  // sort configuration per table body id: { key: function(item) -> value, order: 'asc'|'desc' }
  const sortConfig = {};
  // Expanded flight-plan persistence (store set of keys in localStorage)
  const EXPANDED_STORAGE_KEY = 'vncrcc.expandedFP';
  function loadExpandedSet(){ try{ const v = JSON.parse(localStorage.getItem(EXPANDED_STORAGE_KEY) || '[]'); return new Set(Array.isArray(v)?v:[]); }catch(e){return new Set()} }
  function saveExpandedSet(s){ try{ localStorage.setItem(EXPANDED_STORAGE_KEY, JSON.stringify(Array.from(s))); }catch(e){} }
  let expandedSet = loadExpandedSet();

  function renderList(listId, items, itemFn){
    const list = el(listId);
    if(!list) return;
    list.innerHTML = '';
    items.forEach(item => {
      const li = document.createElement('li');
      li.innerHTML = itemFn(item);
      list.appendChild(li);
    });
  }



  function setPermalink(){
    const r = el('vso-range').value;
    // build affiliations list from checked boxes and extras
    const checks = Array.from(document.querySelectorAll('.aff-check:checked')).map(i=>i.value);
    const extras = (el('custom-aff').dataset.added || '').split(',').map(s=>s.trim()).filter(Boolean);
    const affs = [...checks, ...extras];
    const p = new URL(window.location.href);
    p.searchParams.set('vso_range', r);
    if(affs.length) p.searchParams.set('vso_aff', affs.join(',')); else p.searchParams.delete('vso_aff');
    el('permalink').href = p.toString();
  }

  // Format epoch seconds in Zulu (UTC). If includeDate is true returns YYYY-MM-DD HHMMz, else HHMMz
  function formatZuluEpoch(sec, includeDate=true){
    if(!sec) return '-';
    try{
      const d = new Date(sec * 1000);
      const Y = d.getUTCFullYear();
      const M = String(d.getUTCMonth()+1).padStart(2,'0');
      const D = String(d.getUTCDate()).padStart(2,'0');
      const H = String(d.getUTCHours()).padStart(2,'0');
      const m = String(d.getUTCMinutes()).padStart(2,'0');
      const time = `${H}${m}z`;
      return includeDate ? `${Y}-${M}-${D} ${time}` : time;
    }catch(e){ return '-'; }
  }

  function haversineNm(lat1, lon1, lat2, lon2){
    const R = 6371.0; // km
    const toRad = d => d * Math.PI/180;
    const dlat = toRad(lat2-lat1);
    const dlon = toRad(lon2-lon1);
    const a = Math.sin(dlat/2)*Math.sin(dlat/2) + Math.cos(toRad(lat1))*Math.cos(toRad(lat2))*Math.sin(dlon/2)*Math.sin(dlon/2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(Math.max(0,1-a)));
    const km = R * c;
    return km / 1.852;
  }

  function computeDca(lat, lon){
    // compute bearing and distance similar to server-side _dca_radial_range
    const toRad = d => d * Math.PI/180;
    const toDeg = r => r * 180/Math.PI;
    const lat1 = toRad(DCA[0]);
    const lon1 = toRad(DCA[1]);
    const lat2 = toRad(lat);
    const lon2 = toRad(lon);
    const dlon = lon2 - lon1;
    const x = Math.sin(dlon) * Math.cos(lat2);
    const y = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dlon);
    let brng = toDeg(Math.atan2(x,y));
    brng = (brng + 360) % 360;
    const brng_i = Math.round(brng) % 360;
    const dist_nm = haversineNm(DCA[0], DCA[1], lat, lon);
    const dist_i = Math.round(dist_nm);
    const compact = `DCA${String(brng_i).padStart(3,'0')}${String(dist_i).padStart(3,'0')}`;
    return {radial_range: compact, bearing: brng_i, range_nm: dist_i};
  }

  async function loadGeo(name){
    try{
      const res = await fetch(`${API_ROOT}/geo/?name=${encodeURIComponent(name)}`);
      if(!res.ok) return null;
      return await res.json();
    }catch(e){return null}
  }

  async function loadOverlays(){
    const sfra = await loadGeo('sfra');
    const frz = await loadGeo('frz');
    const p56 = await loadGeo('p56');

    if(sfra){
      // Create separate instances for each map
      overlays.p56.sfra = L.geoJSON(sfra, {style:{color:'#0275d8',weight:2,fillOpacity:0.05}});
      overlays.sfra.sfra = L.geoJSON(sfra, {style:{color:'#0275d8',weight:2,fillOpacity:0.05}});
      if(el('toggle-sfra').checked) { 
        overlays.sfra.sfra.addTo(sfraMap); 
      }
    }
    if(frz){
      overlays.p56.frz = L.geoJSON(frz, {style:{color:'#d9534f',weight:2,fillOpacity:0.05}});
      overlays.sfra.frz = L.geoJSON(frz, {style:{color:'#d9534f',weight:2,fillOpacity:0.05}});
      if(el('toggle-frz').checked) { 
        overlays.p56.frz.addTo(p56Map); 
        overlays.sfra.frz.addTo(sfraMap); 
      }
    }
    if(p56){
      overlays.p56.p56 = L.geoJSON(p56, {style:{color:'#f0ad4e',weight:2,fillOpacity:0.05}});
      overlays.sfra.p56 = L.geoJSON(p56, {style:{color:'#f0ad4e',weight:2,fillOpacity:0.05}});
      if(el('toggle-p56').checked) { 
        overlays.p56.p56.addTo(p56Map); 
        overlays.sfra.p56.addTo(sfraMap); 
      }
      // Fit P56 map to P56 bounds
      p56Map.fitBounds(L.geoJSON(p56).getBounds());
      // Invalidate size after a short delay so Leaflet properly lays out tiles
      setTimeout(()=>{ try{ p56Map.invalidateSize(); }catch(e){} }, 200);
    }
  }

  function pointInLayer(lat, lon, layer){
    if(!layer) return false;
    const pt = turf.point([lon, lat]);
    const features = layer.toGeoJSON().features || [];
    for(const f of features){
      try{
        if(turf.booleanPointInPolygon(pt, f)) return true;
      }catch(e){continue}
    }
    return false;
  }

  // plane PNG caching + recolor-on-canvas
  let planePngImage = null;
  const planePngCache = {}; // color -> L.icon

  function loadPlanePng(){
    if(planePngImage) return Promise.resolve(planePngImage);
    return new Promise((resolve, reject)=>{
      const img = new Image();
      img.crossOrigin = 'Anonymous';
      img.onload = ()=>{ planePngImage = img; resolve(img); };
      img.onerror = (e)=>{ reject(e); };
      img.src = '/web/static/plane_icon.png?v=1';
    });
  }

  function tintImageToDataUrl(img, color, size){
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    // draw source image scaled to requested size
    ctx.drawImage(img, 0, 0, size, size);
    // tint: keep alpha, replace color by using source-in composite
    ctx.globalCompositeOperation = 'source-in';
    ctx.fillStyle = color;
    ctx.fillRect(0,0,size,size);
    return canvas.toDataURL('image/png');
  }

  async function createPlaneIcon(color, heading){
    const size = ICON_SIZE;
    try{
      // ensure source image loaded and a recolored dataUrl exists for this color
      if(!planePngCache[color]){
        const img = await loadPlanePng();
        const dataUrl = tintImageToDataUrl(img, color, size);
        planePngCache[color] = dataUrl;
      }
      const dataUrl = planePngCache[color];
      // compute rotation (0 = north/up); add offset if needed
      const rot = ((Number(heading) || 0) + PLANE_ROTATION_OFFSET) % 360;
      const html = `<div style="width:${size}px;height:${size}px;display:flex;align-items:center;justify-content:center;transform-origin:center;"><img src="${dataUrl}" style="width:${size}px;height:${size}px;transform:rotate(${rot}deg);display:block;"/></div>`;
      return L.divIcon({ className: 'plane-divicon', html: html, iconSize: [size,size], iconAnchor: [Math.round(size/2),Math.round(size/2)], popupAnchor: [0,-Math.round(size/2)] });
    }catch(e){
      // fallback to static PNG icon (no rotation)
      return L.icon({ iconUrl: '/web/static/plane_icon.png?v=1', iconSize:[size,size], iconAnchor:[Math.round(size/2),Math.round(size/2)], popupAnchor:[0,-Math.round(size/2)] });
    }
  }

  async function fetchAllAircraft(){
    const res = await fetch(`${API_ROOT}/aircraft/list`);
    if(!res.ok) return [];
    const j = await res.json();
    return j.aircraft || [];
  }

  async function maybeElevation(lat, lon){
    const key = `${lat.toFixed(4)}:${lon.toFixed(4)}`;
    if(elevCache[key]) return elevCache[key];
    try{
      const res = await fetch(`${API_ROOT}/elevation/?lat=${lat}&lon=${lon}`);
      if(!res.ok) return null;
      const j = await res.json();
      elevCache[key] = j.elevation_m;
      return j.elevation_m;
    }catch(e){return null}
  }

  function classifyAircraft(ac, lat, lon, layers){
    // priority: FRZ > P56 > SFRA - use p56 map overlays for classification
    if(pointInLayer(lat, lon, overlays.p56.frz)) return 'frz';
    if(pointInLayer(lat, lon, overlays.p56.p56)) return 'p56';
    if(pointInLayer(lat, lon, overlays.p56.sfra)) return 'sfra';
    return 'air';
  }

  async function refresh(){
    try{
    setPermalink();
    // track keys present in this refresh so we can prune persisted expanded keys
    const presentKeys = new Set();
    // load overlays if not yet
    if(!overlays.p56.sfra && !overlays.p56.frz && !overlays.p56.p56) await loadOverlays();

    // fetch aircraft
    const aircraft = await fetchAllAircraft();
    console.log('Fetched aircraft count:', aircraft.length);
    const range_nm = parseInt(el('vso-range').value || DEFAULT_RANGE_NM, 10);
    console.log('VSO range setting:', range_nm, 'nm from DCA');
    const filtered = aircraft.filter(a=>{
      const lat = a.latitude || a.lat || a.y;
      const lon = a.longitude || a.lon || a.x;
      if(lat==null||lon==null) return false;
      const nm = haversineNm(DCA[0], DCA[1], lat, lon);
      return nm <= range_nm;
    });
    console.log('Filtered aircraft count:', filtered.length);

    // Precompute on-ground detection for suspicious aircraft this refresh.
    // This ensures the 'On Ground' logic runs every time data is pulled when
    // an aircraft meets the suspicion trigger (low GS or low alt + low GS).
    // TEMPORARILY DISABLED - elevation lookups are blocking rendering
    /*
    try{
      await Promise.all(filtered.map(async ac => {
        try{
          const lat = ac.latitude || ac.lat || ac.y;
          const lon = ac.longitude || ac.lon || ac.x;
          const gs = Number(ac.groundspeed || ac.gs || 0);
          const alt = Number(ac.altitude || ac.alt || 0);
          let onGround = false;
          // suspicion trigger: either very low groundspeed OR moderately low GS with low altitude
          if((gs <= 5) || (gs < 100 && alt < 1000)){
            const elev_m = await maybeElevation(lat, lon);
            if(elev_m != null){
              const elev_ft = elev_m * 3.28084;
              const agl = alt - elev_ft;
              if(agl <= 5 || gs <= 5) onGround = true; // +5ft tolerance as requested
            }else{
              // fallback: if elevation lookup failed, rely on very low GS
              if(gs <= 5) onGround = true;
            }
          }
          ac._onGround = onGround;
        }catch(e){ ac._onGround = false; }
      }));
    }catch(e){ }
    */
    // Simple on-ground heuristic without elevation lookup
    filtered.forEach(ac => {
      const gs = Number(ac.groundspeed || ac.gs || 0);
      const alt = Number(ac.altitude || ac.alt || 0);
      // Mark as on ground if very low GS or very low altitude + low GS
      ac._onGround = (gs <= 5) || (gs < 50 && alt < 500);
    });
    console.log('On-ground detection complete (simple heuristic)');

  // Instead of calling SFRA/FRZ endpoints for counts/lists, compute them from
  // the same client-side overlays used to render the map so the UI and map
  // always match. We still fetch P56 history for the details panel but the
  // count/listing will be driven by client-side classification below.
    console.log('Fetching P56 history for details...');
    const p56json = await fetch(`${API_ROOT}/p56/`).then(r=>r.ok?r.json():{breaches:[],history:{}});

  // keep a local copy of the latest aircraft snapshot for lookups
  const latest_ac = aircraft || [];

    // prepare empty lists which will be populated while creating markers
    el('sfra-count').textContent = '0';
    el('frz-count').textContent = '0';
    el('p56-count').textContent = '0';
    const sfraList = [];
    const frzList = [];
    const p56List = [];
    const groundList = [];
    const airList = [];
    console.log('Prepared client-side lists for classification (will populate during render)');

  const renderTable = (tbodyId, items, rowFn, keyFn, fpOptions) => {
      console.log('Rendering table', tbodyId, 'with', items.length, 'items');
      const tbody = el(tbodyId);
      tbody.innerHTML = '';
      // compute colspan dynamically from the table header so different tables
      // that have different column counts (e.g. P56 with no Status) automatically
      // produce the correct flight-plan expansion width.
      const table = tbody.closest('table');
      let colspan = 1;
      try{ colspan = table.querySelectorAll('thead th').length }catch(e){}
      // Apply sorting if configured for this table
      try{
        const conf = sortConfig[tbodyId];
        if(conf && typeof conf.key === 'function'){
          console.log('Applying sort to', tbodyId, '- column:', conf.key._col, 'order:', conf.order);
          items = items.slice(); // copy
          items.sort((a,b)=>{
            const va = conf.key(a);
            const vb = conf.key(b);
            if(va==null && vb==null) return 0;
            if(va==null) return conf.order==='asc'? -1: 1;
            if(vb==null) return conf.order==='asc'? 1: -1;
            if(typeof va === 'number' && typeof vb === 'number') return conf.order==='asc'? va-vb : vb-va;
            const sa = String(va).toLowerCase();
            const sb = String(vb).toLowerCase();
            if(sa < sb) return conf.order==='asc'? -1: 1;
            if(sa > sb) return conf.order==='asc'? 1: -1;
            return 0;
          });
          console.log('Sorted', tbodyId, '- first item:', items[0]?.callsign || items[0]?.cid || '?');
        }
      }catch(e){console.error('Sort error for', tbodyId, e)}
      items.forEach(item => {
        const tr = document.createElement('tr');
        tr.className = 'expandable';
        tr.innerHTML = rowFn(item);
  const fpDiv = document.createElement('tr');
  fpDiv.className = 'flight-plan';
  fpDiv.innerHTML = `<td class="flight-plan-cell" colspan="${colspan}">${formatFlightPlan(item, fpOptions)}</td>`;
        // compute optional key for persistence
        let key = null;
        try{ if(typeof keyFn === 'function') key = keyFn(item); }catch(e){}
  if(key){ tr.dataset.fpKey = key; fpDiv.dataset.fpKey = key; presentKeys.add(key); }
  // if this key is in expandedSet, show it initially
  if(key && expandedSet.has(key)) fpDiv.classList.add('show');
        tr.addEventListener('click', () => {
          const opening = !fpDiv.classList.contains('show');
          fpDiv.classList.toggle('show');
          if(key){ if(opening) { expandedSet.add(key); saveExpandedSet(expandedSet); } else { expandedSet.delete(key); saveExpandedSet(expandedSet); } }
        });
        tbody.appendChild(tr);
        tbody.appendChild(fpDiv);
      });

      // after rendering tables and events we'll prune expandedSet entries not present
    };

    const formatFlightPlan = (item, opts) => {
      const ac = item.aircraft || item;
      const fp = ac.flight_plan || {};
      
      // Extract all fields
      const aid = ac.callsign || '—';
      const cid = ac.cid || '—';
      const bcn = ac.transponder || '—';
      const typ = fp.aircraft_faa || fp.aircraft_short || '—';
  const eq = fp.equipment || '—';
      const dep = fp.departure || '—';
      const dest = fp.arrival || '—';
      const spd = fp.cruise_tas || '—';
      const alt = fp.altitude || ac.altitude || '—';
      const route = fp.route || '—';
      const remarks = fp.remarks || '';

      // Compact full-width layout: all main fields in 1-2 lines, then RTE and RMK full-width
      let html = '<div class="fp-compact">';
      
      // Row 1: All main fields (AID, CID, BCN, TYP, EQ, DEP, DEST, SPD, ALT) - will wrap to 2 lines if needed
      html += `<div class="fp-row-inline">`;
      html += `<span class="fp-inline-field"><span class="fp-lbl">AID</span> ${aid}</span>`;
      html += `<span class="fp-inline-field"><span class="fp-lbl">CID</span> ${cid}</span>`;
      html += `<span class="fp-inline-field"><span class="fp-lbl">BCN</span> ${bcn}</span>`;
      html += `<span class="fp-inline-field"><span class="fp-lbl">TYP</span> ${typ}</span>`;
      if(!(opts && opts.hideEquipment)){
        html += `<span class="fp-inline-field"><span class="fp-lbl">EQ</span> ${eq}</span>`;
      }
      html += `<span class="fp-inline-field"><span class="fp-lbl">DEP</span> ${dep}</span>`;
      html += `<span class="fp-inline-field"><span class="fp-lbl">DEST</span> ${dest}</span>`;
      html += `<span class="fp-inline-field"><span class="fp-lbl">SPD</span> ${spd}</span>`;
      html += `<span class="fp-inline-field"><span class="fp-lbl">ALT</span> ${alt}</span>`;
      html += `</div>`;
      
      // Row 2: RTE (full width)
      html += `<div class="fp-row-inline">`;
      html += `<span class="fp-inline-field fp-route-field"><span class="fp-lbl">RTE</span> ${route}</span>`;
      html += `</div>`;
      
      // Row 3: RMK (full width)
      if (remarks) {
        html += `<div class="fp-row-inline">`;
        html += `<div class="fp-remarks-box"><div class="fp-lbl">RMK</div><div class="fp-rmk-text">${remarks}</div></div>`;
        html += `</div>`;
      }

      html += `</div>`;
      return html;
    };

    // Render tables

    // P56 current inside
    const currentInside = Object.keys(p56json.history?.current_inside || {}).filter(cid => p56json.history.current_inside[cid].inside).map(cid => {
      const ci = p56json.history.current_inside[cid];
      const ac = latest_ac.find(a => String(a.cid) === cid) || {};
      return { ...ci, ...ac };
    });
    // helper: friendly label for status and swatch class
    const statusLabel = s => ({ p56: 'P-56', frz: 'FRZ', sfra: 'SFRA', ground: 'On Ground', air: 'Airborne' }[s] || s.toUpperCase());
    const swatchClass = s => `status-swatch-${s}`;

  // default sort for P56 current is callsign ascending
  if(!sortConfig['p56-tbody']) {
    sortConfig['p56-tbody'] = { key: (it)=> (it.callsign||'').toLowerCase(), order: 'asc' };
    sortConfig['p56-tbody'].key._col = 'callsign';
  }
  renderTable('p56-tbody', currentInside, ci => {
      const lat = ci.latitude || ci.last_position?.lat;
      const lon = ci.longitude || ci.last_position?.lon;
      const dca = computeDca(lat, lon);
      const dep = (ci.flight_plan && (ci.flight_plan.departure || ci.flight_plan.depart)) || '';
      const arr = (ci.flight_plan && (ci.flight_plan.arrival || ci.flight_plan.arr)) || '';
      const acType = (ci.flight_plan && ci.flight_plan.aircraft_faa) || (ci.flight_plan && ci.flight_plan.aircraft_short) || '';
      const squawk = ci.transponder || '';
      let squawkClass = '';
      if (squawk === '1200') squawkClass = 'squawk-1200';
      else if (['7500', '7600', '7700'].includes(squawk)) squawkClass = 'squawk-emergency';
      else if (squawk === '7777') squawkClass = 'squawk-7777';
      else if (['1226', '1205', '1234'].includes(squawk)) squawkClass = 'squawk-vfr';
      const squawkHtml = squawkClass ? `<span class="${squawkClass}">${squawk}</span>` : squawk;
      // P56: per user request we remove the Status column for P56 tables.
      return `<td>${ci.callsign || ''}</td><td>${acType}</td><td>${ci.name || ''}</td><td>${ci.cid || ''}</td><td>${dca.radial_range}</td><td>${Math.round(ci.altitude || 0)}</td><td>${Math.round(ci.groundspeed || 0)}</td><td>${squawkHtml}</td><td>${ci.flight_plan?.assigned_transponder || ''}</td><td>${dep} → ${arr}</td>`;
  }, ci => `p56-current:${ci.cid||ci.callsign||''}`, { hideEquipment: true });

    // P56 events (intrusion log) - default sort: most recent on top
    const events = p56json.history?.events || [];
    if(!sortConfig['p56-events-tbody']) {
      sortConfig['p56-events-tbody'] = { key: (e)=> e.recorded_at || 0, order: 'desc' };
      sortConfig['p56-events-tbody'].key._col = 'date / time';
    }
    const tbodyEvents = el('p56-events-tbody');
    tbodyEvents.innerHTML = '';
    // apply sorting here as we already do for renderTable
    try{
      const conf = sortConfig['p56-events-tbody'];
      if(conf){
        events.sort((a,b)=>{
          const va = conf.key(a); const vb = conf.key(b);
          return conf.order==='asc' ? (va - vb) : (vb - va);
        });
      }
    }catch(e){/* ignore */}
    events.forEach(evt => {
      const tr = document.createElement('tr');
      tr.className = 'expandable';
      // include date + time in Zulu
      const recorded = evt.recorded_at ? formatZuluEpoch(evt.recorded_at, true) : '-';
      const dep = (evt.flight_plan && (evt.flight_plan.departure || evt.flight_plan.depart)) || '';
      const arr = (evt.flight_plan && (evt.flight_plan.arrival || evt.flight_plan.arr)) || '';
      // For P56 event log we no longer display a Status column; render core columns
      tr.innerHTML = `<td>${evt.callsign || ''}</td><td>${(evt.flight_plan && evt.flight_plan.aircraft_faa) || (evt.flight_plan && evt.flight_plan.aircraft_short) || ''}</td><td>${evt.name || ''}</td><td>${evt.cid || ''}</td><td>${recorded}</td><td>${dep}</td><td>${arr}</td>`;
      const fpDiv = document.createElement('tr');
      fpDiv.className = 'flight-plan';
      // colspan will be adjusted by renderTable when used; here we compute from header
        try{
        const evtTable = tbodyEvents.closest('table');
        const ncols = evtTable ? evtTable.querySelectorAll('thead th').length : 7;
        fpDiv.innerHTML = `<td class="flight-plan-cell" colspan="${ncols}">${formatFlightPlan(evt, { hideEquipment: true })}</td>`;
      }catch(e){
        fpDiv.innerHTML = `<td class="flight-plan-cell" colspan="7">${formatFlightPlan(evt, { hideEquipment: true })}</td>`;
      }
      // attach persistence key for this event so expanded state survives refresh
      const evtKey = `${evt.cid||''}:${evt.recorded_at||''}`;
      tr.dataset.fpKey = evtKey;
      fpDiv.dataset.fpKey = evtKey;
  presentKeys.add(evtKey);
      // if it was expanded previously, show it and draw path
      if(expandedSet.has(evtKey)){
        fpDiv.classList.add('show');
        p56PathLayer.clearLayers();
        const positions = (evt.pre_positions || []).concat(evt.post_positions || []);
        if (positions.length > 1) {
          const latlngs = positions.map(p => [p.lat, p.lon]);
          const polyline = L.polyline(latlngs, { color: 'yellow', weight: 3, opacity: 0.8 });
          p56PathLayer.addLayer(polyline);
        }
      }
      tr.addEventListener('click', () => {
        // Toggle flight-plan row
        const opening = !fpDiv.classList.contains('show');
        fpDiv.classList.toggle('show');
        if(opening){
          // Draw path when opening
          p56PathLayer.clearLayers();
          const positions = (evt.pre_positions || []).concat(evt.post_positions || []);
          if (positions.length > 1) {
            const latlngs = positions.map(p => [p.lat, p.lon]);
            const polyline = L.polyline(latlngs, { color: 'yellow', weight: 3, opacity: 0.8 });
            p56PathLayer.addLayer(polyline);
          }
          expandedSet.add(evtKey); saveExpandedSet(expandedSet);
        }else{
          // If collapsing, remove the displayed path
          p56PathLayer.clearLayers();
          expandedSet.delete(evtKey); saveExpandedSet(expandedSet);
        }
      });
      tbodyEvents.appendChild(tr);
      tbodyEvents.appendChild(fpDiv);
    });

    // prune expandedSet entries for keys that are no longer present in any table
    try{
      const toRemove = [];
      expandedSet.forEach(k => { if(!presentKeys.has(k)) toRemove.push(k); });
      if(toRemove.length){ toRemove.forEach(k=>expandedSet.delete(k)); saveExpandedSet(expandedSet); }
    }catch(e){/* ignore pruning errors */}

    // Build a simple leaderboard from intrusion events (count by CID)
    try{
      const lbMap = {};
      events.forEach(evt => {
        const cid = String(evt.cid || (evt.flight_plan && evt.flight_plan.cid) || '');
        if(!cid) return;
        if(!lbMap[cid]) lbMap[cid] = { cid, callsign: evt.callsign || '', name: evt.name || '', count: 0, first: evt.recorded_at || null, last: evt.recorded_at || null };
        lbMap[cid].count += 1;
        const t = evt.recorded_at || null;
        if(t){ if(!lbMap[cid].first || t < lbMap[cid].first) lbMap[cid].first = t; if(!lbMap[cid].last || t > lbMap[cid].last) lbMap[cid].last = t; }
      });
      let lb = Object.values(lbMap).sort((a,b)=>b.count - a.count).slice(0,50);
      // default leaderboard sort: rank ascending (1..n) based on count desc above
      if(!sortConfig['p56-leaderboard-tbody']) {
        const keyFn = function(r, idx){ return idx+1; };
        keyFn._col = 'rank';
        sortConfig['p56-leaderboard-tbody'] = { key: keyFn, order: 'asc' };
      }
      const lbTb = el('p56-leaderboard-tbody');
      if(lbTb){ 
        // apply sorting if user clicked headers: support sorting by cid,callsign,count,first,last
        const conf = sortConfig['p56-leaderboard-tbody'];
        if(conf && conf.key && conf.key._col){
          // comparator based on selected column
          const col = conf.key._col;
          lb = lb.slice();
          lb.sort((A,B)=>{
            let va, vb;
            if(col==='rank'){ va = A._rank; vb = B._rank; }
            else if(col==='cid'){ va = A.cid; vb = B.cid; }
            else if(col==='callsign'){ va = (latest_ac.find(a=>String(a.cid)===String(A.cid))?.callsign) || A.callsign || A.name || '' ; vb = (latest_ac.find(a=>String(a.cid)===String(B.cid))?.callsign) || B.callsign || B.name || '' ; }
            else if(col==='count'){ va = A.count; vb = B.count; }
            else if(col==='first'){ va = A.first || 0; vb = B.first || 0; }
            else if(col==='last'){ va = A.last || 0; vb = B.last || 0; }
            if(typeof va === 'number' && typeof vb === 'number') return conf.order==='asc'? va-vb : vb-va;
            const sa = String(va).toLowerCase(); const sb = String(vb).toLowerCase();
            if(sa < sb) return conf.order==='asc'? -1: 1;
            if(sa > sb) return conf.order==='asc'? 1: -1;
            return 0;
          });
        }
        lbTb.innerHTML = '';
        lb.forEach((r, idx) => {
          // assign rank after sorting (rank = index+1)
          r._rank = idx+1;
          const ac = latest_ac.find(a => String(a.cid) === String(r.cid)) || {};
          const callsign = ac.callsign || r.callsign || r.name || '';
          const first = r.first ? formatZuluEpoch(r.first, true) : '-';
          const last = r.last ? formatZuluEpoch(r.last, true) : '-';
          const tr = document.createElement('tr');
          tr.innerHTML = `<td>${idx+1}</td><td>${r.cid}</td><td>${callsign}</td><td>${r.count}</td><td>${first}</td><td>${last}</td>`;
          lbTb.appendChild(tr);
        });
      }
    }catch(e){ /* ignore leaderboard errors */ }

  // SFRA/FRZ tables rendering will be performed after markers are created so
  // the lists reflect the exact same classification used on the map.

    // markers
  // clear per-category groups
  categories.forEach(cat => { p56MarkerGroups[cat].clearLayers(); sfraMarkerGroups[cat].clearLayers(); });
    console.log('Starting marker creation for', filtered.length, 'aircraft');
    for(const ac of filtered){
      try{
      const lat = ac.latitude || ac.lat || ac.y;
      const lon = ac.longitude || ac.lon || ac.x;
      const heading = ac.heading || 0;
      const groundspeed = Number(ac.groundspeed || ac.gs || 0);
      const altitude = Number(ac.altitude || ac.alt || 0);
      let status = classifyAircraft(ac, lat, lon, overlays);

      // Use precomputed on-ground flag from earlier in this refresh (if set)
      if(ac._onGround) status = 'ground';

      console.log('Processing', ac.callsign, 'status:', status, 'lat:', lat, 'lon:', lon);

      // Colors: FRZ (red), P56 (orange), SFRA (blue), ground (gray), airborne outside SFRA (green)
      const color = status==='frz'? '#d9534f' : status==='p56'? '#f0ad4e' : status==='sfra'? '#0275d8' : status==='ground'? '#6c757d' : '#28a745';
      // create marker/icon defensively so one failure doesn't prevent all markers from showing
      let markerP56, markerSFRA;
      
      try{
        const icon = await createPlaneIcon(color, heading).catch(()=>null);
        if(icon){
          markerP56 = L.marker([lat, lon], {icon: icon});
          markerSFRA = L.marker([lat, lon], {icon: icon});
        }else{
          // fallback to small circle marker
          markerP56 = L.circleMarker([lat, lon], {radius:6, color: color, fillColor: color, fillOpacity:0.8, weight:2});
          markerSFRA = L.circleMarker([lat, lon], {radius:6, color: color, fillColor: color, fillOpacity:0.8, weight:2});
        }
      }catch(err){
        console.error('Marker creation failed for aircraft', ac, err);
        markerP56 = L.circleMarker([lat, lon], {radius:6, color: color, fillColor: color, fillOpacity:0.8, weight:2});
        markerSFRA = L.circleMarker([lat, lon], {radius:6, color: color, fillColor: color, fillOpacity:0.8, weight:2});
      }
  const dca = ac.dca || computeDca(lat, lon);
  const cid = ac.cid || '';
  const dep = (ac.flight_plan && (ac.flight_plan.departure || ac.flight_plan.depart)) || '';
  const arr = (ac.flight_plan && (ac.flight_plan.arrival || ac.flight_plan.arr)) || '';
      // Summary popup: first line = callsign, pilot name, CID. Second line = DCA radial-range,
      // dep → dest, aircraft type. Clicking the aircraft replaces the popup with the full
      // JSON returned by the API for that aircraft.
      const summary = `<div class="ac-summary"><strong>${ac.callsign||''}</strong> — ${ac.name||''} (CID: ${cid})</div>
        <div>${dca.radial_range} — ${dep || '-'} → ${arr || '-'} — ${(ac.flight_plan && ac.flight_plan.aircraft_faa) || (ac.flight_plan && ac.flight_plan.aircraft_short) || ac.type || ac.aircraft_type || '-'}</div>
        <div><em>${status.toUpperCase()}</em> — Squawk: ${ac.transponder || '-'} / ${ac.flight_plan?.assigned_transponder || '-'}</div>`;
      markerP56.bindPopup(summary);
      markerSFRA.bindPopup(summary);

      // show a compact tooltip on hover with first-line summary (callsign, pilot, cid, gs, alt, route)
      try{
        const callsign = ac.callsign || '';
        const pilotName = ac.name || '';
        const cidField = ac.cid || '';
        const gsVal = Math.round(Number(ac.groundspeed || ac.gs || 0));
        const altVal = Math.round(Number(ac.altitude || ac.alt || 0));
        const depField = (ac.flight_plan && (ac.flight_plan.departure || ac.flight_plan.depart)) || '';
        const arrField = (ac.flight_plan && (ac.flight_plan.arrival || ac.flight_plan.arr)) || '';
  // Prefer a human-friendly type/model from multiple possible fields used by
  // different data sources. Prefer `aircraft_faa` then `aircraft_short` when
  // available, then fall back to older fields for broader compatibility.
  const acType = (ac.flight_plan && ac.flight_plan.aircraft_faa) || (ac.flight_plan && ac.flight_plan.aircraft_short) || ac.type || ac.aircraft_type || ac.aircraft || ac.model || ac.aircraft_model || ac.registration || '';
  const line1 = acType ? `<strong>${callsign}</strong> <span class="ac-type">${acType}</span>` : `<strong>${callsign}</strong>`;
  let line2 = '-';
  if(pilotName && cidField) line2 = `${pilotName}, ${cidField}`;
  else if(pilotName) line2 = pilotName;
  else if(cidField) line2 = cidField;
        const line3 = `GS: ${gsVal} kt — ALT: ${altVal} ft — Squawk: ${ac.transponder || '-'} / ${ac.flight_plan?.assigned_transponder || '-'}`;
        const line4 = (depField || arrField) ? `${depField || '-'} → ${arrField || '-'}` : '';
        const tooltipHtml = `<div class="ac-tooltip">` +
                            `<div>${line1}</div>` +
                            `<div>${line2}</div>` +
                            `<div>${line3}</div>` +
                            `<div>${line4}</div>` +
                            `</div>`;
        markerP56.bindTooltip(tooltipHtml, {direction:'top', className:'fp-tooltip', sticky:true});
        markerSFRA.bindTooltip(tooltipHtml, {direction:'top', className:'fp-tooltip', sticky:true});
      }catch(e){/* ignore tooltip errors */}

      // When the marker is clicked, replace the popup content with the full aircraft JSON
      // so users can see the full data from the API.
      markerP56.on('click', ()=>{
        try{
          const full = JSON.stringify(ac, null, 2).replace(/</g, '&lt;');
          const detailHtml = `<div class="ac-full"><pre class="fp">${full}</pre></div>`;
          markerP56.setPopupContent(detailHtml);
          markerP56.openPopup();
        }catch(e){ /* ignore */ }
      });
      markerSFRA.on('click', ()=>{
        try{
          const full = JSON.stringify(ac, null, 2).replace(/</g, '&lt;');
          const detailHtml = `<div class="ac-full"><pre class="fp">${full}</pre></div>`;
          markerSFRA.setPopupContent(detailHtml);
          markerSFRA.openPopup();
        }catch(e){ /* ignore */ }
      });
      // add markers to their category groups
      const grp = p56MarkerGroups[status] || p56MarkerGroups['air'];
      const sgrp = sfraMarkerGroups[status] || sfraMarkerGroups['air'];
      grp.addLayer(markerP56);
      sgrp.addLayer(markerSFRA);
      console.log('Added marker for', ac.callsign, 'to', status, 'group');
      // Populate client-side lists so UI tables/counts match the map classification
      try{
        if(status === 'sfra') sfraList.push(ac);
        else if(status === 'frz') frzList.push(ac);
        else if(status === 'p56') p56List.push(ac);
        else if(status === 'ground') groundList.push(ac);
        else airList.push(ac);
      }catch(e){/* ignore list population errors */}
      }catch(e){
        console.error('Failed to process aircraft', ac.callsign, e);
      }
    }
    console.log('Finished marker creation');

    // Populate counts and render SFRA/FRZ tables from client-side lists so UI
    // exactly matches the map classification.
    try{
      el('sfra-count').textContent = sfraList.length;
      el('frz-count').textContent = frzList.length;
      el('p56-count').textContent = p56List.length;

      // Render SFRA table
      renderTable('sfra-tbody', sfraList, it => {
        const ac = it.aircraft || it;
        const dca = it.dca || computeDca(ac.latitude, ac.longitude);
        const cid = ac.cid || '';
        const dep = (ac.flight_plan && (ac.flight_plan.departure || ac.flight_plan.depart)) || '';
        const arr = (ac.flight_plan && (ac.flight_plan.arrival || ac.flight_plan.arr)) || '';
        const acType = (ac.flight_plan && ac.flight_plan.aircraft_faa) || (ac.flight_plan && ac.flight_plan.aircraft_short) || '';
        const squawk = ac.transponder || '';
        let squawkClass = '';
        if (squawk === '1200') squawkClass = 'squawk-1200';
        else if (['7500', '7600', '7700'].includes(squawk)) squawkClass = 'squawk-emergency';
        else if (squawk === '7777') squawkClass = 'squawk-7777';
        else if (['1226', '1205', '1234'].includes(squawk)) squawkClass = 'squawk-vfr';
        const squawkHtml = squawkClass ? `<span class="${squawkClass}">${squawk}</span>` : squawk;
        let status = classifyAircraft(ac, ac.latitude, ac.longitude, overlays);
        if(ac._onGround) status = 'ground';
        const statusHtmlRow = `<td><span class="status-${status} status-label">${statusLabel(status)}</span></td>`;
        return `<td>${ac.callsign || ''}</td><td>${acType}</td><td>${ac.name || ''}</td><td>${cid}</td><td>${dca.radial_range}</td><td>${Math.round(ac.altitude || 0)}</td><td>${Math.round(ac.groundspeed || 0)}</td><td>${squawkHtml}</td><td>${ac.flight_plan?.assigned_transponder || ''}</td><td>${dep} → ${arr}</td>${statusHtmlRow}`;
      }, it => `sfra:${(it.aircraft||it).cid|| (it.aircraft||it).callsign || ''}`);

      // Render FRZ table
      renderTable('frz-tbody', frzList, it => {
        const ac = it.aircraft || it;
        const dca = it.dca || computeDca(ac.latitude, ac.longitude);
        const cid = ac.cid || '';
        const dep = (ac.flight_plan && (ac.flight_plan.departure || ac.flight_plan.depart)) || '';
        const arr = (ac.flight_plan && (ac.flight_plan.arrival || ac.flight_plan.arr)) || '';
        const acType = (ac.flight_plan && ac.flight_plan.aircraft_faa) || (ac.flight_plan && ac.flight_plan.aircraft_short) || '';
        const squawk = ac.transponder || '';
        let squawkClass = '';
        if (squawk === '1200') squawkClass = 'squawk-1200';
        else if (['7500', '7600', '7700'].includes(squawk)) squawkClass = 'squawk-emergency';
        else if (squawk === '7777') squawkClass = 'squawk-7777';
        else if (['1226', '1205', '1234'].includes(squawk)) squawkClass = 'squawk-vfr';
        const squawkHtml = squawkClass ? `<span class="${squawkClass}">${squawk}</span>` : squawk;
        let status = classifyAircraft(ac, ac.latitude, ac.longitude, overlays);
        if(ac._onGround) status = 'ground';
        const statusHtmlRow = `<td><span class="status-${status} status-label">${statusLabel(status)}</span></td>`;
        return `<td>${ac.callsign || ''}</td><td>${acType}</td><td>${ac.name || ''}</td><td>${cid}</td><td>${dca.radial_range}</td><td>${Math.round(ac.altitude || 0)}</td><td>${Math.round(ac.groundspeed || 0)}</td><td>${squawkHtml}</td><td>${ac.flight_plan?.assigned_transponder || ''}</td><td>${dep} → ${arr}</td>${statusHtmlRow}`;
      }, it => `frz:${(it.aircraft||it).cid|| (it.aircraft||it).callsign || ''}`);

    }catch(e){ console.error('Error rendering lists after markers', e); }


    // Ensure category groups visibility matches legend toggles
    const toggleGroup = (id, cat) => {
      const cb = el(id);
      if(!cb) return;
      const pgrp = p56MarkerGroups[cat];
      const sgrp = sfraMarkerGroups[cat];
      // initial state
      if(cb.checked){ 
        p56Map.addLayer(pgrp); 
        sfraMap.addLayer(sgrp); 
        console.log('Added', cat, 'group to maps (initial)');
      } else { 
        p56Map.removeLayer(pgrp); 
        sfraMap.removeLayer(sgrp); 
        console.log('Removed', cat, 'group from maps (initial)');
      }
      // only attach listener once
      if(!cb._toggleAttached){
        cb._toggleAttached = true;
        cb.addEventListener('change', ()=>{
          if(cb.checked){ 
            p56Map.addLayer(pgrp); 
            sfraMap.addLayer(sgrp); 
            console.log('Added', cat, 'group to maps');
          } else { 
            p56Map.removeLayer(pgrp); 
            sfraMap.removeLayer(sgrp); 
            console.log('Removed', cat, 'group from maps');
          }
        });
      }
    };
    toggleGroup('toggle-ac-p56','p56');
    toggleGroup('toggle-ac-frz','frz');
    toggleGroup('toggle-ac-sfra','sfra');
    toggleGroup('toggle-ac-air','air');
    toggleGroup('toggle-ac-ground','ground');

    // Make legend collapsible
    try{
      const legend = el('legend');
      const btn = el('legend-toggle');
      if(btn && legend && !btn._legendAttached){
        btn._legendAttached = true;
        btn.addEventListener('click', ()=>{
          const collapsed = legend.classList.toggle('collapsed');
          btn.setAttribute('aria-expanded', String(!collapsed));
          btn.textContent = collapsed ? 'Legend ▸' : 'Legend ▾';
        });
      }
    }catch(e){/* ignore */}

    // Add sortable header handlers for each traffic table
    try{
      document.querySelectorAll('.traffic-table').forEach(table => {
        const tbody = table.querySelector('tbody');
        const tbodyId = tbody?.id;
        if(!tbodyId) return;
        // attach click handlers to header cells
        Array.from(table.querySelectorAll('thead th')).forEach((th, idx) => {
          // prevent duplicate listeners
          if(th._sortableAttached) return; th._sortableAttached = true;
          th.addEventListener('click', ()=>{
            // determine default key mapping per table and column index
            const col = th.textContent.trim().toLowerCase();
              // cycle sort order: none -> asc -> desc -> none
              const prev = sortConfig[tbodyId];
              let order = 'asc';
              if(prev && prev.key && prev.key._col === col){
                if(prev.order === 'asc') order = 'desc';
                else if(prev.order === 'desc') order = null; // remove sort
              } else {
                order = 'asc';
              }
            // set comparator key function with a marker of which column
              if(tbodyId === 'p56-leaderboard-tbody'){
              // use special key wrapper that holds _col so render can identify
              const keyFn = function(r){ return 0; };
              keyFn._col = col;
                if(order) sortConfig[tbodyId] = { key: keyFn, order }; else delete sortConfig[tbodyId];
            }else if(tbodyId === 'p56-events-tbody'){
              // column likely 'date / time' or 'callsign' etc.
                if(order){
                  if(col.includes('date') || col.includes('time')) sortConfig[tbodyId] = { key: (e)=> e.recorded_at || 0, order };
                  else if(col.includes('callsign')) sortConfig[tbodyId] = { key: (e)=> (e.callsign||'').toLowerCase(), order };
                  else sortConfig[tbodyId] = { key: (e)=> (String(e[col])||'').toLowerCase(), order };
                  sortConfig[tbodyId].key._col = col;
                } else delete sortConfig[tbodyId];
            }else{
              // regular traffic tables: p56-tbody, sfra-tbody, frz-tbody
                if(order){
                  if(col.includes('callsign')) sortConfig[tbodyId] = { key: (a)=> (a.callsign||'').toLowerCase(), order };
                  else if(col.includes('type')) sortConfig[tbodyId] = { key: (a)=> ((a.flight_plan?.aircraft_faa || a.flight_plan?.aircraft_short || '')||'').toLowerCase(), order };
                  else if(col.includes('name')) sortConfig[tbodyId] = { key: (a)=> (a.name||'').toLowerCase(), order };
                  else if(col.includes('cid')) sortConfig[tbodyId] = { key: (a)=> Number(a.cid||0), order };
                  else if(col.includes('bullseye') || col.includes('dca')) {
                    // Sort bullseye by distance first (range), then bearing
                    sortConfig[tbodyId] = { key: (a)=> {
                      const dca = a.dca || computeDca(a.latitude||a.last_position?.lat, a.longitude||a.last_position?.lon);
                      return dca.range_nm * 1000 + dca.bearing; // distance is primary, bearing secondary
                    }, order };
                  }
                  else if(col.includes('alt')) sortConfig[tbodyId] = { key: (a)=> Number(a.altitude||a.alt||0), order };
                  else if(col.includes('gs') || col.includes('ground')) sortConfig[tbodyId] = { key: (a)=> Number(a.groundspeed||a.gs||0), order };
                  else if(col.includes('squawk')) sortConfig[tbodyId] = { key: (a)=> Number(a.transponder||0), order };
                  else if(col.includes('assigned')) sortConfig[tbodyId] = { key: (a)=> Number(a.flight_plan?.assigned_transponder||0), order };
                  else if(col.includes('route') || col.includes('dep') || col.includes('arr')) {
                    sortConfig[tbodyId] = { key: (a)=> {
                      const dep = (a.flight_plan?.departure || a.flight_plan?.depart || '');
                      const arr = (a.flight_plan?.arrival || a.flight_plan?.arr || '');
                      return `${dep} ${arr}`.toLowerCase();
                    }, order };
                  }
                  else if(col.includes('status')) sortConfig[tbodyId] = { key: (a)=> (a.status||'').toLowerCase(), order };
                  else sortConfig[tbodyId] = { key: (a)=> (String(a[col])||'').toLowerCase(), order };
                  sortConfig[tbodyId].key._col = col;
                } else delete sortConfig[tbodyId];
            }
            // update header sort indicators
              document.querySelectorAll('.traffic-table thead th').forEach(h=>{ h.classList.remove('sort-asc','sort-desc'); });
              if(order === 'asc') th.classList.add('sort-asc'); else if(order === 'desc') th.classList.add('sort-desc');
            // re-render only this table, don't refetch data
            // The renderTable function will use the sortConfig we just set
            console.log('Sorting', tbodyId, 'by', col, 'order:', order);
            // Trigger a minimal re-render by calling the table-specific render
            // We can't call refresh() as it would refetch all data
            // Instead, find and re-render just this table using the last data
            // For now, we'll trigger a full refresh but this is suboptimal
            // TODO: cache the last table data and re-render only that table
            if(window._lastRefreshData){
              // Use cached data to re-render without fetching
              console.log('Would re-render from cache, but not implemented yet - calling full refresh');
            }
            refresh();
          });
        });
      });
    }catch(e){/* ignore */}

    // VSO panel: use filtered but further filter by affiliations
    // build affiliations list from checked boxes + custom
    const checks = Array.from(document.querySelectorAll('.aff-check:checked')).map(i=>i.value);
    const extras = (el('custom-aff').dataset.added || '').split(',').map(s=>s.trim()).filter(Boolean);
    const affs = [...checks, ...extras].map(s=>s.toLowerCase());
    const vsoMatches = [];
    for(const ac of filtered){
      const rmk = ((ac.flight_plan||{}).remarks||'').toLowerCase();
      if(affs.length===0){ vsoMatches.push({aircraft:ac, dca:ac.dca||null, matched_affiliations:[]}); }
      else{
        const matched = affs.filter(p=> rmk.includes(p));
        if(matched.length) vsoMatches.push({aircraft:ac, dca:ac.dca||null, matched_affiliations: matched});
      }
    }
    el('vso-count').textContent = vsoMatches.length;
    renderList('vso-list', vsoMatches, it=>{ const ac=it.aircraft; return `<strong>${ac.callsign||''}</strong> — ${ac.latitude?.toFixed?.(5)||''}, ${ac.longitude?.toFixed?.(5)||''} <br/><em>${(it.matched_affiliations||[]).join(', ')}</em>`; });
    }catch(err){
      console.error('REFRESH ERROR:', err);
      console.error('Error stack:', err.stack);
      alert('Dashboard refresh failed. Check console for details. Error: ' + err.message);
    }
  }

  // UI interactions - attach robust handlers with error logging so clicks always attempt to run
  try{
    const applyBtn = el('apply');
    if(applyBtn){
      applyBtn.addEventListener('click', ()=>{
        try{
          applyBtn.disabled = true;
          // ensure permalink is up-to-date
          setPermalink();
          const link = el('permalink');
          // navigate to the permalink in the same tab so the URL reflects new parameters
          if(link && link.href && link.href !== '#'){
            window.location.href = link.href;
          }else{
            // fallback to single-page refresh
            refresh();
          }
        }catch(e){
          console.error('Apply handler error', e);
          alert('Error applying settings: ' + (e && e.message ? e.message : e));
        }finally{ setTimeout(()=>applyBtn.disabled=false, 400); }
      });
    }
  }catch(e){ console.error('Failed to attach UI handlers', e); }

  // Keep permalink updated whenever inputs that affect it change.
  try{
    // update when affiliation checkboxes change
    document.querySelectorAll('.aff-check').forEach(cb => cb.addEventListener('change', ()=>{ setPermalink(); }));
    // update when overlay toggles change
    ['toggle-sfra','toggle-frz','toggle-p56','toggle-ac-p56','toggle-ac-frz','toggle-ac-sfra','toggle-ac-air','toggle-ac-ground'].forEach(id => {
      const elc = document.getElementById(id);
      if(elc) elc.addEventListener('change', ()=> setPermalink());
    });
    // update when custom aff is added (the add-aff handler already updates permalink, but ensure consistency)
    const addAff = el('add-aff'); if(addAff) addAff.addEventListener('click', ()=> setPermalink());
    // update when permalink should reflect current VSO range input changes
    const vsoRange = el('vso-range'); if(vsoRange) vsoRange.addEventListener('input', ()=> setPermalink());
  }catch(e){ console.error('Failed to attach permalink-updating listeners', e); }
  // apply VSO range when user presses Enter or blurs the input
  try{
    const vsoRange = el('vso-range');
    if(vsoRange){
      vsoRange.addEventListener('keydown', (ev)=>{
        if(ev.key === 'Enter'){
          ev.preventDefault();
          setPermalink(); refresh();
        }
      });
      vsoRange.addEventListener('blur', ()=>{ setPermalink(); refresh(); });
    }
  }catch(e){/* ignore */}
  el('toggle-sfra').addEventListener('change', ()=>{ 
    if(overlays.p56.sfra && overlays.sfra.sfra){ 
      if(el('toggle-sfra').checked) { 
        overlays.p56.sfra.addTo(p56Map); 
        overlays.sfra.sfra.addTo(sfraMap); 
      } else { 
        p56Map.removeLayer(overlays.p56.sfra); 
        sfraMap.removeLayer(overlays.sfra.sfra); 
      }
    }
  });
  el('toggle-frz').addEventListener('change', ()=>{ 
    if(overlays.p56.frz && overlays.sfra.frz){ 
      if(el('toggle-frz').checked) { 
        overlays.p56.frz.addTo(p56Map); 
        overlays.sfra.frz.addTo(sfraMap); 
      } else { 
        p56Map.removeLayer(overlays.p56.frz); 
        sfraMap.removeLayer(overlays.sfra.frz); 
      }
    }
  });
  el('toggle-p56').addEventListener('change', ()=>{ 
    if(overlays.p56.p56 && overlays.sfra.p56){ 
      if(el('toggle-p56').checked) { 
        overlays.p56.p56.addTo(p56Map); 
        overlays.sfra.p56.addTo(sfraMap); 
      } else { 
        p56Map.removeLayer(overlays.p56.p56); 
        sfraMap.removeLayer(overlays.sfra.p56); 
      }
    }
  });

  // add custom affiliation
  el('add-aff').addEventListener('click', ()=>{
    const v = el('custom-aff').value.trim();
    if(!v) return;
    const prev = el('custom-aff').dataset.added || '';
    const arr = prev? prev.split(',').map(s=>s.trim()).filter(Boolean):[];
    if(!arr.includes(v)) arr.push(v);
    el('custom-aff').dataset.added = arr.join(',');
    el('custom-aff').value = '';
    setPermalink();
  });

  // initial load
  setPermalink();
  loadOverlays().then(()=>refresh()).then(()=>{ try{ p56Map.invalidateSize(); sfraMap.invalidateSize(); }catch(e){} });
  // ensure maps reflow on window resize
  window.addEventListener('resize', ()=>{ try{ p56Map.invalidateSize(); sfraMap.invalidateSize(); }catch(e){} });
  // run refresh periodically and trigger Leaflet reflow after each refresh
  window.setInterval(()=>{ refresh().then(()=>{ try{ p56Map.invalidateSize(); sfraMap.invalidateSize(); }catch(e){} }); }, REFRESH);

})();
