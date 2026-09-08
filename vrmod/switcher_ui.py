"""Browser UI for the game's Data folder -- a modern replacement for TrackMan.

ONE view over one live folder: a library grid of every track and car, beside a
detail pane for whatever is selected. The pane embeds the very same viewer or
car-shell page the server already serves, in an iframe, so browsing and modding
stop being separate browser tabs -- and modding needed no new code, because
those pages already carry the Textures/Parts/Sound drawers and their own Save.

There was briefly a separate "Game" tab for what is installed. It turned out to
be the same data and the same actions behind a second navigation concept, so it
collapsed into an "In game" filter chip plus a toolbar carrying the two things
that were genuinely not per-item: the car-selector capacity, and Restore all.

The detail pane's action bar is deliberately split -- view controls (Drive,
Expand) on the left, controls that change the GAME (Install, Restore, Add to
game) on the right, advisories on their own line above both. See actionBar().

Both asset types turn out to be the same shape: limited capacity in the game,
unlimited library on disk. Tracks have 8 named slots; cars have no slots at
all, just however many .car files are present, bounded by what the game's
selector can draw (see CAR_SELECTOR_CAP).

View pages are built per request rather than generated up front, which is the
whole reason to run this as a server instead of using the `gallery` command: a
shell page embeds every mesh, texture and sound it needs, so pre-building a
folder of them costs megabytes you mostly never open. `gallery` still exists
for when a portable folder of pages IS the point.

Deliberately a local web app rather than a native GUI: the UI is HTML, so it
reuses viewer.py's WebGL track viewer directly and lets a slot be previewed
in actual 3D instead of a static screenshot. Wrapping this same page in a
real app window later (pywebview over Edge WebView2) needs no UI changes,
which is why the markup is kept free of anything browser-chrome specific.

The server binds to 127.0.0.1 only. It writes to the game's Data folder, so
it must never be reachable from off-machine.
"""
from __future__ import annotations

import functools
import http.server
import json
import threading
import webbrowser
from pathlib import Path

from . import aifield, archive, carshot, cf, doctor, envelope, grf, hornball, mod as mod_mod, patchset, primarycar, resolution, stp, switcher, track as track_mod, trackmap, vertexbuffer, viewer, vrampatch

_PAGE = r"""<!doctype html>
<meta charset="utf-8"><title>Viper Racing -- Mod Manager</title>
<style>
:root{--bg:#15171c;--panel:#1d2027;--edge:#2c313b;--fg:#e6e8ec;--dim:#9aa1ad;
      --acc:#5aa9e6;--ok:#4bbf73;--warn:#e0a33e;--bad:#e0574a;}
*{box-sizing:border-box}
/* Author rules on layout containers outrank the UA stylesheet's [hidden]
   regardless of specificity, so hiding a view needs this to actually bite. */
[hidden]{display:none!important}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--fg);height:100vh;display:flex;
     flex-direction:column;overflow:hidden;
     font:14px/1.5 "Segoe UI",system-ui,sans-serif}
header{padding:0 20px;height:52px;flex:none;border-bottom:1px solid var(--edge);
       display:flex;align-items:center;gap:16px}
h1{font-size:15px;margin:0;font-weight:600;letter-spacing:.01em}
header .path{color:var(--dim);font-size:11.5px;margin-left:auto;
             font-family:ui-monospace,Consolas,monospace}
h2{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim);
   margin:0 0 10px;font-weight:600}
#health{font-size:11.5px;padding:4px 11px;border-radius:99px}
#health.ok,#health.info{border-color:#25402c;color:var(--ok)}
#health.warn{border-color:#4a3a1a;color:var(--warn)}
#health.bad{border-color:#5a2f2b;color:var(--bad)}
#health-panel{position:absolute;right:20px;top:56px;width:min(560px,calc(100vw - 40px));
  max-height:70vh;overflow-y:auto;background:var(--panel);border:1px solid var(--edge);
  border-radius:10px;padding:14px 16px;z-index:30;box-shadow:0 12px 34px rgba(0,0,0,.5)}
#health-panel .f{padding:9px 0;border-top:1px solid var(--edge)}
#health-panel .f:first-child{border-top:0}
#health-panel .t{font-weight:600;font-size:13px;display:flex;gap:8px;align-items:baseline}
#health-panel .d{color:var(--dim);font-size:12px;margin-top:3px}
#health-panel .x{margin-top:5px;font-size:12px;color:var(--acc)}
#health-panel .dot{width:8px;height:8px;border-radius:50%;flex:none;margin-top:5px}
.dot.ok,.dot.info{background:var(--ok)} .dot.warn{background:var(--warn)}
.dot.bad{background:var(--bad)}
.toolbar{display:flex;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap}
.toolbar .cap{margin-left:auto;color:var(--dim);font-size:12px;
              font-variant-numeric:tabular-nums}
.toolbar .cap b{color:var(--fg)}
button{background:#2a2f3a;color:var(--fg);border:1px solid var(--edge);
       border-radius:6px;padding:6px 11px;font:inherit;font-size:12px;cursor:pointer}
button:hover:not(:disabled){background:#333a47;border-color:#454e5e}
button:disabled{opacity:.35;cursor:default}
button.primary{background:var(--acc);border-color:var(--acc);color:#0d1620;font-weight:600}
button.primary:hover:not(:disabled){background:#6fb6ea}
button.danger{border-color:#5a2f2b;color:#f0a49b}
select{background:#2a2f3a;color:var(--fg);border:1px solid var(--edge);
       border-radius:6px;padding:6px;font:inherit;font-size:12px}
main{flex:1;min-height:0;overflow:hidden}

/* ---- Library: a scrolling grid beside a detail pane ---- */
#view-library{display:grid;grid-template-columns:var(--lib-w,54%) 7px 1fr;height:100%}
/* Drag handle between the panes. A grid track of its own rather than an
   absolutely-positioned overlay, so it can never drift out of alignment. */
#splitter{cursor:col-resize;background:var(--edge);position:relative}
#splitter:hover,#splitter.dragging{background:var(--acc)}
#splitter::after{content:"";position:absolute;inset:0 -4px}   /* wider grab area */
body.resizing{cursor:col-resize;user-select:none}
body.resizing #frame{pointer-events:none}   /* keep the drag out of the iframe */
/* Driving wants the whole window: the track viewer reserves a fixed 320px for
   its own Textures drawer, so in a 46% pane the 3D canvas is a sliver. Expanded
   hands the pane the full width instead of trying to make the viewer shrink. */
#view-library.expanded{grid-template-columns:0 0 1fr}
/* Collapse the library by zeroing its column and clipping it -- NOT with
   display:none, which drops it out of the grid entirely and leaves the detail
   pane sitting in the zero-width first track. */
#view-library.expanded #lib{overflow:hidden;visibility:hidden;padding:0;border-right:0}
#lib{overflow-y:auto;padding:16px 18px}
.chips{display:flex;gap:6px}
.chips button.on{background:#2f3846;border-color:#4a5566;color:var(--fg);font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px}
.item{background:var(--panel);border:1px solid var(--edge);border-radius:8px;padding:9px;
      cursor:pointer;display:flex;flex-direction:column;gap:7px;text-align:left}
.item:hover{border-color:#454e5e;background:#212530}
.item.sel{border-color:var(--acc);background:#1f2733}
.item .shots{display:flex;gap:5px}
.item .shot,.item .map{flex:1 1 0;min-width:0;height:62px;border-radius:4px;
      background:#000;border:1px solid #10131a}
.item .shot{object-fit:cover}
.item .shot.gen{object-fit:contain;background:#12141a}
.item .carshot{flex:1 1 0;min-width:0;height:80px;border-radius:4px;background:#191c22;
      border:1px solid #10131a;object-fit:contain}
.item .map{object-fit:contain}
.item .nm{font-weight:600;font-size:13px;text-transform:capitalize;
          white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.item .sub{color:var(--dim);font-size:11.5px;font-family:ui-monospace,Consolas,monospace;
           white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.item .spec{display:flex;gap:11px;font-size:11px;color:var(--dim);
            font-variant-numeric:tabular-nums}
.item .spec b{color:var(--fg);font-weight:600}
/* Mesh size gets its own line rather than a third item on the spec row: at a
   narrow pane three values truncated, and this one needs room to say what it
   means. Wraps instead of ellipsing, because a half-shown warning is worse
   than a two-line one. */
.item .meta{font-size:11px;color:var(--dim);line-height:1.35;
            font-variant-numeric:tabular-nums}
.item .meta.w{color:var(--warn)}
.badge{font-size:10.5px;padding:1px 7px;border-radius:99px;white-space:nowrap}
.badge.stock{background:#1e3326;color:var(--ok)}
.badge.mod{background:#3a2f18;color:var(--warn)}
.badge.live{background:#1c2c3a;color:var(--acc)}
.item .top{display:flex;justify-content:space-between;align-items:center;gap:6px}
.item .top .tags{display:flex;align-items:center;gap:6px;flex:none}
/* "In the game" is a quiet status dot, not a badge: the library is a gallery
   first, so which mods are live is a glance, not a label competing with the
   card's own name and attributes. Same dot for cars and tracks. */
.item .ingame{width:8px;height:8px;border-radius:50%;background:var(--acc);
              flex:none;box-shadow:0 0 0 3px rgba(90,169,230,.16)}

/* ---- Detail: the existing viewer pages, embedded rather than popped out ---- */
#detail{display:flex;flex-direction:column;min-width:0;height:100%}
#frame-wrap{flex:1;min-height:0;position:relative;background:#0f1115}
#frame{width:100%;height:100%;border:0;display:block}
/* Two kinds of control share this bar and should not read as one list: the
   left group changes how you are LOOKING at the thing, the right group changes
   the GAME. Anything advisory goes on its own line above both, so a long
   warning cannot push the buttons around. */
#detail .act{padding:12px 18px;border-top:1px solid var(--edge);flex:none;
             display:flex;flex-direction:column;gap:9px}
#detail .act .line{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
#detail .act .grp{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
#detail .act .grp.game{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
#detail .act .msg{font-size:12px;color:var(--dim);display:flex;gap:10px;
                  align-items:center;flex-wrap:wrap}
#detail .act .msg.warn{color:var(--warn)}
.placeholder{height:100%;display:flex;align-items:center;justify-content:center;
             color:var(--dim);font-style:italic;padding:30px;text-align:center}
.plan{background:#171a20;border:1px solid var(--edge);border-radius:6px;padding:10px;
      margin:0 18px 12px;font-size:12.5px}
.plan ul{margin:0;padding-left:18px}
.plan li{margin:3px 0}
.w{color:var(--warn)}
.e{color:var(--bad)}

.empty{color:var(--dim);padding:10px;font-style:italic}
#toast{position:fixed;right:20px;bottom:20px;background:var(--panel);
       border:1px solid var(--edge);border-left:3px solid var(--acc);
       border-radius:6px;padding:11px 15px;max-width:420px;display:none;
       white-space:pre-wrap;font-size:13px;z-index:20}

/* --- View nav (Library / Game) ------------------------------------------- */
.viewnav{display:flex;gap:2px;background:var(--bg);border:1px solid var(--edge);
         border-radius:8px;padding:2px}
.viewnav button{background:none;border:0;color:var(--dim);font:inherit;
                font-size:12.5px;padding:5px 15px;border-radius:6px;cursor:pointer}
.viewnav button:hover{color:var(--fg)}
.viewnav button.on{background:var(--panel);color:var(--fg);
                   box-shadow:0 1px 2px rgba(0,0,0,.3)}

/* --- Game configurator --------------------------------------------------- */
#view-game{flex:1;overflow-y:auto;min-height:0}
.config{max-width:940px;margin:0 auto;padding:26px 24px 60px;
        display:flex;flex-direction:column;gap:18px}
.panel{background:var(--panel);border:1px solid var(--edge);border-radius:12px;
       padding:20px 22px}
.panel-head{display:flex;align-items:baseline;gap:10px;margin:0 0 4px}
.panel-head h2{margin:0}
.panel-head .note{color:var(--dim);font-size:12px;margin-left:auto}
.panel .lede{color:var(--dim);font-size:12.5px;margin:0 0 16px}

/* stepper */
.stepper{display:flex;align-items:center;gap:0;border:1px solid var(--edge);
         border-radius:8px;overflow:hidden;width:max-content}
.stepper button{width:38px;height:38px;background:var(--bg);border:0;color:var(--fg);
                font-size:19px;line-height:1;cursor:pointer}
.stepper button:hover:not(:disabled){background:var(--edge)}
.stepper button:disabled{color:var(--edge);cursor:default}
.stepper .val{min-width:54px;text-align:center;font-size:19px;font-weight:600;
              font-variant-numeric:tabular-nums}
.ai-row{display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.ai-row .field-label{font-size:11px;text-transform:uppercase;letter-spacing:.08em;
                     color:var(--dim);display:block;margin-bottom:7px;font-weight:600}
.ai-total{color:var(--dim);font-size:12.5px}
.ai-total b{color:var(--fg);font-weight:600}

/* toggle switch */
.tgl{position:relative;display:inline-flex;align-items:center;gap:10px;cursor:pointer;
     font-size:13px;color:var(--fg)}
.tgl input{position:absolute;opacity:0;width:0;height:0}
.tgl .track{width:38px;height:21px;border-radius:99px;background:var(--edge);
            flex:none;transition:background .15s;position:relative}
.tgl .track::after{content:"";position:absolute;top:2px;left:2px;width:17px;height:17px;
                   border-radius:50%;background:#fff;transition:transform .15s}
.tgl input:checked + .track{background:var(--acc)}
.tgl input:checked + .track::after{transform:translateX(17px)}

/* roster / slot grids inside the config */
.rost{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px}
.rost-item{display:flex;align-items:center;gap:11px;background:var(--bg);
           border:1px solid var(--edge);border-radius:9px;padding:9px 12px}
.rost-item .nm{font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rost-item .sub{color:var(--dim);font-size:11px}
.rost-item .grow{flex:1;min-width:0}
.badge{font-size:10px;text-transform:uppercase;letter-spacing:.06em;font-weight:600;
       padding:2px 7px;border-radius:99px;border:1px solid;flex:none}
.badge.ai{color:var(--acc);border-color:#2c4a63}
.badge.active{color:var(--ok);border-color:#25402c}
.mini{background:var(--bg);border:1px solid var(--edge);color:var(--fg);font:inherit;
      font-size:12px;padding:5px 12px;border-radius:7px;cursor:pointer;flex:none}
.mini:hover{border-color:var(--acc);color:var(--acc)}
.mini.on{background:var(--acc);border-color:var(--acc);color:#08131d}

/* fixes checklist */
.fix{display:flex;align-items:flex-start;gap:12px;padding:12px 0;
     border-top:1px solid var(--edge)}
.fix:first-child{border-top:0}
.fix .dot{width:9px;height:9px;border-radius:50%;flex:none;margin-top:5px}
.fix .dot.ok{background:var(--ok)} .fix .dot.warn{background:var(--warn)}
.fix .dot.bad{background:var(--bad)} .fix .dot.info{background:var(--acc)}
.fix .body{flex:1;min-width:0}
.fix .t{font-size:13px;font-weight:600}
.fix .d{color:var(--dim);font-size:12px;margin-top:2px}
.fix .d a{color:var(--acc)}

/* --- Landing screen (no folder chosen) ---------------------------------- */
#view-landing{flex:1;display:flex;align-items:center;justify-content:center;min-height:0}
.landing{max-width:440px;text-align:center;padding:32px}
.landing .mark{font-size:52px;line-height:1;margin-bottom:14px}
.landing h2{font-size:22px;margin:0 0 10px;color:var(--fg);text-transform:none;
            letter-spacing:0}
.landing p{color:var(--dim);font-size:14px;margin:0 0 20px}
.landing .hint{font-size:12px;margin-top:18px}
.landing code{background:var(--bg);border:1px solid var(--edge);border-radius:4px;
              padding:1px 5px;font-size:11.5px}
#landing-btn{font-size:14px;padding:11px 22px;border-radius:9px;background:var(--acc);
             color:#08131d;border:0;font-weight:600;cursor:pointer}
#landing-btn:hover{filter:brightness(1.08)}
#change-folder{font-size:11.5px;padding:4px 11px;border-radius:99px;background:var(--panel);
               border:1px solid var(--edge);color:var(--dim);cursor:pointer}
#change-folder:hover{color:var(--fg);border-color:var(--acc)}
header .path{cursor:default}
</style>
<header>
  <h1>Viper Racing</h1>
  <nav class="viewnav" id="viewnav" hidden>
    <button id="nav-library" class="on" onclick="switchView('library')">Library</button>
    <button id="nav-game" onclick="switchView('game')">Game</button>
  </nav>
  <span class="path" id="dir"></span>
  <button id="change-folder" onclick="chooseFolder()" hidden title="Choose a different Data folder">Change folder</button>
  <!-- Install health lives behind a chip rather than a second screen: it is
       something you check occasionally, not a place you work. -->
  <button id="health" onclick="toggleHealth()" hidden></button>
</header>
<div id="health-panel" hidden><div class="inner" id="health-list"></div></div>

<!-- The opening screen: no folder chosen yet. The desktop app starts here; a
     native folder picker (or a typed path in a plain browser) sets the folder. -->
<main id="view-landing" hidden>
  <div class="landing">
    <div class="mark">🏁</div>
    <h2>Viper Racing Mod Manager</h2>
    <p>Choose your Viper Racing <b>Data</b> folder to get started.</p>
    <button id="landing-btn" onclick="chooseFolder()">Choose Data folder…</button>
    <p class="hint">The folder containing <code>race.bin</code> and your <code>.car</code> files.</p>
  </div>
</main>

<!-- The Game tab: a configurator for the game as a whole (opponents, cars,
     tracks, fixes), as opposed to Library which is for editing one asset. -->
<main id="view-game" hidden><div class="config" id="config"></div></main>

<main id="view-library" hidden>
  <section id="lib">
    <!-- Library is for editing ONE asset; the "In game" chip just filters this
         same grid to what is installed. The whole-game settings that don't belong
         to any single asset -- AI field size, the AI's shared car, install fixes --
         live in the separate Game view (the configurator) instead. -->
    <div class="toolbar">
      <div class="chips">
        <button id="chip-all" class="on" onclick="setFilter('all')">All</button>
        <button id="chip-track" onclick="setFilter('track')">Tracks</button>
        <button id="chip-car" onclick="setFilter('car')">Cars</button>
        <button id="chip-ingame" onclick="setFilter('ingame')">In game</button>
      </div>
      <span class="cap" id="cap"></span>
      <button class="danger" id="restoreAll">Restore all slots</button>
    </div>
    <div class="grid" id="grid"></div>
  </section>
  <div id="splitter" title="Drag to resize"></div>
  <section id="detail">
    <div id="detail-body" class="placeholder">Pick something on the left to view it in 3D,
      change its textures, or put it in the game.</div>
  </section>
</main>

<div id="toast"></div>
<script>
let STATE = null, SEL = null, FILTER = 'all', VIEW = 'library', AI_MOD = '';

const api = (p, body) => fetch(p, body ? {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
  } : undefined).then(r => r.json());

const el$ = (id) => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function toast(msg, kind){
  const t = el$('toast');
  t.textContent = msg;
  t.style.borderLeftColor = kind==='bad' ? 'var(--bad)' : kind==='warn' ? 'var(--warn)' : 'var(--acc)';
  t.style.display = 'block';
  clearTimeout(t._h); t._h = setTimeout(()=>t.style.display='none', 6000);
}

function setFilter(f){
  FILTER = f;
  for(const c of ['all','track','car','ingame']) el$('chip-'+c).classList.toggle('on', c === f);
  renderLibrary();
  renderToolbar();          // caption follows the filter (cars / tracks / both)
}

function toggleHealth(){
  const p = el$('health-panel');
  p.hidden = !p.hidden;
  if(!p.hidden) loadHealth();          // re-check every time the panel opens
}
// A DPI/audio fix is applied OUTSIDE the app (a Windows setting, or dropping DLLs
// in), so re-check when the window regains focus -- otherwise the panel would show
// stale state until a manual page refresh.
window.addEventListener('focus', () => { if(!el$('health-panel').hidden) loadHealth(); });

async function loadHealth(){
  const r = await api('/api/doctor');
  const chip = el$('health');
  const counts = r.findings.reduce((a, f) => (a[f.level] = (a[f.level] || 0) + 1, a), {});
  const bad = (counts.bad || 0), warn = (counts.warn || 0);
  chip.hidden = false;
  chip.className = r.worst;
  chip.textContent = bad ? `Install: ${bad} problem${bad > 1 ? 's' : ''}`
                    : warn ? `Install: ${warn} to check`
                    : 'Install: healthy';
  el$('health-list').innerHTML = r.findings.map(f => `
    <div class="f">
      <div class="t"><span class="dot ${f.level}"></span>${esc(f.title)}</div>
      <div class="d">${esc(f.detail)}</div>
      ${f.fix ? `<div class="x">${esc(f.fix)}</div>` : ''}
      ${f.link ? `<div style="margin-top:5px"><a href="${esc(f.link)}" target="_blank"
        rel="noopener" style="color:var(--acc)">${esc(f.link)} &#8599;</a></div>` : ''}
      ${f.action ? `<div style="margin-top:7px"><button onclick="applyFix('${f.action}')"
        >${({vram:'Apply startup fix',dpi:'Set DPI-aware',patch:'Apply enhancements'})[f.action]
          || 'Apply this fix'}</button></div>` : ''}
    </div>`).join('');
}

async function applyFix(action){
  const r = await api('/api/fix', {action});
  if(!r.ok) return toast(r.error, 'bad');
  toast(r.message);
  await loadHealth();
  if(VIEW === 'game') renderGame();     // the Game tab shows the same fixes
}

async function refresh(){
  STATE = await api('/api/status');
  // No folder chosen -> show the landing screen and stop; everything else needs
  // a Data folder to render.
  const need = !!(STATE && STATE.needs_folder);
  el$('view-landing').hidden = !need;
  el$('viewnav').hidden = need;
  el$('change-folder').hidden = need;
  el$('view-library').hidden = need || VIEW !== 'library';
  el$('view-game').hidden = need || VIEW !== 'game';
  if(need){ el$('dir').textContent = ''; el$('health').hidden = true; return; }
  el$('dir').textContent = STATE.data_dir;
  renderLibrary();
  renderToolbar();
  loadHealth();
  if(VIEW === 'game') renderGame();     // keep the configurator in step
}

// Choose (or change) the Data folder. In the desktop app this opens a native
// folder picker via the pywebview bridge; in a plain browser it falls back to a
// typed path. Either way the server is pointed at the folder and the page reloads.
async function chooseFolder(){
  if(window.pywebview && window.pywebview.api && window.pywebview.api.pick_folder){
    const r = await window.pywebview.api.pick_folder();
    if(r && r.ok) location.reload();
    else if(r && r.error) toast(r.error, 'bad');
    return;
  }
  const path = prompt('Path to your Viper Racing Data folder:');
  if(!path) return;
  const r = await api('/api/set_folder', {path});
  if(r.ok) location.reload(); else toast(r.error, 'bad');
}

// Library edits one asset; Game configures the whole install. They share STATE,
// so every action handler just calls refresh() and the active view re-renders.
function switchView(v){
  VIEW = v;
  el$('nav-library').classList.toggle('on', v === 'library');
  el$('nav-game').classList.toggle('on', v === 'game');
  el$('view-library').hidden = v !== 'library';
  el$('view-game').hidden = v !== 'game';
  if(v === 'game') renderGame();
}

// The two things not per-item: the asset tally and the one bulk action. The
// game has no car limit -- every .car loads -- so this is just counts. The
// caption follows the filter: cars when viewing cars, tracks when viewing
// tracks, both otherwise.
function renderToolbar(){
  const active = STATE.cars.filter(c => c.active).length;
  const aside = STATE.cars.length - active;
  const addons = (STATE.library_tracks || []).filter(t => t.is_addon).length;
  const slots = (STATE.slots || []).length;
  const carsTxt = `<b>${active}</b> car${active===1?'':'s'}${aside ? ` &middot; ${aside} set aside` : ''}`;
  const tracksTxt = `<b>${slots}</b> track${slots===1?'':'s'}${addons ? ` &middot; ${addons} add-on${addons===1?'':'s'}` : ''}`;
  el$('cap').innerHTML = FILTER === 'car' ? carsTxt
                       : FILTER === 'track' ? tracksTxt
                       : `${carsTxt} &nbsp;&middot;&nbsp; ${tracksTxt}`;
  const modded = STATE.slots.filter(s => !s.is_stock).length;
  el$('restoreAll').disabled = modded === 0;
  el$('restoreAll').textContent = modded
    ? `Restore all slots (${modded})` : 'All slots are stock';
}

// ---- Library -------------------------------------------------------------
// One grid over both asset types. A track and a car are different enough that
// their cards show different things (a track is recognised by its shape, a car
// by its numbers), but they sit in one list because "what have I got?" is one
// question, not two.
function libraryItems(){
  const out = [];
  for(const t of STATE.library_tracks) out.push(Object.assign({kind:'track'}, t));
  for(const c of STATE.cars) out.push(Object.assign({kind:'car'}, c));
  if(FILTER === 'ingame') return out.filter(i => i.kind === 'track' ? i.in_slot : i.active);
  return out.filter(i => FILTER === 'all' || i.kind === FILTER);
}

function itemKey(i){ return i.kind + ':' + i.name; }

function trackThumbs(t){
  const game = t.preview ? '/preview/'+encodeURIComponent(t.preview)
             : t.stp ? '/stp/'+encodeURIComponent(t.stp)
             : t.slot ? '/icon/'+t.slot+'.png' : '';
  // No in-game menu picture -> render the track's own 3D mesh (same wireframe
  // look as the car thumbnails) so it still shows something drawn from its
  // geometry rather than a blank. "gen" switches the fit to contain, since a
  // rendered wireframe wants the whole frame, unlike a cropped photo.
  const shot = game || '/trackshot/'+encodeURIComponent(t.name);
  return `<div class="shots">
    <img class="shot${game?'':' gen'}" src="${shot}" alt="" onerror="this.style.visibility='hidden'">
    <img class="map" src="/map/${encodeURIComponent(t.name)}" alt="" onerror="this.style.visibility='hidden'">
  </div>`;
}

function renderLibrary(){
  const items = libraryItems();
  el$('grid').innerHTML = items.length ? items.map(i => {
    const sel = SEL === itemKey(i) ? ' sel' : '';
    if(i.kind === 'track'){
      const tag = i.in_slot ? `<span class="ingame" title="In the game"></span>`
                : i.is_addon ? `<span class="badge mod">add-on</span>` : '';
      return `<div class="item${sel}" onclick="select('${esc(itemKey(i))}')">
        ${trackThumbs(i)}
        <div class="top"><span class="nm">${esc(i.display_name || i.stem)}</span>
          <span class="tags">${tag}</span></div>
        <div class="sub">${esc(i.name)}${i.miles?' · '+i.miles.toFixed(1)+' mi':''}</div>
        ${i.mesh?`<div class="meta">${i.mesh[0].toLocaleString()} vertices · ${
          i.mesh[1].toLocaleString()} faces</div>`:''}
        ${i.occupied_by?`<div class="sub">← ${esc(i.occupied_by)}</div>`:''}
      </div>`;
    }
    return `<div class="item${sel}" onclick="select('${esc(itemKey(i))}')">
      <div class="shots"><img class="carshot" src="/carshot/${encodeURIComponent(i.name)}"
        alt="" loading="lazy" onerror="this.style.visibility='hidden'"></div>
      <div class="top"><span class="nm">${esc(i.stem)}</span>
        <span class="tags">
          ${i.active ? '<span class="ingame" title="In the game"></span>'
                     : '<span class="badge mod">off</span>'}
          ${i.cockpit?'<span class="badge stock">cockpit</span>':''}
        </span></div>
      <div class="sub">${esc(i.name)}</div>
      ${i.error ? `<div class="sub e">${esc(i.error)}</div>` : `
      <div class="spec">
        <span><b>${i.power_max?Math.round(i.power_max):'—'}</b> hp</span>
        <span><b>${i.mass?Math.round(i.mass).toLocaleString():'—'}</b> lb</span>
      </div>
      ${i.peak_vertices?`<div class="meta${i.needs_patch?' w':''}"
        title="${i.needs_patch
          ? 'The largest single part has ' + i.peak_vertices.toLocaleString() +
            ' vertices, over the original game’s limit of 1,200 per object, so this car needs a patched race.bin'
          : 'Vertices in the largest single part. The original game allows 1,200 per object.'}"
        >largest part ${i.peak_vertices.toLocaleString()} v${
          i.needs_patch?' · needs patch':''}</div>`:''}`}
    </div>`;
  }).join('') : '<div class="empty">Nothing of that kind in this folder.</div>';
  renderDetail();
}

function findSelected(){
  return libraryItems().find(i => itemKey(i) === SEL)
      || (STATE ? [].concat(
           STATE.library_tracks.map(t=>Object.assign({kind:'track'},t)),
           STATE.cars.map(c=>Object.assign({kind:'car'},c))
         ).find(i => itemKey(i) === SEL) : null);
}

function select(k){
  if(SEL === k) return;              // don't reload the iframe on a re-click
  SEL = k;
  renderLibrary();
}

// The detail pane embeds the very same page the viewer already serves, rather
// than opening it in another tab. The viewer pages are self-contained, so this
// needs no changes on their side -- it just stops the workflow scattering
// across browser tabs.
function renderDetail(){
  const d = el$('detail');
  const i = findSelected();
  if(!i){
    d.innerHTML = `<div id="detail-body" class="placeholder">Pick something on the left to
      view it in 3D, change its textures, or put it in the game.</div>`;
    return;
  }
  const src = i.kind === 'track' ? '/view/'+encodeURIComponent(i.name)
                                 : '/car/'+encodeURIComponent(i.name);
  let actions;
  if(i.kind === 'car'){
    actions = actionBar({
      game: `<button class="${i.active?'':'primary'}"
              onclick="setCarActive('${esc(i.name)}', ${!i.active})"
              >${i.active?'Remove from game':'Add to game'}</button>`,
      msg: i.active ? 'In the game.' : 'Set aside in the Disabled folder.',
    });
  } else if(i.in_slot){
    actions = actionBar({
      game: `<button class="danger" ${i.is_stock?'disabled':''}
              onclick="restore('${esc(i.slot)}')">Restore original</button>`,
      msg: `<span class="badge live">in game</span> In the ${esc(i.slot)} slot` +
           (i.is_stock ? ', still the stock track.'
                       : `, holding ${esc(i.occupied_by || 'a modified track')}.`),
    });
  } else {
    const opts = STATE.slots.map(s =>
      `<option value="${s.slot}">${esc(s.display_name)} (${s.slot})${s.is_stock?'':' — occupied'}</option>`).join('');
    // The menu picture is offered whether or not one exists -- it is a game
    // asset this tool can write, not just a repair for a missing file, and a
    // track that HAS an ugly one should be replaceable too. The advisory line
    // still calls out the missing case, because that one has consequences.
    actions = actionBar({
      game: `<button onclick="makeShot()">${i.has_shot ? 'Update' : 'Set'} menu picture</button>
             <label class="sub" style="color:var(--dim)">Install into</label>
             <select id="slotSel">${opts}</select>
             <button onclick="preview()">Preview changes</button>
             <button class="primary" onclick="doInstall(false)">Install</button>`,
      msg: i.has_shot ? '' :
        `No menu picture &mdash; the game would show the previous track's.`,
      warn: !i.has_shot,
    });
  }
  // Only rebuild the frame when the source actually changes -- re-rendering the
  // pane on every list repaint would restart a multi-megabyte page load.
  const existing = el$('frame');
  if(existing && existing.dataset.src === src){
    el$('detail-actions').innerHTML = actions;
    return;
  }
  // No title banner here: both embedded pages already label themselves with
  // the same name-over-filename pair, immediately below where a banner would
  // sit. Dropping it removes the duplication and gives the 3D view the space.
  d.innerHTML = `
    <div id="frame-wrap"><iframe id="frame" data-src="${esc(src)}" src="${esc(src)}"></iframe></div>
    <div class="act" id="detail-actions">${actions}</div>
    <div id="plan"></div>`;
}

// One shape for every kind of thing the pane can show: an optional advisory
// line, then view controls on the left and game-changing controls on the right.
// Keeping the split structural means a new action lands on the correct side by
// construction rather than wherever the string happened to be concatenated.
// The footer carries ONLY things that change the game. Looking at the thing
// -- drive, expand, mod -- belongs to the embedded view, which owns its own
// controls and asks us for room through vrmodHost below.
function actionBar({game = '', msg = '', warn = false}){
  return `${msg ? `<div class="msg${warn ? ' warn' : ''}">${msg}</div>` : ''}
    ${game ? `<div class="line"><span class="grp game">${game}</span></div>` : ''}`;
}

// The API the embedded viewer/shell pages call. Same-origin, so they reach it
// as window.parent.vrmodHost with no message plumbing.
window.vrmodHost = {
  isExpanded: () => el$('view-library').classList.contains('expanded'),
  setExpanded: (on) => toggleExpand(!!on),
};

// Same-origin iframe, so the viewer's own controls can just be clicked from
// here rather than inventing a message protocol for them.
function frameDoc(){
  const f = el$('frame');
  try { return f && f.contentDocument; } catch(e) { return null; }
}

function toggleExpand(force){
  const v = el$('view-library');
  const on = force === undefined ? !v.classList.contains('expanded') : force;
  v.classList.toggle('expanded', on);
}

// ---- draggable divider ---------------------------------------------------
// The iframe swallows mousemove once the pointer crosses into it, so the drag
// is tracked on the document with pointer events disabled on the frame for the
// duration (body.resizing). Without that the divider sticks the moment you
// drag rightwards over the 3D view.
(function splitter(){
  const bar = el$('splitter'), grid = el$('view-library');
  let dragging = false;
  const MIN = 260;                        // keep both panes usable
  bar.addEventListener('mousedown', (e) => {
    dragging = true; e.preventDefault();
    bar.classList.add('dragging');
    document.body.classList.add('resizing');
  });
  document.addEventListener('mousemove', (e) => {
    if(!dragging) return;
    const r = grid.getBoundingClientRect();
    const w = Math.min(Math.max(e.clientX - r.left, MIN), r.width - MIN);
    grid.style.setProperty('--lib-w', w + 'px');
  });
  document.addEventListener('mouseup', () => {
    if(!dragging) return;
    dragging = false;
    bar.classList.remove('dragging');
    document.body.classList.remove('resizing');
    // The iframe only refits on its own resize event, which a grid-track
    // change does fire -- but nudge the canvas anyway in case it missed it.
    try { el$('frame').contentWindow.dispatchEvent(new Event('resize')); } catch(e) {}
  });
  // Double-click resets to the default split.
  bar.addEventListener('dblclick', () => grid.style.removeProperty('--lib-w'));
})();

// The embedded viewer already knows how to grab the canvas and POST it to
// /api/thumbnail as a loose .stp -- the exact form install() looks for. So
// this just drives that, rather than re-implementing capture here. Same-origin
// iframe, so its button is directly clickable.
function makeShot(){
  const d = frameDoc();
  const btn = d && d.getElementById("shot-btn");
  if(!btn) return toast("Open the track in 3D first.", "warn");
  toggleExpand(true);            // capture what you can actually see
  setTimeout(() => {
    btn.click();
    // The write is server-side; give it a moment, then re-read so the card
    // and the install plan pick the new .stp up.
    setTimeout(refresh, 1200);
  }, 300);
}

async function preview(){
  const i = findSelected();
  const p = await api('/api/plan', {tra:i.name, slot:el$('slotSel').value});
  el$('plan').innerHTML = p.blocked
    ? `<div class="plan e">Blocked: ${esc(p.blocked)}</div>`
    : `<div class="plan"><ul>${p.steps.map(s=>`<li>${esc(s)}</li>`).join('')}</ul>
       ${p.warnings.map(w=>`<div class="w" style="margin-top:8px">⚠ ${esc(w)}</div>`).join('')}</div>`;
}

async function doInstall(force){
  const i = findSelected();
  const slot = el$('slotSel').value;
  const r = await api('/api/install', {tra:i.name, slot, force});
  if(r.ok){
    toast('Installed '+i.name+' into '+slot);
    SEL = 'track:'+slot+'.trk';       // land on the slot you just filled
    setFilter('ingame');              // ...and show what is in the game now
    await refresh();
  }
  else if(r.needs_force){
    el$('plan').innerHTML =
      `<div class="plan"><div class="w">⚠ ${esc(r.error)}</div>
       <div style="margin-top:10px"><button class="danger" onclick="doInstall(true)">Install anyway</button></div></div>`;
    toast(r.error, 'warn');
  } else toast(r.error, 'bad');
}

async function restore(slot){
  const r = await api('/api/restore', {slot});
  toast(r.done.join('\n')); SEL = null; await refresh();
}

// Moves the .car between the Data folder and Data/Disabled/ -- see
// switcher.set_car_active(). Lives here with the other actions rather than
// beside the card that calls it, because it outlived the view it was written
// for and was once deleted along with it.
async function setCarActive(name, active){
  const r = await api('/api/car_active', {name, active});
  if(!r.ok) return toast(r.error, 'bad');
  toast((active ? 'Added ' : 'Removed ') + name + (active ? ' to' : ' from') + ' the game');
  SEL = 'car:' + r.name;              // follow the file so the pane stays put
  await refresh();
}

el$('restoreAll').onclick = async () => {
  const r = await api('/api/restore', {all:true});
  toast(r.done.join('\n')); SEL = null; await refresh();
};

/* ---- Game configurator -------------------------------------------------- */
// Cars that can be dropped onto the AI: any .car except the primary itself.
function aiCandidates(){
  return (STATE.cars || []).filter(c =>
    c.name.toLowerCase() !== 'viper.car' && c.name.toLowerCase().endsWith('.car'));
}

async function renderGame(){
  if(!STATE) return;
  const af = STATE.ai_field || {count:null, max:15};
  const count = af.count == null ? 0 : af.count, total = count + 1;
  // status is "stock (never overlaid)" | "overlaid (...)" | "no viper.car";
  // match the real overlaid state, not the word inside "never overlaid".
  const overlaid = /^overlaid/.test(STATE.primary_car || '');
  const cands = aiCandidates();
  const verts = STATE.vertex_verts, vmax = STATE.vertex_max;
  const active = (STATE.cars || []).filter(c => c.active).length;
  const aside = (STATE.cars || []).length - active;
  const modded = (STATE.slots || []).filter(s => !s.is_stock).length;
  const kb = b => (b/1024 | 0).toLocaleString();
  const dr = await api('/api/doctor');
  const hb = await api('/api/hornball');

  const opponents = `
   <div class="panel">
     <div class="panel-head"><h2>AI opponents</h2>
       <span class="note">${total} on the grid &middot; in-menu picker locks to 7</span></div>
     <p class="lede">How many cars line up against you. The tool sets it directly, so it
       can go past the menu's limit of 7 &mdash; up to ${af.max}.</p>
     <div class="ai-row">
       <div><span class="field-label">Opponents</span>
         <div class="stepper">
           <button onclick="aiStep(-1)" ${count<=0?'disabled':''}>&minus;</button>
           <span class="val" id="ai-val">${count}</span>
           <button onclick="aiStep(1)" ${count>=af.max?'disabled':''}>+</button>
         </div></div>
       <span class="ai-total">On the grid: <b>${total}</b> cars
         <span style="opacity:.55">(you + ${count})</span></span>
     </div>
   </div>`;

  const carLine = verts
    ? `Engine buffer holds <b style="color:var(--fg)">${verts.toLocaleString()}</b> verts per mesh${
        (vmax && verts < vmax)
          ? ` &mdash; raise it with <code>vrmod patch --max-verts</code> for a high-poly car`
          : ''}.`
    : '';
  const aiCar = `
   <div class="panel">
     <div class="panel-head"><h2>Default car</h2>
       <span class="note">${overlaid ? 'Mod car installed' : 'Stock Viper'}</span></div>
     <p class="lede">The game's primary car — the default for <b>you and every AI</b>. Swap in a
       mod car and the whole field, you included, drives it. (Picking another car on the in-game
       car-select only lasts that session; it resets to this on the next launch.)</p>
     ${cands.length ? `
     <div class="ai-row">
       <div><span class="field-label">Car</span><br>
         <select id="ai-car" class="mini" style="padding:7px 12px">
           <option value="">Stock Viper</option>
           ${cands.map(c => `<option value="${esc(c.name)}" ${AI_MOD===c.name?'selected':''}
             >${esc(c.stem)}</option>`).join('')}
         </select></div>
       <label class="tgl"><input type="checkbox" id="ai-diff"><span class="track"></span>
         Different colour per driver</label>
       <button class="mini on" onclick="applyAiCar()">Apply</button>
       ${overlaid ? `<button class="mini" onclick="revertAiCar()">Revert to stock</button>` : ''}
     </div>
     ${carLine ? `<p class="lede" style="margin:14px 0 0">${carLine}</p>` : ''}`
     : `<p class="empty">Add a mod car (a .car file) to the Data folder to make it the default car.</p>`}
   </div>`;

  const cars = `
   <div class="panel">
     <div class="panel-head"><h2>Cars in the game</h2>
       <span class="note">${active} in the game${aside ? ` · ${aside} set aside` : ''}</span></div>
     <p class="lede">Every car in the Data folder is in the game — the engine loads them all.
       Set one aside to move it to the Disabled folder. (You and the AI both default to the
       primary car above.)</p>
     <div class="rost">
       ${(STATE.cars || []).map(c => {
         const isViper = c.name.toLowerCase() === 'viper.car';
         return `<div class="rost-item">
           <div class="grow"><div class="nm">${esc(c.stem)}</div>
             <div class="sub">${kb(c.size)} KB</div></div>
           ${isViper ? `<span class="badge ai">AI car</span>` : ''}
           <button class="mini ${c.active?'on':''}"
             onclick="setCarActive('${esc(c.name)}', ${!c.active})"
             >${c.active?'In game':'Add'}</button>
         </div>`;
       }).join('')}
     </div>
   </div>`;

  const nSlots = (STATE.slots || []).length;
  const addons = (STATE.library_tracks || []).filter(t => t.is_addon).length;
  const tracks = `
   <div class="panel">
     <div class="panel-head"><h2>Track slots</h2>
       <span class="note">${nSlots} in the game${modded ? ` · ${modded} modded` : ''}${
         addons ? ` · ${addons} add-on${addons===1?'':'s'} in the folder` : ''}</span></div>
     <p class="lede">The ${nSlots===8?'eight':nSlots} built-in track slots. Install add-ons from the
       Library tab, then restore a slot here to get the original back.</p>
     <div class="rost">
       ${(STATE.slots || []).map(s => {
         const shot = s.preview ? '/preview/'+encodeURIComponent(s.preview) : '';
         return `<div class="rost-item">
           ${shot ? `<img src="${shot}" style="width:46px;height:34px;object-fit:cover;
             border-radius:5px;flex:none">` : ''}
           <div class="grow"><div class="nm">${esc(s.display_name)}</div>
             <div class="sub">${esc(s.slot)}${s.is_stock?'':' &middot; modded'}</div></div>
           ${s.is_stock
             ? `<span class="badge" style="color:var(--dim);border-color:var(--edge)">stock</span>`
             : `<button class="mini" onclick="restore('${esc(s.slot)}')">Restore</button>`}
         </div>`;
       }).join('')}
     </div>
   </div>`;

  const res = STATE.resolution;
  let resPanel = '';
  if(res){
    const cur = res.container.join('x');
    // The engine's legacy Direct3D caps surface WIDTH at 2048, so 1440p/4K can't
    // work (they error with DDERR_INVALIDOBJECT) -- 1920x1080 is the real ceiling.
    const presets = ['1280x720', '1600x900', '1920x1080'];
    if(!res.stock && !presets.includes(cur)) presets.unshift(cur);   // keep a custom res visible
    const label = o => { const [w, h] = o.split('x');
      const tag = {'1280x720':' (720p)', '1920x1080':' (1080p)'}[o] || '';
      return `${w} × ${h}${tag}`; };
    const opts = `<option value="stock" ${res.stock?'selected':''}>Stock (1024 × 768, no modern mode)</option>`
      + presets.map(o => `<option value="${o}" ${(!res.stock && cur===o)?'selected':''}>${label(o)}</option>`).join('');
    resPanel = `
     <div class="panel">
       <div class="panel-head"><h2>Resolution</h2>
         <span class="note">${res.stock ? 'Stock — 1024×768 max' : cur.replace('x', '×')}</span></div>
       <p class="lede">The video menu offers three fixed modes topping out at 1024×768 (a fourth
         table slot, 512×384, isn't shown), with no in-menu way to add more. This installs a modern
         resolution into the top slot — the 1024×768 one — so it appears there in its place, and
         applies the HUD/aspect fixes so the tachometer and on-screen display stay intact at that size.</p>
       <div class="ai-row">
         <div><span class="field-label">Race at</span><br>
           <select id="res-pick" class="mini" style="padding:7px 12px">${opts}</select></div>
         <button class="mini on" onclick="applyResolution()">Apply</button>
       </div>
       <p class="lede" style="margin:14px 0 0">The other menu modes (${res.others.slice(0,2).map(m=>m[0]+'×'+m[1]).join(', ')}) stay put. The engine's legacy
         Direct3D caps width at 2048, so 1920×1080 is the practical maximum (1440p/4K won't start).
         Apply sets it as the <b>race mode</b> too, so the game boots straight into it (menus keep
         their own resolution). Takes effect next launch; a large resolution on a scaled desktop also
         needs the DPI fix (in Compatibility below)${res.stock ? '' : '. Reverting restores the stock race.bin — drops the modern mode and the HUD fixes'}.</p>
     </div>`;
  }

  let hbPanel = '';
  if(hb && hb.available){
    const b = hb.bounds, sm = hb.speed_mult, cd = hb.cooldown;
    const row = (lab, id, valId, val, unit, min, max, step, ends) => `
      <div style="display:flex;align-items:center;gap:14px;margin-top:12px">
        <label class="field-label" style="min-width:150px;margin:0">${lab}
          <b id="${valId}" style="color:var(--fg)">${val.toFixed(2)}${unit}</b></label>
        <input type="range" id="${id}" min="${min}" max="${max}" step="${step}" value="${val}"
          style="flex:1;accent-color:var(--acc)"
          oninput="el$('${valId}').textContent=(+this.value).toFixed(2)+'${unit}'">
        <span style="color:var(--dim);font-size:12px;min-width:96px;text-align:right">${ends}</span>
      </div>`;
    hbPanel = `
     <div class="panel">
       <div class="panel-head"><h2>Horn-ball</h2>
         <span class="note">${hb.is_stock ? 'Stock throw'
           : `${sm.toFixed(2)}× · ${cd.toFixed(2)}s`}</span></div>
       <p class="lede">The hidden <b>hacks</b> toy: honk and your car fires a ball out the front.
         Turn <b>Horn ball</b> on in the game's hacks menu to use it; these sliders set how hard it
         throws and how often. Takes effect next launch.</p>
       ${row('Throw speed', 'hb-speed', 'hb-sv', sm, '×', b.speed_min, b.speed_max, 0.25,
             `${b.speed_min}× – ${b.speed_max}× (1× stock)`)}
       ${row('Cooldown', 'hb-cd', 'hb-cv', cd, 's', b.cd_min, b.cd_max, 0.05,
             `${b.cd_min}s – ${b.cd_max}s (2s stock)`)}
       <div class="ai-row" style="margin-top:14px">
         <button class="mini on" onclick="applyHornball()">Apply</button>
         ${hb.is_stock ? '' : `<button class="mini" onclick="resetHornball()">Reset to stock</button>`}
       </div>
     </div>`;
  }

  const fixBtn = {vram:'Apply', dpi:'Set DPI-aware', patch:'Apply'};
  const fixes = `
   <div class="panel">
     <div class="panel-head"><h2>Compatibility &amp; fixes</h2>
       <span class="note">${dr.worst==='ok' ? 'All good'
         : dr.worst==='warn' ? 'Things to check' : 'Needs attention'}</span></div>
     <div>
       ${dr.findings.map(f => `
         <div class="fix"><span class="dot ${f.level}"></span>
           <div class="body"><div class="t">${esc(f.title)}</div>
             <div class="d">${esc(f.detail)}${f.fix ? ' '+esc(f.fix) : ''}
               ${f.link ? ` <a href="${esc(f.link)}" target="_blank" rel="noopener"
                 >${esc(f.link)} &#8599;</a>` : ''}</div></div>
           ${f.action ? `<button class="mini" onclick="applyFix('${f.action}')"
             >${fixBtn[f.action] || 'Fix'}</button>` : ''}
         </div>`).join('')}
     </div>
   </div>`;

  el$('config').innerHTML = opponents + aiCar + cars + tracks + hbPanel + resPanel + fixes;
}

async function applyHornball(){
  const speed_mult = +el$('hb-speed').value, cooldown = +el$('hb-cd').value;
  const r = await api('/api/hornball', {speed_mult, cooldown});
  if(!r.ok) return toast(r.error, 'bad');
  toast(`Horn-ball: ${r.speed_mult.toFixed(2)}× speed, ${r.cooldown.toFixed(2)}s cooldown `
        + `— takes effect next launch.`);
  renderGame();
}

async function resetHornball(){
  const r = await api('/api/hornball', {reset:true});
  if(!r.ok) return toast(r.error, 'bad');
  toast('Horn-ball reset to stock (1× speed, 2s cooldown).');
  renderGame();
}

async function aiStep(delta){
  const af = STATE.ai_field || {count:0, max:15};
  const cur = af.count || 0, next = Math.max(0, Math.min(af.max, cur + delta));
  if(next === cur) return;
  const r = await api('/api/aifield', {count: next});
  if(!r.ok) return toast(r.error, 'bad');
  toast(`AI field: ${r.count} opponent${r.count===1?'':'s'} (${r.total} cars total)`);
  await refresh();
}

async function applyAiCar(){
  const mod = el$('ai-car').value;
  if(!mod) return revertAiCar();
  const diff = el$('ai-diff').checked;
  AI_MOD = mod;
  const r = await api('/api/primarycar', {mod, paint_slots: diff});
  if(!r.ok) return toast(r.error, 'bad');
  toast('Everyone now drives ' + mod + (r.vertex_warning ? '\n\n⚠ ' + r.vertex_warning : ''),
        r.vertex_warning ? 'warn' : undefined);
  await refresh();
}

async function revertAiCar(){
  const r = await api('/api/primarycar', {revert: true});
  if(!r.ok) return toast(r.error, 'bad');
  AI_MOD = ''; toast(r.message); await refresh();
}

async function applyResolution(){
  const v = el$('res-pick').value;
  if(v === 'stock'){
    if(STATE.resolution && STATE.resolution.stock) return toast('Already the stock table.');
    const r = await api('/api/resolution', {revert: true});
    if(!r.ok) return toast(r.error, 'bad');
    toast(r.message); return refresh();
  }
  const [w, h] = v.split('x').map(Number);
  const r = await api('/api/resolution', {width: w, height: h});
  if(!r.ok) return toast(r.error, 'bad');
  const tail = r.selected
    ? ' Set as the race mode, so the game boots into it.'
    : ' No options.cfg yet — pick it in the game’s video menu, or run the game once first.';
  toast(`Resolution set to ${w}×${h}.` + tail
        + (r.note ? '\n\n⚠ ' + r.note : ''), r.note ? 'warn' : undefined);
  await refresh();
}

refresh();
</script>
"""


_MAP_CACHE: dict = {}
_SHOT_CACHE: dict = {}
_TRACKSHOT_CACHE: dict = {}


class _Handler(http.server.BaseHTTPRequestHandler):
    # None until the user picks a Data folder (the desktop app opens with no
    # folder and shows a landing screen). Set at runtime via set_data_dir().
    data_dir: Path | None = None

    def log_message(self, *a):  # keep the console clean
        pass

    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, "application/json", json.dumps(obj).encode("utf-8"))

    def do_GET(self):
        d = self.data_dir
        if self.path in ("/", "/index.html"):
            return self._send(200, "text/html; charset=utf-8", _PAGE.encode("utf-8"))
        # No folder chosen yet -> tell the page to show its landing screen. The
        # page won't call any other endpoint until a folder is set.
        if d is None:
            if self.path == "/api/status":
                return self._json({"needs_folder": True})
            return self._json({"ok": False, "error": "no data folder selected"}, 409)
        if self.path == "/api/doctor":
            rep = doctor.check(d)
            return self._json({
                "worst": rep.worst,
                "root": str(rep.game_root),
                "findings": [{"level": f.level, "title": f.title, "detail": f.detail,
                              "fix": f.fix, "action": f.action, "link": f.link}
                             for f in rep.findings],
            })
        if self.path == "/api/hornball":
            if not hornball.available(d):
                return self._json({"available": False})
            t = hornball.read(d)
            return self._json({
                "available": True,
                "speed_mult": round(t.speed_mult, 3), "cooldown": round(t.cooldown, 3),
                "is_stock": t.is_stock,
                "bounds": {"speed_min": hornball.SPEED_MIN, "speed_max": hornball.SPEED_MAX,
                           "cd_min": hornball.COOLDOWN_MIN, "cd_max": hornball.COOLDOWN_MAX},
            })
        if self.path == "/api/status":
            return self._json(_status_payload(d))
        if self.path.startswith("/map/"):
            # The Track Info outline, drawn from the track's own centre line.
            # Cheap enough (about 20 ms) to render on demand, but cached by
            # file mtime so a page refresh doesn't redraw every card.
            from urllib.parse import unquote
            name = unquote(self.path[len("/map/"):])
            f = d / name
            if f.parent.resolve() != d.resolve() or not f.is_file():
                return self._send(404, "text/plain", b"not found")
            key = (str(f), f.stat().st_mtime_ns)
            hit = _MAP_CACHE.get(key)
            if hit is None:
                try:
                    pixels, w, h = trackmap.render(f)
                except Exception:
                    return self._send(404, "text/plain", b"no centre line")
                hit = viewer._rgb_png(w, h, [bytearray(pixels[y * w * 3:(y + 1) * w * 3])
                                             for y in range(h)])
                _MAP_CACHE.clear()          # keyed by mtime, so stale entries are dead weight
                _MAP_CACHE[key] = hit
            return self._send(200, "image/png", hit)
        if self.path.startswith("/carshot/"):
            # A car has no stored menu picture, so draw one from its body mesh
            # (see carshot.py). About 0.1 s each, cached by file mtime so a
            # page refresh doesn't re-render the whole folder.
            from urllib.parse import unquote
            name = unquote(self.path[len("/carshot/"):])
            f = switcher.find_car(d, name)
            if f is None:
                return self._send(404, "text/plain", b"not found")
            key = (str(f), f.stat().st_mtime_ns)
            hit = _SHOT_CACHE.get(key)
            if hit is None:
                try:
                    hit = carshot.to_png(f)
                except Exception:
                    return self._send(404, "text/plain", b"no body mesh")
                _SHOT_CACHE.clear()      # keyed by mtime, so stale entries are dead weight
                _SHOT_CACHE[key] = hit
            return self._send(200, "image/png", hit)
        if self.path.startswith("/trackshot/"):
            # A track with no menu picture (an add-on that ships neither a .jpg
            # nor a .stp) would otherwise show only its flat outline. Render its
            # 3D scenery mesh instead -- the same wireframe carshot draws for a
            # car (see carshot.track_to_png), so every track has a preview drawn
            # from its own geometry. ~0.15s, cached by mtime like /carshot.
            from urllib.parse import unquote
            name = unquote(self.path[len("/trackshot/"):])
            f = d / name
            if f.parent.resolve() != d.resolve() or not f.is_file():
                return self._send(404, "text/plain", b"not found")
            key = (str(f), f.stat().st_mtime_ns)
            hit = _TRACKSHOT_CACHE.get(key)
            if hit is None:
                try:
                    hit = carshot.track_to_png(f)
                except Exception:
                    return self._send(404, "text/plain", b"no mesh")
                _TRACKSHOT_CACHE.clear()
                _TRACKSHOT_CACHE[key] = hit
            return self._send(200, "image/png", hit)
        if self.path.startswith("/icon/"):
            # Stock menu screenshots, pre-converted from each <slot>.stp in
            # ui.res. Shipped as PNG because .stp isn't decoded yet -- see the
            # project notes. Fixed set of 8, so a one-off conversion beats a
            # runtime dependency on Stp2Tga.exe.
            slot = self.path[len("/icon/"):]
            if slot.endswith(".png"):
                slot = slot[:-4]
            icon = Path(__file__).parent / "assets" / "slots" / f"{slot}.png"
            if slot not in switcher.STOCK_TRACKS or not icon.is_file():
                return self._send(404, "text/plain", b"not found")
            return self._send(200, "image/png", icon.read_bytes())
        if self.path.startswith("/stp/"):
            # Add-on tracks often ship a .stp screenshot but no .jpg, which
            # used to leave a blank thumbnail. Decoded live; stamps using the
            # compressed variant stp.py doesn't handle yet just 404 back to
            # the blank placeholder rather than erroring the page.
            from urllib.parse import unquote
            name = unquote(self.path[len("/stp/"):])
            f = d / name
            if f.parent.resolve() != d.resolve() or not f.is_file():
                return self._send(404, "text/plain", b"not found")
            try:
                return self._send(200, "image/png", stp.to_png(stp.parse(f.read_bytes())))
            except Exception:
                return self._send(404, "text/plain", b"undecodable stamp")
        if self.path.startswith("/preview/"):
            from urllib.parse import unquote
            name = unquote(self.path[len("/preview/"):])
            p = d / name
            # Confine to the data dir -- the name comes from the page, but
            # treat it as untrusted input regardless.
            if p.parent.resolve() != d.resolve() or not p.is_file():
                return self._send(404, "text/plain", b"not found")
            ctype = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "application/octet-stream"
            return self._send(200, ctype, p.read_bytes())
        if self.path.startswith("/view/"):
            from urllib.parse import unquote
            name = unquote(self.path[len("/view/"):])
            p = d / name
            if p.parent.resolve() != d.resolve() or not p.is_file():
                return self._send(404, "text/plain", b"not found")
            try:
                html = viewer.build_track_viewer_html(p)
            except Exception as ex:
                return self._send(500, "text/plain", f"{type(ex).__name__}: {ex}".encode())
            return self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))
        if self.path.startswith("/car/"):
            # Same on-demand shape as /view/, but for the car shell. Built per
            # request rather than pre-generated: the shell embeds every mesh,
            # texture and sound up front, so viper.car alone is several MB of
            # HTML that mostly nobody opens.
            from urllib.parse import unquote
            name = unquote(self.path[len("/car/"):])
            # find_car looks in Data and Data/Disabled, and returns None for
            # anything outside both -- so it is the containment check too.
            p = switcher.find_car(d, name)
            if p is None:
                return self._send(404, "text/plain", b"not found")
            try:
                html = viewer.build_shell_html(p, paint_dir=_paint_dir(d))
            except Exception as ex:
                return self._send(500, "text/plain", f"{type(ex).__name__}: {ex}".encode())
            return self._send(200, "text/html; charset=utf-8", html.encode("utf-8"))
        self._send(404, "text/plain", b"not found")

    def do_POST(self):
        d = self.data_dir
        n = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(n) or b"{}")
        # Dev/browser fallback for choosing a folder without the native picker.
        if self.path == "/api/set_folder":
            if is_data_folder(req.get("path", "")):
                set_data_dir(req["path"])
                return self._json({"ok": True, "path": str(get_data_dir())})
            return self._json({"ok": False, "error": "not a Viper Racing Data folder "
                               "(needs race.bin or a .car file)"})
        if d is None:
            return self._json({"ok": False, "error": "no data folder selected"}, 409)
        try:
            if self.path == "/__vrmod_commit__":
                # Both the car shell and the track viewer Save through this one
                # route (cli.COMMIT_PATH). Only the standalone `serve` used to
                # handle it, so Save failed with "unknown endpoint" inside the
                # switcher. cli imports this module, so import it lazily here to
                # dodge the top-level cycle.
                from . import cli
                target = req.get("track_path") or req.get("car_path")
                if not target or Path(target).parent.resolve() != d.resolve():
                    return self._json({"ok": False,
                                       "error": "edit target is outside this Data folder"})
                try:
                    out_path, backup_path, resized, warnings, data = cli._apply_commit(req)
                    payload = {"ok": True, "out_path": str(out_path),
                               "backup_path": str(backup_path) if backup_path else None,
                               "resized": resized, "warnings": warnings}
                    # "elsewhere": nothing was written -- the page hands these
                    # bytes to the OS save dialog (see viewer.py), which is why
                    # this server never writes outside the folder it was given.
                    if data is not None:
                        payload["filename"] = out_path.name
                        payload["data"] = data
                    return self._json(payload)
                except Exception as ex:
                    return self._json({"ok": False, "error": f"{type(ex).__name__}: {ex}"})
            if self.path == "/api/plan":
                p = switcher.plan_install(d, d / req["tra"], req["slot"])
                return self._json({
                    "steps": p.steps, "warnings": p.warnings, "blocked": p.blocked,
                })
            if self.path == "/api/install":
                try:
                    switcher.install(d, d / req["tra"], req["slot"], force=bool(req.get("force")))
                    return self._json({"ok": True})
                except switcher.SwitcherError as ex:
                    return self._json({
                        "ok": False, "error": str(ex),
                        "needs_force": "NOT the stock file" in str(ex),
                    })
            if self.path == "/api/thumbnail":
                import base64
                track = Path(req["track"])
                # The page hands back the path it was built from; only accept
                # one inside the folder this server is serving.
                if track.parent.resolve() != d.resolve() or not track.is_file():
                    return self._json({"ok": False, "error": "track is outside this Data folder"})
                w, h = int(req["width"]), int(req["height"])
                rgb = base64.b64decode(req["rgb"])
                if len(rgb) != w * h * 3:
                    return self._json({"ok": False, "error": "pixel data size mismatch"})
                # Written as a LOOSE, !IGM-truncated stamp beside the track --
                # the form add-on tracks ship, and exactly what install() looks
                # for when it swaps the menu screenshot into ui.res.
                shot = d / f"{track.stem}.stp"
                shot.write_bytes(stp.to_loose(stp.build_from_rgb(rgb, w, h)))
                return self._json({"ok": True, "wrote": shot.name})
            if self.path == "/api/fix":
                # Only named, understood repairs -- never an arbitrary write.
                action = req.get("action")
                if action == "vram":
                    at = vrampatch.apply(d)
                    return self._json({"ok": True,
                                       "message": f"Startup fix applied at {hex(at)} "
                                                  "(original saved as race.bin.vram-backup)."})
                if action == "dpi":
                    msg = patchset.set_dpi_aware(d)
                    return self._json({"ok": True,
                                       "message": f"DPI-aware set ({msg}). Takes effect "
                                                  "on the next launch."})
                if action == "patch":
                    rep = patchset.apply(d, mode=(1920, 1080))
                    steps = ", ".join(n for n, _ in rep.steps)
                    return self._json({"ok": True,
                                       "message": f"Applied the patch set ({steps}). "
                                                  "Rebuildable from the snapshot; revert with "
                                                  "vrmod patch --revert."})
                return self._json({"ok": False, "error": f"unknown fix: {action}"}, 400)
            if self.path == "/api/hornball":
                if not hornball.available(d):
                    return self._json({"ok": False, "error": "this race.bin has no tunable "
                                       "horn-ball launch code"}, 400)
                if req.get("reset"):
                    t = hornball.reset(d)
                else:
                    t = hornball.apply(d, speed_mult=req.get("speed_mult"),
                                       cooldown=req.get("cooldown"))
                return self._json({"ok": True, "speed_mult": round(t.speed_mult, 3),
                                   "cooldown": round(t.cooldown, 3), "is_stock": t.is_stock})
            if self.path == "/api/car_active":
                new = switcher.set_car_active(d, req["name"], bool(req["active"]))
                return self._json({"ok": True, "name": new})
            if self.path == "/api/restore":
                done = switcher.restore_all(d) if req.get("all") else switcher.restore(d, req["slot"])
                return self._json({"ok": True, "done": done})
            if self.path == "/api/aifield":
                try:
                    r = aifield.set_count(d, int(req["count"]))
                    return self._json({"ok": True, "count": r["ai_car_count"], "total": r["total"]})
                except aifield.AiFieldError as ex:
                    return self._json({"ok": False, "error": str(ex)})
            if self.path == "/api/primarycar":
                try:
                    if req.get("revert"):
                        return self._json({"ok": True, "message": primarycar.revert(d)})
                    r = primarycar.install(d, d / req["mod"], paint_slots=bool(req.get("paint_slots")))
                    return self._json({"ok": True, "mod": r["mod"],
                                       "vertex_warning": r["vertex_warning"]})
                except primarycar.PrimaryCarError as ex:
                    return self._json({"ok": False, "error": str(ex)})
            if self.path == "/api/resolution":
                # Revert restores the pristine race.bin (stock 1024x768 table,
                # no HUD fixes). A width/height rebuilds race.bin from the snapshot
                # with the full patch set at that mode, so the tachometer/HUD stay
                # intact -- setting the table alone would distort them.
                if req.get("revert"):
                    return self._json({"ok": True, "message": patchset.revert(d)})
                w, h = int(req["width"]), int(req["height"])
                rep = patchset.apply(d, mode=(w, h))
                # ...and select it for RACING (index 4 = the container slot 0), so
                # the game uses it without the player picking it in the video menu.
                sel = resolution.select_race_mode(d, patchset.DEFAULT_INDEX)
                return self._json({"ok": True, "width": w, "height": h,
                                   "note": rep.notes[0] if rep.notes else None,
                                   "selected": sel is not None})
        except Exception as ex:
            return self._json({"ok": False, "error": f"{type(ex).__name__}: {ex}"}, 500)
        self._json({"ok": False, "error": "unknown endpoint"}, 404)


def _paint_dir(d: Path) -> Path | None:
    """A live install's Config/ folder, if there is one beside Data.

    The main body paint isn't in the static archives -- it's a paintN.tex the
    game writes into Config/ -- so without this the shell falls back to a
    stand-in colour. Auto-detected rather than a flag, since it's always in
    the same place relative to the Data folder we're already pointed at.
    """
    cfg = d.parent / "Config"
    return cfg if (cfg / "paint0.tex").is_file() else None


_MESH_CACHE: dict = {}


def _track_mesh_size(path: Path) -> tuple[int, int] | None:
    """(vertices, faces) of a track's scenery mesh, cached by file mtime.

    About 15ms per track, so cheap enough for a listing -- but the cache stops
    a page refresh re-parsing every archive in the folder.
    """
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return None
    if key in _MESH_CACHE:
        return _MESH_CACHE[key]
    try:
        entries = archive.read(path)
        e = next(x for x in entries if x.name.lower() == "track.grf")
        m = grf.parse(envelope.build(e.tag, e.version, e.payload)).mesh
        out = (len(m.vertices), len(m.faces))
    except Exception:
        out = None
    _MESH_CACHE.clear()
    _MESH_CACHE[key] = out
    return out


def _car_entry(c: Path, active: bool) -> dict:
    """One card's worth of a .car, read without assembling any geometry.

    A car that won't parse is reported with its error rather than dropped --
    same rule the gallery uses, since a folder of mods will have broken ones
    and hiding them is worse than showing why they failed.
    """
    entry = {"name": c.name, "stem": c.stem, "size": c.stat().st_size,
             "parts": 0, "cockpit": False, "error": None, "active": active}
    try:
        entries = archive.read(c)
    except Exception as ex:
        entry["error"] = f"{type(ex).__name__}: {ex}"
        return entry
    entry["parts"] = sum(1 for e in entries if e.name.lower().endswith(".mod"))
    # The game's vertex ceiling is PER OBJECT, not per car (mod.VERTEX_BUDGETS),
    # so the peak is what decides whether a car needs a patched race.bin -- a
    # total would be misleading. Cheap: about 10ms for a whole car.
    total = peak = 0
    for e in entries:
        if not e.name.lower().endswith(".mod"):
            continue
        try:
            m = mod_mod.parse(envelope.build(e.tag, e.version, e.payload))
        except Exception:
            continue
        total += len(m.vertices)
        peak = max(peak, len(m.vertices))
    entry["vertices"], entry["peak_vertices"] = total, peak
    entry["needs_patch"] = peak > mod_mod.VERTEX_BUDGETS["original"]
    entry["cockpit"] = any(e.name.lower() == "cockpit.tab" for e in entries)
    cfe = next((e for e in entries if e.name.lower().endswith(".cf")), None)
    if cfe is not None:
        try:
            # Imperial, matching the game's own units -- checked against the
            # real car the stock viper.cf describes (450 hp / 490 lb-ft).
            values = cf.parse(envelope.build(cfe.tag, cfe.version, cfe.payload))
            for k in ("power_max", "torque_max", "mass"):
                entry[k] = values.get(k)
        except Exception:
            pass                      # a card without figures still opens
    return entry


def _status_payload(d: Path) -> dict:
    slots = []
    for s in switcher.status(d):
        # When a slot is occupied, the picture the game actually shows is the
        # add-on's own screenshot, so surface that instead of the stock icon.
        preview = shot = None
        if s.occupied_by:
            preview = next((c.name for c in (d / f"{s.occupied_by}.jpg", d / f"{s.occupied_by}.JPG")
                            if c.exists()), None)
            if preview is None and (d / f"{s.occupied_by}.stp").exists():
                shot = f"{s.occupied_by}.stp"
        # Length of whatever is actually in the slot, so a modded track
        # reports its own figure rather than the stock one.
        try:
            miles = track_mod.length_miles(d / f"{s.slot}.trk")
        except Exception:
            miles = None
        slots.append({
            "slot": s.slot, "display_name": s.display_name, "is_stock": s.is_stock,
            "occupied_by": s.occupied_by, "size": s.size, "preview": preview,
            "stp": shot, "miles": miles,
        })
    tracks = []
    for t in switcher.available_tracks(d):
        jpg = next((c.name for c in (d / f"{t.stem}.jpg", d / f"{t.stem}.JPG") if c.exists()), None)
        try:
            miles = track_mod.length_miles(t)
        except Exception:
            miles = None
        tracks.append({
            "name": t.name, "stem": t.stem, "size": t.stat().st_size,
            "preview": jpg, "has_stp": (d / f"{t.stem}.stp").exists(),
            "stp": f"{t.stem}.stp" if (d / f"{t.stem}.stp").exists() else None,
            "miles": miles,
        })
    # Active cars sit in Data itself; deactivated ones are moved into
    # Data/Disabled/, which the game's scan does not look into.
    cars = [_car_entry(path, active) for path, active in switcher.car_paths(d)]

    # One library list covering both the 8 tracks currently in the game and any
    # add-on .tra sitting beside them, because "what tracks have I got?" is one
    # question. Each entry says whether it is live in a slot, which is what
    # decides whether it offers Install or Restore.
    by_slot = {s["slot"]: s for s in slots}
    library_tracks = []
    for slot, info in by_slot.items():
        f = d / f"{slot}.trk"
        if not f.is_file():
            continue
        library_tracks.append({
            "name": f.name, "stem": slot, "slot": slot, "in_slot": True,
            "is_addon": False, "is_stock": info["is_stock"],
            "display_name": info["display_name"], "miles": info["miles"],
            "preview": info["preview"], "stp": info["stp"],
            "size": info["size"], "occupied_by": info["occupied_by"],
            "mesh": _track_mesh_size(f),
        })
    for t in tracks:
        library_tracks.append({
            "name": t["name"], "stem": t["stem"], "slot": None, "in_slot": False,
            "is_addon": True, "is_stock": False,
            "display_name": t["stem"], "miles": t["miles"],
            "preview": t["preview"], "stp": t["stp"], "size": t["size"],
            "occupied_by": None, "mesh": _track_mesh_size(d / t["name"]),
            # The game's track-select screen shows a <slot>.stp out of ui.res.
            # An add-on without one installs over whatever is already there, so
            # the menu ends up showing the PREVIOUS track's picture under the
            # new name -- worse than blank. Flag it so it can be generated.
            "has_shot": bool(t["stp"]),
        })

    # ---- configurator state: AI field, the primary/AI car, the vertex buffer ----
    try:
        ai_field = {"count": aifield.status(d).get("ai_car_count"), "max": aifield.MAX_AI}
    except Exception:
        ai_field = {"count": None, "max": aifield.MAX_AI}
    try:
        primary = primarycar.status(d)
    except Exception:
        primary = "unknown"
    try:
        verts = vertexbuffer.buffer_verts(d)
    except Exception:
        verts = None
    try:
        res = resolution.read(d)                       # slot order; [0] is the container
        res_info = {"container": list(res[0]), "others": [list(m) for m in res[1:]],
                    "stock": tuple(res[0]) == (1024, 768)}
    except Exception:
        res_info = None

    return {
        "data_dir": str(d.resolve()), "slots": slots, "tracks": tracks, "cars": cars,
        "library_tracks": library_tracks,
        "car_active_count": sum(1 for c in cars if c["active"]),
        "car_disabled_count": sum(1 for c in cars if not c["active"]),
        "ai_field": ai_field, "primary_car": primary,
        "vertex_verts": verts, "vertex_max": vertexbuffer.FORMAT_CAP_VERTS,
        "resolution": res_info,
    }


def is_data_folder(path: Path | str) -> bool:
    """A plausible Viper Racing Data folder: has race.bin or at least one .car."""
    try:
        p = Path(path)
    except (TypeError, ValueError):
        return False
    return p.is_dir() and ((p / "race.bin").is_file() or any(p.glob("*.car")))


def set_data_dir(path: Path | str | None) -> Path | None:
    """Point the running server at a Data folder (or None for the landing state).
    Shared class state, so this takes effect for every subsequent request."""
    _Handler.data_dir = Path(path) if path else None
    return _Handler.data_dir


def get_data_dir() -> Path | None:
    return _Handler.data_dir


def start_server(port: int = 0):
    """Start the switcher in a daemon thread and return (server, port). The
    server is folder-agnostic: it serves the landing screen until set_data_dir()
    is called. Used by the desktop app; `serve()` remains the blocking CLI form."""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def serve(data_dir: Path | str, port: int = 8770, open_browser: bool = True) -> None:
    d = Path(data_dir)
    handler = functools.partial(_Handler)
    _Handler.data_dir = d
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Track Switcher serving {d.resolve()}\n  {url}\nCtrl-C to stop.")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
