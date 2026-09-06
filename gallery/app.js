// Gallery UI: a split view (library grid left, 3D viewer right) driven by an
// asset provider (providers.js). The UI is provider-agnostic -- swap in the
// community provider later and none of this changes.

const $ = id => document.getElementById(id);
function status(msg, cls){ const s = $("status"); s.textContent = msg; s.className = cls || ""; }

let provider = null, selCard = null, thumbObserver = null;

// ---- loading overlay (CSS spinner keeps animating even if the main thread blocks)
function overlay(show, msg, sub){
  if (show){ if (msg != null) $("overlay-msg").textContent = msg;
             if (sub != null) $("overlay-sub").textContent = sub; $("overlay").hidden = false; }
  else $("overlay").hidden = true;
}
const paintYield = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));

// ---- boot: prepare the provider (Pyodide + worker pool)
async function boot(){
  try{
    overlay(true, "Starting the gallery…", "");
    provider = new LocalFolderProvider();
    await provider.init(sub => overlay(true, "Starting the gallery…", sub));
    overlay(false);
    status("ready — open your Viper Racing Data folder", "ok");
    $("open-folder").disabled = false;
  }catch(e){ overlay(false); status("startup failed:\n" + e.message, "err"); }
}

// ---- folder picking (File System Access API -> friendlier "view files" prompt)
async function chooseFolder(){
  if (window.showDirectoryPicker){
    let handle;
    try { handle = await window.showDirectoryPicker({mode:"read"}); }
    catch(e){ if (e && e.name === "AbortError") return; status("couldn't open folder:\n" + e.message, "err"); return; }
    const files = [];
    for await (const entry of handle.values())
      if (entry.kind === "file") files.push(await entry.getFile());
    await loadFolder(files);
  } else {
    $("folder").click();   // fallback: native directory input
  }
}

async function loadFolder(files){
  try{
    overlay(true, "Loading your Data folder…",
            `Reading ${files.length} files (they stay in this browser — nothing is uploaded)`);
    await paintYield();
    await provider.load(files);
    overlay(true, "Reading your Data folder…", "Parsing cars and tracks (this happens once)");
    await paintYield();
    const lib = await provider.list();
    renderLibrary(lib);
    overlay(false);
    status(`${lib.cars.length} cars, ${lib.tracks.length} tracks · previews load as you scroll`, "ok");
  }catch(e){ overlay(false); status("folder load failed:\n" + e.message, "err"); }
}

// ---- lazy thumbnails: only the tiles scrolled into view are rendered; the pool
//      parallelizes them across workers, so firing several at once is fine.
function resetThumbs(){
  if (thumbObserver) thumbObserver.disconnect();
  thumbObserver = new IntersectionObserver(entries => {
    for (const e of entries)
      if (e.isIntersecting && e.target.__item){
        thumbObserver.unobserve(e.target);
        loadThumb(e.target, e.target.__item);
      }
  }, {root: $("library"), rootMargin: "300px"});   // prefetch a little below the fold
}
async function loadThumb(shot, item){
  try{
    const url = await provider.thumbnail(item);
    const img = new Image(); img.src = url; shot.innerHTML = ""; shot.appendChild(img);
  }catch(e){ shot.textContent = item.kind === "track" ? "no preview" : "no mesh"; }
}

// ---- library grid (placeholders now; thumbnails fill in on scroll)
function renderLibrary(lib){
  const grid = $("grid"); grid.innerHTML = ""; selCard = null; resetThumbs();
  addSection(grid, "Cars", lib.cars.length);
  lib.cars.forEach(it => addCard(grid, it));
  addSection(grid, "Tracks", lib.tracks.length);
  lib.tracks.forEach(it => addCard(grid, it));
}
function addSection(grid, label, n){
  if (!n) return;
  const h = document.createElement("div"); h.className = "sectionhdr";
  h.textContent = `${label} (${n})`; grid.appendChild(h);
}
function addCard(grid, item){
  const card = document.createElement("div"); card.className = "card";
  const shot = document.createElement("div"); shot.className = "shot"; shot.textContent = "…";
  const meta = document.createElement("div"); meta.className = "meta";
  const dot = `<span class="dot ${item.active ? "on" : "off"}"></span>`;
  // Flag the one verdict that's actionable when browsing: a car that references
  // textures it doesn't ship (see car.texture_provenance) renders wrong for
  // anyone who downloads it. Self-contained/portable are both fine, so no chip.
  const chip = item.verdict === "incomplete"
    ? ` <span class="vchip incomplete" title="References textures it doesn't ship — renders wrong for anyone who downloads it">⚠ incomplete</span>`
    : "";
  meta.innerHTML = `<div class="name">${dot}${item.name}${chip}</div>` +
                   `<div class="sub${item.error ? " tag" : ""}">${item.sub}</div>`;
  card.appendChild(shot); card.appendChild(meta); grid.appendChild(card);
  if (item.error){ shot.textContent = "✕"; return; }
  card.onclick = () => openItem(item, card);
  shot.__item = item; thumbObserver.observe(shot);
}

function selectCard(card){ if (selCard) selCard.classList.remove("sel"); selCard = card; if (card) card.classList.add("sel"); }

async function openItem(item, card){
  selectCard(card);
  $("viewer-empty").hidden = true; $("frame").hidden = false; $("viewerbar").hidden = false;
  $("v-title").textContent = item.name; $("v-stat").textContent = "building viewer…";
  try{
    const t0 = performance.now();
    const html = await provider.viewerHTML(item);
    $("frame").srcdoc = html;
    $("v-stat").textContent = `${((performance.now()-t0)/1000).toFixed(1)}s`;
  }catch(e){ $("v-stat").textContent = "failed: " + e.message; }
}

$("open-folder").onclick = chooseFolder;
$("folder").onchange = e => loadFolder([...e.target.files]);

boot();
