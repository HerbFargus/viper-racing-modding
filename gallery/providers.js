// Asset providers: the seam that lets one gallery UI serve two very different
// sources. The viewer/renderer is identical; only where the bytes come from
// differs. Today: LocalFolderProvider (your own Data folder, all client-side).
// Future (Repo B, the community gallery): RemoteGalleryProvider, below.
//
// An item is the common shape the UI renders:
//   {kind:"car"|"track", file, name, sub, active, error, meta...}
// A provider offers:
//   init(onStatus)        -> prepare (load Pyodide, spin up the pool, ...)
//   load(input)           -> ingest a source (folder files / manifest url)
//   list()                -> {cars:[item], tracks:[item]}
//   thumbnail(item)       -> Promise<string>  (a URL usable as <img src>)
//   viewerHTML(item)      -> Promise<string>  (self-contained HTML for the iframe)

const LIBRARIAN_GLUE = `
import json
from pathlib import Path
import vrmod.switcher_ui as sui
from vrmod import switcher, viewer
DATA = Path('/data')

def gallery_status():
    return json.dumps(sui._status_payload(DATA))

def gallery_car_html(name):
    f = switcher.find_car(DATA, name)
    return viewer.build_shell_html(str(f), paint_dir=sui._paint_dir(DATA),
                                   title=f.stem, view_only=True)

def gallery_track_html(fname):
    return viewer.build_track_viewer_html(str(DATA / fname), view_only=True)
`;

// ---------------------------------------------------------------------------
// Your own Data folder, 100% client-side. A main-thread "librarian" Pyodide
// reads the folder (the listing) and builds the interactive viewer on demand;
// a pool of worker Pyodides renders the grid thumbnails in parallel.
// ---------------------------------------------------------------------------
class LocalFolderProvider {
  constructor(){ this.py = null; this.pool = null; this.glue = {}; }

  async init(onStatus){
    onStatus && onStatus("Loading Pyodide (~6 MB, first run only — then cached)");
    this.py = await loadPyodide();
    onStatus && onStatus("Unpacking the vrmod toolkit…");
    const zip = await (await fetch("vrmod.zip")).arrayBuffer();
    this.py.unpackArchive(zip, "zip");
    this.py.runPython("import sys; sys.path.insert(0, '/home/pyodide')");
    onStatus && onStatus("Importing vrmod…");
    await this.py.runPythonAsync(LIBRARIAN_GLUE);
    for (const n of ["gallery_status","gallery_car_html","gallery_track_html"])
      this.glue[n] = this.py.globals.get(n);
    this.pool = new RenderPool("render-worker.js");
  }

  // files: an array of File objects (flat Data folder). Writes them into the
  // librarian's FS and primes the worker pool with the shared race.res.
  async load(files){
    this.py.FS.mkdirTree("/data");
    for (const f of files)
      this.py.FS.writeFile("/data/" + f.name, new Uint8Array(await f.arrayBuffer()));
    let raceRes = null;
    try { raceRes = this.py.FS.readFile("/data/race.res").slice().buffer; } catch(e){/* no shared res */}
    await this.pool.init(raceRes);
  }

  async list(){
    const st = JSON.parse(this.glue.gallery_status());
    const cars = (st.cars || []).map(c => ({
      kind:"car", file:c.name, name:c.stem, active:c.active, error:c.error,
      sub: c.error ? c.error
         : `${c.parts} parts${c.cockpit ? " · cockpit" : ""}${c.needs_patch ? " · needs patch" : ""}`,
    }));
    const tracks = (st.library_tracks || []).map(t => ({
      kind:"track", file:t.name, name:t.display_name || t.stem, active:t.in_slot,
      sub: `${t.in_slot ? "in slot " + t.slot : "add-on"}${t.miles ? " · " + t.miles.toFixed(2) + " mi" : ""}`,
    }));
    return {cars, tracks};
  }

  // Render a thumbnail in the pool and hand back an object-URL for <img src>.
  async thumbnail(item){
    const bytes = this.py.FS.readFile("/data/" + item.file).slice().buffer;   // standalone copy
    const png = await this.pool.render(item.kind, item.file, bytes);
    return URL.createObjectURL(new Blob([png], {type:"image/png"}));
  }

  async viewerHTML(item){
    return item.kind === "track"
      ? this.glue.gallery_track_html(item.file)
      : this.glue.gallery_car_html(item.file);
  }
}

// ---------------------------------------------------------------------------
// Community gallery (Repo B) — NOT built yet, just the seam. The whole point of
// this abstraction: the UI below never changes; only these methods do.
//
// When built, it will:
//   load(manifestUrl)  -> fetch manifest.json (metadata for every hosted asset)
//   list()             -> map manifest entries to the same item shape
//   thumbnail(item)    -> return item.thumb (a PRE-BAKED PNG URL committed by CI
//                         at submission time) -- no client render, instant grid
//   viewerHTML(item)   -> fetch the hosted, same-origin .car/.trk and run the
//                         same client-side viewer (build_shell_html) on click
// ---------------------------------------------------------------------------
class RemoteGalleryProvider {
  constructor(){ throw new Error("RemoteGalleryProvider is a stub for the future community gallery (Repo B)."); }
}
