// ── map ───────────────────────────────────────────────────────────────────────
const map = L.map('map', { center:[20,0], zoom:2, zoomControl:true });
L.maplibreGL({
  style: 'https://api.maptiler.com/maps/01a17dd7-9b9f-7958-952b-29245fa7b0b6/style.json?key=5miHE96oeLhxy700Wy9w',
  attribution: '© <a href="https://www.maptiler.com/">MapTiler</a> © OpenStreetMap contributors'
}).addTo(map);



function makeIcon(isNew) {
  return L.divIcon({
    className:'',
    html:`<div style="width:12px;height:12px;border-radius:50%;background:${isNew?'#00ff41':'#00aa2a'};border:2px solid ${isNew?'#00ff41':'#1a4a1a'};box-shadow:0 0 ${isNew?'12px':'6px'} ${isNew?'#00ff41':'#00aa2a'}"></div>`,
    iconSize:[12,12], iconAnchor:[6,6]
  });
}

// ── state ─────────────────────────────────────────────────────────────────────
let knownIds = new Set(), markers = {}, allPings = [], selected = null;
let notesCache = {}, labelsCache = {};

// ── tier badge ────────────────────────────────────────────────────────────────
function tierLabel(ping) {
  const tier = ping.method_tier || 4;
  const acc  = ping.accuracy_m;
  const cols = {1:'#00ff41',2:'#00cc33',3:'#ffb800',4:'#ff6600'};
  const lbls = {1:'GPS',2:'WiFi-API',3:'WiFi-BSSID',4:'IP-GEO'};
  const c = cols[tier]||'#ff6600', l = lbls[tier]||'IP-GEO';
  return `<span style="color:${c};font-size:9px;border:1px solid ${c};padding:1px 4px;margin-right:4px">${l}</span><span style="color:var(--text-dim);font-size:9px">${acc?'±'+acc+'m':''}</span>`;
}

// ── render ping item ──────────────────────────────────────────────────────────
function renderPingItem(ping, index, isNew) {
  const div = document.createElement('div');
  div.className = 'ping-item' + (isNew ? ' new' : '');
  div.dataset.index = index;
  const id    = pingId(ping);
  const note  = notesCache[id]  || '';
  const label = labelsCache[ping.hostname] || '';
  div.innerHTML = `
    <div class="ping-num">#${String(index+1).padStart(3,'0')} ${tierLabel(ping)}</div>
    <div class="ping-host">${ping.hostname||'unknown'} @ ${ping.user||'?'}${label ? `<span class="ping-label-tag">${label}</span>` : ''}</div>
    <div class="ping-location">⌖ ${ping.city||'?'}, ${ping.country||'?'}</div>
    <div class="ping-ip">${ping.ip||'—'} · ${ping.isp||'—'}</div>
    <div class="ping-time">${ping.timestamp||'—'} UTC</div>
    <div class="ping-coords">${ping.lat}, ${ping.lon}</div>
    ${note ? `<div class="ping-note-preview">✎ ${note}</div>` : ''}
  `;
  div.addEventListener('click', () => selectPing(index));
  return div;
}

// ── ping id ─────────────────────────────────────────────────────────────────
function pingId(ping) {
  return `${ping.timestamp}${ping.hostname}${ping.ip}`.replace(/\s/g,'');
}

// ── accuracy circle ───────────────────────────────────────────────────────────
let accuracyCircle = null;
function showAccuracyCircle(ping) {
  if (accuracyCircle) { map.removeLayer(accuracyCircle); accuracyCircle = null; }
  if (!ping.accuracy_m || ping.accuracy_m > 50000) return;
  const cols = {1:'#00ff41',2:'#00cc33',3:'#ffb800',4:'#ff6600'};
  const col  = cols[ping.method_tier] || '#ff6600';
  accuracyCircle = L.circle([ping.lat, ping.lon], {
    radius:ping.accuracy_m, color:col, fillColor:col,
    fillOpacity:.07, weight:1, dashArray:'4 4'
  }).addTo(map);
}

// ── select ping ───────────────────────────────────────────────────────────────
function selectPing(index) {
  const ping = allPings[index];
  if (!ping) return;
  selected = index;

  const zoom = ping.method_tier <= 2 ? 15 : ping.method_tier === 3 ? 13 : 10;
  map.flyTo([ping.lat, ping.lon], zoom, { duration:1.2 });
  showAccuracyCircle(ping);

  Object.values(markers).forEach(m => { m.setIcon(makeIcon(false)); m.setZIndexOffset(0); });
  const key = `${ping.lat},${ping.lon}`;
  if (markers[key]) { markers[key].setIcon(makeIcon(true)); markers[key].setZIndexOffset(1000); }

  document.querySelectorAll('.ping-item').forEach(el => el.classList.remove('selected'));
  const el = document.querySelector(`.ping-item[data-index="${index}"]`);
  if (el) el.classList.add('selected');

  const id    = pingId(ping);
  const note  = notesCache[id] || '';
  const label = labelsCache[ping.hostname] || '';
  const cols  = {1:'#00ff41',2:'#00cc33',3:'#ffb800',4:'#ff6600'};
  const tc    = cols[ping.method_tier] || '#ff6600';

  document.getElementById('detail-content').innerHTML = `
    <div class="detail-row"><span class="detail-key">host</span><span class="detail-val">${ping.hostname||'—'}</span></div>
    <div class="detail-row"><span class="detail-key">user</span><span class="detail-val">${ping.user||'—'}</span></div>
    <div class="detail-row"><span class="detail-key">os</span><span class="detail-val">${ping.os||'—'}</span></div>
    <div class="detail-row"><span class="detail-key">ip</span><span class="detail-val">${ping.ip||'—'}</span></div>
    <div class="detail-row"><span class="detail-key">isp</span><span class="detail-val">${ping.isp||'—'}</span></div>
    <div class="detail-row"><span class="detail-key">location</span><span class="detail-val">${ping.city}, ${ping.region}, ${ping.country}</span></div>
    <div class="detail-row"><span class="detail-key">coords</span><span class="detail-val">${ping.lat}, ${ping.lon}</span></div>
    <div class="detail-row"><span class="detail-key">accuracy</span><span class="detail-val" style="color:${tc}">±${ping.accuracy_m||'?'}m — ${ping.method||'?'}</span></div>
    <div class="detail-row"><span class="detail-key">time</span><span class="detail-val">${ping.timestamp} UTC</span></div>

    <div style="margin-top:10px;border-top:1px solid var(--green-muted);padding-top:10px">
      <div class="label-row">
        <span style="font-size:9px;color:var(--text-dim);min-width:70px">host label</span>
        <input class="label-input" id="label-input" placeholder="e.g. Target A / test machine" value="${label}"/>
      </div>
      <div style="font-size:9px;color:var(--text-dim);margin-bottom:4px">note</div>
      <textarea class="notes-area" id="note-input" placeholder="add a note about this ping...">${note}</textarea>
      <div style="display:flex;align-items:center">
        <button class="save-note-btn" onclick="saveNote('${id}','${ping.hostname}')">[ SAVE ]</button>
        <span class="save-ok" id="save-ok">✓ saved</span>
      </div>
    </div>
  `;
}

// ── save note + label ─────────────────────────────────────────────────────────
async function saveNote(id, hostname) {
  const note  = document.getElementById('note-input').value;
  const label = document.getElementById('label-input').value;

  const r1 = await fetch('/api/note',  { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id, note}) });
  const r2 = await fetch('/api/label', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({hostname, label}) });
  if (r1.status === 401 || r2.status === 401) { location.href = '/'; return; }

  notesCache[id]        = note;
  labelsCache[hostname] = label;

  const ok = document.getElementById('save-ok');
  ok.style.opacity = '1';
  setTimeout(() => ok.style.opacity = '0', 2000);

  const idx = allPings.findIndex(p => pingId(p) === id);
  if (idx >= 0) {
    const list    = document.getElementById('ping-list');
    const oldItem = list.querySelector(`.ping-item[data-index="${idx}"]`);
    if (oldItem) {
      const newItem = renderPingItem(allPings[idx], idx, false);
      newItem.classList.add('selected');
      list.replaceChild(newItem, oldItem);
    }
  }
}

// ── add map marker ────────────────────────────────────────────────────────────
function addMarker(ping, isNew) {
  if (ping.lat == null || ping.lon == null) return;
  const key = `${ping.lat},${ping.lon}`;
  const popupHtml = `<div style="font-family:'Share Tech Mono',monospace;font-size:11px;color:#00ff41;background:#0d1318;padding:8px;border:1px solid #1a4a1a"><b>${ping.hostname||'unknown'}</b><br>${ping.city}, ${ping.country}<br><span style="color:#4a6a4a">${ping.ip}</span></div>`;
  if (markers[key]) {
    markers[key].setIcon(makeIcon(isNew));
  } else {
    markers[key] = L.marker([ping.lat, ping.lon], { icon:makeIcon(isNew) })
      .addTo(map)
      .bindPopup(L.popup({ className:'dark-popup', closeButton:false, maxWidth:200 }).setContent(popupHtml));
    markers[key].on('click', () => {
      const idx = allPings.findIndex(p => p.lat===ping.lat && p.lon===ping.lon);
      if (idx >= 0) selectPing(idx);
    });
  }
}

// ── stats ─────────────────────────────────────────────────────────────────────
function updateStats() {
  document.getElementById('total-count').textContent = allPings.length;
  document.getElementById('unique-hosts').textContent = new Set(allPings.map(p=>p.hostname)).size;
  if (allPings.length > 0) {
    const last = allPings[allPings.length-1];
    document.getElementById('last-seen').textContent = last.timestamp ? last.timestamp.split(' ')[1] : '—';
  }
  document.getElementById('ping-count').textContent = `${allPings.length} ping${allPings.length!==1?'s':''}`;
}

// ── clear confirm ─────────────────────────────────────────────────────────────
function confirmClear() { document.getElementById('confirm-overlay').classList.add('show'); }
function cancelClear()  { document.getElementById('confirm-overlay').classList.remove('show'); }
async function doClear() {
  const r = await fetch('/api/clear', { method:'POST' });
  if (r.status === 401) { location.href = '/'; return; }
  cancelClear();
  allPings=[]; knownIds=new Set(); notesCache={}; labelsCache={};
  Object.values(markers).forEach(m => map.removeLayer(m));
  markers={};
  if (accuracyCircle) { map.removeLayer(accuracyCircle); accuracyCircle=null; }
  document.getElementById('ping-list').innerHTML = '<div id="empty-state">[ ping log cleared ]</div>';
  document.getElementById('detail-content').innerHTML = 'click a ping to inspect';
  updateStats();
}

// ── poll (single combined endpoint — lighter on free-tier limits) ─────────────
async function poll() {
  try {
    const res = await fetch('/api/state');
    if (res.status === 401) { location.href = '/'; return; }
    const { pings, notes, labels } = await res.json();
    notesCache  = notes  || {};
    labelsCache = labels || {};

    const list  = document.getElementById('ping-list');
    const empty = document.getElementById('empty-state');
    let hasNew  = false;

    pings.forEach((ping) => {
      const id = pingId(ping);
      if (!knownIds.has(id)) {
        knownIds.add(id);
        allPings.push(ping);
        hasNew = true;
        if (empty) empty.remove();
        list.insertBefore(renderPingItem(ping, allPings.length-1, true), list.firstChild);
        addMarker(ping, true);
      }
    });

    if (hasNew) updateStats();
  } catch(e) { console.warn('poll error', e); }
}

poll();
setInterval(poll, 5000);
