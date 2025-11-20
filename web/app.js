// Simple dashboard app that queries the API endpoints and renders lists + map.
(function(){
  const API_ROOT = window.location.origin + '/api/v1';
  const DCA = [38.8514403, -77.0377214];
  const DEFAULT_RANGE_NM = 300;
  const REFRESH = 15000;
  // Add light client-side jitter and shared cooldown to de-sync tabs and respect 429s
  const JITTER_PCT = 0.03; // +/-3% (reduced from 10% to keep timing predictable)
  const MAX_COOLDOWN_MS = 60 * 1000; // cap any client-side cooldown to 60s
  const COOLDOWN_KEY = 'vncrcc.cooldownUntil';

  function withJitter(ms){
    const delta = ms * JITTER_PCT;
    return Math.max(0, Math.round(ms + (Math.random()*2*delta - delta)));
  }
  function getSharedCooldownUntil(){
    try{ const v = parseInt(localStorage.getItem(COOLDOWN_KEY)||'0',10); return isNaN(v)?0:v; }catch(e){ return 0; }
  }
  function setSharedCooldownUntil(ts){
    try{ localStorage.setItem(COOLDOWN_KEY, String(ts)); }catch(e){}
  }
  function parseRetryAfter(header){
    if(!header) return null;
    const h = String(header).trim();
    if(/^\d+$/.test(h)) return Date.now() + parseInt(h,10)*1000; // seconds
    const t = Date.parse(h);
    return isNaN(t) ? null : t;
  }
  async function fetchWithBackoff(url, opts){
    // Respect shared cooldown across tabs
    const now = Date.now();
    const until = getSharedCooldownUntil();
    if(until > now){ const err = new Error('In shared cooldown'); err.code='COOLDOWN'; err.retryAt=until; throw err; }
    const resp = await fetch(url, opts);
    if(resp.status === 429){
      const ra = resp.headers.get('Retry-After');
      const parsed = parseRetryAfter(ra);
      const fallback = now + REFRESH; // default to one base cycle
      // Clamp retry time to avoid excessively long cooldowns
      const retryAt = Math.min(parsed || fallback, now + MAX_COOLDOWN_MS);
      const jittered = now + Math.round((retryAt - now) * (0.9 + Math.random()*0.2));
      setSharedCooldownUntil(jittered);
      const err = new Error('Rate limited'); err.code='RATE_LIMIT'; err.retryAt=jittered; throw err;
    }
    return resp;
  }

  const el = id => document.getElementById(id);
  
  // P56 Alert System
  let previousP56EventKeys = new Set();
  let p56AlertAudio = null;
  let p56AlertTimeout = null;
  let p56AlertFadeTimeout = null;

  function loadP56AlertPreferences() {
    try {
      const banner = localStorage.getItem('p56-alert-banner');
      const sound = localStorage.getItem('p56-alert-sound');
      if (banner !== null) el('toggle-p56-banner').checked = banner === 'true';
      if (sound !== null) el('toggle-p56-sound').checked = sound === 'true';
    } catch (e) { /* ignore */ }
  }

  function saveP56AlertPreferences() {
    try {
      localStorage.setItem('p56-alert-banner', el('toggle-p56-banner').checked);
      localStorage.setItem('p56-alert-sound', el('toggle-p56-sound').checked);
    } catch (e) { /* ignore */ }
  }

  function showP56Alert() {
    const bannerEl = el('p56-alert-banner');
    const showBanner = el('toggle-p56-banner').checked;
    const playSound = el('toggle-p56-sound').checked;

    // Clear any existing timers
    if (p56AlertTimeout) clearTimeout(p56AlertTimeout);
    if (p56AlertFadeTimeout) clearTimeout(p56AlertFadeTimeout);

    // Show banner if enabled
    if (showBanner) {
      bannerEl.classList.remove('fadeout');
      bannerEl.classList.add('show');
      
      // Start 5s visible timer, then 5s fade
      p56AlertTimeout = setTimeout(() => {
        bannerEl.classList.add('fadeout');
        p56AlertFadeTimeout = setTimeout(() => {
          hideP56Alert();
        }, 5000);
      }, 5000);
    }

    // Play sound if enabled
    if (playSound) {
      try {
        if (!p56AlertAudio) {
          p56AlertAudio = new Audio('static/p56_alert.mp3');
        }
        p56AlertAudio.currentTime = 0;
        p56AlertAudio.play().catch(e => console.warn('P56 alert audio play failed:', e));
      } catch (e) {
        console.warn('P56 alert audio error:', e);
      }
    }
  }

  function hideP56Alert() {
    const bannerEl = el('p56-alert-banner');
    bannerEl.classList.remove('show', 'fadeout');
    
    // Stop audio if playing
    if (p56AlertAudio) {
      try {
        p56AlertAudio.pause();
        p56AlertAudio.currentTime = 0;
      } catch (e) { /* ignore */ }
    }
    
    // Clear timers
    if (p56AlertTimeout) {
      clearTimeout(p56AlertTimeout);
      p56AlertTimeout = null;
    }
    if (p56AlertFadeTimeout) {
      clearTimeout(p56AlertFadeTimeout);
      p56AlertFadeTimeout = null;
    }
  }

  function detectNewP56Events(events) {
    // Build set of current event keys (cid:timestamp)
    const currentKeys = new Set();
    events.forEach(evt => {
      const key = `${evt.cid || ''}:${evt.recorded_at || ''}`;
      currentKeys.add(key);
    });

    // Check if there are new keys not in previous set (skip if this is first load)
    let hasNewEvents = false;
    if (previousP56EventKeys.size > 0) {
      currentKeys.forEach(key => {
        if (!previousP56EventKeys.has(key)) {
          hasNewEvents = true;
        }
      });
    }

    // Update previous set
    previousP56EventKeys = currentKeys;

    // Trigger alert if new events detected
    if (hasNewEvents) {
      showP56Alert();
    }
  }
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
  const sfraMap = L.map('sfra-map', { zoomControl: false, doubleClickZoom: false }).setView(DCA, 9);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',{maxZoom:19,attribution:''}).addTo(p56Map);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',{maxZoom:19,attribution:''}).addTo(sfraMap);

  // layers - create separate overlay objects for each map since Leaflet doesn't allow sharing
  const overlays = {
    p56: { sfra: null, frz: null, p56: null },
    sfra: { sfra: null, frz: null, p56: null }
  };
  // Track visible flight paths per aircraft CID
  const visiblePaths = new Set();
  // Track current aircraft CIDs to detect when they disconnect/go out of range
  let currentAircraftCids = new Set();
  // Cache last known position history for incremental updates
  const lastKnownHistory = {};

  // Create path layers for flight path visualization
  const p56PathLayer = L.layerGroup().addTo(p56Map);
  const sfraPathLayer = L.layerGroup().addTo(sfraMap);

  // Helper: add small sampled labels for intrusion track points to a layer
  function addIntrusionLabels(layer, positions) {
    if (!layer || !positions || positions.length === 0) return;
    const MAX_LABELS = 50;
    const step = Math.max(1, Math.ceil(positions.length / MAX_LABELS));
    positions.forEach((p, i) => {
      if (i % step !== 0 && i !== positions.length - 1) return; // sample
      const h = (p.heading !== undefined && p.heading !== null) ? Math.round(p.heading) : '–';
      const alt = (p.alt !== undefined && p.alt !== null) ? Math.round(p.alt) : '–';
      const gs = (p.gs !== undefined && p.gs !== null) ? Math.round(p.gs) : '–';
      const html = `<div class=\"p56-point-label\">${h}&deg; / ${alt}ft / ${gs}kts</div>`;
      const marker = L.marker([p.lat, p.lon], {
        icon: L.divIcon({
          className: 'p56-point-label-wrapper',
          html,
          iconSize: [1, 1],
          iconAnchor: [0, 0]
        })
      });
      layer.addLayer(marker);
    });
  }

  // Marker categories and per-category marker groups for each map
  const categories = ['p56', 'frz', 'sfra', 'vicinity', 'ground'];
  const p56MarkerGroups = {};
  const sfraMarkerGroups = {};
  categories.forEach(cat => {
    p56MarkerGroups[cat] = L.layerGroup();
    sfraMarkerGroups[cat] = L.layerGroup();
  });

  // Helper: highlight a table row and marker halo for a given CID when a path is visible
  function highlightRowAndMarker(cidVal, show){
    try{
      // Rows: sfra:, frz:, p56-current:
      const sfraRow = document.querySelector(`tr[data-fp-key="sfra:${cidVal}"]`);
      const frzRow = document.querySelector(`tr[data-fp-key="frz:${cidVal}"]`);
      const p56Row = document.querySelector(`tr[data-fp-key="p56-current:${cidVal}"]`);
      [sfraRow, frzRow, p56Row].forEach(r => {
        if(!r) return;
        const fp = document.querySelector(`tr.flight-plan[data-fp-key="${r.dataset.fpKey}"]`);
        if(show){ r.classList.add('row-path-highlight'); if(fp && !fp.classList.contains('show')) fp.classList.add('show'); expandedSet.add(r.dataset.fpKey); }
        else { r.classList.remove('row-path-highlight'); if(fp && fp.classList.contains('show')) fp.classList.remove('show'); expandedSet.delete(r.dataset.fpKey); }
      });
    }catch(e){/* ignore DOM errors */}

    try{
      // Marker halo: iterate marker groups
      categories.forEach(cat => {
        const groups = [p56MarkerGroups[cat], sfraMarkerGroups[cat]];
        groups.forEach(g => {
          try{
            g.eachLayer(m => {
              try{
                if(m._flightPathCid === cidVal){
                  const el = m.getElement && m.getElement();
                  if(el){ if(show) el.classList.add('path-highlight'); else el.classList.remove('path-highlight'); }
                }
              }catch(e){/* ignore marker element errors */}
            });
          }catch(e){/* ignore group errors */}
        });
      });
    }catch(e){/* ignore overall errors */}
    // Persist expandedSet to localStorage after changes
    try{ saveExpandedSet(expandedSet); }catch(e){}
  }

  // Function to update all visible flight paths (call after data refresh)
  async function updateVisiblePaths(historyData) {
    if (visiblePaths.size === 0) return;
    
    // Updating visible flight paths
    
    try {
      // Use pre-fetched history data if available, otherwise fetch it
      const data = historyData || await (async () => {
        const range_nm = parseFloat(el('vso-range')?.value || DEFAULT_RANGE_NM);
        const response = await fetch(`${API_ROOT}/aircraft/list/history?range_nm=${range_nm}`);
        return await response.json();
      })();
      
      // Check for disconnected/out-of-range aircraft and remove their paths
      const pathsToRemove = [];
      for (const cid of visiblePaths) {
        const cidKey = String(cid);
        // If aircraft is no longer in current data OR has no/insufficient history, remove its path
        if (!currentAircraftCids.has(cidKey) || !data.history?.[cidKey] || data.history[cidKey].length < 2) {
          pathsToRemove.push(cidKey);
          // Aircraft disconnected or out of range, removing path
        }
      }
      
      // Remove paths for disconnected aircraft
      pathsToRemove.forEach(cidKey => {
        [p56PathLayer, sfraPathLayer].forEach(pathLayer => {
          pathLayer.eachLayer(layer => {
            if (layer._flightPathCid === cidKey) {
              pathLayer.removeLayer(layer);
            }
          });
        });
        visiblePaths.delete(cidKey);
        delete lastKnownHistory[cidKey];
        // Remove visual highlights
        highlightRowAndMarker(cidKey, false);
      });
      
      // Update paths for remaining visible aircraft (always do full refresh for simplicity and correctness)
      for (const cid of visiblePaths) {
        const cidKey = String(cid);
        const history = data.history?.[cidKey];
        if (!history || history.length < 2) continue;
        
        // Always do full path update to ensure accuracy (history can rotate/trim old points)
        // Updating path
        
        [p56PathLayer, sfraPathLayer].forEach(pathLayer => {
          let foundLayer = null;
          
          // Find existing polyline for this CID
          pathLayer.eachLayer(layer => {
            if (layer._flightPathCid === cidKey && layer.setLatLngs) {
              foundLayer = layer;
            }
          });
          
          const points = history.map(pos => [pos.lat, pos.lon]);
          
          if (foundLayer) {
            // Update existing polyline in place (efficient, no DOM removal/recreation)
            foundLayer.setLatLngs(points);
          } else {
            // Create new polyline if not found (shouldn't happen but defensive)
            const polyline = L.polyline(points, {
              color: '#00ff00',
              weight: 2,
              opacity: 0.8,
              dashArray: '5, 5'
            });
            polyline._flightPathCid = cidKey;
            pathLayer.addLayer(polyline);
          }
        });
        
        // Update cache
        lastKnownHistory[cidKey] = history;
      }
    } catch (error) {
      console.error('Failed to update visible paths:', error);
    }
  }

  // Function to toggle flight path for an aircraft (shows/hides on BOTH maps)
  async function toggleFlightPath(cid, mapType) {
    // Normalize CID to string for consistent keys across UI and layers
    const cidKey = String(cid);
    // Helper: find and toggle table row highlight/expansion for sfra/frz/p56-current rows
    function setRowHighlight(cidVal, show){
      try{
        const sfraRow = document.querySelector(`tr[data-fp-key="sfra:${cidVal}"]`);
        const frzRow = document.querySelector(`tr[data-fp-key="frz:${cidVal}"]`);
        const p56Row = document.querySelector(`tr[data-fp-key="p56-current:${cidVal}"]`);
        [sfraRow, frzRow, p56Row].forEach(r => {
          if(!r) return;
          const fp = document.querySelector(`tr.flight-plan[data-fp-key="${r.dataset.fpKey}"]`);
          if(show){ r.classList.add('row-path-highlight'); if(fp && !fp.classList.contains('show')) fp.classList.add('show'); expandedSet.add(r.dataset.fpKey); saveExpandedSet(expandedSet); }
          else { r.classList.remove('row-path-highlight'); if(fp && fp.classList.contains('show')) fp.classList.remove('show'); expandedSet.delete(r.dataset.fpKey); saveExpandedSet(expandedSet); }
        });
      }catch(e){/* ignore DOM errors */}
    }

    // Helper: add/remove marker halo for both marker variants if present on aircraft object
    function setMarkerHalo(cidVal, add){
      try{
        // search for markers in marker groups that we previously attached _flightPathCid to
        // iterate all groups and their layers
        categories.forEach(cat => {
          const groups = [p56MarkerGroups[cat], sfraMarkerGroups[cat]];
          groups.forEach(g => {
            try{
              g.eachLayer(m => {
                try{
                  if(m._flightPathCid === cidVal){
                    const el = m.getElement && m.getElement();
                    if(el){ if(add) el.classList.add('path-highlight'); else el.classList.remove('path-highlight'); }
                  }
                }catch(e){}
              });
            }catch(e){}
          });
        });
      }catch(e){}
    }

    if (visiblePaths.has(cidKey)) {
      // Hide path - remove all polylines for this CID from BOTH maps
      [p56PathLayer, sfraPathLayer].forEach(pathLayer => {
        pathLayer.eachLayer(layer => {
          if (layer._flightPathCid === cidKey) {
            pathLayer.removeLayer(layer);
          }
        });
      });
      visiblePaths.delete(cidKey);
      // Clean up history cache
      delete lastKnownHistory[cidKey];
      // remove visual highlights
      setRowHighlight(cidKey, false);
      setMarkerHalo(cidKey, false);
      // Hidden flight path
    } else {
      // Show path - fetch history and draw polyline on BOTH maps
      try {
        const range_nm = parseFloat(el('vso-range')?.value || DEFAULT_RANGE_NM);
        const response = await fetch(`${API_ROOT}/aircraft/list/history?range_nm=${range_nm}`);
        const data = await response.json();
        const history = data.history?.[cidKey];

        if (history && history.length > 1) {
          // Create lat/lng points from history
          const points = history.map(pos => [pos.lat, pos.lon]);

          // Add polyline to BOTH maps
          [p56PathLayer, sfraPathLayer].forEach(pathLayer => {
            const polyline = L.polyline(points, {
              color: '#00ff00', // Bright green for visibility
              weight: 2,
              opacity: 0.8,
              dashArray: '5, 5' // Dashed line
            });
            
            // Mark this polyline with the CID for later removal
            polyline._flightPathCid = cidKey;
            pathLayer.addLayer(polyline);
          });

          visiblePaths.add(cidKey);
          // Cache the initial history for incremental updates
          lastKnownHistory[cidKey] = history;

          // add visual highlights
          setRowHighlight(cidKey, true);
          setMarkerHalo(cidKey, true);

          console.log(`Shown flight path for ${cidKey} with ${points.length} points on both maps`);
        } else {
          console.log(`No history data available for ${cidKey}`);
        }
      } catch (error) {
        console.error(`Failed to fetch history for ${cidKey}:`, error);
      }
    }
  }

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
  // Track last update time for display
  let lastUpdateTime = 0;
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
    // Return range_nm as a numeric value with one decimal of precision so
    // the frontend can display and filter using the more accurate distance.
    return {radial_range: compact, bearing: brng_i, range_nm: Number(dist_nm.toFixed(1))};
  }

  async function loadGeo(name){
    try{
      const res = await fetchWithBackoff(`${API_ROOT}/geo/?name=${encodeURIComponent(name)}`);
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
      // FRZ color swapped to orange
      overlays.p56.frz = L.geoJSON(frz, {style:{color:'#f0ad4e',weight:2,fillOpacity:0.05}});
      overlays.sfra.frz = L.geoJSON(frz, {style:{color:'#f0ad4e',weight:2,fillOpacity:0.05}});
      if(el('toggle-frz').checked) { 
        overlays.p56.frz.addTo(p56Map); 
        overlays.sfra.frz.addTo(sfraMap); 
      }
    }
    if(p56){
      // P56 color swapped to red
      overlays.p56.p56 = L.geoJSON(p56, {style:{color:'#d9534f',weight:2,fillOpacity:0.05}});
      overlays.sfra.p56 = L.geoJSON(p56, {style:{color:'#d9534f',weight:2,fillOpacity:0.05}});
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
      img.src = '/static/plane_icon.png?v=1';
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
      return L.icon({ iconUrl: '/static/plane_icon.png?v=1', iconSize:[size,size], iconAnchor:[Math.round(size/2),Math.round(size/2)], popupAnchor:[0,-Math.round(size/2)] });
    }
  }

  async function fetchAllAircraft(){
    const res = await fetchWithBackoff(`${API_ROOT}/aircraft/list`);
    if(!res.ok) return [];
    const j = await res.json();
    return j.aircraft || [];
  }

  async function maybeElevation(lat, lon){
    const key = `${lat.toFixed(4)}:${lon.toFixed(4)}`;
    if(elevCache[key]) return elevCache[key];
    try{
      const res = await fetchWithBackoff(`${API_ROOT}/elevation/?lat=${lat}&lon=${lon}`);
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
                const statusToColor = s => s==='frz'? '#f0ad4e' : s==='p56'? '#d9534f' : s==='sfra'? '#0275d8' : s==='ground'? '#6c757d' : '#28a745';
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

  // Global cache for table data to enable fast sorting without full refresh
  let tableDataCache = null;

  // Fast table re-rendering using cached data (for sorting without full refresh)
  function rerenderTable(tbodyId) {
    if (!tableDataCache) {
      console.log('No cached data, falling back to full refresh');
      refresh();
      return;
    }

    // Fast re-rendering table

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
        return `<td>${ci.callsign || ''}</td><td>${acType}</td><td>${ci.name || ''}</td><td>${ci.cid || ''}</td><td>${dca.bearing}°</td><td>${dca.range_nm.toFixed(1)} nm</td><td>${Math.round(ci.altitude || 0)}</td><td>${Math.round(ci.groundspeed || 0)}</td><td>${squawkHtml}</td><td>${dep}</td><td>${arr}</td>`;
      }, ci => `p56-current:${ci.cid||ci.callsign||''}`);
    } else if (tbodyId === 'p56-events-tbody') {
      const tbodyEvents = el('p56-events-tbody');
      tbodyEvents.innerHTML = '';
      // apply robust sorting (numeric or string) similar to renderTable
      let evtsLocal = Array.isArray(events) ? events.slice() : [];
      try{
        const conf = sortConfig['p56-events-tbody'];
        if(conf && typeof conf.key === 'function'){
          evtsLocal.sort((a,b)=>{
            try{
              const va = conf.key(a); const vb = conf.key(b);
              if(va==null && vb==null) return 0;
              if(va==null) return conf.order==='asc'? -1: 1;
              if(vb==null) return conf.order==='asc'? 1: -1;
              if(typeof va === 'number' && typeof vb === 'number') return conf.order==='asc'? va-vb : vb-va;
              const sa = String(va).toLowerCase(); const sb = String(vb).toLowerCase();
              if(sa < sb) return conf.order==='asc'? -1: 1;
              if(sa > sb) return conf.order==='asc'? 1: -1;
            }catch(e){ /* fallback to equal on error */ }
            return 0;
          });
        }
      }catch(e){/* ignore */}
      evtsLocal.forEach(evt => {
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
          const positions = (evt.pre_positions || []).concat(evt.intrusion_positions || evt.post_positions || []);
          if (positions.length > 1) {
            const latlngs = positions.map(p => [p.lat, p.lon]);
            const polyline = L.polyline(latlngs, { color: 'yellow', weight: 3, opacity: 0.8 });
            p56PathLayer.addLayer(polyline);
            addIntrusionLabels(p56PathLayer, positions);
            addIntrusionLabels(sfraPathLayer, positions);
          }
        }
        tr.addEventListener('click', () => {
          const opening = !fpDiv.classList.contains('show');
          fpDiv.classList.toggle('show');
          if(opening){
            p56PathLayer.clearLayers();
            const positions = (evt.pre_positions || []).concat(evt.intrusion_positions || evt.post_positions || []);
            if (positions.length > 1) {
              const latlngs = positions.map(p => [p.lat, p.lon]);
              const polyline = L.polyline(latlngs, { color: 'yellow', weight: 3, opacity: 0.8 });
              p56PathLayer.addLayer(polyline);
              addIntrusionLabels(p56PathLayer, positions);
              addIntrusionLabels(sfraPathLayer, positions);
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
      // Leaderboard is not sortable - this rerender should not be called
      console.warn('P56 leaderboard does not support sorting');
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
        return `<td>${ac.callsign || ''}</td><td>${acType}</td><td>${ac.name || ''}</td><td>${cid}</td><td>${dca.bearing}°</td><td>${dca.range_nm.toFixed(1)} nm</td><td>${Math.round(ac.altitude || 0)}</td><td>${Math.round(ac.groundspeed || 0)}</td><td>${squawkHtml}</td><td>${dep}</td><td>${arr}</td>`;
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
        const assigned = ac.flight_plan?.assigned_transponder || '';
        const squawkHtml = squawkClass ? `<span class="${squawkClass}">${squawk}</span> / ${assigned}` : `${squawk} / ${assigned}`;
        let area = classifyAircraft(ac, ac.latitude, ac.longitude, overlays);
        let isGround = ac._onGround;
        let statusText = isGround ? 'Ground' : 'Airborne';
        // If this CID is currently inside P-56, show the P56 swatch (red) but keep status text
        const statusSwatch = (typeof currentP56Cids !== 'undefined' && currentP56Cids.has && currentP56Cids.has(String(cid))) ? 'p56' : (isGround ? 'ground' : 'airborne');
        const statusHtmlRow = `<td><span class="status-${statusSwatch} status-label">${statusText}</span></td>`;
        return `<td>${ac.callsign || ''}</td><td>${acType}</td><td>${ac.name || ''}</td><td>${cid}</td><td>${dca.bearing}°</td><td>${Number(dca.range_nm).toFixed(1)} nm</td><td>${Math.round(ac.altitude || 0)}</td><td>${Math.round(ac.groundspeed || 0)}</td><td>${squawkHtml}</td><td>${dep}</td><td>${arr}</td>${statusHtmlRow}`;
      }, it => `frz:${(it.aircraft||it).cid|| (it.aircraft||it).callsign || ''}`);
    } else if (tbodyId === 'vso-tbody') {
      // Re-render VSO table using cached filtered aircraft
      const filtered = latest_ac || [];
      const selectedAff = (el('custom-aff')?.dataset?.selected || '').split(',').map(s=>s.trim()).filter(Boolean).map(s=>s.toLowerCase());
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
      renderTable('vso-tbody', vsoMatches, it => {
        const ac = it.aircraft || {};
        const lat = ac.latitude || ac.lat || ac.y;
        const lon = ac.longitude || ac.lon || ac.x;
        const dca = it.dca || (lat!=null && lon!=null ? computeDca(lat, lon) : { bearing: '-', range_nm: 0 });
        const aff = (it.matched_affiliations || []).map(a => a.toUpperCase()).join(', ');
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
        let isGround = ac._onGround;
        let statusText = isGround ? 'Ground' : 'Airborne';
        return `<td>${aff || '-'}</td><td>${ac.callsign || ''}</td><td>${acType}</td><td>${ac.name || ''}</td><td>${ac.cid || ''}</td><td>${dca.bearing}°</td><td>${dca.range_nm.toFixed(1)} nm</td><td>${Math.round(ac.altitude || 0)}</td><td>${Math.round(ac.groundspeed || 0)}</td><td>${squawkHtml}</td><td>${dep}</td><td>${arr}</td><td>${statusText}</td>`;
      }, it => `vso:${(it.aircraft||{}).cid || (it.aircraft||{}).callsign || ''}`);
    } else {
      console.log('No rerender logic for table:', tbodyId);
    }
  }

  async function refresh(aircraftSnapshot, historyData){
    try{
    setPermalink();
    // track keys present in this refresh so we can prune persisted expanded keys
    const presentKeys = new Set();
    // Declare variables that need function-level scope for caching
    let lb = [];
    // load overlays if not yet
    if(!overlays.p56.sfra && !overlays.p56.frz && !overlays.p56.p56) await loadOverlays();

  // fetch aircraft (use provided snapshot if caller already fetched it)
  const aircraft = aircraftSnapshot || await fetchAllAircraft();
  // Fetched aircraft
  // Read VSO range as a floating value so fractional nautical miles are respected
  const range_nm = parseFloat(el('vso-range').value || DEFAULT_RANGE_NM);
  // VSO range filter applied
    const filtered = aircraft.filter(a=>{
      const lat = a.latitude || a.lat || a.y;
      const lon = a.longitude || a.lon || a.x;
      if(lat==null||lon==null) return false;
      const nm = haversineNm(DCA[0], DCA[1], lat, lon);
      return nm <= range_nm;
    });
    // Filtered aircraft
    
    // Update current aircraft CIDs for disconnection detection
    currentAircraftCids = new Set(filtered.map(a => String(a.cid || '')).filter(c => c));

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
    // More lenient rules to catch fast-taxiing aircraft:
    // 1. GS <= 10 kt (stationary/slow taxi)
    // 2. GS < 40 kt AND alt < 500 ft (fast taxi or low approach - but 500 ft is too low for normal flight)
    // 3. GS < 60 kt AND alt < 200 ft (very low - likely on runway or final)
    filtered.forEach(ac => {
      const gs = Number(ac.groundspeed || ac.gs || 0);
      const alt = Number(ac.altitude || ac.alt || 0);
      ac._onGround = (gs <= 10) || (gs < 40 && alt < 500) || (gs < 60 && alt < 200);
    });
    // On-ground detection complete

  // Instead of calling SFRA/FRZ endpoints for counts/lists, compute them from
  // the same client-side overlays used to render the map so the UI and map
  // always match. We still fetch P56 history for the details panel but the
  // count/listing will be driven by client-side classification below.
    const p56json = await fetchWithBackoff(`${API_ROOT}/p56/`).then(r=>r.ok?r.json():{breaches:[],history:{}}).catch(()=>({breaches:[],history:{}}));
    // Build a quick lookup set of CIDs currently inside P-56 so we can
    // force their marker color to the P-56 color regardless of on-ground state.
    const currentP56Cids = new Set();
    try{
      const cis = p56json.history?.current_inside || {};
      Object.keys(cis).forEach(k => { try{ if(cis[k] && cis[k].inside) currentP56Cids.add(String(k)); }catch(e){} });
    }catch(e){ /* ignore */ }

    const vipjson = await fetchWithBackoff(`${API_ROOT}/vip/`).then(r=>r.ok?r.json():{aircraft:[],count:0}).catch(()=>({aircraft:[],count:0}));
    const vipList = vipjson.aircraft || [];
    el('vip-count').textContent = vipList.length;

    // Fetching controllers
    const ctrlsjson = await fetchWithBackoff(`${API_ROOT}/controllers/`).then(r=>r.ok?r.json():{controllers:[],count:0}).catch(()=>({controllers:[],count:0}));
    const controllersList = ctrlsjson.controllers || [];
    el('controllers-count').textContent = controllersList.length;

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
    // Prepared client-side lists

    // If overlays are not loaded (geo data not available), fall back to API for SFRA/FRZ lists
    // to ensure the UI populates even if client-side classification can't work.
    if (!overlays.p56.sfra || !overlays.p56.frz) {
      console.log('Geo overlays not loaded, falling back to API for SFRA/FRZ lists');
      const sfrajson = await fetchWithBackoff(`${API_ROOT}/sfra/`).then(r=>r.ok?r.json():{aircraft:[]}).catch(()=>({aircraft:[]}));
      const frzjson = await fetchWithBackoff(`${API_ROOT}/frz/`).then(r=>r.ok?r.json():{aircraft:[]}).catch(()=>({aircraft:[]}));
      sfraList.push(...(sfrajson.aircraft || []));
      frzList.push(...(frzjson.aircraft || []));
    }

  const renderTable = (tbodyId, items, rowFn, keyFn, fpOptions) => {
      // Fast batched render: build HTML for all rows and attach a single delegated
      // click handler on the tbody. This avoids creating many DOM nodes and
      // per-row listeners, making sorting much faster.
      const tbody = el(tbodyId);
      if(!tbody) return;
      // compute colspan dynamically from the table header
      const table = tbody.closest('table');
      let colspan = 1;
      try{ colspan = table.querySelectorAll('thead th').length }catch(e){}

      // Apply sorting if configured for this table
      try{
        const conf = sortConfig[tbodyId];
        if(conf && typeof conf.key === 'function'){
          items = items.slice(); // copy
          items.sort((a,b)=>{
            try{
              const va = conf.key(a); const vb = conf.key(b);
              if(va==null && vb==null) return 0;
              if(va==null) return conf.order==='asc'? -1: 1;
              if(vb==null) return conf.order==='asc'? 1: -1;
              if(typeof va === 'number' && typeof vb === 'number') return conf.order==='asc'? va-vb : vb-va;
              const sa = String(va).toLowerCase(); const sb = String(vb).toLowerCase();
              if(sa < sb) return conf.order==='asc'? -1: 1;
              if(sa > sb) return conf.order==='asc'? 1: -1;
            }catch(e){ /* fallback to equal on error */ }
            return 0;
          });
        }
      }catch(e){ console.error('Sort error for', tbodyId, e) }

      const parts = [];
      // build HTML string for all rows
      items.forEach(item => {
        let rowHtml = '';
        try{ rowHtml = rowFn(item) || ''; }catch(err){ console.error('renderTable rowFn error for', tbodyId, err, item); rowHtml = `<td colspan="${colspan}">Error rendering row</td>`; }
        const key = (typeof keyFn === 'function') ? (() => { try{ return keyFn(item); }catch(e){return null} })() : null;
        const fpHtml = formatFlightPlan(item, fpOptions);
        const onGroundClass = item && item._onGround ? ' on-ground' : '';
        const fpShow = key && expandedSet.has(key) ? ' show' : '';
        const dataAttr = key ? ` data-fp-key="${String(key).replace(/"/g,'') }"` : '';
        parts.push(`<tr class="expandable${onGroundClass}"${dataAttr}>${rowHtml}</tr>`);
        parts.push(`<tr class="flight-plan${fpShow}"${dataAttr}><td class="flight-plan-cell" colspan="${colspan}">${fpHtml}</td></tr>`);
        if(key) try{ presentKeys.add(key); }catch(e){}
      });

      // set innerHTML in one shot
      tbody.innerHTML = parts.join('');

      // attach delegated click handler once per tbody
      if(!tbody._delegationAttached){
        tbody._delegationAttached = true;
        tbody.addEventListener('click', async (ev)=>{
          try{
            const tr = ev.target.closest('tr.expandable');
            if(!tr) return;
            const key = tr.dataset.fpKey;
            if(!key) return;
            const tbodyIdLocal = tbody.id;
            const fpRow = tbody.querySelector(`tr.flight-plan[data-fp-key="${key}"]`);
            if(!fpRow) return;
            const opening = !fpRow.classList.contains('show');
            fpRow.classList.toggle('show');
            if(opening){ expandedSet.add(key); saveExpandedSet(expandedSet); }
            else { expandedSet.delete(key); saveExpandedSet(expandedSet); }

            // Sync flight-path display similar to prior per-row handlers
            try{
              // p56 event rows: key is '<cid>:<recorded_at>' and we draw pre/post positions
              if(tbodyIdLocal === 'p56-events-tbody'){
                const evts = tableDataCache?.events || [];
                const evt = evts.find(e => `${String(e.cid||'')}:${String(e.recorded_at||'')}` === key);
                if(opening){
                  p56PathLayer.clearLayers(); sfraPathLayer.clearLayers();
                  const positions = evt?.intrusion_positions || (evt?.pre_positions || []).concat(evt?.post_positions || []);
                  if(positions && positions.length > 1){
                    const latlngs = positions.map(p => [p.lat, p.lon]);
                    const polylineP56 = L.polyline(latlngs, { color: 'yellow', weight: 3, opacity: 0.8 });
                    const polylineSFRA = L.polyline(latlngs, { color: 'yellow', weight: 3, opacity: 0.8 });
                    p56PathLayer.addLayer(polylineP56);
                    sfraPathLayer.addLayer(polylineSFRA);
                    addIntrusionLabels(p56PathLayer, positions);
                    addIntrusionLabels(sfraPathLayer, positions);
                  }
                }else{ p56PathLayer.clearLayers(); sfraPathLayer.clearLayers(); }
              } else {
                // other tables: keys like 'sfra:<cid>' or 'frz:<cid>' or 'p56-current:<cid>'
                const parts = String(key).split(':');
                const prefix = parts[0];
                const cidVal = parts.slice(1).join(':');
                let mapType = null;
                if(prefix === 'sfra') mapType = 'sfra';
                else if(prefix === 'frz') mapType = 'p56';
                else if(prefix === 'p56-current') mapType = 'p56';
                else if(prefix === 'vso') mapType = 'sfra';
                if(mapType && cidVal){
                  // call toggleFlightPath to show/hide the path (it will be idempotent)
                  try{ toggleFlightPath(cidVal, mapType).catch(e=>console.error('toggleFlightPath error', e)); }catch(e){}
                }
              }
            }catch(e){ console.error('Failed to sync flight-path for delegated click', e); }

          }catch(e){ console.error('tbody click handler error', e); }
        });
      }
    };

    /**
     * renderTableWithDivider: Like renderTable, but takes two arrays (airborne, ground)
     * and inserts a divider row between them. Uses 12 columns for colspan.
     */
    const renderTableWithDivider = (tbodyId, airborneItems, groundItems, rowFn, keyFn, fpOptions = {}) => {
      const tbody = document.getElementById(tbodyId);
      if(!tbody) return;
      const expandedSet = loadExpandedSet();
      // compute colspan dynamically from the table header (mirror renderTable)
      let colspan = 12;
      try{
        const table = tbody.closest('table');
        if(table){ colspan = table.querySelectorAll('thead th').length || 12; }
      }catch(e){}

      const parts = [];
      const buildRows = (items) => {
        items.forEach(item => {
          const key = keyFn(item);
          let rowHtml = '';
          try{ rowHtml = rowFn(item) || ''; }catch(err){ rowHtml = `<td colspan="${colspan}">Row error</td>`; }
          const fpHtml = formatFlightPlan(item, fpOptions);
          const onGroundClass = item && item._isOnGround ? ' on-ground' : '';
          const dataAttr = key ? ` data-fp-key="${String(key).replace(/"/g,'') }"` : '';
          const fpShow = key && expandedSet.has(key) ? ' show' : '';
          parts.push(`<tr class="expandable${onGroundClass}"${dataAttr}>${rowHtml}</tr>`);
          parts.push(`<tr class="flight-plan${fpShow}"${dataAttr}><td class="flight-plan-cell" colspan="${colspan}">${fpHtml}</td></tr>`);
        });
      };

      // Airborne rows
      buildRows(airborneItems);
      // Divider
      if(airborneItems.length > 0 && groundItems.length > 0){
        parts.push(`<tr class="ground-divider"><td colspan="${colspan}"></td></tr>`);
      }
      // Ground rows
      buildRows(groundItems);

      tbody.innerHTML = parts.join('');

      // Attach delegated click handler once per tbody (same pattern as renderTable)
      if(!tbody._delegationAttached){
        tbody._delegationAttached = true;
        tbody.addEventListener('click', async (ev)=>{
          try{
            const tr = ev.target.closest('tr.expandable');
            if(!tr) return;
            const key = tr.dataset.fpKey;
            if(!key) return;
            const fpRow = tbody.querySelector(`tr.flight-plan[data-fp-key="${key}"]`);
            if(!fpRow) return;
            const opening = !fpRow.classList.contains('show');
            fpRow.classList.toggle('show');
            if(opening){ expandedSet.add(key); saveExpandedSet(expandedSet); }
            else { expandedSet.delete(key); saveExpandedSet(expandedSet); }
            try{
              const partsArr = String(key).split(':');
              const prefix = partsArr[0];
              const cidVal = partsArr.slice(1).join(':');
              let mapType = null;
              if(prefix === 'sfra') mapType = 'sfra';
              else if(prefix === 'frz') mapType = 'p56';
              else if(prefix === 'p56-current') mapType = 'p56';
              else if(prefix === 'vso') mapType = 'sfra';
              if(mapType && cidVal){
                try{ toggleFlightPath(cidVal, mapType).catch(e=>console.error('toggleFlightPath error', e)); }catch(e){}
              }
            }catch(e){ console.error('Failed to sync flight-path for divider table click', e); }
          }catch(e){ console.error('divider table tbody click handler error', e); }
        });
      }
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
    const squawkHtml = squawkClass ? `<span class="${squawkClass}">${squawk}</span>` : squawk;
    return `<td>${ci.callsign || ''}</td><td>${acType}</td><td>${ci.name || ''}</td><td>${ci.cid || ''}</td><td>${dca.bearing}°</td><td>${dca.range_nm.toFixed(1)} nm</td><td>${Math.round(ci.altitude || 0)}</td><td>${Math.round(ci.groundspeed || 0)}</td><td>${squawkHtml}</td><td>${dep}</td><td>${arr}</td>`;
  }, ci => `p56-current:${ci.cid||ci.callsign||''}`, { hideEquipment: true });

    // P56 events (intrusion log) - default sort: most recent on top
    const events = p56json.history?.events || [];
    
    // Detect new P56 events and trigger alert
    detectNewP56Events(events);
    
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
          sfraPathLayer.clearLayers();
          const positions = (evt.pre_positions || []).concat(evt.intrusion_positions || evt.post_positions || []);
          if (positions.length > 1) {
            const latlngs = positions.map(p => [p.lat, p.lon]);
            const polylineP56 = L.polyline(latlngs, { color: 'yellow', weight: 3, opacity: 0.8 });
            const polylineSFRA = L.polyline(latlngs, { color: 'yellow', weight: 3, opacity: 0.8 });
            p56PathLayer.addLayer(polylineP56);
            sfraPathLayer.addLayer(polylineSFRA);
            addIntrusionLabels(p56PathLayer, positions);
            addIntrusionLabels(sfraPathLayer, positions);
          }
        }
      tr.addEventListener('click', () => {
        // Toggle flight-plan row
        const opening = !fpDiv.classList.contains('show');
        fpDiv.classList.toggle('show');
          if(opening){
            // Draw path when opening
            p56PathLayer.clearLayers();
            sfraPathLayer.clearLayers();
            const positions = (evt.pre_positions || []).concat(evt.intrusion_positions || evt.post_positions || []);
            if (positions.length > 1) {
              const latlngs = positions.map(p => [p.lat, p.lon]);
              const polylineP56 = L.polyline(latlngs, { color: 'yellow', weight: 3, opacity: 0.8 });
              const polylineSFRA = L.polyline(latlngs, { color: 'yellow', weight: 3, opacity: 0.8 });
              p56PathLayer.addLayer(polylineP56);
              sfraPathLayer.addLayer(polylineSFRA);
              addIntrusionLabels(p56PathLayer, positions);
              addIntrusionLabels(sfraPathLayer, positions);
            }
            expandedSet.add(evtKey); saveExpandedSet(expandedSet);
          }else{
            // If collapsing, remove the displayed path
            p56PathLayer.clearLayers();
            sfraPathLayer.clearLayers();
            expandedSet.delete(evtKey); saveExpandedSet(expandedSet);
          }
      });
      tbodyEvents.appendChild(tr);
      tbodyEvents.appendChild(fpDiv);
    });

    // Build a simple leaderboard from intrusion events (count by CID)
    try{
      const lbMap = {};
      // Collect multiple callsigns per CID (some CIDs may use different callsigns over time)
      events.forEach(evt => {
        const cid = String(evt.cid || (evt.flight_plan && evt.flight_plan.cid) || '');
        if(!cid) return;
        if(!lbMap[cid]) lbMap[cid] = { cid, callsigns: new Set(), names: new Set(), count: 0, first: evt.recorded_at || null, last: evt.recorded_at || null };
        if(evt.callsign) lbMap[cid].callsigns.add(evt.callsign);
        if(evt.name) lbMap[cid].names.add(evt.name);
        lbMap[cid].count += 1;
        const t = evt.recorded_at || null;
        if(t){ if(!lbMap[cid].first || t < lbMap[cid].first) lbMap[cid].first = t; if(!lbMap[cid].last || t > lbMap[cid].last) lbMap[cid].last = t; }
      });
      // Convert to array: sort by count desc, then by most recent bust (last) desc
      let lb = Object.values(lbMap).sort((a,b)=>{
        if(b.count !== a.count) return b.count - a.count;
        // Tie on count: sort by most recent bust first
        return (b.last || 0) - (a.last || 0);
      }).slice(0,50);
      // Leaderboard always shows default order: by bust count desc, then most recent bust first
      const lbTb = el('p56-leaderboard-tbody');
      if(lbTb){ 
        lbTb.innerHTML = '';
        // Assign ranks with tie handling: same count = same rank, blank for subsequent ties
        let currentRank = 1;
        let prevCount = null;
        let tieStart = 0;
        lb.forEach((r, idx) => {
          if(r.count !== prevCount){
            // New rank: account for any previous ties
            currentRank = idx + 1;
            tieStart = idx;
          }
          r._rank = currentRank;
          r._isTied = (idx > tieStart && r.count === prevCount);
          prevCount = r.count;
          const ac = latest_ac.find(a => String(a.cid) === String(r.cid)) || {};
          // prefer collected callsigns (may be multiple); render each on its own line for wrapping
          let callsignHtml = '';
          try{
            if(r.callsigns && r.callsigns.size){
              const all = Array.from(r.callsigns);
              // show only the most recent up to 5 callsigns; Sets preserve insertion order
              const max = 5;
              const recent = all.length > max ? all.slice(-max) : all;
              callsignHtml = recent.join('<br/>');
              if(all.length > max){ const more = all.length - max; callsignHtml += `<div class="callsign-more">... (+${more} more)</div>`; }
            } else {
              callsignHtml = ac.callsign || (Array.from(r.names||[])[0]) || '';
            }
          }catch(e){ callsignHtml = ac.callsign || '' }
          // Get the most recent pilot name: prefer from latest_ac, else last from collected names
          let pilotName = '';
          try{
            pilotName = ac.name || (r.names && r.names.size ? Array.from(r.names).slice(-1)[0] : '');
          }catch(e){ pilotName = ''; }
          const first = r.first ? formatZuluEpoch(r.first, true) : '-';
          const last = r.last ? formatZuluEpoch(r.last, true) : '-';
          const tr = document.createElement('tr');
          // Show rank only if not a tied entry (first person in tie shows rank, rest show blank)
          const rankDisplay = r._isTied ? '' : r._rank;
          tr.innerHTML = `<td>${rankDisplay}</td><td>${r.cid}</td><td>${pilotName}</td><td class="lb-callsigns">${callsignHtml}</td><td>${r.count}</td><td>${first}</td><td>${last}</td>`;
          lbTb.appendChild(tr);
        });
      }
    }catch(e){ /* ignore leaderboard errors */ }

  // SFRA/FRZ tables rendering will be performed after markers are created so
  // the lists reflect the exact same classification used on the map.

    // markers (incremental update to reduce latency between history vs icon refresh)
    if(!window.markersByCid){ window.markersByCid = { p56:{}, sfra:{} }; }
    if(window.INCREMENTAL_MARKERS === undefined) window.INCREMENTAL_MARKERS = true;

    if(window.INCREMENTAL_MARKERS){
      // Build lookup of current CIDs
      const currentCids = new Set(filtered.map(a => String(a.cid||'')));    
      // Remove markers for aircraft no longer present
      ['p56','sfra'].forEach(ctx => {
        const store = window.markersByCid[ctx];
        Object.keys(store).forEach(cid => {
          if(!currentCids.has(cid)){
            try{
              const rec = store[cid];
              if(rec){
                const grpOld = (ctx==='p56'? p56MarkerGroups : sfraMarkerGroups)[rec.statusClass] || (ctx==='p56'? p56MarkerGroups.vicinity : sfraMarkerGroups.vicinity);
                if(grpOld && rec.marker){ grpOld.removeLayer(rec.marker); }
              }
            }catch(e){}
            delete store[cid];
          }
        });
      });

      // Update / create markers for current aircraft
      for(const ac of filtered){
        try{
          const cid = String(ac.cid||'');
          if(!cid) continue;
          const lat = ac.latitude || ac.lat || ac.y;
          const lon = ac.longitude || ac.lon || ac.x;
          const heading = ac.heading || 0;
          const area = classifyAircraft(ac, lat, lon, overlays);
          const isGround = ac._onGround;
          let statusClass = isGround ? 'ground' : area;
          if(currentP56Cids.has(cid)){ statusClass = 'p56'; }
          const color = statusClass==='frz'? '#f0ad4e' : statusClass==='p56'? '#d9534f' : statusClass==='sfra'? '#0275d8' : statusClass==='ground'? '#6c757d' : '#28a745';
          const ctxs = [{ctx:'p56', groups:p56MarkerGroups},{ctx:'sfra', groups:sfraMarkerGroups}];
          for(const ctx of ctxs){
            const store = window.markersByCid[ctx.ctx];
            let rec = store[cid];
            if(rec){
              // Existing marker: move + recolor/heading if changed
              if(rec.marker && lat!=null && lon!=null){ rec.marker.setLatLng([lat,lon]); }
              const headingChanged = Math.abs((rec.heading||0) - heading) >= 5;
              const statusChanged = rec.statusClass !== statusClass;
              if(headingChanged || statusChanged){
                try{
                  const icon = await createPlaneIcon(color, heading).catch(()=>null);
                  if(icon && rec.marker.setIcon) rec.marker.setIcon(icon);
                }catch(e){}
              }
              if(statusChanged){
                // Move marker between category groups
                try{
                  const oldGrp = ctx.groups[rec.statusClass] || ctx.groups.vicinity;
                  const newGrp = ctx.groups[statusClass] || ctx.groups.vicinity;
                  if(oldGrp !== newGrp){ oldGrp.removeLayer(rec.marker); newGrp.addLayer(rec.marker); }
                }catch(e){}
                rec.statusClass = statusClass;
              }
              rec.heading = heading;
            }else{
              // New marker
              let icon = null;
              try{ icon = await createPlaneIcon(color, heading).catch(()=>null); }catch(e){ icon = null; }
              let marker = null;
              if(icon){ marker = L.marker([lat,lon], {icon}); } else { marker = L.circleMarker([lat,lon], {radius:6,color,fillColor:color,fillOpacity:0.8,weight:2}); }
              marker._flightPathCid = cid;
              const grp = ctx.groups[statusClass] || ctx.groups.vicinity;
              grp.addLayer(marker);
              marker.on('click', ()=> toggleFlightPath(cid, ctx.ctx));
              store[cid] = { marker, heading, statusClass };
              // Minimal tooltip (defer full rebuild cost)
              try{
                const gsVal = Math.round(Number(ac.groundspeed||ac.gs||0));
                const altVal = Math.round(Number(ac.altitude||ac.alt||0));
                const tooltipHtml = `<div class="ac-tooltip"><div><strong>${ac.callsign||''}</strong></div><div>${gsVal} kt / ${altVal} ft</div></div>`;
                marker.bindTooltip(tooltipHtml,{direction:'top',className:'fp-tooltip',sticky:true});
              }catch(e){}
            }
          }
          // Populate client-side lists (area based) for tables
          ac._airspace = area; ac._isOnGround = isGround;
          if(area === 'sfra') sfraList.push(ac); else if(area === 'frz') frzList.push(ac); else if(area === 'p56') p56List.push(ac); else airList.push(ac);
          if(isGround) groundList.push(ac);
        }catch(e){ /* per-aircraft failure ignored */ }
      }
      // Incremental marker update complete
    } else {
      // Fallback: original full rebuild path
  // clear per-category groups
  categories.forEach(cat => { p56MarkerGroups[cat].clearLayers(); sfraMarkerGroups[cat].clearLayers(); });
    // Starting marker creation

    // Parallelize icon creation for all aircraft to avoid sequential blocking
    const markerDataPromises = filtered.map(async (ac) => {
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
        if(currentP56Cids.has(String(ac.cid || ''))){ statusClass = 'p56'; statusText = 'P-56'; }
        const color = statusClass==='frz'? '#f0ad4e' : statusClass==='p56'? '#d9534f' : statusClass==='sfra'? '#0275d8' : statusClass==='ground'? '#6c757d' : '#28a745';
        const icon = await createPlaneIcon(color, heading).catch(()=>null);
        return { ac, lat, lon, heading, area, isGround, statusText, statusClass, color, icon };
      }catch(err){ return null; }
    });
    const markerDataArray = await Promise.all(markerDataPromises);
    for(const markerData of markerDataArray){
      if(!markerData) continue;
      const {ac, lat, lon, heading, area, isGround, statusText, statusClass, color, icon} = markerData;
      try{
        let markerP56 = icon? L.marker([lat,lon],{icon}) : L.circleMarker([lat,lon],{radius:6,color,fillColor:color,fillOpacity:0.8,weight:2});
        let markerSFRA = icon? L.marker([lat,lon],{icon}) : L.circleMarker([lat,lon],{radius:6,color,fillColor:color,fillOpacity:0.8,weight:2});
        markerP56._flightPathCid = String(ac.cid||''); markerSFRA._flightPathCid = String(ac.cid||'');
        const grp = p56MarkerGroups[statusClass] || p56MarkerGroups.vicinity;
        const sgrp = sfraMarkerGroups[statusClass] || sfraMarkerGroups.vicinity;
        grp.addLayer(markerP56); sgrp.addLayer(markerSFRA);
        markerP56.on('click',()=>toggleFlightPath(ac.cid,'p56')); markerSFRA.on('click',()=>toggleFlightPath(ac.cid,'sfra'));
        ac._markerP56 = markerP56; ac._markerSFRA = markerSFRA; ac._status = statusClass;
        ac._airspace = area; ac._isOnGround = isGround;
        if(area==='sfra') sfraList.push(ac); else if(area==='frz') frzList.push(ac); else if(area==='p56') p56List.push(ac); else airList.push(ac);
        if(isGround) groundList.push(ac);
      }catch(e){ }
    }
    }
    // Finished marker creation

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
  // Show current P56 intrusions count (from history.current_inside) so the
  // "P56 Current Intrusion" panel reflects the server-side detection
  // rather than client-side classification which may differ.
  el('p56-count').textContent = (currentInside || []).length;

      // Helper to render airspace tables with ground/airborne grouping and divider
      const renderAirspaceTable = (tbodyId, list, keyPrefix) => {
        // Split into airborne and ground, preserving stored flags
        const airborne = list.filter(ac => !ac._isOnGround);
        const ground = list.filter(ac => ac._isOnGround);
        
        // Common row renderer
        const makeRow = (it) => {
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
          const isGround = ac._isOnGround;
          const statusText = isGround ? 'Ground' : 'Airborne';
          // If this CID is currently inside P-56, show the P56 swatch (red) but keep status text
          const statusSwatch = (typeof currentP56Cids !== 'undefined' && currentP56Cids.has && currentP56Cids.has(String(cid))) ? 'p56' : (isGround ? 'ground' : 'airborne');
          const statusHtmlRow = `<td><span class="status-${statusSwatch} status-label">${statusText}</span></td>`;
          return `<td>${ac.callsign || ''}</td><td>${acType}</td><td>${ac.name || ''}</td><td>${cid}</td><td>${dca.bearing}°</td><td>${Number(dca.range_nm).toFixed(1)} nm</td><td>${Math.round(ac.altitude || 0)}</td><td>${Math.round(ac.groundspeed || 0)}</td><td>${squawkHtml}</td><td>${dep}</td><td>${arr}</td>${statusHtmlRow}`;
        };
        
        // Render airborne first, then divider, then ground
        renderTableWithDivider(tbodyId, airborne, ground, makeRow, it => `${keyPrefix}:${(it.aircraft||it).cid|| (it.aircraft||it).callsign || ''}`);
      };

      // Render SFRA table
      renderAirspaceTable('sfra-tbody', sfraList, 'sfra');

      // Render FRZ table
      renderAirspaceTable('frz-tbody', frzList, 'frz');

      // Render VIP table
      renderTable('vip-tbody', vipList, it => {
        const cid = it.cid || '';
        const dep = (it.flight_plan && (it.flight_plan.departure || it.flight_plan.depart)) || '';
        const arr = (it.flight_plan && (it.flight_plan.arrival || it.flight_plan.arr)) || '';
        const acType = (it.flight_plan && it.flight_plan.aircraft_faa) || (it.flight_plan && it.flight_plan.aircraft_short) || '';
        const squawk = it.transponder || '';
        let squawkClass = '';
        if (squawk === '1200') squawkClass = 'squawk-1200';
        else if (['7500', '7600', '7700'].includes(squawk)) squawkClass = 'squawk-emergency';
        else if (squawk === '7777') squawkClass = 'squawk-7777';
        const squawkHtml = squawkClass ? `<span class="${squawkClass}">${squawk}</span>` : squawk;
        return `<td><strong>${it.callsign || ''}</strong></td><td>${it.vip_title || ''}</td><td>${it.vip_type || ''}</td><td>${acType}</td><td>${it.name || ''}</td><td>${cid}</td><td>${Math.round(it.altitude || 0)}</td><td>${Math.round(it.groundspeed || 0)}</td><td>${squawkHtml}</td><td>${dep}</td><td>${arr}</td>`;
      }, it => `vip:${it.cid || it.callsign || ''}`);

      // Render Controllers table
      renderTable('controllers-tbody', controllersList, it => {
        const cid = it.cid || '';
        const name = it.realName || '';
        const callsign = it.callsign || '';
        const facility = it.facilityId || '';
        const position = it.positionName || '';
        const freq = it.frequency || '';
        const rating = it.rating || '';
        return `<td><strong>${callsign}</strong></td><td>${name}</td><td>${cid}</td><td>${facility}</td><td>${position}</td><td>${freq}</td><td>${rating}</td>`;
      }, it => `ctrl:${it.cid || it.callsign || ''}`);
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
        // Added group to maps (initial)
      } else { 
        p56Map.removeLayer(pgrp); 
        sfraMap.removeLayer(sgrp); 
        // Removed group from maps (initial)
      }
      // only attach listener once
      if(!cb._toggleAttached){
        cb._toggleAttached = true;
        cb.addEventListener('change', ()=>{
          if(cb.checked){ 
            p56Map.addLayer(pgrp); 
            sfraMap.addLayer(sgrp); 
            // Added group to maps
          } else { 
            p56Map.removeLayer(pgrp); 
            sfraMap.removeLayer(sgrp); 
            // Removed group from maps
          }
        });
      }
    };
    toggleGroup('toggle-ac-p56','p56');
    toggleGroup('toggle-ac-frz','frz');
    toggleGroup('toggle-ac-sfra','sfra');
    toggleGroup('toggle-ac-vicinity','vicinity');
    toggleGroup('toggle-ac-ground','ground');

    // Marker counts updated

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
        // Skip P56 leaderboard and P56 events - they should always show default order
        if(tbodyId === 'p56-leaderboard-tbody' || tbodyId === 'p56-events-tbody') return;
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
                  else if(col.includes('route') || col.includes('dep') || col.includes('arr') || col.includes('-')) {
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
            // Sorting table
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
      let isGround = ac._onGround;
      let statusText = isGround ? 'Ground' : 'Airborne';
      return `<td>${aff || '-'}</td><td>${ac.callsign || ''}</td><td>${acType}</td><td>${ac.name || ''}</td><td>${ac.cid || ''}</td><td>${dca.bearing}°</td><td>${dca.range_nm.toFixed(1)} nm</td><td>${Math.round(ac.altitude || 0)}</td><td>${Math.round(ac.groundspeed || 0)}</td><td>${squawkHtml}</td><td>${dep}</td><td>${arr}</td><td>${statusText}</td>`;
    }, it => `vso:${(it.aircraft||{}).cid || (it.aircraft||{}).callsign || ''}`);
    // Default sort for VSO table: affiliation (alpha) then range (numeric asc)
    if(!sortConfig['vso-tbody']){
      sortConfig['vso-tbody'] = { key: (it)=>{
        try{
          const aff = (it.matched_affiliations || []).join(',').toLowerCase();
          const ac = it.aircraft || {};
          const dca = it.dca || (ac.latitude!=null && ac.longitude!=null ? computeDca(ac.latitude, ac.longitude) : { range_nm: 0 });
          // Build a sortable string: affiliation then zero-padded numeric range
          // Use tenths of a nautical mile for stable, fractional-aware sorting
          const rn = String(Math.round(Number(dca.range_nm || 0) * 10)).padStart(6,'0');
          return `${aff} ${rn}`;
        }catch(e){ return ''; }
      }, order: 'asc' };
      sortConfig['vso-tbody'].key._col = 'affiliation/range';
    }
    lastUpdateTime = Date.now();
    updateTimeDisplay();

    // Cache the processed data for fast table re-rendering during sorting
    tableDataCache = {
      currentInside: currentInside || [],
      events: events || [],
      lb: lb || [],
      sfraList: sfraList || [],
      frzList: frzList || [],
      latest_ac: filtered || [],
      p56json: p56json || {}
    };
    // Cached table data

    // Update visible flight paths immediately - markers are already added to layer groups
    // Leaflet handles internal batching, so both markers and paths render together
    await updateVisiblePaths(historyData);

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

  // Admin cog (⚙): open selective purge modal for P56 events
  try{
    const adminBtn = el('admin-clear-p56');
    if(adminBtn && !adminBtn._adminAttached){
      adminBtn._adminAttached = true;
      adminBtn.addEventListener('click', async (ev)=>{
        ev.preventDefault();
        try{
          // Prefer cached events; fallback to fetch
          let events = (tableDataCache && Array.isArray(tableDataCache.events)) ? tableDataCache.events.slice() : null;
          if(!events){
            const p56json = await fetch(`${API_ROOT}/p56/`).then(r=>r.ok?r.json():{history:{}});
            events = p56json.history?.events || [];
          }
          openAdminMenu(events || []);
        }catch(err){ console.error('Failed to open admin menu', err); }
      });
    }
  }catch(e){ console.error('Failed to attach admin purge handler', e); }

  // Build and open admin menu (purge + metrics)
  function openAdminMenu(events){
    let overlay = document.getElementById('admin-menu-overlay');
    if(!overlay){
      overlay = document.createElement('div');
      overlay.id = 'admin-menu-overlay';
      overlay.className = 'modal-overlay';
      overlay.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="admin-menu-title" style="max-width:400px;">
          <header>
            <h3 id="admin-menu-title">Admin Menu</h3>
            <button class="btn" id="admin-menu-close">✕</button>
          </header>
          <div class="modal-body" style="display:flex;flex-direction:column;gap:12px;padding:20px;">
            <button class="btn" id="admin-purge-btn" style="padding:12px;font-size:16px;">
              🗑️ Purge P56 Entries
            </button>
            <button class="btn" id="admin-metrics-btn" style="padding:12px;font-size:16px;">
              📊 View Metrics Dashboard
            </button>
          </div>
        </div>`;
      document.body.appendChild(overlay);
    }
    
    const close = ()=> overlay.classList.remove('show');
    overlay.querySelector('#admin-menu-close').onclick = close;
    overlay.addEventListener('click', (e)=>{ if(e.target === overlay) close(); });
    
    overlay.querySelector('#admin-purge-btn').onclick = ()=>{
      close();
      openP56PurgeModal(events);
    };
    
    overlay.querySelector('#admin-metrics-btn').onclick = ()=>{
      window.location.href = '/metrics.html';
    };
    
    overlay.classList.add('show');
  }

  // Build and open purge modal
  function openP56PurgeModal(events){
    let overlay = document.getElementById('purge-overlay');
    if(!overlay){
      overlay = document.createElement('div');
      overlay.id = 'purge-overlay';
      overlay.className = 'modal-overlay';
      overlay.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="purge-title">
          <header>
            <h3 id="purge-title">P56 Intrusion Log — Select entries to purge</h3>
            <button class="btn" id="purge-close">✕</button>
          </header>
          <div class="modal-body">
            <div style="margin-bottom:8px; display:flex; gap:8px; flex-wrap:wrap;">
              <button class="btn" id="purge-select-all">Select all</button>
              <button class="btn" id="purge-select-none">Select none</button>
            </div>
            <div class="list" id="purge-list"></div>
          </div>
          <footer>
            <button class="btn" id="purge-cancel">Cancel</button>
            <button class="btn btn-danger" id="purge-confirm">Purge selected…</button>
          </footer>
        </div>`;
      document.body.appendChild(overlay);
    }

    // Populate list
    const list = overlay.querySelector('#purge-list');
    list.innerHTML = '';
    // Sort newest first
    const evts = events.slice().sort((a,b)=> (b.recorded_at||0) - (a.recorded_at||0));
    evts.forEach(evt => {
      const key = `${evt.cid||''}:${evt.recorded_at||''}`;
      const recorded = evt.recorded_at ? formatZuluEpoch(evt.recorded_at, true) : '-';
      const div = document.createElement('div');
      div.className = 'list-item';
      div.innerHTML = `
        <input type="checkbox" class="purge-item" value="${key}">
        <div style="flex:1;min-width:0;">
          <div><strong>${evt.callsign||''}</strong> — ${evt.name||''} (CID: ${evt.cid||''})</div>
          <div style="color:#9fb9d8;font-size:12px;">${recorded} • ${((evt.flight_plan&&evt.flight_plan.aircraft_faa)|| (evt.flight_plan&&evt.flight_plan.aircraft_short) || '')} • ${((evt.flight_plan&&evt.flight_plan.departure)||'')}-${((evt.flight_plan&&evt.flight_plan.arrival)||'')}</div>
        </div>`;
      list.appendChild(div);
    });

    // Wire controls
    const close = ()=> overlay.classList.remove('show');
    overlay.querySelector('#purge-close').onclick = close;
    overlay.querySelector('#purge-cancel').onclick = close;
    overlay.addEventListener('click', (e)=>{ if(e.target === overlay) close(); });
    overlay.querySelector('#purge-select-all').onclick = ()=>{
      list.querySelectorAll('.purge-item').forEach(cb => cb.checked = true);
    };
    overlay.querySelector('#purge-select-none').onclick = ()=>{
      list.querySelectorAll('.purge-item').forEach(cb => cb.checked = false);
    };
    overlay.querySelector('#purge-confirm').onclick = async ()=>{
      try{
        const checked = Array.from(list.querySelectorAll('.purge-item:checked')).map(cb => cb.value);
        if(checked.length === 0){ 
          await showConfirmation({ title: 'No selection', message: 'No entries selected.', isError: true });
          return; 
        }
        const pwd = await askPassword({ title: 'Admin verification', message: 'Enter admin password to purge selected entries.' });
        if(!pwd) return; // cancelled
        const resp = await fetchWithBackoff(`${API_ROOT}/p56/purge`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ password: pwd, keys: checked }) });
        if(!resp.ok){
          const j = await resp.json().catch(()=>({detail:resp.statusText}));
          await showConfirmation({ title: 'Purge failed', message: j.detail || JSON.stringify(j), isError: true });
          return;
        }
        const j = await resp.json().catch(()=>({}));
        const purged = j?.result?.purged ?? 0;
        close();
        await showConfirmation({ title: 'Success', message: `Purged ${purged} entr${purged===1?'y':'ies'}. Refreshing…`, isError: false });
        try{ await pollAircraftThenRefresh(); }catch(e){}
      }catch(err){
        console.error('Purge error', err);
        await showConfirmation({ title: 'Error', message: 'Purge failed: ' + (err && err.message ? err.message : err), isError: true });
      }
    };

    // Show overlay
    overlay.classList.add('show');
  }

  // Password dialog with hidden entry and hold-to-show button
  function askPassword(opts){
    const { title = 'Admin verification', message = 'Enter admin password.' } = opts || {};
    return new Promise(resolve => {
      let overlay = document.getElementById('pwd-overlay');
      if(!overlay){
        overlay = document.createElement('div');
        overlay.id = 'pwd-overlay';
        overlay.className = 'modal-overlay';
        overlay.innerHTML = `
          <div class="modal small" role="dialog" aria-modal="true" aria-labelledby="pwd-title">
            <header>
              <h3 id="pwd-title"></h3>
              <button class="btn" id="pwd-close">✕</button>
            </header>
            <div class="modal-body">
              <div style="margin-bottom:8px;color:#cfe6ff" id="pwd-msg"></div>
              <div class="pwd-row">
                <input id="pwd-input" class="pwd-field" type="password" autocomplete="current-password" placeholder="Password"/>
                <button class="btn btn-icon" id="pwd-peek" aria-label="Hold to show password">👁</button>
              </div>
            </div>
            <footer>
              <button class="btn" id="pwd-cancel">Cancel</button>
              <button class="btn btn-danger" id="pwd-ok">OK</button>
            </footer>
          </div>`;
        document.body.appendChild(overlay);
      }
      overlay.querySelector('#pwd-title').textContent = title;
      overlay.querySelector('#pwd-msg').textContent = message;
      const input = overlay.querySelector('#pwd-input');
      input.value = '';
      const show = () => { input.type = 'text'; };
      const hide = () => { input.type = 'password'; };
      const peek = overlay.querySelector('#pwd-peek');
      const okBtn = overlay.querySelector('#pwd-ok');
      const cancelBtn = overlay.querySelector('#pwd-cancel');
      const closeBtn = overlay.querySelector('#pwd-close');

      const cleanup = () => {
        // Remove transient listeners
        peek.removeEventListener('mousedown', show);
        peek.removeEventListener('mouseup', hide);
        peek.removeEventListener('mouseleave', hide);
        peek.removeEventListener('touchstart', show, { passive: true });
        peek.removeEventListener('touchend', hide);
        peek.removeEventListener('touchcancel', hide);
        input.removeEventListener('keydown', onKey);
        closeBtn.onclick = null;
        cancelBtn.onclick = null;
        okBtn.onclick = null;
      };

      const onKey = (ev) => {
        if(ev.key === 'Enter') { ev.preventDefault(); submit(); }
        if(ev.key === 'Escape') { ev.preventDefault(); cancel(); }
      };

      const submit = () => { const val = input.value || ''; overlay.classList.remove('show'); cleanup(); resolve(val || null); };
      const cancel = () => { overlay.classList.remove('show'); cleanup(); resolve(null); };

      peek.addEventListener('mousedown', show);
      peek.addEventListener('mouseup', hide);
      peek.addEventListener('mouseleave', hide);
      peek.addEventListener('touchstart', show, { passive: true });
      peek.addEventListener('touchend', hide);
      peek.addEventListener('touchcancel', hide);
      input.addEventListener('keydown', onKey);
      closeBtn.onclick = cancel;
      cancelBtn.onclick = cancel;
      okBtn.onclick = submit;

      // Do not close when clicking backdrop to avoid accidental dismissal
      overlay.onclick = (e)=>{ if(e.target === overlay) {/* ignore backdrop clicks */} };

      overlay.classList.add('show');
      setTimeout(()=> input.focus(), 0);
    });
  }

  // Confirmation dialog that auto-closes after 3 seconds
  function showConfirmation(opts){
    const { title = 'Confirmation', message = '', isError = false } = opts || {};
    return new Promise(resolve => {
      let overlay = document.getElementById('confirm-overlay');
      if(!overlay){
        overlay = document.createElement('div');
        overlay.id = 'confirm-overlay';
        overlay.className = 'modal-overlay';
        overlay.innerHTML = `
          <div class="modal small" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
            <header>
              <h3 id="confirm-title"></h3>
              <button class="btn" id="confirm-close">✕</button>
            </header>
            <div class="modal-body">
              <div style="color:#cfe6ff;text-align:center;padding:12px 0;" id="confirm-msg"></div>
            </div>
            <footer style="justify-content:center;">
              <button class="btn" id="confirm-ok">OK</button>
            </footer>
          </div>`;
        document.body.appendChild(overlay);
      }

      const modal = overlay.querySelector('.modal');
      overlay.querySelector('#confirm-title').textContent = title;
      overlay.querySelector('#confirm-msg').textContent = message;
      
      // Style based on error vs success
      const header = modal.querySelector('header');
      if(isError){
        header.style.borderBottom = '1px solid #d9534f';
        overlay.querySelector('#confirm-title').style.color = '#ff6b6b';
      } else {
        header.style.borderBottom = '1px solid #28a745';
        overlay.querySelector('#confirm-title').style.color = '#5cb85c';
      }

      const closeBtn = overlay.querySelector('#confirm-close');
      const okBtn = overlay.querySelector('#confirm-ok');

      let autoCloseTimer = null;

      const cleanup = () => {
        if(autoCloseTimer) clearTimeout(autoCloseTimer);
        closeBtn.onclick = null;
        okBtn.onclick = null;
      };

      const close = () => {
        overlay.classList.remove('show');
        cleanup();
        resolve();
      };

      closeBtn.onclick = close;
      okBtn.onclick = close;
      overlay.onclick = (e) => { if(e.target === overlay) close(); };

      // Auto-close after 3 seconds
      autoCloseTimer = setTimeout(close, 3000);

      overlay.classList.add('show');
    });
  }

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
    // Defensive: container may be missing in some embed or reduced pages
    if (!container || !container.contains(e.target)) {
      if (dropdown && dropdown.classList) dropdown.classList.remove('show');
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

  // Helper wrapper: poll aircraft first, then call refresh with that snapshot so
  // other API calls are executed immediately after the aircraft fetch.
  async function pollAircraftThenRefresh(){
    try{
      // Fetch aircraft and history in parallel for visible paths
      const aircraftPromise = fetchAllAircraft();
      const historyPromise = (visiblePaths.size > 0) ? fetchHistoryData() : Promise.resolve(null);
      
      const [aircraft, historyData] = await Promise.all([aircraftPromise, historyPromise]);
      await refresh(aircraft, historyData);
    }catch(e){ console.error('pollAircraftThenRefresh error', e); }
  }
  
  // Helper to fetch history data
  async function fetchHistoryData() {
    try {
      const range_nm = parseFloat(el('vso-range')?.value || DEFAULT_RANGE_NM);
      const response = await fetchWithBackoff(`${API_ROOT}/aircraft/list/history?range_nm=${range_nm}`);
      return await response.json();
    } catch (error) {
      console.error('Failed to fetch history data:', error);
      return null;
    }
  }

  // Fetch and display build version/timestamp
  async function fetchBuildInfo(){
    try{
      const resp = await fetchWithBackoff('/api/version');
      const data = await resp.json();
      if(data.version){
        el('build-version').textContent = data.version;
      }
      if(data.timestamp){
        el('build-timestamp').textContent = new Date(data.timestamp * 1000).toLocaleString();
      }
    }catch(e){
      console.warn('Failed to fetch build info', e);
      el('build-version').textContent = 'unknown';
      el('build-timestamp').textContent = 'unknown';
    }
  }

  // P56 Alert Controls
  loadP56AlertPreferences();
  el('toggle-p56-banner').addEventListener('change', saveP56AlertPreferences);
  el('toggle-p56-sound').addEventListener('change', saveP56AlertPreferences);
  el('test-p56-alert').addEventListener('click', showP56Alert);
  el('p56-alert-close').addEventListener('click', hideP56Alert);

  // initial load
  setPermalink();
  fetchBuildInfo();
  loadOverlays().then(()=>pollAircraftThenRefresh()).then(()=>{ try{ p56Map.invalidateSize(); sfraMap.invalidateSize(); }catch(e){} });
  // ensure maps reflow on window resize
  window.addEventListener('resize', ()=>{ try{ p56Map.invalidateSize(); sfraMap.invalidateSize(); }catch(e){} });
  // run periodic polling with jitter and shared cooldown awareness
  // Adaptive polling: reduce frequency when tab is not visible to save server resources
  let isPageVisible = !document.hidden;
  const INACTIVE_MULTIPLIER = 1.5; // Poll 50% slower when tab hidden (15s → 22.5s)
  
  document.addEventListener('visibilitychange', () => {
    isPageVisible = !document.hidden;
    console.log(`Page visibility changed: ${isPageVisible ? 'visible' : 'hidden'}`);
  });
  
  function scheduleNextPoll(baseMs){
    const now = Date.now();
    const cooldownRemaining = Math.max(0, getSharedCooldownUntil() - now);
    
    // Increase poll interval when page is hidden to reduce server load
    const effectiveDelay = isPageVisible ? baseMs : baseMs * INACTIVE_MULTIPLIER;
    const delay = Math.max(withJitter(effectiveDelay), cooldownRemaining);
    
    const scheduleTime = Date.now();
    console.log(`[POLL] Scheduled next poll in ${(delay/1000).toFixed(1)}s (base: ${(baseMs/1000).toFixed(1)}s, visible: ${isPageVisible}, cooldown: ${cooldownRemaining}ms)`);
    
    window.setTimeout(async ()=>{
      const pollStart = Date.now();
      const actualDelay = pollStart - scheduleTime;
      console.log(`[POLL] Starting poll (actual delay: ${(actualDelay/1000).toFixed(1)}s)`);
      try {
        await pollAircraftThenRefresh();
        const pollEnd = Date.now();
        const pollDuration = pollEnd - pollStart;
        console.log(`[POLL] Completed in ${(pollDuration/1000).toFixed(2)}s`);
      } catch (e) {
        // If rate-limited, honor the stored cooldown next tick
        console.warn('Poll error', e);
      } finally {
        try{ p56Map.invalidateSize(); sfraMap.invalidateSize(); }catch(e){}
        scheduleNextPoll(REFRESH);
      }
    }, delay);
  }
  scheduleNextPoll(REFRESH);

})();
