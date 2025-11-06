// Simple dashboard app that queries the API endpoints and renders lists + map.
(function(){
  const API_ROOT = window.location.origin + '/api/v1';
  const DCA = [38.8514403, -77.0377214];
  const DEFAULT_RANGE_NM = 100;
  const REFRESH = 15000;

  const el = id => document.getElementById(id);
  const params = new URLSearchParams(window.location.search);

  // affiliation defaults
  const DEFAULT_AFF = ["vusaf","vuscg","usnv"];

  // initialize inputs from URL
  el('vso-range').value = params.get('vso_range') || DEFAULT_RANGE_NM;
  // load any provided vso_aff as comma-separated and add as checkboxes
  const providedAff = (params.get('vso_aff') || '').split(',').map(s=>s.trim()).filter(Boolean);

  // map setup - dark tiles
  const map = L.map('map').setView(DCA, 8);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',{maxZoom:19,attribution:''}).addTo(map);

  // layers
  const overlays = {sfra: null, frz: null, p56: null};
  const markerGroup = L.markerClusterGroup();
  map.addLayer(markerGroup);

  // caches
  const elevCache = {};

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
      overlays.sfra = L.geoJSON(sfra, {style:{color:'#0275d8',weight:2,fillOpacity:0.05}});
      if(el('toggle-sfra').checked) overlays.sfra.addTo(map);
    }
    if(frz){
      overlays.frz = L.geoJSON(frz, {style:{color:'#d9534f',weight:2,fillOpacity:0.05}});
      if(el('toggle-frz').checked) overlays.frz.addTo(map);
    }
    if(p56){
      overlays.p56 = L.geoJSON(p56, {style:{color:'#f0ad4e',weight:2,fillOpacity:0.05}});
      if(el('toggle-p56').checked) overlays.p56.addTo(map);
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

  function createPlaneIcon(color, heading){
    // simple airplane silhouette SVG (rotated via CSS transform)
    const svg = `
      <svg width="28" height="28" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" style="transform: rotate(${heading||0}deg);">
        <path fill="${color}" d="M21 16v-2l-8-5V3.5a1 1 0 0 0-1-1 1 1 0 0 0-1 1V9L3 14v2l7-1v4l2-1v1l2-1v-1l2 1v-4l7 1z" />
      </svg>`;
    return L.divIcon({className:'plane-divicon', html:svg, iconSize:[28,28], iconAnchor:[14,14]});
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
    // priority: FRZ > P56 > SFRA
    if(pointInLayer(lat, lon, overlays.frz)) return 'frz';
    if(pointInLayer(lat, lon, overlays.p56)) return 'p56';
    if(pointInLayer(lat, lon, overlays.sfra)) return 'sfra';
    return 'air';
  }

  async function refresh(){
    setPermalink();
    // load overlays if not yet
    if(!overlays.sfra && !overlays.frz && !overlays.p56) await loadOverlays();

    // fetch aircraft
    const aircraft = await fetchAllAircraft();
    const range_nm = parseInt(el('vso-range').value || DEFAULT_RANGE_NM, 10);
    const filtered = aircraft.filter(a=>{
      const lat = a.latitude || a.lat || a.y;
      const lon = a.longitude || a.lon || a.x;
      if(lat==null||lon==null) return false;
      const nm = haversineNm(DCA[0], DCA[1], lat, lon);
      return nm <= range_nm;
    });

    // update counts using sfra/frz endpoints for UI lists
    const sfraList = await fetch(`${API_ROOT}/sfra/`).then(r=>r.ok?r.json():{aircraft:[]}).then(j=>j.aircraft||[]);
    const frzList = await fetch(`${API_ROOT}/frz/`).then(r=>r.ok?r.json():{aircraft:[]}).then(j=>j.aircraft||[]);
    const p56json = await fetch(`${API_ROOT}/p56/`).then(r=>r.ok?r.json():{breaches:[],history:{}});

    el('sfra-count').textContent = sfraList.length;
    el('frz-count').textContent = frzList.length;
    el('p56-count').textContent = (p56json.breaches||[]).length;
    el('p56-details').textContent = JSON.stringify(p56json.history||{}, null, 2);

    // update lists
    const renderList = (id, items, fmt) => { const ul=el(id); ul.innerHTML=''; items.forEach(it=>{const li=document.createElement('li');li.innerHTML=fmt(it);ul.appendChild(li);}); };
    renderList('sfra-list', sfraList, it=>{
      const ac = it.aircraft||it;
      const dca = it.dca || computeDca(ac.latitude, ac.longitude);
      const cid = ac.cid || '';
      const dep = (ac.flight_plan && (ac.flight_plan.departure || ac.flight_plan.depart)) || '';
      const arr = (ac.flight_plan && (ac.flight_plan.arrival || ac.flight_plan.arr)) || '';
      return `<strong>${ac.callsign||''}</strong> — ${dca.radial_range} — CID:${cid} — ${dep || '-'} → ${arr || '-'}`;
    });
  renderList('frz-list', frzList, it=>{ const ac=it.aircraft||it; const dca = it.dca || computeDca(ac.latitude, ac.longitude); const cid = ac.cid||''; const dep=(ac.flight_plan && (ac.flight_plan.departure||ac.flight_plan.depart))||''; const arr=(ac.flight_plan && (ac.flight_plan.arrival||ac.flight_plan.arr))||''; return `<strong>${ac.callsign||''}</strong> — ${dca.radial_range} — CID:${cid} — ${dep||'-'} → ${arr||'-'}`; });

    // markers
    markerGroup.clearLayers();
    for(const ac of filtered){
      const lat = ac.latitude || ac.lat || ac.y;
      const lon = ac.longitude || ac.lon || ac.x;
      const heading = ac.heading || 0;
      const groundspeed = Number(ac.groundspeed || ac.gs || 0);
      const altitude = Number(ac.altitude || ac.alt || 0);
      let status = classifyAircraft(ac, lat, lon, overlays);

      // decide ground using thresholds
      let onGround = false;
      if((groundspeed < 100) && (altitude < 1000)){
        // check elevation to compute AGL
        const elev_m = await maybeElevation(lat, lon);
        if(elev_m!=null){
          const elev_ft = elev_m * 3.28084;
          const agl = altitude - elev_ft;
          if(agl <= 5 || groundspeed <= 5) onGround = true;
        }else{
          if(groundspeed <= 5) onGround = true;
        }
      }
      if(onGround) status = 'ground';

      const color = status==='frz'? '#d9534f' : status==='p56'? '#f0ad4e' : status==='sfra'? '#0275d8' : status==='ground'? '#6c757d' : '#2b7ae4';
      const marker = L.marker([lat, lon], {icon: createPlaneIcon(color, heading)});
  const dca = ac.dca || computeDca(lat, lon);
  const cid = ac.cid || '';
  const dep = (ac.flight_plan && (ac.flight_plan.departure || ac.flight_plan.depart)) || '';
  const arr = (ac.flight_plan && (ac.flight_plan.arrival || ac.flight_plan.arr)) || '';
  const popup = `<div><b>${ac.callsign||''}</b> (CID: ${cid})<br/>${ac.name||''}<br/>${dca.radial_range} — Alt: ${altitude} ft GS: ${groundspeed}<br/>${dep || '-'} → ${arr || '-'}<br/><em>${status.toUpperCase()}</em></div>`;
      marker.bindPopup(popup);
      // show full flight plan in a tooltip on hover if available
      try{
        const fp = ac.flight_plan ? (typeof ac.flight_plan === 'object' ? JSON.stringify(ac.flight_plan, null, 2) : String(ac.flight_plan)) : '';
        if(fp){
          marker.bindTooltip(`<pre class="fp">${fp.replace(/</g, '&lt;')}</pre>`, {direction:'top', className:'fp-tooltip', sticky:true});
        }
      }catch(e){/* ignore tooltip errors */}
      markerGroup.addLayer(marker);
    }

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
  }

  // UI interactions
  el('apply').addEventListener('click', ()=>{ setPermalink(); refresh(); });
  el('refresh').addEventListener('click', ()=>refresh());
  el('toggle-sfra').addEventListener('change', ()=>{ if(overlays.sfra){ if(el('toggle-sfra').checked) overlays.sfra.addTo(map); else map.removeLayer(overlays.sfra); }});
  el('toggle-frz').addEventListener('change', ()=>{ if(overlays.frz){ if(el('toggle-frz').checked) overlays.frz.addTo(map); else map.removeLayer(overlays.frz); }});
  el('toggle-p56').addEventListener('change', ()=>{ if(overlays.p56){ if(el('toggle-p56').checked) overlays.p56.addTo(map); else map.removeLayer(overlays.p56); }});

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
  loadOverlays().then(()=>refresh());
  window.setInterval(refresh, REFRESH);

})();
