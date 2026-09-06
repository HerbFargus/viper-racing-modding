// Thumbnail render worker: a headless Pyodide + vrmod that renders one thumbnail
// per request. The main thread runs a pool of these (see pool.js) so thumbnails
// render in parallel across CPU cores instead of serially on the one main thread.
//
// Protocol (postMessage):
//   {type:"init", id, raceRes}   -> loads Pyodide + vrmod, writes shared race.res,
//                                    replies {type:"ready", id, ms}
//   {type:"render", jobId, kind, name, bytes}
//                                -> writes the file, renders, replies
//                                   {type:"result", jobId, png}  (png transferred)
//                                   or {type:"result", jobId, error}
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");

let pyodide, renderCar, renderTrack, readyPromise;

async function init(raceRes){
  pyodide = await loadPyodide();
  const zip = await (await fetch("vrmod.zip")).arrayBuffer();
  pyodide.unpackArchive(zip, "zip");
  pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide')");
  await pyodide.runPythonAsync(`
from pathlib import Path
from vrmod import carshot
DATA = Path('/data'); DATA.mkdir(exist_ok=True)
def render_car(name):   return bytes(carshot.to_png(DATA / name))
def render_track(name): return bytes(carshot.track_to_png(DATA / name))
`);
  renderCar = pyodide.globals.get("render_car");
  renderTrack = pyodide.globals.get("render_track");
  pyodide.FS.mkdirTree("/data");
  if (raceRes) pyodide.FS.writeFile("/data/race.res", new Uint8Array(raceRes));  // shared by every car
}

onmessage = async (e) => {
  const m = e.data;
  if (m.type === "init"){
    const t0 = performance.now();
    readyPromise = init(m.raceRes)
      .then(() => postMessage({type:"ready", id:m.id, ms: Math.round(performance.now()-t0)}))
      .catch(err => postMessage({type:"error", id:m.id, error:String(err)}));
    return;
  }
  if (m.type === "render"){
    try{
      await readyPromise;
      pyodide.FS.writeFile("/data/" + m.name, new Uint8Array(m.bytes));
      const res = (m.kind === "track" ? renderTrack : renderCar)(m.name);
      const u8 = res.toJs();          // Uint8Array copy of the PNG bytes
      res.destroy();
      postMessage({type:"result", jobId:m.jobId, png:u8.buffer}, [u8.buffer]);  // transfer
    }catch(err){
      postMessage({type:"result", jobId:m.jobId, error:String(err)});
    }
  }
};
