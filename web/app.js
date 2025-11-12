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
  // load any provided vso_aff as comma-separated
  const providedAff = (params.get('vso_aff') || '').split(',').map(s=>s.trim()).filter(Boolean);
  if(providedAff.length){
    // Store selected affiliations (both defaults and customs)
    el('custom-aff').dataset.selected = providedAff.join(',');
    // Add custom affiliations to the dataset
    const customAff = providedAff.filter(aff => !DEFAULT_AFF.includes(aff.toLowerCase()));
    if(customAff.length){
      el('custom-aff').dataset.custom = customAff.join(',');
    }
  } else {
    // Default: select all default affiliations
    el('custom-aff').dataset.selected = DEFAULT_AFF.join(',');
  }
  renderAffDropdown(); // Render the dropdown with current selections

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
  const categories = ['frz','p56','sfra','ground','vicinity'];
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

  // Create update time display in top right
  const updateDiv = document.createElement('div');
  updateDiv.id = 'update-time';
  updateDiv.style.position = 'absolute';
  updateDiv.style.top = '10px';
  updateDiv.style.right = '10px';
  updateDiv.style.background = 'rgba(0,0,0,0.8)';
  updateDiv.style.color = 'white';
  updateDiv.style.padding = '5px';
  updateDiv.style.fontSize = '16px';
  updateDiv.style.zIndex = '1000';
  document.body.appendChild(updateDiv);

  function updateTimeDisplay() {
    const now = Date.now();
    const last = lastUpdateTime;
    const diff = last > 0 ? now - last : 0;
    const lastStr = last > 0 ? formatZuluEpoch(Math.floor(last / 1000), true) : '--';
    const nowStr = formatZuluEpoch(Math.floor(now / 1000), true);
    updateDiv.innerHTML = `Last: ${lastStr}<br>Now: ${nowStr}`;
    if (diff > 60000) updateDiv.style.color = 'red';
    else if (diff > 30000) updateDiv.style.color = 'yellow';
    else updateDiv.style.color = 'white';
  }

  // Update time display every second for live ticking
  setInterval(updateTimeDisplay, 1000);

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
    // build affiliations list from selected affiliations in dataset
    const selectedAff = (el('custom-aff').dataset.selected || '').split(',').map(s=>s.trim()).filter(Boolean);
    const p = new URL(window.location.href);
    p.searchParams.set('vso_range', r);
    if(selectedAff.length) p.searchParams.set('vso_aff', selectedAff.join(',')); else p.searchParams.delete('vso_aff');
    el('permalink').href = p.toString();
  }

  // Format epoch seconds in Zulu (UTC). If includeDate is true returns YYYY-MM-DD HHMMSSz, else HHMMSSz
  function formatZuluEpoch(sec, includeDate=true){
    if(!sec) return '-';
    try{
      const d = new Date(sec * 1000);
      const Y = d.getUTCFullYear();
      const M = String(d.getUTCMonth()+1).padStart(2,'0');
      const D = String(d.getUTCDate()).padStart(2,'0');
      const H = String(d.getUTCHours()).padStart(2,'0');
      const m = String(d.getUTCMinutes()).padStart(2,'0');
      const s = String(d.getUTCSeconds()).padStart(2,'0');
      const time = `${H}${m}${s}z`;
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
    return {radial_range: compact, bearing: brng_i, range_nm: Math.round(dist_nm * 10) / 10};
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

  // Background elevation checker: queries local elevation for suspicious aircraft
  // without blocking the main rendering path. It deduplicates by rounded coords
  // and limits concurrency. When results arrive it updates markers in-place.
  async function runBackgroundElevationChecks(aircraftList){
    try{
      // Build map of unique keys -> aircraft array that share the same rounded coord
      const keyMap = new Map();
      aircraftList.forEach(ac=>{
        try{
          const lat = ac.latitude || ac.lat || ac.y;
          const lon = ac.longitude || ac.lon || ac.x;
          if(lat==null || lon==null) return;
          const gs = Number(ac.groundspeed || ac.gs || 0);
          const alt = Number(ac.altitude || ac.alt || 0);
          // Suspicion trigger (same as earlier precise path): very low GS OR
          // moderately low GS with low altitude. We only query those to conserve resources.
          if((gs <= 5) || (gs < 100 && alt < 1000)){
            const key = `${lat.toFixed(4)}:${lon.toFixed(4)}`;
            if(elevCache[key] !== undefined) return; // already have cached value
            if(!keyMap.has(key)) keyMap.set(key, { lat, lon, acs: [] });
            keyMap.get(key).acs.push(ac);
          }
        }catch(e){/* ignore */}
      });
      const keys = Array.from(keyMap.keys());
      if(keys.length === 0) return;
      const concurrency = 6;
      let idx = 0;
      async function worker(){
        while(true){
          const i = idx++;
          if(i >= keys.length) return;
          const key = keys[i];
          const entry = keyMap.get(key);
          const lat = entry.lat; const lon = entry.lon;
          let elev = null;
          try{ elev = await maybeElevation(lat, lon); }catch(e){ elev = null; }
          // Update all aircraft that share this key
          for(const ac of entry.acs){
            try{
              const gs = Number(ac.groundspeed || ac.gs || 0);
              const alt = Number(ac.altitude || ac.alt || 0);
              let newOnGround = ac._onGround;
              if(elev != null){
                const elev_ft = elev * 3.28084;
                const agl = alt - elev_ft;
                newOnGround = (agl <= 5) || (gs <= 5);
              }else{
                // local elevation not available for this point: apply the user's
                // specified fallback: treat as on-ground when alt < 1000 ft and GS < 20 kt.
                newOnGround = (gs <= 5) || (gs < 20 && alt < 1000);
              }
              if(newOnGround !== ac._onGround){
                ac._onGround = newOnGround;
                // recompute status and move marker between groups if needed
                const oldStatus = ac._status || classifyAircraft(ac, ac.latitude||ac.lat||ac.y, ac.longitude||ac.lon||ac.x, overlays);
                const newStatus = ac._onGround ? 'ground' : classifyAircraft(ac, ac.latitude||ac.lat||ac.y, ac.longitude||ac.lon||ac.x, overlays);
                if(oldStatus !== newStatus){
                  try{
                    const mP = ac._markerP56; const mS = ac._markerSFRA;
                    const oldGrpP = p56MarkerGroups[oldStatus] || p56MarkerGroups['vicinity'];
                    const oldGrpS = sfraMarkerGroups[oldStatus] || sfraMarkerGroups['vicinity'];
                    const newGrpP = p56MarkerGroups[newStatus] || p56MarkerGroups['vicinity'];
                    const newGrpS = sfraMarkerGroups[newStatus] || sfraMarkerGroups['vicinity'];
                    if(oldGrpP && mP) oldGrpP.removeLayer(mP);
                    if(oldGrpS && mS) oldGrpS.removeLayer(mS);
                    if(newGrpP && mP) newGrpP.addLayer(mP);
                    if(newGrpS && mS) newGrpS.addLayer(mS);
                  }catch(e){/* ignore group move errors */}
                }
                // update marker color/icon in-place
                const statusToColor = s => s==='frz'? '#d9534f' : s==='p56'? '#f0ad4e' : s==='sfra'? '#0275d8' : s==='ground'? '#6c757d' : '#28a745';
                const targetColor = statusToColor(newStatus);
                const heading = ac.heading || 0;
                const marker = ac._markerP56 || ac._markerSFRA;
                if(marker){
                  if(typeof marker.setIcon === 'function'){
                    try{
                      const icon = await createPlaneIcon(targetColor, heading);
                      marker.setIcon(icon);
                    }catch(e){ try{ marker.setStyle && marker.setStyle({ color: targetColor, fillColor: targetColor }); }catch(e){} }
                  } else {
                    try{ marker.setStyle && marker.setStyle({ color: targetColor, fillColor: targetColor }); }catch(e){}
                  }
                }
                ac._status = newStatus;
              }
            }catch(e){ console.error('Failed to apply background elevation result for', ac.callsign, e); }
          }
        }
      }
      const workers = [];
      for(let w=0; w<Math.min(concurrency, keys.length); w++) workers.push(worker());
      await Promise.all(workers);
    }catch(e){ console.error('runBackgroundElevationChecks error', e); }
  }

  function classifyAircraft(ac, lat, lon, layers){
    // priority: FRZ > P56 > SFRA - use p56 map overlays for classification
    // Check geographical location first
    let geoArea = 'vicinity';
    if(pointInLayer(lat, lon, overlays.p56.frz)) geoArea = 'frz';
    else if(pointInLayer(lat, lon, overlays.p56.p56)) geoArea = 'p56';
    else if(pointInLayer(lat, lon, overlays.p56.sfra)) geoArea = 'sfra';

    // If aircraft is in a restricted area but above 18000ft, classify as vicinity
    const altitude = Number(ac.altitude || ac.alt || 0);
    if(geoArea !== 'vicinity' && altitude > 18000) {
      return 'vicinity';
    }

    return geoArea;
  }

  // Global map for track layers
  const trackLayers = new Map(); // cid -> polyline

  function findAircraftByCid(cid) {
    for (const cat of categories) {
      const grp = p56MarkerGroups[cat];
      if (grp) {
        let found = null;
        grp.eachLayer(layer => {
          if (layer.ac && String(layer.ac.cid) === String(cid)) {
            found = layer.ac;
          }
        });
        if (found) return found;
      }
      const sgrp = sfraMarkerGroups[cat];
      if (sgrp) {
        let found = null;
        sgrp.eachLayer(layer => {
          if (layer.ac && String(layer.ac.cid) === String(cid)) {
            found = layer.ac;
          }
        });
        if (found) return found;
      }
    }
    return null;
  }

  function toggleTrack(cid) {
    if (!cid) return;
    const existing = trackLayers.get(cid);
    if (existing) {
      // remove track
      p56Map.removeLayer(existing);
      sfraMap.removeLayer(existing);
      trackLayers.delete(cid);
      console.log('Removed track for CID', cid);
    } else {
      // find the aircraft
      const ac = findAircraftByCid(cid);
      if (!ac || !ac.position_history || ac.position_history.length < 2) {
        console.log('No position history for CID', cid);
        return;
      }
      // create polyline
      const latlngs = ac.position_history.map(h => [h.latitude, h.longitude]).filter(([lat, lon]) => lat != null && lon != null);
      if (latlngs.length < 2) return;
      const polyline = L.polyline(latlngs, { color: 'blue', weight: 2, opacity: 0.8 });
      p56Map.addLayer(polyline);
      sfraMap.addLayer(polyline);
      trackLayers.set(cid, polyline);
      console.log('Added track for CID', cid, 'with', latlngs.length, 'points');
    }
  }

  // Fast table re-rendering using cached data (for sorting without full refresh)
  function rerenderTable(tbodyId) {
    if (!tableDataCache) {
      console.log('No cached data, falling back to full refresh');
      refresh();
      return;
    }

    console.log('Fast re-rendering table:', tbodyId);

    const { currentInside, events, lb, sfraList, frzList, latest_ac, p56json } = tableDataCache;

    // Re-render the specific table using cached data
    if (tbodyId === 'p56-tbody') {
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
        return `<td>${ci.callsign || ''}</td><td>${acType}</td><td>${ci.name || ''}</td><td>${ci.cid || ''}</td><td>${dca.bearing}°</td><td>${dca.range_nm.toFixed(1)} nm</td><td>${Math.round(ci.altitude || 0)}</td><td>${Math.round(ci.groundspeed || 0)}</td><td>${squawkHtml}</td><td>${ci.flight_plan?.assigned_transponder || ''}</td><td>${dep} → ${arr}</td>`;
      }, ci => `p56-current:${ci.cid||ci.callsign||''}`);
    } else if (tbodyId === 'p56-events-tbody') {
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
        const recorded = evt.recorded_at ? formatZuluEpoch(evt.recorded_at, true) : '-';
        const dep = (evt.flight_plan && (evt.flight_plan.departure || evt.flight_plan.depart)) || '';
        const arr = (evt.flight_plan && (evt.flight_plan.arrival || evt.flight_plan.arr)) || '';
        tr.innerHTML = `<td>${evt.callsign || ''}</td><td>${(evt.flight_plan && evt.flight_plan.aircraft_faa) || (evt.flight_plan && evt.flight_plan.aircraft_short) || ''}</td><td>${evt.name || ''}</td><td>${evt.cid || ''}</td><td>${recorded}</td><td>${dep}</td><td>${arr}</td>`;
        const fpDiv = document.createElement('tr');
        fpDiv.className = 'flight-plan';
        try{
          const evtTable = tbodyEvents.closest('table');
          const ncols = evtTable ? evtTable.querySelectorAll('thead th').length : 7;
          fpDiv.innerHTML = `<td class="flight-plan-cell" colspan="${ncols}">${formatFlightPlan(evt)}</td>`;
        }catch(e){
          fpDiv.innerHTML = `<td class="flight-plan-cell" colspan="7">${formatFlightPlan(evt)}</td>`;
        }
        const evtKey = `${evt.cid||''}:${evt.recorded_at||''}`;
        tr.dataset.fpKey = evtKey;
        fpDiv.dataset.fpKey = evtKey;
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
          const opening = !fpDiv.classList.contains('show');
          fpDiv.classList.toggle('show');
          if(opening){
            p56PathLayer.clearLayers();
            const positions = (evt.pre_positions || []).concat(evt.post_positions || []);
            if (positions.length > 1) {
              const latlngs = positions.map(p => [p.lat, p.lon]);
              const polyline = L.polyline(latlngs, { color: 'yellow', weight: 3, opacity: 0.8 });
              p56PathLayer.addLayer(polyline);
            }
            expandedSet.add(evtKey); saveExpandedSet(expandedSet);
          }else{
            p56PathLayer.clearLayers();
            expandedSet.delete(evtKey); saveExpandedSet(expandedSet);
          }
        });
        tbodyEvents.appendChild(tr);
        tbodyEvents.appendChild(fpDiv);
      });
    } else if (tbodyId === 'p56-leaderboard-tbody') {
      const lbTb = el('p56-leaderboard-tbody');
      if(lbTb){
        const conf = sortConfig['p56-leaderboard-tbody'];
        if(conf && conf.key && conf.key._col){
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
    } else if (tbodyId === 'sfra-tbody') {
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
        const assigned = ac.flight_plan?.assigned_transponder || '';
        const combined = `<div class="squawk-cell">${squawkHtml}${assigned? ('<span class="assigned">assigned: ' + assigned + '</span>') : ''}</div>`;
        return `<td>${ac.callsign || ''}</td><td>${acType}</td><td>${ac.name || ''}</td><td>${cid}</td><td>${dca.bearing}°</td><td>${dca.range_nm.toFixed(1)} nm</td><td>${Math.round(ac.altitude || 0)}</td><td>${Math.round(ac.groundspeed || 0)}</td><td>${combined}</td><td>${dep} → ${arr}</td>`;
      }, it => `sfra:${(it.aircraft||it).cid|| (it.aircraft||it).callsign || ''}`);
    } else if (tbodyId === 'frz-tbody') {
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
        const assigned = ac.flight_plan?.assigned_transponder || '';
        const combined = `<div class="squawk-cell">${squawkHtml}${assigned? ('<span class="assigned">assigned: ' + assigned + '</span>') : ''}</div>`;
        return `<td>${ac.callsign || ''}</td><td>${acType}</td><td>${ac.name || ''}</td><td>${cid}</td><td>${dca.bearing}°</td><td>${dca.range_nm.toFixed(1)} nm</td><td>${Math.round(ac.altitude || 0)}</td><td>${Math.round(ac.groundspeed || 0)}</td><td>${combined}</td><td>${dep} → ${arr}</td>`;
      }, it => `frz:${(it.aircraft||it).cid|| (it.aircraft||it).callsign || ''}`);
    }
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
              // fallback: if elevation lookup failed, rely on groundspeed+alt heuristic
              // treat as on-ground when very low GS OR moderately low GS with low altitude
              // (gs <= 5) OR (gs < 20 && alt < 1000)
              if(gs <= 5 || (gs < 20 && alt < 1000)) onGround = true;
            }
          }
          ac._onGround = onGround;
        }catch(e){ ac._onGround = false; }
      }));
    }catch(e){ }
    */
    // Simple on-ground heuristic without elevation lookup
    // Use a conservative fallback: treat aircraft as on-ground when
    // very low GS, or when GS is low and altitude is below 1000 ft.
    // New rule: (gs <= 5) OR (gs < 20 && alt < 1000)
    filtered.forEach(ac => {
      const gs = Number(ac.groundspeed || ac.gs || 0);
      const alt = Number(ac.altitude || ac.alt || 0);
      ac._onGround = (gs <= 5) || (gs < 20 && alt < 1000);
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

    // If overlays are not loaded (geo data not available), fall back to API for SFRA/FRZ lists
    // to ensure the UI populates even if client-side classification can't work.
    if (!overlays.p56.sfra || !overlays.p56.frz) {
      console.log('Geo overlays not loaded, falling back to API for SFRA/FRZ lists');
      const sfrajson = await fetch(`${API_ROOT}/sfra/`).then(r=>r.ok?r.json():{aircraft:[]});
      const frzjson = await fetch(`${API_ROOT}/frz/`).then(r=>r.ok?r.json():{aircraft:[]});
      sfraList.push(...(sfrajson.aircraft || []));
      frzList.push(...(frzjson.aircraft || []));
    }

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
        // shade row slightly if aircraft is on the ground
        try{ if(item._onGround) tr.classList.add('on-ground'); }catch(e){}
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
      const dep = fp.departure || '—';
      const dest = fp.arrival || '—';
      const spd = fp.cruise_tas || '—';
      const alt = fp.altitude || ac.altitude || '—';
      const route = fp.route || '—';
      const remarks = fp.remarks || '';

      // Compact full-width layout: all main fields in 1-2 lines, then RTE and RMK full-width
      let html = '<div class="fp-compact">';
      
      // Row 1: All main fields (AID, CID, BCN, TYP, DEP, DEST, SPD, ALT) - will wrap to 2 lines if needed
      html += `<div class="fp-row-inline">`;
      html += `<span class="fp-inline-field"><span class="fp-lbl">AID</span> ${aid}</span>`;
      html += `<span class="fp-inline-field"><span class="fp-lbl">CID</span> ${cid}</span>`;
      html += `<span class="fp-inline-field"><span class="fp-lbl">BCN</span> ${bcn}</span>`;
      html += `<span class="fp-inline-field"><span class="fp-lbl">TYP</span> ${typ}</span>`;
      html += `<span class="fp-inline-field"><span class="fp-lbl">DEP</span> ${dep}</span>`;
      html += `<span class="fp-inline-field"><span class="fp-lbl">DEST</span> ${dest}</span>`;
      html += `<span class="fp-inline-field"><span class="fp-lbl">SPD</span> ${spd}</span>`;
      html += `<span class="fp-inline-field"><span class="fp-lbl">ALT</span> ${alt}</span>`;
      html += `</div>`;
      
      // Row 2: RTE (full width)
      html += `<div class="fp-row-block">`;
      html += `<div class="fp-lbl">RTE</div>`;
      html += `<div class="fp-route-content">${route}</div>`;
      html += `</div>`;
      
      // Row 3: RMK (full width)
      if (remarks) {
        html += `<div class="fp-row-block">`;
        html += `<div class="fp-lbl">RMK</div>`;
        html += `<div class="fp-rmk-content">${remarks}</div>`;
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
    const statusLabel = s => ({ p56: 'P-56', frz: 'FRZ', sfra: 'SFRA', ground: 'On Ground', vicinity: 'Vicinity' }[s] || s.toUpperCase());
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
    const assigned = ci.flight_plan?.assigned_transponder || '';
    const squawkHtml = squawkClass ? `<span class="${squawkClass}">${squawk}</span> / ${assigned}` : `${squawk} / ${assigned}`;
    return `<td>${ci.callsign || ''}</td><td>${acType}</td><td>${ci.name || ''}</td><td>${ci.cid || ''}</td><td>${dca.bearing}°</td><td>${dca.range_nm.toFixed(1)} nm</td><td>${Math.round(ci.altitude || 0)}</td><td>${Math.round(ci.groundspeed || 0)}</td><td>${squawkHtml}</td><td>${dep} → ${arr}</td>`;
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
        fpDiv.innerHTML = `<td class="flight-plan-cell" colspan="${ncols}">${formatFlightPlan(evt)}</td>`;
      }catch(e){
        fpDiv.innerHTML = `<td class="flight-plan-cell" colspan="7">${formatFlightPlan(evt)}</td>`;
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
    // clear old track layers
    trackLayers.forEach(polyline => {
      p56Map.removeLayer(polyline);
      sfraMap.removeLayer(polyline);
    });
    trackLayers.clear();

    console.log('Starting marker creation for', filtered.length, 'aircraft');
    for(const ac of filtered){
      try{
      const lat = ac.latitude || ac.lat || ac.y;
      const lon = ac.longitude || ac.lon || ac.x;
      const heading = ac.heading || 0;
      const groundspeed = Number(ac.groundspeed || ac.gs || 0);
      const altitude = Number(ac.altitude || ac.alt || 0);
      let area = classifyAircraft(ac, lat, lon, overlays);
      let isGround = ac._onGround;
      let statusText = isGround ? 'Ground' : 'Airborne';
      let statusClass = isGround ? 'ground' : area;

      console.log('Processing', ac.callsign, 'area:', area, 'isGround:', isGround, 'statusText:', statusText, 'statusClass:', statusClass, 'lat:', lat, 'lon:', lon);

      // Colors: FRZ (red), P56 (orange), SFRA (blue), ground (gray), vicinity (green)
      const color = statusClass==='frz'? '#d9534f' : statusClass==='p56'? '#f0ad4e' : statusClass==='sfra'? '#0275d8' : statusClass==='ground'? '#6c757d' : '#28a745';
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
      markerP56.ac = ac;
      markerSFRA.ac = ac;
      // Summary popup: first line = callsign, pilot name, CID. Second line = DCA radial-range,
      // dep → dest, aircraft type. Clicking the aircraft replaces the popup with the full
      // JSON returned by the API for that aircraft.
      // Show either ON GROUND or the area (SFRA/FRZ/P56/VICINITY) in the popup
      const popupStatus = isGround ? 'ON GROUND' : (String(area || 'vicinity').toUpperCase());
      const summary = `<div class="ac-summary"><strong>${ac.callsign||''}</strong> — ${ac.name||''} (CID: ${cid})</div>
        <div>${dca.radial_range} — ${dep || '-'} → ${arr || '-'} — ${(ac.flight_plan && ac.flight_plan.aircraft_faa) || (ac.flight_plan && ac.flight_plan.aircraft_short) || ac.type || ac.aircraft_type || '-'}</div>
        <div><em>${popupStatus}</em> — Squawk: ${ac.transponder || '-'} / ${ac.flight_plan?.assigned_transponder || '-'}</div>
        <div><button onclick="toggleTrack('${cid}')">Toggle Track</button></div>`;
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
  // add markers to their category groups (use statusClass which holds the final group)
  const grp = p56MarkerGroups[statusClass] || p56MarkerGroups['vicinity'];
  const sgrp = sfraMarkerGroups[statusClass] || sfraMarkerGroups['vicinity'];
  grp.addLayer(markerP56);
  sgrp.addLayer(markerSFRA);
  // Attach marker references and current status to the aircraft object so
  // background elevation checks can update markers in-place without a full refresh.
  try{ ac._markerP56 = markerP56; ac._markerSFRA = markerSFRA; ac._status = statusClass; }catch(e){}
      console.log('Added marker for', ac.callsign, 'to', status, 'group');
      // Populate client-side lists so UI tables/counts match the map classification
      try{
        if(area === 'sfra') sfraList.push(ac);
        else if(area === 'frz') frzList.push(ac);
        else if(area === 'p56') p56List.push(ac);
        else if(status === 'ground') groundList.push(ac);
        else airList.push(ac);
      }catch(e){/* ignore list population errors */}
      }catch(e){
        console.error('Failed to process aircraft', ac.callsign, e);
      }
    }
    console.log('Finished marker creation');

  // Kick off background elevation checks for suspicious aircraft. This runs
  // asynchronously (non-blocking) and will update markers in-place when
  // local elevation data is available. We deduplicate requests by rounded
  // lat/lon (4 decimal places) and limit concurrency to avoid overloading
  // the client or server.
  try{ runBackgroundElevationChecks(filtered).catch(e=>console.error('Background elevation checks failed', e)); }catch(e){console.error(e)}

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
        const assigned = ac.flight_plan?.assigned_transponder || '';
        const squawkHtml = squawkClass ? `<span class="${squawkClass}">${squawk}</span> / ${assigned}` : `${squawk} / ${assigned}`;
        let area = classifyAircraft(ac, ac.latitude, ac.longitude, overlays);
        let isGround = ac._onGround;
        let statusText = isGround ? 'Ground' : 'Airborne';
        let statusClass = isGround ? 'ground' : 'airborne';
        const statusHtmlRow = `<td><span class="status-${statusClass} status-label">${statusText}</span></td>`;
        return `<td>${ac.callsign || ''}</td><td>${acType}</td><td>${ac.name || ''}</td><td>${cid}</td><td>${dca.bearing}°</td><td>${dca.range_nm.toFixed(1)} nm</td><td>${Math.round(ac.altitude || 0)}</td><td>${Math.round(ac.groundspeed || 0)}</td><td>${squawkHtml}</td><td>${dep} → ${arr}</td>${statusHtmlRow}`;
      }, it => `sfra:${(it.aircraft||it).cid|| (it.aircraft||it).callsign || ''}`);

      // Render FRZ table
      renderTable('frz-tbody', frzList, it => {
        const ac = it.aircraft || it;
        const dca = it.dca || computeDca(ac.latitude, ac.longitude);
        const cid = ac.cid || '';
        const dep = (ac.flight_plan && (ac.flight_plan.departure || ac.flight_plan.depart)) || '';
        const arr = (ac.flight_plan && ac.flight_plan.arrival || ac.flight_plan.arr) || '';
        const acType = (ac.flight_plan && ac.flight_plan.aircraft_faa) || (ac.flight_plan && ac.flight_plan.aircraft_short) || '';
        const squawk = ac.transponder || '';
        let squawkClass = '';
        if (squawk === '1200') squawkClass = 'squawk-1200';
        else if (['7500', '7600', '7700'].includes(squawk)) squawkClass = 'squawk-emergency';
        else if (squawk === '7777') squawkClass = 'squawk-7777';
        else if (['1226', '1205', '1234'].includes(squawk)) squawkClass = 'squawk-vfr';
        const assigned = ac.flight_plan?.assigned_transponder || '';
        const squawkHtml = squawkClass ? `<span class="${squawkClass}">${squawk}</span> / ${assigned}` : `${squawk} / ${assigned}`;
        let area = classifyAircraft(ac, ac.latitude, ac.longitude, overlays);
        let isGround = ac._onGround;
        let statusText = isGround ? 'Ground' : 'Airborne';
        let statusClass = isGround ? 'ground' : 'airborne';
        const statusHtmlRow = `<td><span class="status-${statusClass} status-label">${statusText}</span></td>`;
        return `<td>${ac.callsign || ''}</td><td>${acType}</td><td>${ac.name || ''}</td><td>${cid}</td><td>${dca.bearing}°</td><td>${dca.range_nm.toFixed(1)} nm</td><td>${Math.round(ac.altitude || 0)}</td><td>${Math.round(ac.groundspeed || 0)}</td><td>${squawkHtml}</td><td>${dep} → ${arr}</td>${statusHtmlRow}`;
      }, it => `frz:${(it.aircraft||it).cid|| (it.aircraft||it).callsign || ''}`);

    }catch(e){ console.error('Error rendering lists after markers', e); }

    // prune expandedSet entries for keys that are no longer present in any table
    try{
      const toRemove = [];
      expandedSet.forEach(k => { if(!presentKeys.has(k)) toRemove.push(k); });
      if(toRemove.length){ toRemove.forEach(k=>expandedSet.delete(k)); saveExpandedSet(expandedSet); }
    }catch(e){/* ignore pruning errors */}


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
    toggleGroup('toggle-ac-vicinity','vicinity');
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
                  else if(col.includes('bearing')) sortConfig[tbodyId] = { key: (a)=> {
                    const dca = a.dca || computeDca(a.latitude||a.last_position?.lat, a.longitude||a.last_position?.lon);
                    return dca.bearing;
                  }, order };
                  else if(col.includes('range')) sortConfig[tbodyId] = { key: (a)=> {
                    const dca = a.dca || computeDca(a.latitude||a.last_position?.lat, a.longitude||a.last_position?.lon);
                    return dca.range_nm;
                  }, order };
                  else if(col.includes('alt')) sortConfig[tbodyId] = { key: (a)=> Number(a.altitude||a.alt||0), order };
                  else if(col.includes('gs') || col.includes('ground')) sortConfig[tbodyId] = { key: (a)=> Number(a.groundspeed||a.gs||0), order };
                  else if(col.includes('squawk')) sortConfig[tbodyId] = { key: (a)=> Number(a.transponder||0), order };
                  else if(col.includes('assigned')) sortConfig[tbodyId] = { key: (a)=> Number(a.flight_plan?.assigned_transponder||0), order };
                  else if(col.includes('route') || col.includes('dep') || col.includes('arr') || col.includes('→')) {
                    sortConfig[tbodyId] = { key: (a)=> {
                      const dep = (a.flight_plan?.departure || a.flight_plan?.depart || '');
                      const arr = (a.flight_plan?.arrival || a.flight_plan?.arr || '');
                      return `${dep} ${arr}`.toLowerCase();
                    }, order };
                  }
                  else if(col.includes('status')) sortConfig[tbodyId] = { key: (a)=> a._onGround ? 'ground' : 'airborne', order };
                  else sortConfig[tbodyId] = { key: (a)=> (String(a[col])||'').toLowerCase(), order };
                  sortConfig[tbodyId].key._col = col;
                } else delete sortConfig[tbodyId];
            }
            // update header sort indicators
              document.querySelectorAll('.traffic-table thead th').forEach(h=>{ h.classList.remove('sort-asc','sort-desc'); });
              if(order === 'asc') th.classList.add('sort-asc'); else if(order === 'desc') th.classList.add('sort-desc');
            // re-render only this table using cached data for fast sorting
            console.log('Sorting', tbodyId, 'by', col, 'order:', order);
            rerenderTable(tbodyId);
          });
        });
      });
    }catch(e){/* ignore */}

    // VSO panel: use filtered but further filter by affiliations
    // build affiliations list from selected affiliations in dataset
    const selectedAff = (el('custom-aff').dataset.selected || '').split(',').map(s=>s.trim()).filter(Boolean).map(s=>s.toLowerCase());
    const vsoMatches = [];
    for(const ac of filtered){
      const rmk = ((ac.flight_plan||{}).remarks||'').toLowerCase();
      if(selectedAff.length===0){ vsoMatches.push({aircraft:ac, dca:ac.dca||null, matched_affiliations:[]}); }
      else{
        const matched = selectedAff.filter(p=> rmk.includes(p));
        if(matched.length) vsoMatches.push({aircraft:ac, dca:ac.dca||null, matched_affiliations: matched});
      }
    }
    el('vso-count').textContent = vsoMatches.length;
    // Render VSO matches in a traffic-table matching SFRA/FRZ layout with an
    // extra leftmost Affiliation column.
    renderTable('vso-tbody', vsoMatches, it => {
      const ac = it.aircraft || {};
      const lat = ac.latitude || ac.lat || ac.y;
      const lon = ac.longitude || ac.lon || ac.x;
      const dca = it.dca || (lat!=null && lon!=null ? computeDca(lat, lon) : { bearing: '-', range_nm: 0 });
      const aff = (it.matched_affiliations || []).map(a => a.toUpperCase()).join(', ');
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
      const assigned = ac.flight_plan?.assigned_transponder || '';
      const squawkHtml = squawkClass ? `<span class="${squawkClass}">${squawk}</span> / ${assigned}` : `${squawk} / ${assigned}`;
      let area = classifyAircraft(ac, ac.latitude, ac.longitude, overlays);
      let isGround = ac._onGround;
      let statusText = isGround ? 'Ground' : 'Airborne';
      let statusClass = isGround ? 'ground' : 'airborne';
      const statusHtmlRow = `<td><span class="status-${statusClass} status-label">${statusText}</span></td>`;
      return `<td>${aff}</td><td>${ac.callsign || ''}</td><td>${acType}</td><td>${ac.name || ''}</td><td>${cid}</td><td>${dca.bearing}°</td><td>${Number(dca.range_nm).toFixed(1)} nm</td><td>${Math.round(ac.altitude || 0)}</td><td>${Math.round(ac.groundspeed || 0)}</td><td>${squawkHtml}</td><td>${dep} → ${arr}</td>${statusHtmlRow}`;
    }, it => `vso:${(it.aircraft||{}).cid|| (it.aircraft||{}).callsign || ''}`);
    // Default sort for VSO table: affiliation (alpha) then range (numeric asc)
    if(!sortConfig['vso-tbody']){
      sortConfig['vso-tbody'] = { key: (it)=>{
        try{
          const aff = (it.matched_affiliations || []).join(',').toLowerCase();
          const ac = it.aircraft || {};
          const dca = it.dca || (ac.latitude!=null && ac.longitude!=null ? computeDca(ac.latitude, ac.longitude) : { range_nm: 0 });
          // Build a sortable string: affiliation then zero-padded numeric range
          const rn = String(Math.round(Number(dca.range_nm || 0))).padStart(6,'0');
          return `${aff} ${rn}`;
        }catch(e){ return ''; }
      }, order: 'asc' };
      sortConfig['vso-tbody'].key._col = 'affiliation/range';
    }
    lastUpdateTime = Date.now();
    updateTimeDisplay();

    // Cache the processed data for fast table re-rendering during sorting
    tableDataCache = {
      currentInside,
      events,
      lb,
      sfraList,
      frzList,
      latest_ac,
      p56json
    };
    console.log('Cached table data for fast sorting');

    }catch(err){
      console.error('REFRESH ERROR:', err);
      console.error('Error stack:', err.stack);
      // Removed alert popup
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
          // Update the URL without navigating (single-page behavior) and refresh data
          if(link && link.href && link.href !== '#'){
            try{
              const u = new URL(link.href);
              // Use replaceState to update the address bar without reloading
              history.replaceState(null, '', u.pathname + u.search + u.hash);
            }catch(e){ /* if URL parsing fails, ignore and continue */ }
            refresh();
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
    // update when overlay toggles change
    ['toggle-sfra','toggle-frz','toggle-p56','toggle-ac-p56','toggle-ac-frz','toggle-ac-sfra','toggle-ac-vicinity','toggle-ac-ground'].forEach(id => {
      const elc = document.getElementById(id);
      if(elc) elc.addEventListener('change', ()=> setPermalink());
    });
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

  // Render affiliation dropdown with checkboxes
  function renderAffDropdown(){
    const container = el('aff-options');
    container.innerHTML = '';
    const selectedAff = (el('custom-aff').dataset.selected || '').split(',').map(s=>s.trim()).filter(Boolean);
    const customAff = (el('custom-aff').dataset.custom || '').split(',').map(s=>s.trim()).filter(Boolean);

    // Add default affiliations
    DEFAULT_AFF.forEach(aff => {
      const optionDiv = document.createElement('div');
      optionDiv.className = 'aff-option';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.id = `aff-${aff}`;
      checkbox.value = aff;
      checkbox.checked = selectedAff.includes(aff.toLowerCase());
      checkbox.addEventListener('change', () => {
        updateSelectedAffiliations();
        setPermalink();
        updateDropdownButton();
      });
      const label = document.createElement('label');
      label.htmlFor = `aff-${aff}`;
      label.textContent = aff.toUpperCase();
      optionDiv.appendChild(checkbox);
      optionDiv.appendChild(label);
      container.appendChild(optionDiv);
    });

    // Add custom affiliations with delete buttons
    customAff.forEach(aff => {
      const optionDiv = document.createElement('div');
      optionDiv.className = 'aff-option';
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.id = `aff-${aff}`;
      checkbox.value = aff.toLowerCase();
      checkbox.checked = selectedAff.includes(aff.toLowerCase());
      checkbox.addEventListener('change', () => {
        updateSelectedAffiliations();
        setPermalink();
        updateDropdownButton();
      });
      const label = document.createElement('label');
      label.htmlFor = `aff-${aff}`;
      label.textContent = aff.toUpperCase();
      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.className = 'delete-aff';
      deleteBtn.setAttribute('aria-label', `Delete ${aff}`);
      deleteBtn.title = `Delete ${aff}`;
      // modern inline SVG 'X' icon for a crisp, consistent look
      deleteBtn.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" focusable="false"><path d="M6 6 L18 18 M6 18 L18 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>';
      deleteBtn.onclick = () => deleteCustomAffiliation(aff);
      optionDiv.appendChild(checkbox);
      optionDiv.appendChild(label);
      optionDiv.appendChild(deleteBtn);
      container.appendChild(optionDiv);
    });

    updateDropdownButton();
  }

  // Update selected affiliations based on checkbox states
  function updateSelectedAffiliations(){
    const checkboxes = document.querySelectorAll('#aff-options input[type="checkbox"]:checked');
    const selected = Array.from(checkboxes).map(cb => cb.value);
    el('custom-aff').dataset.selected = selected.join(',');
  }

  // Update dropdown button text to show selected affiliations
  function updateDropdownButton(){
    const btn = el('aff-dropdown-btn');
    btn.textContent = '▼';
  }

  // Delete a custom affiliation
  function deleteCustomAffiliation(aff){
    const customAff = (el('custom-aff').dataset.custom || '').split(',').map(s=>s.trim()).filter(Boolean);
    const newCustom = customAff.filter(a => a !== aff);
    el('custom-aff').dataset.custom = newCustom.join(',');

    // Also remove from selected if it was selected
    const selectedAff = (el('custom-aff').dataset.selected || '').split(',').map(s=>s.trim()).filter(Boolean);
    const newSelected = selectedAff.filter(a => a !== aff.toLowerCase());
    el('custom-aff').dataset.selected = newSelected.join(',');

    renderAffDropdown();
    setPermalink();
  }

  // Dropdown button click handler
  el('aff-dropdown-btn').addEventListener('click', (e) => {
    e.stopPropagation();
    const dropdown = el('aff-dropdown');
    const isVisible = dropdown.classList.contains('show');
    if (isVisible) {
      dropdown.classList.remove('show');
    } else {
      dropdown.classList.add('show');
    }
  });

  // Close dropdown when clicking outside
  document.addEventListener('click', (e) => {
    const dropdown = el('aff-dropdown');
    const container = el('aff-dropdown-container');
    if (!container.contains(e.target)) {
      el('aff-dropdown').classList.remove('show');
    }
  });

  // Add custom affiliation
  function addCustomAffiliation(){
    const v = el('custom-aff').value.trim();
    if(!v) return;
    const customAff = (el('custom-aff').dataset.custom || '').split(',').map(s=>s.trim()).filter(Boolean);
    const selectedAff = (el('custom-aff').dataset.selected || '').split(',').map(s=>s.trim()).filter(Boolean);

    // Check if already exists
    if(customAff.includes(v) || DEFAULT_AFF.includes(v.toLowerCase())) return;

    // Add to custom affiliations
    customAff.push(v);
    el('custom-aff').dataset.custom = customAff.join(',');

    // Auto-select the new affiliation
    selectedAff.push(v.toLowerCase());
    el('custom-aff').dataset.selected = selectedAff.join(',');

    el('custom-aff').value = '';
    renderAffDropdown();
    setPermalink();
  }

  // Add Enter key support for custom affiliation input
  el('custom-aff').addEventListener('keydown', (ev)=>{
    if(ev.key === 'Enter'){
      ev.preventDefault();
      addCustomAffiliation();
    }
  });

  // initial load
  setPermalink();
  loadOverlays().then(()=>refresh()).then(()=>{ try{ p56Map.invalidateSize(); sfraMap.invalidateSize(); }catch(e){} });
  // ensure maps reflow on window resize
  window.addEventListener('resize', ()=>{ try{ p56Map.invalidateSize(); sfraMap.invalidateSize(); }catch(e){} });
  // run refresh periodically and trigger Leaflet reflow after each refresh
  window.setInterval(()=>{ refresh().then(()=>{ try{ p56Map.invalidateSize(); sfraMap.invalidateSize(); }catch(e){} }); }, REFRESH);

})();
