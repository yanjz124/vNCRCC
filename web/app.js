// Simple dashboard app that queries the API endpoints and renders lists + map.
(function(){
  const API_ROOT = window.location.origin + '/api/v1';
  const DCA = [38.8514403, -77.0377214];
  const REFRESH = 15000;

  const el = id => document.getElementById(id);

  const params = new URLSearchParams(window.location.search);
  const defaultRange = params.get('vso_range') || '60';
  const defaultAff = params.get('vso_aff') || '';

  el('vso-range').value = defaultRange;
  el('vso-aff').value = defaultAff;

  const map = L.map('map').setView(DCA, 10);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:''}).addTo(map);
  const sfraLayer = L.layerGroup().addTo(map);

  function setPermalink(){
    const r = el('vso-range').value;
    const a = el('vso-aff').value;
    const p = new URL(window.location.href);
    p.searchParams.set('vso_range', r);
    if(a) p.searchParams.set('vso_aff', a); else p.searchParams.delete('vso_aff');
    el('permalink').href = p.toString();
  }

  async function fetchSFRA(){
    const res = await fetch(`${API_ROOT}/sfra/`);
    if(!res.ok) return [];
    const j = await res.json();
    return j.aircraft || [];
  }
  async function fetchFRZ(){
    const res = await fetch(`${API_ROOT}/frz/`);
    if(!res.ok) return [];
    const j = await res.json();
    return j.aircraft || [];
  }
  async function fetchP56(){
    const res = await fetch(`${API_ROOT}/p56/`);
    if(!res.ok) return {breaches:[], history:{}};
    return await res.json();
  }
  async function fetchVSO(){
    const r = encodeURIComponent(el('vso-range').value || '60');
    const a = encodeURIComponent(el('vso-aff').value || '');
    const url = `${API_ROOT}/vso/?range_nm=${r}` + (a?`&affiliations=${a}`:'');
    const res = await fetch(url);
    if(!res.ok) return [];
    const j = await res.json();
    return j.aircraft || [];
  }

  function renderList(containerId, items, formatter){
    const ul = el(containerId);
    ul.innerHTML = '';
    items.forEach(it=>{
      const li = document.createElement('li');
      li.innerHTML = formatter(it);
      ul.appendChild(li);
    });
  }

  function dcaText(dca){
    if(!dca) return '';
    return `${dca.radial_range} (${dca.range_nm} nm @ ${dca.bearing}°)`;
  }

  async function refresh(){
    setPermalink();
    // SFRA
    const sfra = await fetchSFRA();
    el('sfra-count').textContent = sfra.length;
    renderList('sfra-list', sfra, it=>{
      const ac = it.aircraft || it;
      return `<strong>${ac.callsign||ac.callsign}</strong> — ${ac.latitude?.toFixed?.(5)||''}, ${ac.longitude?.toFixed?.(5)||''} — ${dcaText(it.dca)}`;
    });

    // update map markers
    sfraLayer.clearLayers();
    sfra.forEach(it=>{
      const ac = it.aircraft || it;
      if(ac.latitude==null) return;
      const m = L.circleMarker([ac.latitude, ac.longitude], {radius:6, color:'#d33'}).addTo(sfraLayer);
      const popup = `<div><b>${ac.callsign||ac.callsign}</b><br/>${ac.name || ''}<br/>${dcaText(it.dca)}<br/>RMK: ${((ac.flight_plan||{}).remarks||'')}</div>`;
      m.bindPopup(popup);
    });

    // FRZ
    const frz = await fetchFRZ();
    el('frz-count').textContent = frz.length;
    renderList('frz-list', frz, it=>{
      const ac = it.aircraft || it;
      return `<strong>${ac.callsign||''}</strong> — ${ac.latitude?.toFixed?.(5)||''}, ${ac.longitude?.toFixed?.(5)||''} — ${dcaText(it.dca)}`;
    });

    // P56
    const p56 = await fetchP56();
    const breaches = p56.breaches || [];
    el('p56-count').textContent = breaches.length;
    el('p56-details').textContent = JSON.stringify(p56.history || {}, null, 2);

    // VSO
    const vso = await fetchVSO();
    el('vso-count').textContent = vso.length;
    renderList('vso-list', vso, it=>{
      const ac = it.aircraft || it;
      const matched = (it.matched_affiliations||[]).join(', ');
      return `<strong>${ac.callsign||''}</strong> — ${ac.latitude?.toFixed?.(5)||''}, ${ac.longitude?.toFixed?.(5)||''} — ${dcaText(it.dca)} <br/><em>${matched}</em>`;
    });
  }

  el('apply').addEventListener('click', ()=>{ setPermalink(); refresh(); });
  el('refresh').addEventListener('click', ()=>refresh());

  // set initial permalink
  setPermalink();
  refresh();
  window.setInterval(refresh, REFRESH);

})();
