"""Generate a self-contained three.js HTML page: the assembled car (mod.write_obj's
output, embedded inline) plus a stats panel driven by cf.py's field values. Editing
the stats panel and clicking "Export edited .txt" produces a file compatible with
`python -m vrmod.cli txt2cf` -- there's no backend here, so writing the .cf back out
still goes through the existing CLI, this just gets you the edited values."""
from __future__ import annotations

import base64
import html as html_escape
import json
import math
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from . import archive, car, cf, envelope, grf, ili, mod, sfx, tex

_TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>__TITLE__</title>
<style>
  html,body{margin:0;height:100%;background:#1a1a1a;font-family:system-ui,sans-serif;overflow:hidden}
  #canvas-wrap{position:absolute;inset:0}
  #panel{position:absolute;top:0;right:0;width:320px;height:100%;background:#20242c;color:#e8eaf2;
         box-sizing:border-box;padding:16px;overflow-y:auto;border-left:1px solid #333}
  #panel h2{margin:0 0 4px;font-size:1.1rem}
  #panel .hint{font-size:.75rem;color:#8a90a4;margin-bottom:14px}
  .section{margin-bottom:14px}
  .section h3{font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:#8a90a4;
              margin:0 0 6px;border-bottom:1px solid #333;padding-bottom:4px}
  .row{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:4px;font-size:.82rem}
  .row label{color:#c4c8d8}
  .row input{width:90px;background:#14161c;border:1px solid #3a3f4e;color:#e8eaf2;
             border-radius:3px;padding:3px 6px;font-size:.8rem;text-align:right}
  #export{width:100%;padding:10px;margin-top:10px;background:#1911ab;color:#fff;border:none;
          border-radius:4px;font-size:.85rem;cursor:pointer}
  #export:hover{background:#2419d0}
  #hint2{font-size:.72rem;color:#8a90a4;margin-top:8px}
  #fatal-error{position:absolute;top:0;left:0;right:320px;padding:16px;background:#3a1414;
               color:#ffd9d9;font-family:monospace;font-size:.85rem;white-space:pre-wrap;
               z-index:10;display:none}
</style>
<script>
  // Registered before anything else (and in its own script tag) so it can still catch
  // and display a failure even if the CDN script or the main inline script below fails
  // to load/parse entirely -- otherwise a broken page just silently shows nothing but
  // the static shell (title/hint/button), which is exactly what happened when this was
  // opened directly as a file:// page instead of through a local server.
  window.addEventListener("error", (e) => {
    const el = document.getElementById("fatal-error");
    el.style.display = "block";
    el.textContent += "ERROR: " + (e.error ? (e.error.stack || e.error.message) : e.message) + "\n";
  });
  window.addEventListener("unhandledrejection", (e) => {
    const el = document.getElementById("fatal-error");
    el.style.display = "block";
    el.textContent += "UNHANDLED REJECTION: " + e.reason + "\n";
  });
</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head><body>
<div id="canvas-wrap"></div>
<div id="fatal-error"></div>
<div id="panel">
  <h2>__CAR_TITLE__</h2>
  <div class="hint">Drag to orbit. Fields are editable; "Export edited .txt" downloads a file for <code>txt2cf</code>.</div>
  <div id="sections"></div>
  <button id="export">Export edited .txt</button>
  <div id="hint2">python -m vrmod.cli txt2cf edited.txt original.cf out.cf</div>
</div>
<script>
const OBJ_TEXT = __OBJ_JSON__;
const STATS = __STATS_JSON__;
const SECTIONS = __SECTIONS_JSON__;
const TEXTURES = __TEXTURES_JSON__;  // material name -> data:image/png;base64,... or null

function parseObj(text) {
  const positions = [], uvs = [], normals = [], groups = [];
  let current = null;
  for (const line of text.split("\n")) {
    const parts = line.trim().split(/\s+/);
    if (parts[0] === "v") positions.push(parts.slice(1).map(Number));
    else if (parts[0] === "vt") uvs.push(parts.slice(1).map(Number));
    else if (parts[0] === "vn") normals.push(parts.slice(1).map(Number));
    else if (parts[0] === "usemtl") { current = {material: parts[1], faces: []}; groups.push(current); }
    else if (parts[0] === "f") {
      const idx = parts.slice(1).map(p => p.split("/").map(x => parseInt(x,10)-1));
      current.faces.push(idx);
    }
  }
  return {positions, uvs, normals, groups};
}

const textureCache = {};
function loadTexture(dataUri) {
  if (!dataUri) return null;
  if (!textureCache[dataUri]) {
    textureCache[dataUri] = new THREE.TextureLoader().load(dataUri);
  }
  return textureCache[dataUri];
}

function buildStatsPanel() {
  const root = document.getElementById("sections");
  for (const [title, fields] of SECTIONS) {
    const sec = document.createElement("div");
    sec.className = "section";
    const h3 = document.createElement("h3");
    h3.textContent = title;
    sec.appendChild(h3);
    for (const name of fields) {
      if (!(name in STATS)) continue;
      const row = document.createElement("div");
      row.className = "row";
      const label = document.createElement("label");
      label.textContent = name;
      const input = document.createElement("input");
      input.type = "number";
      input.step = "any";
      input.value = STATS[name];
      input.dataset.field = name;
      row.appendChild(label);
      row.appendChild(input);
      sec.appendChild(row);
    }
    root.appendChild(sec);
  }
}

function exportTxt() {
  const inputs = document.querySelectorAll("#sections input");
  let lines = [];
  inputs.forEach(inp => lines.push(inp.dataset.field + " " + inp.value));
  const blob = new Blob([lines.join("\n") + "\n"], {type: "text/plain"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "edited.txt";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function main() {
  if (typeof THREE === "undefined") {
    const el = document.getElementById("fatal-error");
    el.style.display = "block";
    el.textContent = "three.js (bundled with this tool) didn't initialize -- the 3D "
      + "library failed to load. This shouldn't require internet; check the browser "
      + "console (F12) for the specific error.";
    return;
  }
  buildStatsPanel();
  document.getElementById("export").addEventListener("click", exportTxt);

  const parsed = parseObj(OBJ_TEXT);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1a1a1a);
  const wrap = document.getElementById("canvas-wrap");
  const W = () => wrap.clientWidth, H = () => wrap.clientHeight;
  const camera = new THREE.PerspectiveCamera(45, W()/H(), 0.01, 1000);
  const renderer = new THREE.WebGLRenderer({antialias:true, preserveDrawingBuffer:true});
  renderer.setSize(W(), H());
  wrap.appendChild(renderer.domElement);

  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  const dl = new THREE.DirectionalLight(0xffffff, 0.9);
  dl.position.set(5,10,7);
  scene.add(dl);
  const dl2 = new THREE.DirectionalLight(0xffffff, 0.4);
  dl2.position.set(-5,3,-7);
  scene.add(dl2);

  const fallbackColors = [0x999999, 0x777777, 0xaaaaaa, 0x888888];
  const root = new THREE.Group();
  parsed.groups.forEach((g, gi) => {
    const posArr = [], uvArr = [];
    for (const face of g.faces) {
      // Fan-triangulate n-gons (real models -- Blender especially -- export
      // quads and larger polys, not just triangles) and tolerate faces with no
      // vt (f a//n): parseObj yields ui=NaN there, so guard with isFinite and
      // fall back to (0,0) rather than indexing uvs[NaN] -> undefined -> crash.
      for (let k = 1; k + 1 < face.length; k++) {
        const tri = [face[0], face[k], face[k + 1]];
        if (tri.some(v => !parsed.positions[v[0]])) continue;   // skip a face with a bad index
        for (const [pi, ui] of tri) {
          const p = parsed.positions[pi];
          posArr.push(p[0], p[1], p[2]);
          const uv = Number.isFinite(ui) ? parsed.uvs[ui] : null;
          uvArr.push(uv ? uv[0] : 0, uv ? uv[1] : 0);
        }
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(posArr, 3));
    geo.setAttribute("uv", new THREE.Float32BufferAttribute(uvArr, 2));
    geo.computeVertexNormals();

    const dataUri = TEXTURES[g.material];
    const matOpts = {side: THREE.DoubleSide};
    // alphaTest, not just an opaque map: several low-poly parts (e.g. the
    // steering wheel, which is a single flat quad) get their real silhouette
    // entirely from the texture's alpha channel (spokes/rim cut out), not
    // from geometry -- a period trick, not a modeling bug.
    if (dataUri) { matOpts.map = loadTexture(dataUri); matOpts.alphaTest = 0.5; }
    else matOpts.color = fallbackColors[gi % fallbackColors.length];
    root.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial(matOpts)));
  });
  scene.add(root);

  const box = new THREE.Box3().setFromObject(root);
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z);
  const radius = maxDim * 2.3;

  let az = 0.7, el = 0.22;
  function updateCam() {
    camera.position.set(
      center.x + radius*Math.cos(el)*Math.sin(az),
      center.y + radius*Math.sin(el),
      center.z + radius*Math.cos(el)*Math.cos(az)
    );
    camera.lookAt(center);
  }
  updateCam();

  let isDown = false, lastX = 0, lastY = 0;
  renderer.domElement.addEventListener("mousedown", e => { isDown = true; lastX = e.clientX; lastY = e.clientY; });
  window.addEventListener("mouseup", () => isDown = false);
  window.addEventListener("mousemove", e => {
    if (!isDown) return;
    az += (e.clientX - lastX) * 0.01;
    el = Math.max(-1.4, Math.min(1.4, el + (e.clientY - lastY) * 0.01));
    lastX = e.clientX; lastY = e.clientY;
    updateCam();
  });
  window.addEventListener("resize", () => {
    camera.aspect = W()/H();
    camera.updateProjectionMatrix();
    renderer.setSize(W(), H());
  });

  function animate(){ requestAnimationFrame(animate); renderer.render(scene, camera); }
  animate();
}
window.addEventListener("load", main);
</script>
</body></html>
"""

_SECTIONS = [
    ("Dimensions", ["mass", "width", "height", "wheelbase", "ftrack", "rtrack", "weight_distribution"]),
    ("Engine", ["power_max", "power_rpm", "torque_max", "torque_rpm", "redline", "idle_speed"]),
    ("Drivetrain", ["num_gears", "rear_end_ratio1", "rear_end_ratio2"]),
    ("Chassis (front/rear)", [
        "fbump1", "rbump1", "frebound1", "rrebound1", "fsprings1", "rsprings1", "fsway1", "rsway1",
    ]),
    ("Alignment", ["ftoe1", "rtoe1", "fcamber1", "rcamber1", "fbrake1", "rbrake1", "wheel_lock"]),
    ("Aero", ["fspoiler1", "rspoiler1", "front_lift", "rear_lift", "drag_coefficient", "frontal_area"]),
]

# (min, max) per .cf field across the game's 5 genuinely-stock retail cars --
# viper, exotic, plane, sedan, sports (the USA disc's own Data/, not the
# community Mario-Kart-conversion cars that tend to live alongside them in a
# modder's folder and would skew this toward joke/novelty values). Hardcoded
# from a one-time computation rather than read live, so generating a shell for
# a car in some other folder entirely doesn't depend on these 5 files being
# present. Shown as an informational tooltip in Car Configs (see buildStatsPanel)
# -- not enforced as a min/max on the input, since nothing here is a confirmed
# hard limit the game itself would refuse (e.g. rtrack goes negative on
# plane.car -- plausible for a non-drivable flyover prop with an unused stat,
# not evidence of what's "valid," so blocking anything outside this range would
# risk being flat wrong).
STOCK_STAT_RANGES: dict[str, tuple[float, float]] = {
    "anti_dive": (0.1, 0.1),
    "anti_squat": (0, 0.1),
    "caster": (1, 5),
    "cdiff_stiff": (0.5, 0.5),
    "cm_height": (11, 15.5),
    "cp_height": (12, 22),
    "cp_long": (46, 56),
    "drag_coefficient": (0.28, 0.37),
    "engine_drag": (0.034, 0.037),
    "engine_inertia": (11, 22),
    "fbrake1": (750, 1000),
    "fbrake2": (3000, 4000),
    "fbump1": (5, 5),
    "fbump2": (70, 70),
    "fbump_camber": (-1, -0.3),
    "fbump_toe": (-0.05, 0),
    "fcamber1": (-10, -4),
    "fcamber2": (4, 10),
    "fdiff_stiff": (0.4, 0.4),
    "fground_clearance1": (4, 36),
    "fground_clearance2": (18, 36),
    "frebound1": (5, 5),
    "frebound2": (70, 70),
    "front_lift": (-0.2, 0),
    "frontal_area": (15, 21),
    "fspoiler1": (0, 0),
    "fspoiler2": (-0.8, 0),
    "fspoiler_drag": (0, 0.2),
    "fsprings1": (0, 200),
    "fsprings2": (200, 600),
    "fsway1": (0, 0),
    "fsway2": (400, 500),
    "ftoe1": (-4, -4),
    "ftoe2": (4, 4),
    "ftrack": (56.9, 61.6),
    "fuel_capacity": (17.5, 20),
    "fuel_consumption": (0.003, 0.003),
    "height": (44.7, 54.7),
    "idle_speed": (1200, 1650),
    "lat_drag": (5, 15),
    "mass": (2460, 3850),
    "mx": (45000, 100000),
    "my": (45000, 100000),
    "mz": (6000, 15000),
    "num_gears": (5, 6),
    "power_max": (180, 600),
    "power_rpm": (5000, 7000),
    "rbrake1": (750, 1000),
    "rbrake2": (3000, 4000),
    "rbump1": (5, 5),
    "rbump2": (70, 70),
    "rbump_camber": (-1.2, -0.35),
    "rbump_toe": (0, 0),
    "rcamber1": (-10, -4),
    "rcamber2": (4, 10),
    "rdiff_stiff": (0.5, 0.5),
    "rear_end_ratio1": (2.7, 2.7),
    "rear_end_ratio2": (4.7, 4.7),
    "rear_lift": (-0.4, 0),
    "redline": (6000, 7800),
    "rground_clearance1": (4, 25),
    "rground_clearance2": (18, 25),
    "rolling_resistance": (0.327, 0.54),
    "rrebound1": (5, 5),
    "rrebound2": (70, 70),
    "rspoiler1": (0, 0),
    "rspoiler2": (-1, 0),
    "rspoiler_drag": (0, 0.2),
    "rsprings1": (0, 200),
    "rsprings2": (200, 600),
    "rsway1": (0, 0),
    "rsway2": (400, 500),
    "rtoe1": (-4, -4),
    "rtoe2": (4, 4),
    "rtrack": (-10, 62.6),
    "torque_balance": (0.5, 1),
    "torque_max": (204, 620),
    "torque_rpm": (2000, 4500),
    "trans_drag": (0, 0.002),
    "trans_inertia": (0, 0),
    "vert_drag": (5, 20),
    "weight_distribution": (24, 57.5),
    "wheel_lock": (15, 35),
    "wheelbase": (78, 107),
    "width": (59.9, 75.7),
}


def _build_texture_map(
    car_path: str | Path, material_names: set[str], paint_texture: str | Path | None = None
) -> dict[str, str | None]:
    """Resolve each material to its real .tex, convert to PNG, and return a
    material-name -> data URI map (None where no source texture could be found --
    the caller falls back to a flat color for those)."""
    raw_by_name = car.resolve_textures(car_path, material_names, paint_texture=paint_texture)
    data_uris: dict[str, str | None] = {}
    for name, raw in raw_by_name.items():
        if raw is None:
            data_uris[name] = None
            continue
        png_bytes = tex.tex_to_png_bytes(raw)
        data_uris[name] = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    return data_uris


def build_viewer_html(
    car_path: str | Path, z_offset: float = 0.0, wheel_radius: float | None = None,
    paint_texture: str | Path | None = None,
) -> str:
    result = car.assemble_car(car_path, z_offset=z_offset, wheel_radius=wheel_radius)
    obj_text, _mtl_text = mod.to_obj(result.mesh, "car.mtl")
    material_names = {m.name for m in result.mesh.materials}
    textures = _build_texture_map(car_path, material_names, paint_texture=paint_texture)

    html = _TEMPLATE
    html = html.replace("__TITLE__", f"{result.prefix} viewer")
    html = html.replace("__CAR_TITLE__", result.prefix)
    html = html.replace("__OBJ_JSON__", json.dumps(obj_text))
    html = html.replace("__STATS_JSON__", json.dumps(result.stats))
    html = html.replace("__SECTIONS_JSON__", json.dumps(_SECTIONS))
    html = html.replace("__TEXTURES_JSON__", json.dumps(textures))
    return html


_PART_TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>__TITLE__</title>
<style>
  html,body{margin:0;height:100%;background:#1a1a1a;font-family:system-ui,sans-serif;overflow:hidden}
  #canvas-wrap{position:absolute;inset:0}
  #label{position:absolute;top:16px;left:16px;color:#e8eaf2;font-size:1.1rem;font-weight:600}
  #hint{position:absolute;bottom:16px;left:16px;color:#8a90a4;font-size:.75rem}
  #fatal-error{position:absolute;top:0;left:0;right:0;padding:16px;background:#3a1414;
               color:#ffd9d9;font-family:monospace;font-size:.85rem;white-space:pre-wrap;
               z-index:10;display:none}
</style>
<script>
  window.addEventListener("error", (e) => {
    const el = document.getElementById("fatal-error");
    el.style.display = "block";
    el.textContent += "ERROR: " + (e.error ? (e.error.stack || e.error.message) : e.message) + "\n";
  });
</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head><body>
<div id="canvas-wrap"></div>
<div id="fatal-error"></div>
<div id="label">__TITLE__</div>
<div id="hint">Drag to orbit</div>
<script>
const OBJ_TEXT = __OBJ_JSON__;
const TEXTURES = __TEXTURES_JSON__;

function parseObj(text) {
  const positions = [], uvs = [], normals = [], groups = [];
  let current = null;
  for (const line of text.split("\n")) {
    const parts = line.trim().split(/\s+/);
    if (parts[0] === "v") positions.push(parts.slice(1).map(Number));
    else if (parts[0] === "vt") uvs.push(parts.slice(1).map(Number));
    else if (parts[0] === "vn") normals.push(parts.slice(1).map(Number));
    else if (parts[0] === "usemtl") { current = {material: parts[1], faces: []}; groups.push(current); }
    else if (parts[0] === "f") {
      const idx = parts.slice(1).map(p => p.split("/").map(x => parseInt(x,10)-1));
      current.faces.push(idx);
    }
  }
  return {positions, uvs, normals, groups};
}

function main() {
  if (typeof THREE === "undefined") {
    const el = document.getElementById("fatal-error");
    el.style.display = "block";
    el.textContent = "three.js failed to load from the CDN -- needs internet access, "
      + "or open this via a local server instead of double-clicking the file.";
    return;
  }
  const parsed = parseObj(OBJ_TEXT);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1a1a1a);
  const wrap = document.getElementById("canvas-wrap");
  const W = () => wrap.clientWidth, H = () => wrap.clientHeight;
  const camera = new THREE.PerspectiveCamera(45, W()/H(), 0.01, 1000);
  const renderer = new THREE.WebGLRenderer({antialias:true, preserveDrawingBuffer:true});
  renderer.setSize(W(), H());
  wrap.appendChild(renderer.domElement);

  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  const dl = new THREE.DirectionalLight(0xffffff, 0.9);
  dl.position.set(5,10,7);
  scene.add(dl);
  const dl2 = new THREE.DirectionalLight(0xffffff, 0.4);
  dl2.position.set(-5,3,-7);
  scene.add(dl2);

  const loader = new THREE.TextureLoader();
  const textureCache = {};
  function loadTexture(dataUri) {
    if (!textureCache[dataUri]) textureCache[dataUri] = loader.load(dataUri);
    return textureCache[dataUri];
  }

  const fallbackColors = [0x999999, 0x777777, 0xaaaaaa];
  const root = new THREE.Group();
  parsed.groups.forEach((g, gi) => {
    const posArr = [], uvArr = [];
    for (const face of g.faces) {
      // Fan-triangulate n-gons (real models -- Blender especially -- export
      // quads and larger polys, not just triangles) and tolerate faces with no
      // vt (f a//n): parseObj yields ui=NaN there, so guard with isFinite and
      // fall back to (0,0) rather than indexing uvs[NaN] -> undefined -> crash.
      for (let k = 1; k + 1 < face.length; k++) {
        const tri = [face[0], face[k], face[k + 1]];
        if (tri.some(v => !parsed.positions[v[0]])) continue;   // skip a face with a bad index
        for (const [pi, ui] of tri) {
          const p = parsed.positions[pi];
          posArr.push(p[0], p[1], p[2]);
          const uv = Number.isFinite(ui) ? parsed.uvs[ui] : null;
          uvArr.push(uv ? uv[0] : 0, uv ? uv[1] : 0);
        }
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(posArr, 3));
    geo.setAttribute("uv", new THREE.Float32BufferAttribute(uvArr, 2));
    geo.computeVertexNormals();

    const dataUri = TEXTURES[g.material];
    const matOpts = {side: THREE.DoubleSide};
    // see the matching comment in _TEMPLATE: alpha-cutout parts (e.g. the
    // flat-quad steering wheel) need this to show their real silhouette.
    if (dataUri) { matOpts.map = loadTexture(dataUri); matOpts.alphaTest = 0.5; }
    else matOpts.color = fallbackColors[gi % fallbackColors.length];
    root.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial(matOpts)));
  });
  scene.add(root);

  const box = new THREE.Box3().setFromObject(root);
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z);
  const radius = maxDim * 2.3;

  let az = 0.7, el = 0.3;
  function updateCam() {
    camera.position.set(
      center.x + radius*Math.cos(el)*Math.sin(az),
      center.y + radius*Math.sin(el),
      center.z + radius*Math.cos(el)*Math.cos(az)
    );
    camera.lookAt(center);
  }
  updateCam();

  let isDown = false, lastX = 0, lastY = 0;
  renderer.domElement.addEventListener("mousedown", e => { isDown = true; lastX = e.clientX; lastY = e.clientY; });
  window.addEventListener("mouseup", () => isDown = false);
  window.addEventListener("mousemove", e => {
    if (!isDown) return;
    az += (e.clientX - lastX) * 0.01;
    el = Math.max(-1.4, Math.min(1.4, el + (e.clientY - lastY) * 0.01));
    lastX = e.clientX; lastY = e.clientY;
    updateCam();
  });
  window.addEventListener("resize", () => {
    camera.aspect = W()/H();
    camera.updateProjectionMatrix();
    renderer.setSize(W(), H());
  });

  function animate(){ requestAnimationFrame(animate); renderer.render(scene, camera); }
  animate();
}
window.addEventListener("load", main);
</script>
</body></html>
"""


def _render_mesh_html(mesh: mod.Mesh, textures: dict[str, str | None], title: str) -> str:
    """Shared free-orbit, no-stats-panel renderer behind build_part_viewer_html() and
    build_cockpit_viewer_html() -- any already-built Mesh + resolved texture map."""
    obj_text, _mtl_text = mod.to_obj(mesh, "part.mtl")
    html = _PART_TEMPLATE
    html = html.replace("__TITLE__", title)
    html = html.replace("__OBJ_JSON__", json.dumps(obj_text))
    html = html.replace("__TEXTURES_JSON__", json.dumps(textures))
    return html


def _car_mod_parts(car_path: str | Path) -> dict[str, tuple[str, set[str]] | None]:
    """Every real .mod entry in a car's OWN archive, individually -- {entryName:
    (objText, materialNames), or None if it failed to parse}. Deliberately not the
    same thing as the curated Car/Cockpit/Horn Ball tabs (see build_shell_html):
    those merge several real files together for a cleaner 3D view (chassis = body +
    mirror + spoiler if present; cockpit = dash + wheel) or skip some outright
    (LOD1-7, Needle.mod), which makes "export this and reimport it" ambiguous. This
    instead gives the Parts drawer one real file in, one real file's worth of OBJ
    out, for every entry a real car carries -- verified against viper.car (13 .mod
    entries, including a full 8-level Viper0..7.mod LOD chain) and bowser.car (20,
    including its own overridden wheel_*/fwheel_*/spin_*/ball.mod) with zero parse
    failures, but errors are caught per-entry (not raised) since a modder's own
    archive could contain something unexpected.

    Textures aren't resolved here -- the caller folds materialNames into one
    page-wide material set and resolves it once (see build_shell_html), rather than
    each of a car's 13-21 parts embedding its own separately-resolved copy of
    textures most of them share (every LOD level reuses the body's own material,
    for instance). An earlier per-part version of this ballooned a real 25-car
    gallery from 22.8MB to 68.3MB doing exactly that.
    """
    entries = archive.read(car_path)
    parts: dict[str, tuple[str, set[str]] | None] = {}
    for e in entries:
        if not e.name.lower().endswith(".mod"):
            continue
        raw = envelope.build(e.tag, e.version, e.payload)
        try:
            mesh = mod.parse(raw)
            obj_text, _mtl_text = mod.to_obj(mesh, f"{e.name}.mtl")
            material_names = {m.name for m in mesh.materials}
        except Exception:
            parts[e.name] = None
            continue
        parts[e.name] = (obj_text, material_names)
    return parts


# race.res carries 16 .sfx entries total, but most are generic system audio no
# modding guide treats as belonging to any one car: crash1-3/road1-2/scrape/
# splash (impact/environment noise), go/ready (start countdown), cboth/cclear/
# cleft/cright (spotter voice cues). horn.sfx/shift1.sfx/squeal.sfx are the
# exception -- confirmed per-car overridable in practice (bowser.car ships its
# own horn.sfx AND squeal.sfx, distinct from race.res's), consistent with the
# mksfx guide treating horn/shift as per-car files. Only these three get shown
# as a car's shared-default fallback; the rest stay out of the Sound drawer
# entirely to avoid burying real per-car sounds under generic game audio.
SHARED_SFX_ROLES = ("horn.sfx", "shift1.sfx", "squeal.sfx")


def _car_sfx_parts(car_path: str | Path) -> dict[str, dict | None]:
    """Every real .sfx entry in a car's OWN archive, plus a shared-default fallback
    for any of SHARED_SFX_ROLES the car doesn't own itself -- {entryName: info},
    where info is {"wav_b64": str | None, "sample_rate": int, "bits_per_sample":
    int, "duration": float, "is_pcm": bool, "shared": bool}, or None (own entries
    only) if the entry failed to parse entirely (same per-entry-not-whole-page
    error handling as _car_mod_parts).

    wav_b64 is specifically None for the still-undecoded ADPCM variant
    (format_tag=2 -- see sfx.py's module docstring for what's and isn't solved
    there) rather than omitting the entry: every real .sfx in retail data is PCM,
    but a modder's own archive could carry ADPCM, and listing it (just without a
    player) is more honest than silently hiding a real file, same choice the
    Parts drawer makes for a .mod entry that fails to parse.
    """
    entries = archive.read(car_path)
    parts: dict[str, dict | None] = {}
    for e in entries:
        if not e.name.lower().endswith(".sfx"):
            continue
        raw = envelope.build(e.tag, e.version, e.payload)
        try:
            info = sfx.parse(raw)
        except Exception:
            parts[e.name] = None
            continue
        wav_b64 = base64.b64encode(sfx.to_wav_bytes(info)).decode("ascii") if info.is_pcm else None
        parts[e.name] = {
            "wav_b64": wav_b64,
            "sample_rate": info.sample_rate,
            "bits_per_sample": info.bits_per_sample,
            "duration": round(info.duration_seconds, 2),
            "is_pcm": info.is_pcm,
            "shared": False,
        }

    owned_lower = {name.lower() for name in parts}
    for role in SHARED_SFX_ROLES:
        if role in owned_lower:
            continue
        raw = car.find_shared(car_path, entries, role)
        if raw is None:
            continue
        try:
            info = sfx.parse(raw)
        except Exception:
            # Would mean a real vrmod bug (this is tested retail data, not a
            # modder's own archive) -- skip rather than show a confusing parse
            # error for a file that isn't even this car's own.
            continue
        wav_b64 = base64.b64encode(sfx.to_wav_bytes(info)).decode("ascii") if info.is_pcm else None
        parts[role] = {
            "wav_b64": wav_b64,
            "sample_rate": info.sample_rate,
            "bits_per_sample": info.bits_per_sample,
            "duration": round(info.duration_seconds, 2),
            "is_pcm": info.is_pcm,
            "shared": True,
        }
    return parts


def _resolve_shared_textures(data_dir: str | Path, material_names: set[str]) -> dict[str, str | None]:
    """Same job as _build_texture_map(), but for a shared, car-agnostic part (e.g.
    ball.mod, the horn ball) that isn't tied to any one car's own archive -- looks
    up each material name directly across DEFAULT_SHARED_ARCHIVES in data_dir."""
    data_dir = Path(data_dir)
    textures: dict[str, str | None] = {}
    for name in material_names:
        tex_raw = car.find_in_shared_archives(data_dir, name)
        if tex_raw is None:
            textures[name] = None
            continue
        png_bytes = tex.tex_to_png_bytes(tex_raw)
        textures[name] = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    return textures


def build_part_viewer_html(data_dir: str | Path, mod_name: str, title: str | None = None) -> str:
    """Render a single standalone .mod (searched across the shared resource archives in
    data_dir, e.g. race.res) with its real texture(s) -- no assembly, no stats panel.
    For car-agnostic shared assets like ball.mod (the horn ball) or any of the wheel
    meshes, viewed on their own."""
    data_dir = Path(data_dir)
    raw = car.find_in_shared_archives(data_dir, mod_name)
    if raw is None:
        raise ValueError(f"{mod_name!r} not found in any of {car.DEFAULT_SHARED_ARCHIVES} under {data_dir}")
    mesh = mod.parse(raw)
    textures = _resolve_shared_textures(data_dir, {m.name for m in mesh.materials})
    return _render_mesh_html(mesh, textures, title or mod_name)


def build_cockpit_viewer_html(car_path: str | Path, title: str | None = None) -> str:
    """Dashboard + steering wheel (car.assemble_cockpit(), using the real position from
    cockpit.tab), free-orbit and no stats panel -- a "look around and check the fit"
    view rather than an attempt at the game's exact static cockpit camera, which proved
    to be its own rabbit hole (camera framing is genuinely hard to pin down without
    more reference data, separate from the wheel's position, which cockpit.tab already
    gives us for real)."""
    car_path = Path(car_path)
    result = car.assemble_cockpit(car_path)
    material_names = {m.name for m in result.mesh.materials}
    raw_by_name = car.resolve_textures(car_path, material_names)
    textures: dict[str, str | None] = {}
    for name, raw in raw_by_name.items():
        if raw is None:
            textures[name] = None
            continue
        textures[name] = "data:image/png;base64," + base64.b64encode(tex.tex_to_png_bytes(raw)).decode("ascii")

    return _render_mesh_html(result.mesh, textures, title or f"{result.prefix} cockpit")


def write_cockpit_viewer_html(car_path: str | Path, out_path: str | Path, title: str | None = None) -> None:
    html = build_cockpit_viewer_html(car_path, title=title)
    Path(out_path).write_text(html, encoding="utf-8")


def write_part_viewer_html(
    data_dir: str | Path, mod_name: str, out_path: str | Path, title: str | None = None
) -> None:
    html = build_part_viewer_html(data_dir, mod_name, title=title)
    Path(out_path).write_text(html, encoding="utf-8")


_SHELL_TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>__TITLE__</title>
<style>
  html,body{margin:0;height:100%;background:#1a1a1a;font-family:system-ui,sans-serif;overflow:hidden}
  #canvas-wrap{position:absolute;inset:0;top:52px}
  #topbar{position:absolute;top:0;left:0;right:0;height:52px;background:#20242c;color:#e8eaf2;
          display:flex;align-items:center;gap:24px;padding:0 16px;box-sizing:border-box;
          border-bottom:1px solid #333;z-index:5}
  #car-name{font-weight:700;font-size:1rem;white-space:nowrap;line-height:1.2}
  /* Same name-over-filename pairing the track viewer uses. They diverge as
     soon as anything is modded, and the filename is what you reach for on
     disk while the name is what you recognise. */
  #car-name .file{display:block;color:#8a90a4;font-size:.7rem;font-weight:400;
    font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
  #tabs{display:flex;gap:4px}
  #tabs button{background:none;border:1px solid transparent;color:#a8adc0;padding:8px 14px;
               border-radius:4px;cursor:pointer;font-size:.85rem}
  #tabs button:hover{color:#e8eaf2}
  #tabs button.active{background:#14161c;color:#fff;border-color:#3a3f4e}
  #topbar-actions{margin-left:auto;display:flex;gap:8px}
  #topbar-actions button{background:#14161c;border:1px solid #3a3f4e;color:#e8eaf2;padding:8px 14px;
                          border-radius:4px;cursor:pointer;font-size:.85rem}
  #topbar-actions button:hover{background:#1c1f28}
  #topbar-actions button.active{background:#1911ab;border-color:#1911ab}
  #mod-toggle{background:#2a1f10;border-color:#7a5220;color:#ffce8a}
  #mod-toggle:hover{background:#372811}
  body.mod-mode #mod-toggle{background:#7a5220;border-color:#ffce8a;color:#fff}
  /* Editing panels + file actions appear only in mod mode. */
  #panel-group,#commit-btn,#more-wrap{display:none}
  body.mod-mode #panel-group{display:inline-flex}
  body.mod-mode #commit-btn,body.mod-mode #more-wrap{display:inline-block}
  /* Segmented panel group: joined toggle buttons with hairline dividers. */
  #panel-group{border:1px solid #3a3f4e;border-radius:4px;overflow:hidden}
  #panel-group button{background:#14161c;border:none;border-left:1px solid #3a3f4e;color:#e8eaf2;
                      padding:8px 14px;cursor:pointer;font-size:.85rem;border-radius:0}
  #panel-group button:first-child{border-left:none}
  #panel-group button:hover{background:#1c1f28}
  #panel-group button.active{background:#1911ab}
  /* ⋯ overflow menu for the secondary file actions (Discard, Restore). */
  #more-wrap{position:relative}
  #more-btn{padding:8px 12px}
  #more-menu{position:absolute;top:calc(100% + 4px);right:0;min-width:190px;background:#20242c;
             border:1px solid #3a3f4e;border-radius:6px;padding:4px;z-index:8;flex-direction:column;gap:2px;
             box-shadow:0 8px 24px rgba(0,0,0,.5)}
  #more-menu:not([hidden]){display:flex}
  #more-menu button{display:block;width:100%;text-align:left;background:none;border:none;color:#e8eaf2;
                    padding:8px 10px;border-radius:4px;cursor:pointer;font-size:.82rem;white-space:nowrap}
  #more-menu button:hover{background:#2a2f3a}
  #more-menu button:disabled{color:#5a5f6e;cursor:default;background:none}
  #restore-btn{color:#ffd9d9}
  #restore-btn:hover{background:#3a1414}
  /* View-only (public gallery): no way into mod mode -- hide every mod affordance. */
  body.view-only #mod-toggle,body.view-only #panel-group,
  body.view-only #commit-btn,body.view-only #more-wrap{display:none!important}
  #commit-btn{background:#1a5c2e;border-color:#2e8a4e}
  #commit-btn:hover{background:#206e38}
  #commit-btn:disabled{background:#14161c;border-color:#3a3f4e;color:#5a5f6e;cursor:default}
  /* Below the drawers (z-index:4) so a save/export banner never paints over an
     open drawer's header/filter; its left-aligned text still reads in the open area. */
  #commit-status{position:absolute;top:52px;left:0;right:0;padding:10px 16px;font-size:.82rem;
                  z-index:3;display:none;word-break:break-all}
  #commit-status.ok{display:block;background:#123a1e;color:#9fe3af;border-bottom:1px solid #2e8a4e}
  #commit-status.error{display:block;background:#3a1414;color:#ffd9d9;border-bottom:1px solid #7a2020}
  #commit-status.pending{display:block;background:#20242c;color:#a8adc0;border-bottom:1px solid #3a3f4e}
  .drawer{position:absolute;top:52px;right:0;width:320px;height:calc(100% - 52px);background:#20242c;
          color:#e8eaf2;box-sizing:border-box;padding:16px;overflow-y:auto;border-left:1px solid #333;
          transform:translateX(100%);transition:transform .18s ease;z-index:4}
  .drawer.open{transform:translateX(0)}
  .drawer h2{margin:0 0 4px;font-size:1.1rem}
  .drawer .hint{font-size:.75rem;color:#8a90a4;margin-bottom:14px}
  .section{margin-bottom:14px}
  .section h3{font-size:.72rem;text-transform:uppercase;letter-spacing:.05em;color:#8a90a4;
              margin:0 0 6px;border-bottom:1px solid #333;padding-bottom:4px}
  .row{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:4px;font-size:.82rem}
  .row label{color:#c4c8d8;min-width:0;overflow-wrap:break-word}
  .row.live-field label{color:#8ecfff;cursor:help}
  .row.live-field input{border-color:#2a4a66}
  .row input{width:64px;background:#14161c;border:1px solid #3a3f4e;color:#e8eaf2;
             border-radius:3px;padding:3px 6px;font-size:.8rem;text-align:right}
  .row input[readonly]{background:transparent;border-color:transparent;padding:3px 0;color:#e8eaf2}
  .row.live-field input[readonly]{color:#8ecfff}
  .cockpit-record{margin-bottom:16px}
  .cockpit-record h3{font-size:.78rem;color:#c4c8d8;margin:0 0 6px}
  .cockpit-record.live h3{color:#8ecfff}
  .gauge-preview{display:flex;flex-direction:column;gap:8px;margin-bottom:16px;
    padding:10px;background:#14161c;border:1px solid #2a2e3a;border-radius:6px}
  .gauge-preview button{align-self:flex-start;background:#1c2050;color:#8ecfff;
    border:1px solid #2a2e6a;border-radius:5px;padding:4px 12px;font-size:.72rem;cursor:pointer}
  .gauge-preview button:hover{background:#242a66}
  .gauge-preview label{display:flex;align-items:center;gap:8px;font-size:.7rem;color:#8a90a4}
  .gauge-preview input[type=range]{flex:1;min-width:0}
  .gauge-preview span{min-width:42px;text-align:right;color:#c4c8d8;
    font-variant-numeric:tabular-nums}
  .cockpit-fields{display:flex;gap:6px}
  .cockpit-field{flex:1;min-width:0}
  .cockpit-field label{display:block;font-size:.65rem;color:#8a90a4;margin-bottom:2px}
  .cockpit-field input{background:#14161c;border:1px solid #3a3f4e;
                        color:#e8eaf2;border-radius:3px;padding:4px 5px;font-size:.78rem;text-align:right}
  /* Larger, reliably-clickable +/- replacements for the tiny native number-input
     spinner arrows (see wrapWithStepper's own comment for why). The native ones
     are hidden on any wrapped input rather than left doubled-up alongside these. */
  .stepper{display:flex;align-items:stretch;gap:2px;flex-shrink:0}
  /* Fixed width, not flex:1 -- an unstyled number input's intrinsic/flex-basis
     width falls back to the browser default (~170-190px, the old HTML `size=20`
     behavior), which blew the stepper's footprint out to 213px and left almost
     nothing for the label (see .row label's own comment on why that needs room
     to wrap into). Car Configs' .row.stepper wants this fixed and small;
     Cockpit Configs' narrower 3-per-row layout overrides it back to flexible
     below, where there's no label competing for the same horizontal space. */
  .stepper input{width:56px;box-sizing:border-box}
  .stepper input::-webkit-inner-spin-button,.stepper input::-webkit-outer-spin-button{
    -webkit-appearance:none;margin:0}
  .stepper input{-moz-appearance:textfield}
  .cockpit-field .stepper input{width:auto;flex:1;min-width:0}
  .step-btn{flex:0 0 20px;width:20px;background:#14161c;border:1px solid #3a3f4e;color:#a8adc0;
            border-radius:3px;cursor:pointer;font-size:.85rem;line-height:1;padding:0;
            display:flex;align-items:center;justify-content:center}
  .step-btn:hover{background:#2a2f3a;color:#e8eaf2}
  .step-btn:active{background:#343946}
  .cockpit-field .step-btn{flex-basis:16px;width:16px;font-size:.7rem}
  #cockpit-reset{width:100%;padding:10px;margin-top:6px;border:none;border-radius:4px;
                  font-size:.85rem;cursor:pointer;background:#2a2e38;color:#e8eaf2}
  #cockpit-reset:hover{background:#343946}
  #export,#reset-stats{width:100%;padding:10px;margin-top:10px;border:none;
          border-radius:4px;font-size:.85rem;cursor:pointer;display:none}
  body.mod-mode #export,body.mod-mode #reset-stats{display:block}
  #export{background:#1911ab;color:#fff}
  #export:hover{background:#2419d0}
  #reset-stats{background:#2a2e38;color:#e8eaf2}
  #reset-stats:hover{background:#343946}
  .car-name-row{display:flex;align-items:center;gap:8px;margin:2px 0 8px}
  .car-name-row label{font-size:.8rem;color:#a8adc0;flex:0 0 auto}
  #car-name-input{flex:1 1 auto;min-width:0;background:#14161c;border:1px solid #3a3f4e;color:#e8eaf2;
                  border-radius:3px;padding:6px 8px;font-size:.85rem}
  #car-name-input:focus{outline:none;border-color:#5a6cff}
  #hint2{font-size:.72rem;color:#8a90a4;margin-top:8px;display:none}
  body.mod-mode #hint2{display:block}
  #texture-list{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  /* Texture-provenance readout (car.texture_provenance) */
  .prov-summary{grid-column:1/-1;font-size:12px;padding:8px 10px;border-radius:6px;line-height:1.45}
  .prov-verdict-self-contained{background:#14301c;color:#9fe0b0;border:1px solid #2e6b40}
  .prov-verdict-portable{background:#15233a;color:#9cc7f5;border:1px solid #2e4e7a}
  .prov-verdict-incomplete{background:#3a1516;color:#f0a9a3;border:1px solid #7a2e2e}
  .prov-badge{margin-left:6px;font-size:9px;text-transform:uppercase;letter-spacing:.04em;
    padding:1px 5px;border-radius:4px;vertical-align:middle;cursor:help}
  .prov-own{background:#1c3a26;color:#8fdca6}
  .prov-shared{background:#1c2a44;color:#8fb8ef}
  .prov-paint{background:#2e2444;color:#c3a9ef}
  .prov-missing{background:#442022;color:#ef9a94}
  .swatch{border:2px solid #3a3f4e;border-radius:6px;overflow:hidden;background:#14161c}
  .swatch img{display:block;width:100%;aspect-ratio:1;object-fit:cover}
  .swatch .missing{width:100%;aspect-ratio:1;display:flex;align-items:center;justify-content:center;
                    color:#5a5f6e;font-size:.7rem;text-align:center;padding:4px;box-sizing:border-box}
  .swatch .sub{font-size:.65rem;color:#8a90a4;margin-top:2px;font-variant-numeric:tabular-nums}
  .swatch .name{font-size:.7rem;color:#a8adc0;text-align:center;padding:3px 0;word-break:break-all}
  .swatch.pending{border-color:#e8a33d}
  .swatch.pending .name{color:#e8a33d}
  .swatch-actions{display:flex;flex-direction:row-reverse;margin-top:4px;border-top:1px solid #2a2e3a}
  .swatch-export,.swatch-import{flex:1;text-align:center;cursor:pointer;font-size:.7rem;
                  padding:5px 4px;box-sizing:border-box}
  .swatch-export{background:#14161c;color:#c5cbd8;border-left:1px solid #2a2e3a}
  .swatch-export:hover{background:#2a2f3a}
  .swatch-import{background:#1c1f4a;color:#8ecfff}
  .swatch-import:hover{background:#252a5c}
  .swatch-import input{display:none}
  .swatch-revert{flex:0 0 auto;text-align:center;cursor:pointer;font-size:.85rem;line-height:1;
                 padding:5px 9px;box-sizing:border-box;background:#3a1414;color:#ffd9d9}
  .swatch-revert:hover{background:#4a1a1a}
  #import-tga-status{font-size:.72rem;color:#8ecfff;margin-bottom:8px;min-height:1em;word-break:break-all}
  .empty{font-size:.8rem;color:#8a90a4;font-style:italic}
  .part-grp{font-size:.68rem;color:#7f8598;letter-spacing:.03em;padding:11px 6px 3px;text-transform:none}
  .part-row{display:flex;align-items:center;gap:8px;
            padding:7px 6px;border-bottom:1px solid #23262f;font-size:.82rem;border-radius:4px}
  .part-row.selectable{cursor:pointer}
  .part-row.selectable:hover{background:#242836}
  .part-row.selected{background:#1c1f4a}
  .part-row .dot{width:7px;height:7px;border-radius:50%;flex:0 0 7px;background:#5f6472}
  .part-row.empty .dot{background:transparent;border:1px dashed #5a5f6e;width:6px;height:6px;flex:0 0 6px}
  .part-row.shared-default .dot{background:transparent;border:1px solid #4a5570}
  #parts-list.show-all .part-row.rendered .dot{background:#8ecfff}
  .part-row.filter-hidden,.part-grp.filter-hidden,.part-detail-box.filter-hidden{display:none!important}
  #parts-drawer h2{display:flex;align-items:center;gap:6px}
  .filter-btn{margin-left:auto;background:transparent;border:1px solid #3a3f4e;border-radius:4px;
              color:#7f8598;cursor:pointer;padding:4px 6px;line-height:0}
  .filter-btn:hover{color:#e8eaf2;border-color:#4a5570}
  .filter-btn.active{color:#8ecfff;border-color:#2b2f63;background:#1c1f4a}
  .part-main{display:flex;flex-direction:column;min-width:0;flex:1;gap:1px}
  .part-row .part-name{overflow-wrap:break-word}
  .part-row.empty .part-name{color:#7f8598}
  #parts-list.show-all .part-row.rendered .part-name{font-weight:700;color:#8ecfff}
  .part-sub{font-family:monospace;font-size:.64rem;color:#6f7486;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .part-sub .note{color:#e8a33d}
  .part-row.staged{border-left:3px solid #e8a33d;padding-left:3px}
  .part-row.staged .part-name{color:#e8a33d}
  .part-row.removing .part-name{color:#7f8598;text-decoration:line-through}
  .part-tag{font-size:.62rem;color:#e8a33d;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%}
  .part-tag:empty{display:none}
  .part-always{display:flex;gap:6px;align-items:center;flex-shrink:0}
  /* Buttons are always shown -- no hover reveal (it reflowed jitterily, and it
     would collide with a future hover-to-highlight-in-3D). Removing/added rows
     hide the action buttons since only the revert applies. */
  .part-actions{display:flex;gap:6px;flex-shrink:0}
  .part-row.removing .part-actions,.part-row.added .part-actions{display:none}
  .part-row button,.part-row label.part-import{background:#14161c;border:1px solid #3a3f4e;color:#e8eaf2;
                    padding:4px 7px;border-radius:3px;cursor:pointer;font-size:.7rem;white-space:nowrap}
  .part-row button:hover,.part-row label.part-import:hover{background:#2a2f3a}
  .part-row label.part-import{background:#1c1f4a;color:#8ecfff}
  .part-row label.part-import:hover{background:#252a5c}
  .part-row label.part-import input,.part-add input{display:none}
  .part-add{background:transparent;border:1px dashed #3a4a63;color:#8ecfff;
            padding:5px 10px;border-radius:3px;cursor:pointer;font-size:.72rem;white-space:nowrap}
  .part-add:hover{background:#1c1f4a}
  .part-row button.part-revert{flex:0 0 auto;padding:4px 8px;font-size:.9rem;line-height:1;
                    background:#3a1414;border-color:#7a2020;color:#ffd9d9}
  .part-row button.part-revert:hover{background:#4a1a1a}
  .part-row button.part-remove{flex:0 0 auto;padding:4px 7px;font-size:.85rem;line-height:1;
                    background:#3a1414;border-color:#7a2020;color:#ffd9d9}
  .part-row button.part-remove:hover{background:#4a1a1a}
  .part-lodtoggle{color:#a8adc0}
  .part-lodtoggle:hover{background:#242836}
  .part-lodtoggle .chev{color:#8ecfff;font-size:1.2rem;line-height:1;margin-right:6px;width:1em;display:inline-block;text-align:center}
  .part-row .part-error{color:#a88;font-size:.72rem}
  .sound-row{margin-bottom:16px}
  .sound-row .sound-name{font-size:.82rem;word-break:break-all}
  .sound-row .sound-meta{font-size:.72rem;color:#8a90a4;margin:2px 0 6px}
  .sound-row audio{width:100%;height:32px}
  .sound-row .sound-unplayable{font-size:.72rem;color:#a88}
  .sound-row.pending{border-left:3px solid #e8a33d;padding-left:8px}
  .sound-row.pending .sound-name{color:#e8a33d}
  .sound-row .sound-import{display:inline-block;padding:5px 10px;margin-top:6px;background:#2a2e38;
                            color:#e8eaf2;border-radius:4px;cursor:pointer;font-size:.72rem}
  .sound-row .sound-import:hover{background:#343946}
  .sound-row .sound-import input{display:none}
  .sound-row .sound-actions{display:flex;gap:6px;align-items:center;margin-top:6px}
  .sound-row .sound-actions .sound-import{margin-top:0}
  .sound-row button.sound-revert{padding:4px 9px;font-size:.9rem;line-height:1;border-radius:3px;cursor:pointer;
                    background:#3a1414;border:1px solid #7a2020;color:#ffd9d9}
  .sound-row button.sound-revert:hover{background:#4a1a1a}
  .sound-row .sound-import-status{font-size:.7rem;color:#8ecfff;margin-top:4px;min-height:1em;word-break:break-all}
  .info-i{font-size:.8rem;color:#8ecfff;cursor:help;margin-left:6px;vertical-align:middle;font-weight:400}
  .info-i:hover{color:#bfe4ff}
  /* The parts drawer is a fixed header (heading + locked preview) over a single
     scroll region (the slot list). Only #parts-list scrolls, so nothing ever
     renders behind the preview box. Overrides .drawer's own overflow-y:auto. */
  #parts-drawer{display:flex;flex-direction:column;overflow:hidden}
  #parts-sticky{flex:0 0 auto;margin:0 -16px 8px;padding:0 16px 8px;border-bottom:1px solid #2a2e38}
  #parts-list{flex:1 1 auto;min-height:0;overflow-y:auto;margin:0 -16px;padding:0 16px}
  #part-preview-wrap{margin-bottom:8px;border:1px solid #333;border-radius:6px;overflow:hidden}
  #part-preview-canvas{width:100%;height:150px;background:#14161c}
  #part-preview-canvas canvas{display:block}
  #part-preview-label{padding:6px 8px;font-size:.72rem;color:#a8adc0;background:#1c1f28;word-break:break-all}
  #import-obj-status,#import-tga-status{font-size:.72rem;color:#8ecfff;margin-bottom:8px;min-height:1em;word-break:break-all}
  #hint{position:absolute;bottom:16px;left:16px;color:#8a90a4;font-size:.75rem;z-index:3}
  #eye-mode-bar{display:none;align-items:center;gap:10px;position:absolute;bottom:16px;left:16px;
                color:#8ecfff;font-size:.75rem;z-index:3}
  #exit-eye-mode{background:#14161c;border:1px solid #2a4a66;color:#e8eaf2;padding:5px 10px;
                 border-radius:4px;cursor:pointer;font-size:.72rem}
  #exit-eye-mode:hover{background:#1c2430}
  #cam-readout{position:absolute;top:60px;left:16px;color:#8a90a4;font-size:.72rem;
               font-family:monospace;background:#14161cc0;padding:6px 9px;border-radius:4px;
               z-index:3;white-space:pre;pointer-events:none}
  #fatal-error{position:absolute;top:52px;left:0;right:0;padding:16px;background:#3a1414;
               color:#ffd9d9;font-family:monospace;font-size:.85rem;white-space:pre-wrap;
               z-index:10;display:none}
</style>
<script>
  window.addEventListener("error", (e) => {
    const el = document.getElementById("fatal-error");
    el.style.display = "block";
    el.textContent += "ERROR: " + (e.error ? (e.error.stack || e.error.message) : e.message) + "\n";
  });
  window.addEventListener("unhandledrejection", (e) => {
    const el = document.getElementById("fatal-error");
    el.style.display = "block";
    el.textContent += "UNHANDLED REJECTION: " + e.reason + "\n";
  });
</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
  // Same-origin, so the host's controls are reachable directly -- no message
  // protocol. Null when this page is opened on its own, in which case the
  // button stays hidden and nothing below runs.
  const HOST = (() => {
    try { return window.self !== window.top ? window.parent.vrmodHost : null; }
    catch(e) { return null; }
  })();
  window.addEventListener("DOMContentLoaded", () => {
    const b = document.getElementById("expand-btn");
    if(!HOST || !b) return;
    const sync = () => { b.hidden = false;
      b.textContent = HOST.isExpanded() ? "⇲ Show library" : "⇱ Full width"; };
    sync();
    b.addEventListener("click", () => {
      HOST.setExpanded(!HOST.isExpanded());
      setTimeout(sync, 220);
    });
  });
</script>
</head><body class="__BODY_CLASS__">
<header id="topbar">
  <div id="car-name">__CAR_TITLE__<span class="file">__CAR_FILE__</span></div>
  <nav id="tabs"></nav>
  <div id="topbar-actions">
    <!-- Sizing is a property of the view, so it lives here rather than in the
         host's footer. Hidden unless embedded -- see the HOST block below. -->
    <button id="expand-btn" type="button" hidden></button>
    <!-- Editing panels, grouped as one segmented unit. "Configs" is contextual:
         it opens Car Configs on the Car tab, Cockpit Configs on the Cockpit tab. -->
    <div id="panel-group">
      <button id="configs-btn" title="Edit this view's config (car stats / cockpit calibration)">Configs</button>
      <button id="textures-btn">Textures</button>
      <button id="parts-btn">Parts</button>
      <button id="sound-btn">Sound</button>
    </div>
    <!-- File actions: Save is primary; the rest live in the ⋯ menu. -->
    <button id="commit-btn" title="Save changes to the car (backs up the original first)">Save</button>
    <div id="more-wrap">
      <button id="more-btn" title="More actions" aria-haspopup="true" aria-expanded="false">⋯</button>
      <div id="more-menu" hidden role="menu">
        <button id="discard-btn" role="menuitem" title="Discard every staged (unsaved) change">Discard all changes</button>
        <button id="restore-btn" role="menuitem" title="Revert the car on disk to its original pre-edit backup">Restore original…</button>
      </div>
    </div>
    <button id="mod-toggle">Mod it! ✎</button>
  </div>
</header>
<div id="commit-status"></div>
<div id="canvas-wrap"></div>
<div id="fatal-error"></div>
<div id="cam-readout"></div>
<div id="hint">Drag to orbit -- scroll to zoom</div>
<div id="eye-mode-bar">Driver's-eye view -- drag to look around, scroll to zoom <button id="exit-eye-mode">Back to free orbit</button></div>
<aside id="stats-drawer" class="drawer">
  <h2>Car Configs</h2>
  <div class="car-name-row"><label for="car-name-input">Name</label><input id="car-name-input" type="text" maxlength="32" spellcheck="false" autocomplete="off" placeholder="(car display name)"></div>
  <div class="hint">The name shown in the game's car-select screen (stored in the car's spec sheet). Renaming is display-only and safe -- it never touches the car's filename. Up to 32 characters.</div>
  <div class="hint">The .cf stats behind this car. Fields are editable; <strong class="highlight-demo">blue</strong> fields (hover for the tooltip) move the wheels live in the Car tab. Hover any field for its real stock-car range (viper/exotic/plane/sedan/sports) -- shown for reference only, not enforced. "Export edited .txt" downloads a file for <code>txt2cf</code>/<code>cfpatch</code>.</div>
  <div id="sections"></div>
  <button id="export">Export edited .txt</button>
  <button id="reset-stats">Reset to default</button>
  <div id="hint2">python -m vrmod.cli txt2cf edited.txt original.cf out.cf</div>
</aside>
<aside id="cockpit-configs-drawer" class="drawer">
  <h2>Cockpit Configs</h2>
  <div class="hint">cockpit.tab's real stored positions/calibration. <strong class="highlight-demo">Blue</strong> records (hover for the tooltip) are live: "wheel" moves the steering wheel; "camera" switches to a driver's-eye view from that position (drag to look around; "Back to free orbit" to leave it). "rpm pt"/"mph pt" move the tach/speedo needle pivots, and "rpm dat"/"mph dat" calibrate their sweep — use <strong>Focus gauges</strong> and the RPM/MPH sliders above to sweep each needle and line it up against the painted dial.</div>
  <div id="cockpit-sections"></div>
  <button id="cockpit-reset">Reset to default</button>
</aside>
<aside id="parts-drawer" class="drawer">
  <h2>Parts <span class="info-i" tabindex="0" role="note" aria-label="About the Parts panel" title="The car's mod slots, grouped by role.&#10;&#10;The funnel filters the list to just the parts in the current view (Car / Cockpit / Horn Ball) and follows the tab you switch to. Turn it off to see every slot across all views, including empty ones you can Add and overridable shared assets.&#10;&#10;Filled dot = a slot this car has · dashed = an empty slot · a shared race.res asset is marked 'shared default' (Import to override) or 'override'.&#10;&#10;Each slot has Import / Export and 🗑 remove / ↺ revert; changes stage until Save. Click a slot to preview it.">&#9432;</span><button id="parts-filter-btn" class="filter-btn active" aria-pressed="true" aria-label="Filter parts" title="Showing parts in this view — click to show all slots"><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M2 3H14L9.2 8.7V13L6.8 11.6V8.7Z" fill="currentColor"/></svg></button></h2>
  <div id="parts-sticky">
    <div id="part-preview-wrap">
      <div id="part-preview-canvas"></div>
      <div id="part-preview-label">Click a slot to preview it</div>
    </div>
    <div id="import-obj-status"></div>
  </div>
  <div id="parts-list"></div>
</aside>
<aside id="textures-drawer" class="drawer">
  <h2>Textures</h2>
  <div class="hint">Materials used by the current tab. Export TGA, edit in an image editor, then <code>tga2tex</code> + <code>modpatch</code> to commit.</div>
  <div id="import-tga-status"></div>
  <div id="texture-list"></div>
</aside>
<aside id="sound-drawer" class="drawer">
  <h2>Sound</h2>
  <div class="hint">Every real .sfx file in this car's own archive -- engine RPM-sweep loops, idle, horn, shift, etc. Rows marked "(shared default)" aren't owned by this car -- they're race.res's fallback horn/shift/squeal sound, used unless the car ships its own. ADPCM-encoded entries are listed but can't be played yet (see sfx.py); everything else here is real PCM audio, decoded and playable directly. "Import WAV" replaces any row -- 16-bit mono PCM only -- and commits as a real per-car .sfx, creating a new override if it was a shared default.</div>
  <div id="sound-list"></div>
</aside>
<script>
// Which MOD_PARTS entry (real filename, or null) plugs into which live-rendered
// piece -- see build_shell_html's docstring. This is what lets a reimported OBJ
// update the actual Car/Cockpit/Horn Ball view: those tabs are built from these
// SAME named pieces below (not one pre-merged mesh each) specifically so any one
// piece can be swapped alone, the way the 4 wheel corners already worked.
const CAR_ROLES = __CAR_ROLES_JSON__;
// The source .car's own absolute path, needed so Save tells the local --serve
// endpoint (see cli.py's COMMIT_PATH) which real file to back up and patch.
// Only meaningful when this page is opened via --serve; embedding it does mean
// a shared copy of this file reveals your local folder structure in its source.
const CAR_PATH = __CAR_PATH_JSON__;
const CAR_WHEELS = __CAR_WHEELS_JSON__;  // {front_left/front_right/rear_left/rear_right: objText}
// MOD_PARTS entries that aren't actually this car's own file -- currently just
// ball.mod (the horn ball) when the car uses race.res's shared default rather
// than shipping its own, see build_shell_html's Horn Ball comment. Labeled
// "(shared default)" in the Parts drawer (buildPartsDrawer); editing/committing
// one still works, it just creates a new per-car override on save instead of
// patching an existing entry (archive.upsert_entry, see cli.py's _apply_commit).
const SHARED_PART_NAMES = new Set(__SHARED_PART_NAMES_JSON__);
// One material->dataUri map for the WHOLE page (every tab, every wheel, every
// Parts-drawer entry) -- see build_shell_html's docstring for why this is a single
// shared lookup instead of each part embedding its own resolved copy.
const TEXTURES = __TEXTURES_JSON__;
// Texture provenance (car.texture_provenance): where each texture comes from, so
// the Textures drawer can tell "borrowed from stock/paint (fine)" apart from
// "missing (broken for anyone who downloads this car)". Lowercase name -> bucket.
const PROVENANCE = __PROVENANCE_JSON__;
const PROV_BUCKET = (() => {
  const m = {};
  for (const b of ["own", "shared", "paint", "missing"])
    for (const n of (PROVENANCE[b] || [])) m[n.toLowerCase()] = b;
  return m;
})();
const PROV_META = {
  own:     {label: "own",     title: "shipped in this car -- renders anywhere"},
  shared:  {label: "stock",   title: "a stock shared texture (race.res) -- every install has it"},
  paint:   {label: "paint",   title: "the body-paint slot, set by the in-game Paint Kit"},
  missing: {label: "missing", title: "NOT shipped, not stock, not paint -- will render wrong for anyone who downloads this car"},
};
const TAB_LABELS = {car: "Car", cockpit: "Cockpit", hornball: "Horn Ball"};
const STATS = __STATS_JSON__;
let CAR_NAME = __CAR_NAME_JSON__;   // display name from <prefix>1.tab; let, so Save can roll it forward
const SECTIONS = __SECTIONS_JSON__;
// (min, max) per field across the game's 5 genuinely-stock retail cars -- see
// STOCK_STAT_RANGES's own comment in viewer.py for why only those 5 and why
// this isn't enforced as a hard input limit. Shown as a hover tooltip only
// (see buildStatsPanel) -- purely informational orientation, not a rule.
const STOCK_RANGES = __STOCK_RANGES_JSON__;
const INCH_TO_M = 0.0254;  // matches car.py's INCH_TO_M -- .cf dimensions are in inches
// The only .cf fields that actually move geometry in this tool -- see car.py's
// assemble_car()/assemble_car_live(): wheelbase sets front/rear Z spacing, ftrack/
// rtrack set left/right spacing per axle. Every other stat is physics-only here.
const LIVE_GEOMETRY_FIELDS = new Set(["wheelbase", "ftrack", "rtrack"]);
// Every real .mod entry in the car's OWN archive, individually -- {entryName:
// objText | null (failed to parse)}. Deliberately NOT the same thing as PARTS: the
// 3D tabs merge several real files together for a cleaner view (the Car tab's
// chassis is body + mirror + spoiler if present; Cockpit is dash + wheel) or don't
// show some at all (LOD1-7, Needle.mod), which is fine for looking at the car but
// makes "export this and reimport it" ambiguous -- which real file would an edit
// even go back into? MOD_PARTS sidesteps that entirely: one real file in, one real
// file's worth of OBJ out, so Export always has an honest obj2mod/modpatch target.
const MOD_PARTS = __MOD_PARTS_JSON__;
// Every real .sfx entry in the car's own archive, plus a shared-default fallback
// for horn/shift/squeal if the car doesn't own its own -- {entryName: {wav_b64,
// sample_rate, bits_per_sample, duration, is_pcm, shared} | null}, see
// _car_sfx_parts/SHARED_SFX_ROLES. wav_b64 is null for a still-undecoded ADPCM
// entry or a parse failure -- the Sound drawer lists those too, just without a
// player (see buildSoundDrawer).
const SFX_PARTS = __SFX_PARTS_JSON__;
// cockpit.tab's 6 named records (null if this car has no cockpit) -- {name: [a,b,c]}.
// "camera"/"wheel"/"rpm pt"/"mph pt" are x/y/z positions; "rpm dat"/"mph dat" are
// needle-calibration triples (angle_at_0, angle_at_max, max_value), see
// cockpit_tab.py's module docstring for how each was confirmed. Field labels for
// the two shapes live in COCKPIT_FIELD_LABELS below.
const COCKPIT_RECORDS = __COCKPIT_RECORDS_JSON__;
const COCKPIT_FIELD_LABELS = {
  camera: ["x", "y", "z"], wheel: ["x", "y", "z"], "rpm pt": ["x", "y", "z"], "mph pt": ["x", "y", "z"],
  "rpm dat": ["angle @ 0", "angle @ max", "max rpm"], "mph dat": ["angle @ 0", "angle @ max", "max mph"],
};
const POSITION_RECORDS = new Set(["camera", "wheel", "rpm pt", "mph pt"]);
// "wheel" moves the actual steering wheel mesh (same position
// CAR_ROLES.cockpit.wheel_pos seeds at load); "camera" switches the Cockpit tab
// into a driver's-eye view -- camera pinned at cockpit.tab's real stored eye
// point, looking toward the wheel, drag now free-looks (yaw/pitch) instead of
// orbiting an object (see cockpitEyeMode's comment). A fixed camera was tried
// and deliberately dropped once before in favor of free orbit; this brings it
// back as an opt-in view tied to the field that actually represents it, not the
// default. The other 4 records are still real, still editable, still saved on
// commit; they just have no on-screen anchor yet (no needle mesh is part of the
// Cockpit tab's assembly). The dispatch table mapping each of these two names to
// the function that applies it (COCKPIT_LIVE_RECORDS) lives inside main()
// instead, since both functions need main()'s scene state -- see
// buildCockpitConfigsPanel.
const COCKPIT_LIVE_TITLES = {
  wheel: "Moves the steering wheel live in the Cockpit tab",
  camera: "Switches to a driver's-eye view live from this position",
  "rpm pt": "Moves the tachometer needle's pivot live",
  "mph pt": "Moves the speedometer needle's pivot live",
  "rpm dat": "Calibrates the tach needle sweep live (use the RPM slider to test)",
  "mph dat": "Calibrates the speedo needle sweep live (use the MPH slider to test)",
};

function parseObj(text) {
  const positions = [], uvs = [], normals = [], groups = [];
  let current = null;
  for (const line of text.split("\n")) {
    const parts = line.trim().split(/\s+/);
    if (parts[0] === "v") positions.push(parts.slice(1).map(Number));
    else if (parts[0] === "vt") uvs.push(parts.slice(1).map(Number));
    else if (parts[0] === "vn") normals.push(parts.slice(1).map(Number));
    else if (parts[0] === "usemtl") { current = {material: parts[1], faces: []}; groups.push(current); }
    else if (parts[0] === "f") {
      const idx = parts.slice(1).map(p => p.split("/").map(x => parseInt(x,10)-1));
      current.faces.push(idx);
    }
  }
  return {positions, uvs, normals, groups};
}

const textureCache = {};
function loadTexture(dataUri) {
  if (!dataUri) return null;
  if (!textureCache[dataUri]) {
    textureCache[dataUri] = new THREE.TextureLoader().load(dataUri);
  }
  return textureCache[dataUri];
}

const fallbackColors = [0x999999, 0x777777, 0xaaaaaa, 0x888888];

function buildPartGroup(objText) {
  const parsed = parseObj(objText);
  const group = new THREE.Group();
  const meshesByMaterial = {};
  parsed.groups.forEach((g, gi) => {
    const posArr = [], uvArr = [];
    for (const face of g.faces) {
      // Fan-triangulate n-gons (real models -- Blender especially -- export
      // quads and larger polys, not just triangles) and tolerate faces with no
      // vt (f a//n): parseObj yields ui=NaN there, so guard with isFinite and
      // fall back to (0,0) rather than indexing uvs[NaN] -> undefined -> crash.
      for (let k = 1; k + 1 < face.length; k++) {
        const tri = [face[0], face[k], face[k + 1]];
        if (tri.some(v => !parsed.positions[v[0]])) continue;   // skip a face with a bad index
        for (const [pi, ui] of tri) {
          const p = parsed.positions[pi];
          posArr.push(p[0], p[1], p[2]);
          const uv = Number.isFinite(ui) ? parsed.uvs[ui] : null;
          uvArr.push(uv ? uv[0] : 0, uv ? uv[1] : 0);
        }
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(posArr, 3));
    geo.setAttribute("uv", new THREE.Float32BufferAttribute(uvArr, 2));
    geo.computeVertexNormals();

    const dataUri = TEXTURES[g.material];
    const matOpts = {side: THREE.DoubleSide};
    // alphaTest, not just an opaque map: several low-poly parts (e.g. the
    // steering wheel, a single flat quad) get their real silhouette entirely
    // from the texture's alpha channel (spokes/rim cut out), not geometry.
    if (dataUri) { matOpts.map = loadTexture(dataUri); matOpts.alphaTest = 0.5; }
    else matOpts.color = fallbackColors[gi % fallbackColors.length];
    const meshObj = new THREE.Mesh(geo, new THREE.MeshStandardMaterial(matOpts));
    group.add(meshObj);
    (meshesByMaterial[g.material] = meshesByMaterial[g.material] || []).push(meshObj);
  });
  return {group, meshesByMaterial};
}

// Builds a Car/Cockpit/Horn Ball tab from its real constituent MOD_PARTS pieces
// (per CAR_ROLES) instead of one pre-merged mesh -- each piece is tracked in
// `pieces` by role so applyLiveReimport() can later swap just one out, same as
// the wheel corners already worked before this existed.
function buildTabGroup(key) {
  const group = new THREE.Group();
  const meshesByMaterial = {};
  const pieces = {};
  function addPiece(role, objText, position) {
    if (!objText) return;
    const piece = buildPartGroup(objText);
    if (position) piece.group.position.set(position[0], position[1], position[2]);
    group.add(piece.group);
    pieces[role] = piece;
    for (const [matName, meshes] of Object.entries(piece.meshesByMaterial)) {
      (meshesByMaterial[matName] = meshesByMaterial[matName] || []).push(...meshes);
    }
  }
  // Like addPiece but does NOT fold into meshesByMaterial (see the cockpit needle
  // comment). Orientation is applied later by updateCockpitNeedleLive.
  function addNeedle(role, objText, position) {
    if (!objText) return;
    const piece = buildPartGroup(objText);
    if (position) piece.group.position.set(position[0], position[1], position[2]);
    group.add(piece.group);
    pieces[role] = piece;
  }
  if (key === "car") {
    const roles = CAR_ROLES.car;
    addPiece("body", MOD_PARTS[roles.body]);
    if (roles.sub_b) addPiece("sub_b", MOD_PARTS[roles.sub_b]);
    if (roles.sub_s) addPiece("sub_s", MOD_PARTS[roles.sub_s]);
  } else if (key === "cockpit") {
    const roles = CAR_ROLES.cockpit;
    addPiece("dash", MOD_PARTS[roles.dash]);
    addPiece("wheel", MOD_PARTS[roles.wheel], roles.wheel_pos);
    // The tach + speedo needles: one mesh (Needle.mod) instanced at each pivot.
    // Added via addNeedle (not addPiece) so they're tracked in `pieces` for live
    // orientation but kept OUT of meshesByMaterial -- they're calibration anchors,
    // not texture-editable surfaces, and shouldn't clutter the Textures drawer.
    if (roles.needle && MOD_PARTS[roles.needle]) {
      addNeedle("needle_rpm", MOD_PARTS[roles.needle], roles.rpm_pt);
      addNeedle("needle_mph", MOD_PARTS[roles.needle], roles.mph_pt);
    }
  } else if (key === "hornball") {
    addPiece("ball", MOD_PARTS[CAR_ROLES.hornball]);
  }
  return {group, meshesByMaterial, pieces};
}

// Recomputes a tab's aggregate meshesByMaterial from its current pieces --
// called after applyLiveReimport() swaps one piece, so the Textures drawer
// reflects whatever's actually showing rather than a stale material list.
function recomputeTabMaterials(tabBuilt) {
  const merged = {};
  for (const piece of Object.values(tabBuilt.pieces)) {
    for (const [matName, meshes] of Object.entries(piece.meshesByMaterial)) {
      (merged[matName] = merged[matName] || []).push(...meshes);
    }
  }
  tabBuilt.meshesByMaterial = merged;
}

const dirtyFields = new Set();  // fields the user has actually typed into, in Mod mode
const cockpitDirtyRecords = new Set();  // cockpit.tab record names the user has actually edited

// Trims a float to 2 decimals for display (e.g. 96.19999694824219 -> "96.2")
// without touching the underlying value -- STATS[name] itself stays exact.
function roundDisplay(v) {
  if (Number.isInteger(v)) return String(v);
  return String(Math.round(v * 100) / 100);
}

// A per-field nudge amount sized to the value's own magnitude, since one fixed
// step doesn't work across fields spanning mass (thousands) down to drag
// coefficients (tenths) -- e.g. 96.2 (wheelbase) -> 0.1, 3583 (mass) -> 1,
// 0.037 (engine_drag) -> 0.001. Also set as the input's own `step` attribute,
// so keyboard arrow keys get the same sensible increment as the +/- buttons.
function fieldStep(v) {
  const abs = Math.abs(v);
  if (abs >= 1000) return 10;
  if (abs >= 100) return 1;
  if (abs >= 10) return 0.1;
  if (abs >= 1) return 0.01;
  return 0.001;
}

// Rounds to the decimal precision implied by `step` (e.g. step=0.1 -> 1 decimal)
// -- plain arithmetic on floats drifts (0.1+0.2 !== 0.3), and a stepper you
// click repeatedly would visibly accumulate that drift without this.
function roundStep(v, step) {
  const decimals = Math.max(0, -Math.floor(Math.log10(step)));
  const factor = Math.pow(10, decimals);
  return Math.round(v * factor) / factor;
}

// Wraps an already-built <input type=number> with larger, reliably-clickable
// +/- buttons -- the native spinner arrows browsers draw for number inputs are
// tiny and inconsistently stylable (Chrome/Firefox render them differently, and
// Firefox in particular resists CSS sizing them at all), so this replaces them
// outright (see the .stepper/input[type=number] CSS hiding the native ones)
// rather than trying to reliably enlarge something browsers don't expose
// consistent styling hooks for. Operates on whatever's currently displayed --
// same as a native spinner, which has no concept of "true" precision either;
// click into the field first (see buildStatsPanel's focus/blur handling) if you
// want to nudge from the exact original value rather than its rounded display.
function wrapWithStepper(input, step) {
  const wrap = document.createElement("div");
  wrap.className = "stepper";
  function makeBtn(label, dir) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "step-btn";
    btn.textContent = label;
    btn.tabIndex = -1;  // click/tap only -- keeps Tab order on the real fields
    const nudge = () => {
      input.value = roundStep((Number(input.value) || 0) + dir * step, step);
      input.dispatchEvent(new Event("input", {bubbles: true}));
    };
    // Press-and-hold auto-repeat: one immediate step (a plain click still works),
    // then after a short hold it counts continuously until release. Pointer events
    // (not click) so mouse/touch/pen all repeat; pointer capture means the release
    // is caught even if the cursor drifts off the button mid-hold. The per-field
    // `step` is already magnitude-scaled (see fieldStep), so a fixed rate reads well
    // across fields from mass down to drag without needing acceleration.
    let holdTimer = null, repeatTimer = null;
    const stop = () => { clearTimeout(holdTimer); clearInterval(repeatTimer); holdTimer = repeatTimer = null; };
    btn.addEventListener("pointerdown", e => {
      if (e.button) return;              // primary button / touch only
      e.preventDefault();
      nudge();
      if (btn.setPointerCapture) { try { btn.setPointerCapture(e.pointerId); } catch (_) {} }
      holdTimer = setTimeout(() => { repeatTimer = setInterval(nudge, 55); }, 400);
    });
    btn.addEventListener("pointerup", stop);
    btn.addEventListener("pointercancel", stop);
    btn.addEventListener("lostpointercapture", stop);
    return btn;
  }
  wrap.appendChild(makeBtn("−", -1));
  wrap.appendChild(input);
  wrap.appendChild(makeBtn("+", 1));
  return wrap;
}

// Car Configs is Mod-mode-only (see updateConfigButtonsVisibility), so every
// field here is always editable, just not always showing full precision: an
// untouched field displays roundDisplay's trimmed value and swaps to the real
// one on focus (so nudging it starts from the true number, not the rounded
// display -- important for the live-geometry fields especially), then back to
// trimmed on blur. A field the user has actually typed into (dirtyFields) is
// never touched by this -- whatever they typed is exactly what gets committed.
function buildStatsPanel() {
  const root = document.getElementById("sections");
  for (const [title, fields] of SECTIONS) {
    const sec = document.createElement("div");
    sec.className = "section";
    const h3 = document.createElement("h3");
    h3.textContent = title;
    sec.appendChild(h3);
    for (const name of fields) {
      if (!(name in STATS)) continue;
      const row = document.createElement("div");
      row.className = "row";
      const isLive = LIVE_GEOMETRY_FIELDS.has(name);
      row.classList.toggle("live-field", isLive);
      const label = document.createElement("label");
      // A zero-width space after each underscore gives the browser a wrap point
      // at natural word boundaries (weight_distribution -> "weight_" / "distri-
      // bution") instead of either overflowing the drawer or breaking mid-word
      // at an arbitrary character -- these field names have no real spaces, so
      // without this there's nowhere for a long one to wrap at all.
      label.textContent = name.replace(/_/g, "_​");
      if (isLive) label.title = "Moves the wheels live in the Car tab";
      const input = document.createElement("input");
      input.type = "number";
      const step = fieldStep(STATS[name]);
      input.step = step;
      input.value = roundDisplay(STATS[name]);
      input.dataset.field = name;
      // Informational only -- see STOCK_RANGES' own comment for why this isn't
      // enforced as a min/max on the input.
      if (STOCK_RANGES[name]) {
        input.title = `Stock range: ${STOCK_RANGES[name][0]}–${STOCK_RANGES[name][1]}`;
      }
      input.addEventListener("focus", () => {
        if (!dirtyFields.has(name)) input.value = STATS[name];
      });
      input.addEventListener("blur", () => {
        if (!dirtyFields.has(name)) input.value = roundDisplay(STATS[name]);
      });
      row.appendChild(label);
      row.appendChild(wrapWithStepper(input, step));
      sec.appendChild(row);
    }
    root.appendChild(sec);
  }
  document.getElementById("sections").addEventListener("input", e => {
    if (e.target.dataset && e.target.dataset.field) dirtyFields.add(e.target.dataset.field);
    updateCommitStatus();
  });
}

function exportTxt() {
  const inputs = document.querySelectorAll("#sections input");
  let lines = [];
  inputs.forEach(inp => lines.push(inp.dataset.field + " " + inp.value));
  downloadText(lines.join("\n") + "\n", "edited.txt");
}

function resetStats() {
  // STATS itself is never mutated by input edits (only the <input> elements'
  // values are), so it's always the values this page was generated with --
  // i.e. whatever was actually in the .cf that was imported.
  dirtyFields.clear();
  document.querySelectorAll("#sections input").forEach(inp => {
    inp.value = roundDisplay(STATS[inp.dataset.field]);
  });
  const ni = document.getElementById("car-name-input"); if (ni) ni.value = CAR_NAME;
  document.getElementById("sections").dispatchEvent(new Event("input", {bubbles: true}));
}

// Rebuilt every time the active tab changes -- shows whatever materials that tab's
// meshes actually use, real filenames and thumbnails. Export downloads the real
// texture as TGA; importing one previews it live on every mesh in THIS tab using
// that material (see importTextureAsTga) -- like everything else here, nothing is
// ever written to disk, modretex/modpatch is still the real commit path.
// Textures arrive as data URIs, so the decoded image is where their real
// dimensions live client-side -- and reading them there also covers a TGA
// previewed but not yet committed.
function attachDims(el, img) {
  const line = document.createElement("div");
  line.className = "sub";
  el.insertBefore(line, el.querySelector(".swatch-actions") || null);
  const write = () => {
    if (img.naturalWidth) line.textContent = `${img.naturalWidth}×${img.naturalHeight}`;
  };
  if (img.complete && img.naturalWidth) write(); else img.addEventListener("load", write);
}

// Per-car portability verdict (car.texture_provenance), shown atop the drawer
// regardless of the active tab, so a car that leans on files it doesn't ship
// reads as clearly as one that's self-contained.
function addProvenanceSummary(root) {
  const v = PROVENANCE.verdict;
  if (!v || v === "unknown") return;
  const el = document.createElement("div");
  el.className = "prov-summary prov-verdict-" + v;
  el.innerHTML = {
    "self-contained": "<b>Self-contained</b> &mdash; every texture ships in this car, so it renders anywhere.",
    "portable": "<b>Portable</b> &mdash; leans only on stock shared textures and the Paint Kit, which every install has.",
    "incomplete": "<b>&#9888; Incomplete</b> &mdash; references texture(s) it doesn't ship: <b>" +
                  (PROVENANCE.missing || []).join(", ") +
                  "</b>. These will render wrong for anyone who downloads this car.",
  }[v] || v;
  root.appendChild(el);
}

function buildTextureDrawer(meshesByMaterial) {
  const root = document.getElementById("texture-list");
  root.innerHTML = "";
  const statusEl = document.getElementById("import-tga-status");
  if (statusEl) statusEl.textContent = "";
  addProvenanceSummary(root);
  // Which materials this tab actually shows -- taken from the meshes already
  // built for it (not a per-tab textures dict, see the TEXTURES const's comment).
  const names = meshesByMaterial ? Object.keys(meshesByMaterial) : [];
  if (names.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "no materials found";
    root.appendChild(empty);
    return;
  }
  names.forEach(name => {
    const dataUri = TEXTURES[name];
    const pending = !!pendingTextureEdits[name];     // a staged import awaiting Save
    const el = document.createElement("div");
    el.className = "swatch" + (pending ? " pending" : "");
    let img = null;
    if (dataUri) {
      img = document.createElement("img");
      img.src = dataUri;
      el.appendChild(img);
    } else {
      const missing = document.createElement("div");
      missing.className = "missing";
      missing.textContent = "no texture found";
      el.appendChild(missing);
    }
    const label = document.createElement("div");
    label.className = "name";
    label.textContent = name + (pending ? " (pending)" : "");
    const bucket = PROV_BUCKET[name.toLowerCase()];
    if (bucket) {
      const badge = document.createElement("span");
      badge.className = "prov-badge prov-" + bucket;
      badge.textContent = PROV_META[bucket].label;
      badge.title = PROV_META[bucket].title;
      label.appendChild(badge);
    }
    el.appendChild(label);
    if (dataUri) {
      const actions = document.createElement("div");
      actions.className = "swatch-actions";
      const btn = document.createElement("div");
      btn.className = "swatch-export";
      btn.textContent = "Export TGA";
      btn.addEventListener("click", e => { e.stopPropagation(); exportTextureAsTga(name, dataUri); });
      actions.appendChild(btn);
      const importLabel = document.createElement("label");
      importLabel.className = "swatch-import";
      importLabel.textContent = pending ? "Replace" : "Import";
      importLabel.title = "Import a PNG, TGA, or other image (JPG warns before flattening transparency)";
      const importInput = document.createElement("input");
      importInput.type = "file";
      importInput.accept = ".png,.tga,.jpg,.jpeg,.bmp,.webp,.gif";
      importInput.addEventListener("click", e => e.stopPropagation());
      importInput.addEventListener("change", e => {
        const file = e.target.files[0];
        if (file) importTextureAsTga(name, file, meshesByMaterial);
        e.target.value = "";
      });
      importLabel.appendChild(importInput);
      actions.appendChild(importLabel);
      if (pending) {
        const rev = document.createElement("div");
        rev.className = "swatch-revert";
        rev.textContent = "↺";
        rev.title = "Discard this staged texture and restore the original";
        rev.addEventListener("click", e => {
          e.stopPropagation();
          revertTexture(name, meshesByMaterial);
          buildTextureDrawer(meshesByMaterial);        // redraw: back to the original swatch
        });
        actions.appendChild(rev);
      }
      el.appendChild(actions);
    }
    if (img) attachDims(el, img);
    root.appendChild(el);
  });
}

function downloadText(text, filename) {
  downloadBytes(new Blob([text], {type: "text/plain"}), filename);
}

async function downloadBytes(blobOrBytes, filename) {
  const blob = blobOrBytes instanceof Blob ? blobOrBytes : new Blob([blobOrBytes], {type: "application/octet-stream"});
  // Desktop app path: the embedded webview (pywebview) silently ignores an
  // <a download>, so when the Python bridge is present hand it the bytes and let
  // the OS save dialog write them. The bridge is injected only into the TOP
  // window, but this viewer runs inside the switcher's same-origin iframe, so
  // reach through window.parent too. A plain browser (the CLI-served page, the
  // gallery) has no bridge and falls through to the anchor download below.
  let api = null;
  try {
    api = (window.pywebview && window.pywebview.api)
       || (window.parent && window.parent.pywebview && window.parent.pywebview.api)
       || null;
  } catch (e) { /* cross-origin parent -- no bridge, use the anchor path */ }
  if (api && api.save_file) {
    const buf = new Uint8Array(await blob.arrayBuffer());
    let bin = "";
    for (let i = 0; i < buf.length; i++) bin += String.fromCharCode(buf[i]);
    try { await api.save_file(filename, btoa(bin)); return; }
    catch (e) { /* bridge failed -- fall through to the anchor download */ }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Defer the revoke: calling it synchronously after click() can abort the
  // download before the browser has read the blob.
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function bytesToBase64(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

// Must match cli.py's COMMIT_PATH exactly -- the one route _CommitHandler
// actually understands; every other server (a plain http.server, or opening
// this file directly) either 404s or, for file://, never gets this far at all.
const COMMIT_ROUTE = "/__vrmod_commit__";

// Enables/disables Save based on whether there's anything to send -- called
// after every edit (stat, part reimport, texture reimport) and after Reset to
// default (via the synthetic "input" event it dispatches).
// The car-name field is dirty when the input differs from the saved CAR_NAME.
function carNameChanged() {
  const inp = document.getElementById("car-name-input");
  return !!inp && inp.value.trim() !== CAR_NAME;
}

function updateCommitStatus() {
  const btn = document.getElementById("commit-btn");
  if (!btn) return;
  const hasPending = dirtyFields.size > 0
    || cockpitDirtyRecords.size > 0
    || carNameChanged()
    || Object.keys(pendingPartEdits).length > 0
    || pendingPartRemovals.size > 0
    || Object.keys(pendingTextureEdits).length > 0
    || Object.keys(pendingSfxEdits).length > 0;
  btn.disabled = !hasPending;
  const discard = document.getElementById("discard-btn");
  if (discard) discard.disabled = !hasPending;
}

// Reads a cockpit.tab record's 3 fields straight from the DOM inputs rather than
// a separate JS state object, mirroring updateWheelPositions()'s own pattern for
// the Car tab's wheelbase/ftrack/rtrack fields. Top-level (not inside main()) so
// both commitChanges() and main()'s own updateCockpitWheelLive() can call it.
function getCockpitRecordValues(name) {
  const inputs = document.querySelectorAll(`#cockpit-sections input[data-record="${name}"]`);
  const arr = [0, 0, 0];
  inputs.forEach(inp => { arr[Number(inp.dataset.index)] = Number(inp.value); });
  return arr;
}

async function commitChanges() {
  const statusEl = document.getElementById("commit-status");
  const stats = {};
  dirtyFields.forEach(field => {
    const inp = document.querySelector(`#sections input[data-field="${field}"]`);
    if (inp) stats[field] = Number(inp.value);
  });
  const cockpit = {};
  cockpitDirtyRecords.forEach(name => { cockpit[name] = getCockpitRecordValues(name); });
  const payload = {
    car_path: CAR_PATH, stats, cockpit, parts: pendingPartEdits, textures: pendingTextureEdits,
    sounds: pendingSfxEdits, remove: Array.from(pendingPartRemovals),
  };
  if (carNameChanged()) payload.car_name = document.getElementById("car-name-input").value.trim();

  statusEl.className = "pending";
  statusEl.textContent = "Saving...";
  let result;
  try {
    const resp = await fetch(COMMIT_ROUTE, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    result = await resp.json();
  } catch (err) {
    statusEl.className = "error";
    statusEl.textContent = 'Couldn\'t reach the local save endpoint -- this only works when the page was '
      + 'opened via "python -m vrmod.cli shell ... --serve" (a plain http.server or a file:// open has no '
      + "commit route to talk to).";
    return;
  }
  if (result.ok) {
    statusEl.className = "ok";
    // Say so when an import was fitted to the size the game already expects --
    // silently resizing someone's artwork is the kind of thing they should hear
    // about, and it is also the moment to learn a texture is not what they think.
    const fitted = (result.resized || []).length
      ? ` — resized to fit: ${result.resized.join(", ")}` : "";
    statusEl.textContent =
      `Saved to ${result.out_path} (original backed up to ${result.backup_path})${fitted}`;
    // Over-budget geometry is a different class of message: the save WORKED,
    // but the game may not load the result. It gets its own warning styling
    // rather than being appended to a success line.
    const warn = result.warnings || [];
    if (warn.length) {
      statusEl.className = "pending";
      // Built from character codes rather than escapes: this line has been
      // mangled once already by a quoting layer collapsing its \n.
      const bullet = String.fromCharCode(10, 0x26A0, 32);
      statusEl.textContent += bullet + warn.join(bullet);
    }
    // Parts/textures/sounds just written ARE now the car's real content, so roll
    // their baselines forward and clear the staged state -- the drawer honestly
    // reads as saved, with no snap-back, because we advance the baseline too.
    for (const name of Object.keys(pendingPartEdits)) {
      MOD_PARTS[name] = pendingPartEdits[name];  // saved geometry (incl. a new Add) becomes the baseline
      delete pendingPartEdits[name];
    }
    for (const name of pendingPartRemovals) delete MOD_PARTS[name];  // removed members are gone
    pendingPartRemovals.clear();
    for (const mat of Object.keys(pendingTextureEdits)) {
      delete originalTextures[mat];              // current TEXTURES[mat] is now the baseline
      delete pendingTextureEdits[mat];
    }
    for (const name of Object.keys(importedTexturesByPart)) delete importedTexturesByPart[name];
    for (const name of Object.keys(pendingSfxEdits)) {
      // The staged WAV is now the car's real, owned sound -- roll it into the
      // baseline (owned + previewable) so the redrawn row reads as saved, not
      // pending, with no snap-back to the original.
      const prev = SFX_PARTS[name] || {};
      SFX_PARTS[name] = Object.assign({}, prev, {wav_b64: pendingSfxEdits[name], is_pcm: true, shared: false});
      delete pendingSfxEdits[name];
    }
    if (rebuildTextureDrawer) rebuildTextureDrawer();  // textures: redraw, staged swatches now clean
    if (rebuildPartsDrawer) rebuildPartsDrawer();  // parts: redraw with fresh present/empty states
    buildSoundDrawer();                          // sounds: redraw from the rolled-forward SFX_PARTS
    if (payload.car_name !== undefined) CAR_NAME = payload.car_name;   // name: new baseline, no snap-back
    updateCommitStatus();
    // Stats/cockpit fields are deliberately left as-is: STATS still holds the
    // ORIGINAL pre-edit values (the page never re-fetches what it wrote), so
    // clearing dirtyFields would snap the displayed numbers back on the next
    // Mod-mode toggle. The numeric inputs already show what you typed, so this
    // reads far less like "unsaved" than a part row's amber marker did.
  } else {
    statusEl.className = "error";
    statusEl.textContent = `Save failed: ${result.error}`;
  }
}

// Uncompressed 32-bit TGA -- mirrors tex.py's write_tga() byte-for-byte (18-byte
// header, BGRA pixel order, descriptor 0x28 for top-to-bottom + 8-bit alpha, no
// footer for the 32-bit case -- see that function's docstring). Always 32-bit
// regardless of whether the source material was really opaque: this is generated
// from an already-decoded PNG with no record of the original .tex's colorkey/alpha
// flags, and tga_to_tex's own --mode flag is the right place to pick the real
// target format back up when reimporting, not a guess made here.
function encodeTga(imageData) {
  const {data, width, height} = imageData;
  const header = new Uint8Array(18);
  header[2] = 2; // uncompressed truecolor
  new DataView(header.buffer).setUint16(12, width, true);
  new DataView(header.buffer).setUint16(14, height, true);
  header[16] = 32; // depth
  header[17] = 0x28; // top-to-bottom, 8-bit alpha
  const pixelCount = width * height;
  const body = new Uint8Array(pixelCount * 4);
  for (let i = 0; i < pixelCount; i++) {
    const o = i * 4;
    body[o] = data[o + 2];      // B
    body[o + 1] = data[o + 1];  // G
    body[o + 2] = data[o];      // R
    body[o + 3] = data[o + 3];  // A
  }
  const out = new Uint8Array(header.length + body.length);
  out.set(header, 0);
  out.set(body, header.length);
  return out;
}

function exportTextureAsTga(name, dataUri) {
  const img = new Image();
  img.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0);
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const tgaBytes = encodeTga(imageData);
    downloadBytes(tgaBytes, name.replace(/\.tex$/i, ".tga"));
  };
  img.src = dataUri;
}

// Decodes an uncompressed 24/32-bit TGA ArrayBuffer to {data, width, height}
// (RGBA8888, top-to-bottom row order) -- mirrors tex.py's read_tga() exactly:
// same "only uncompressed truecolor, no color map" restriction, same BGR(A)->
// RGB(A) channel reorder, same handling of the descriptor byte's top-to-bottom
// flag (bottom-to-top source rows get reversed here the same way).
function decodeTga(arrayBuffer) {
  const data = new Uint8Array(arrayBuffer);
  const idLen = data[0], cmapType = data[1], imgType = data[2];
  if (cmapType !== 0 || imgType !== 2) {
    throw new Error("only uncompressed truecolor TGA (no color map) is supported");
  }
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const width = view.getUint16(12, true);
  const height = view.getUint16(14, true);
  const depth = data[16];
  const desc = data[17];
  if (depth !== 24 && depth !== 32) {
    throw new Error(`unsupported bit depth ${depth}`);
  }
  const channels = depth / 8;
  const topToBottom = !!(desc & 0x20);
  const off = 18 + idLen;
  const rowBytes = width * channels;
  const rows = [];
  for (let y = 0; y < height; y++) {
    rows.push(data.subarray(off + y * rowBytes, off + (y + 1) * rowBytes));
  }
  if (!topToBottom) rows.reverse();
  const out = new Uint8ClampedArray(width * height * 4);
  let oi = 0;
  for (const row of rows) {
    for (let x = 0; x < width; x++) {
      const si = x * channels;
      out[oi++] = row[si + 2];                      // R = source B
      out[oi++] = row[si + 1];                       // G
      out[oi++] = row[si];                           // B = source R
      out[oi++] = channels === 4 ? row[si + 3] : 255; // A
    }
  }
  return {data: out, width, height};
}

// Applies a reimported TGA live to whatever's currently on screen -- every mesh
// in the ACTIVE tab using this material (not every tab that happens to share the
// name, and not the Parts-drawer preview -- see the module-level scoping note in
// build_shell_html's docstring). Also updates the shared TEXTURES lookup itself,
// so anything built or swapped in AFTER this point (a later OBJ reimport landing
// on a piece that uses this same material, for instance) picks it up too.
async function importTextureAsTga(name, file, meshesByMaterial) {
  const statusEl = document.getElementById("import-tga-status");
  const setStatus = t => { const s = document.getElementById("import-tga-status"); if (s) s.textContent = t; };
  let imgData;
  try {
    imgData = await decodeImageBytes(file.name, new Uint8Array(await file.arrayBuffer()));
  } catch (err) {
    setStatus(`${file.name}: ${err && err.message ? err.message : err}`);
    return;
  }
  // Transparency gate: a flat/lossy format (JPG, most BMP) has no alpha channel,
  // and the .tex alpha/colorkey modes carry transparency through that channel --
  // so importing one onto a texture that HAD transparency would silently flatten
  // it opaque. Warn before doing that; PNG/TGA carry alpha and skip the prompt.
  if (!imageDataHasAlpha(imgData) && TEXTURES[name] && await dataUriHasAlpha(TEXTURES[name])) {
    if (!confirm(`"${name}" has transparency that ${file.name} can't carry (no alpha channel -- typical of JPG). Import anyway and make it fully opaque?`)) {
      setStatus(`Import cancelled -- ${name} kept. Use a PNG or TGA to preserve transparency.`);
      return;
    }
  }
  const canvas = document.createElement("canvas");
  canvas.width = imgData.width;
  canvas.height = imgData.height;
  canvas.getContext("2d").putImageData(imgData, 0, 0);
  const dataUri = canvas.toDataURL("image/png");
  // Snapshot the pre-import value once so the swatch's ↺ revert can restore it
  // (undefined = the material had no texture before this import).
  if (!(name in originalTextures)) originalTextures[name] = TEXTURES[name];
  TEXTURES[name] = dataUri;
  const newTexture = loadTexture(dataUri);
  const meshes = (meshesByMaterial && meshesByMaterial[name]) || [];
  meshes.forEach(m => { m.material.map = newTexture; m.material.needsUpdate = true; });
  // Re-encoded to TGA bytes (not the PNG dataUri above) for commitChanges() -- the
  // local endpoint decodes real TGA bytes server-side via tex.read_tga_bytes().
  pendingTextureEdits[name] = bytesToBase64(encodeTga(imgData));
  updateCommitStatus();
  buildTextureDrawer(meshesByMaterial);   // redraw: swatch shows the preview, pending marker, and ↺
  setStatus(meshes.length > 0
    ? `Previewing ${file.name} on ${name} -- updated ${meshes.length} mesh(es) in this tab.`
    : `Previewing ${file.name} on ${name} -- not used by any mesh in the current tab, so nothing visible changed.`);
}

// Drop a swatch's staged import and restore the pre-import texture (see
// originalTextures) -- the Textures-drawer counterpart to the Parts/Sound ↺.
function revertTexture(name, meshesByMaterial) {
  if (name in originalTextures) {
    const orig = originalTextures[name];
    if (orig === undefined) delete TEXTURES[name]; else TEXTURES[name] = orig;
    delete originalTextures[name];
  }
  delete pendingTextureEdits[name];
  const meshes = (meshesByMaterial && meshesByMaterial[name]) || [];
  const t = TEXTURES[name] ? loadTexture(TEXTURES[name]) : null;
  meshes.forEach(m => { m.material.map = t; m.material.needsUpdate = true; });
  updateCommitStatus();
}

// ---------------------------------------------------------------------------
// OBJ + .mtl + texture import/export helpers.
//
// The Parts drawer's OBJ import and export are a matched pair: a .mod carries
// only a *material name*, never the image, so a bare .obj (in or out) travels
// unskinned and a swapped body shows "no texture found" until a .tex is wired
// up by hand. These close that gap -- import reads the .obj's companion .mtl
// (map_Kd) and its image files (loose multi-select OR a single .zip) and stages
// each skin under its material name into the same pendingTextureEdits the
// Textures drawer already commits; export emits a zip of the .obj + a generated
// .mtl + a PNG per material. Zip read/write is dependency-free via the
// platform's own Compression/DecompressionStream (deflate-raw).
// ---------------------------------------------------------------------------

function baseName(p) { return String(p).replace(/\\/g, "/").split("/").pop(); }
function sanitizeFilename(s) { return String(s).replace(/[^A-Za-z0-9._-]+/g, "_"); }

// Parse a Wavefront .mtl into {materialName: {img, kd}}. Only map_Kd (the
// diffuse map) has a direct Viper equivalent -- one .tex per material -- so
// other maps are ignored; its filename is the last token (option flags
// -o/-s/-mm/... before it are skipped) reduced to its basename to match how the
// image files are keyed. Kd (the flat diffuse colour) is captured too: colour-
// only models (Blender/Quaternius exports with no image maps) are common, and
// we synthesise a solid-colour .tex from Kd so they import in their real
// colours instead of untextured -- see importOntoMember / solidColorImageData.
function parseMtl(text) {
  const map = {};
  let current = null;
  for (let line of text.split(/\r?\n/)) {
    line = line.trim();
    if (!line || line[0] === "#") continue;
    const parts = line.split(/\s+/);
    const tag = parts[0].toLowerCase();
    if (tag === "newmtl") { current = parts.slice(1).join(" "); map[current] = {img: null, kd: null}; }
    else if (tag === "map_kd" && current) map[current].img = baseName(parts[parts.length - 1]);
    else if (tag === "kd" && current) map[current].kd = parts.slice(1, 4).map(Number);
  }
  return map;
}

// An 8x8 solid-colour ImageData from an MTL Kd triple (0..1 floats). 8px is the
// smallest size encode_to_tex accepts; a flat colour needs no more. Kd is used
// as-authored (Blender's OBJ exporter writes the sRGB base colour here), clamped
// to bytes.
function solidColorImageData(kd) {
  const b = c => Math.max(0, Math.min(255, Math.round((c || 0) * 255)));
  let r = b(kd[0]), g = b(kd[1]), bl = b(kd[2]);
  // Viper keys a pixel transparent whenever its 5-bit RED and 5-bit BLUE are
  // BOTH zero -- not just literal 0x0000. Confirmed in game: 0x0020 (RGB 7,7,7,
  // Quaternius "Windows") renders see-through, while 0x0841 (8,8,8) is solid, so
  // green being non-zero does NOT save it. Any near-black / R&B-starved colour is
  // at risk, so lift red and blue (and floor green) to keep the swatch opaque
  // while preserving its hue -- (8,8,8) is a still-black-looking safe value.
  if ((r >> 3) === 0 && (bl >> 3) === 0) { r = Math.max(r, 8); g = Math.max(g, 8); bl = Math.max(bl, 8); }
  const S = 8, data = new Uint8ClampedArray(S * S * 4);
  for (let i = 0; i < S * S; i++) { data[i*4] = r; data[i*4+1] = g; data[i*4+2] = bl; data[i*4+3] = 255; }
  return new ImageData(data, S, S);
}

// Ordered, de-duplicated usemtl names as they appear in an OBJ.
function objMaterials(objText) {
  const seen = new Set(), out = [];
  for (const line of objText.split(/\r?\n/)) {
    const m = line.match(/^\s*usemtl\s+(.+?)\s*$/);
    if (m && !seen.has(m[1])) { seen.add(m[1]); out.push(m[1]); }
  }
  return out;
}

// Viper matches a mesh's material to its texture by literal name, and the stock
// convention that its texture lookup expects is a ".tex" suffix (VIPER.tex,
// UCAR.tex, ...). Most models in the wild use bare material names (body,
// carpaint, eyeball), which would import as textures the game never resolves --
// rendering untextured. So we normalise every imported material name to end in
// ".tex". It has to be applied in BOTH places the name lands, identically, or
// the .mod material and its texture member stop matching: normalizeObjMaterials
// rewrites the OBJ's usemtl lines (-> the .mod material name via from_obj), and
// the same normalizeMaterialName keys the staged texture member. A name that
// already ends in .tex is left alone, so re-imports and tool-made bundles are
// unchanged (idempotent).
function normalizeMaterialName(name) {
  return /\.tex$/i.test(name) ? name : name + ".tex";
}
function normalizeObjMaterials(objText) {
  return objText.replace(/^(\s*usemtl\s+)(.+?)(\s*)$/gm,
    (_m, pre, name, tail) => pre + normalizeMaterialName(name) + tail);
}

// data: URI -> raw bytes, for turning a TEXTURES[...] PNG back into file bytes.
async function dataUriToBytes(dataUri) {
  return new Uint8Array(await (await fetch(dataUri)).arrayBuffer());
}

// Decode an image file's bytes to canvas ImageData (RGBA, top-to-bottom). The
// browser decodes PNG/JPG/BMP/WebP/GIF; TGA has no native decoder so it goes
// through our own decodeTga (the same one Import TGA uses).
async function decodeImageBytes(name, bytes) {
  if (/\.tga$/i.test(name)) {
    const buf = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    const d = decodeTga(buf);
    return new ImageData(d.data, d.width, d.height);
  }
  const url = URL.createObjectURL(new Blob([bytes]));
  try {
    const img = await new Promise((res, rej) => {
      const im = new Image();
      im.onload = () => res(im);
      im.onerror = () => rej(new Error("couldn't decode image " + name));
      im.src = url;
    });
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0);
    return ctx.getImageData(0, 0, canvas.width, canvas.height);
  } finally {
    URL.revokeObjectURL(url);
  }
}

// True if any pixel is not fully opaque.
function imageDataHasAlpha(imgData) {
  const d = imgData.data;
  for (let i = 3; i < d.length; i += 4) if (d[i] < 255) return true;
  return false;
}
// Same check on a data: URI (the stored original texture), decoded via canvas.
async function dataUriHasAlpha(dataUri) {
  const img = await new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = dataUri; });
  const c = document.createElement("canvas"); c.width = img.naturalWidth; c.height = img.naturalHeight;
  const cx = c.getContext("2d"); cx.drawImage(img, 0, 0);
  return imageDataHasAlpha(cx.getImageData(0, 0, c.width, c.height));
}

// Decode any browser-supported audio (wav/mp3/ogg/m4a/flac...) to a mono 16-bit
// PCM WAV at targetRate -- the only shape sfx.from_wav_bytes accepts (it rejects
// anything not mono/16-bit). decodeAudioData resamples to the context's rate, so
// creating the context AT the original .sfx's rate matches it; channels are
// down-mixed to mono. This is the audio analog of _fit_to_original for textures,
// and it also normalises plain WAVs that would otherwise be rejected (stereo/
// 24-bit/wrong rate).
async function decodeAudioToMonoWav(bytes, targetRate) {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) throw new Error("this browser has no Web Audio decoder");
  const ctx = new AC({sampleRate: targetRate});
  let buf;
  try {
    buf = await ctx.decodeAudioData(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
  } finally {
    if (ctx.close) ctx.close();
  }
  const n = buf.length, chs = buf.numberOfChannels;
  const mono = new Float32Array(n);
  for (let c = 0; c < chs; c++) { const ch = buf.getChannelData(c); for (let i = 0; i < n; i++) mono[i] += ch[i]; }
  if (chs > 1) for (let i = 0; i < n; i++) mono[i] /= chs;
  return encodeWavMono16(mono, buf.sampleRate);
}

// Minimal mono 16-bit PCM WAV (44-byte header) from float samples in [-1, 1].
function encodeWavMono16(samples, rate) {
  const n = samples.length;
  const out = new DataView(new ArrayBuffer(44 + n * 2));
  const str = (o, s) => { for (let i = 0; i < s.length; i++) out.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); out.setUint32(4, 36 + n * 2, true); str(8, "WAVE");
  str(12, "fmt "); out.setUint32(16, 16, true); out.setUint16(20, 1, true);   // PCM
  out.setUint16(22, 1, true);            // mono
  out.setUint32(24, rate, true);
  out.setUint32(28, rate * 2, true);     // byte rate = rate * 1ch * 2bytes
  out.setUint16(32, 2, true);            // block align
  out.setUint16(34, 16, true);           // bits
  str(36, "data"); out.setUint32(40, n * 2, true);
  let o = 44;
  for (let i = 0; i < n; i++) { const s = Math.max(-1, Math.min(1, samples[i])); out.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7FFF, true); o += 2; }
  return new Uint8Array(out.buffer);
}

// Stage one decoded skin under its material name: update the live TEXTURES
// lookup (so a following reimport/preview shows it) and queue the real TGA bytes
// for commit. Returns null on success, or a reason string to report. The 16-char
// guard is the archive's own directory-entry name field (see build_shell_html /
// the format reference's package layer).
function stageMaterialTexture(material, imgData) {
  if (new TextEncoder().encode(material).length > 16) {
    return `${material}: name too long for the archive's 16-char name field -- rename the material in your 3D tool`;
  }
  // Snapshot the pre-import value once, so a Discard on the part that staged
  // this skin can put the original back (undefined = the material had no texture).
  if (!(material in originalTextures)) originalTextures[material] = TEXTURES[material];
  const canvas = document.createElement("canvas");
  canvas.width = imgData.width;
  canvas.height = imgData.height;
  canvas.getContext("2d").putImageData(imgData, 0, 0);
  TEXTURES[material] = canvas.toDataURL("image/png");
  pendingTextureEdits[material] = bytesToBase64(encodeTga(imgData));
  return null;
}

// --- minimal, dependency-free zip read/write (deflate via the platform) ------

async function inflateRaw(bytes) {
  const s = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(s).arrayBuffer());
}
async function deflateRaw(bytes) {
  const s = new Blob([bytes]).stream().pipeThrough(new CompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(s).arrayBuffer());
}

const CRC32_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    t[n] = c >>> 0;
  }
  return t;
})();
function crc32(bytes) {
  let c = 0xFFFFFFFF;
  for (let i = 0; i < bytes.length; i++) c = CRC32_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}

// Read a .zip into {basename: Uint8Array}. Paths flatten to basenames -- a model
// bundle is flat and the .mtl references images by basename anyway. Handles
// stored (method 0) and deflated (method 8) entries.
async function unzipFlat(bytes) {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let eocd = -1;
  for (let i = bytes.length - 22; i >= 0; i--) {
    if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error("not a valid .zip (no end-of-central-directory record)");
  const count = dv.getUint16(eocd + 10, true);
  let off = dv.getUint32(eocd + 16, true);
  const out = {}, dec = new TextDecoder();
  for (let n = 0; n < count; n++) {
    if (dv.getUint32(off, true) !== 0x02014b50) throw new Error("corrupt .zip central directory");
    const method = dv.getUint16(off + 10, true);
    const compSize = dv.getUint32(off + 20, true);
    const nameLen = dv.getUint16(off + 28, true);
    const extraLen = dv.getUint16(off + 30, true);
    const commentLen = dv.getUint16(off + 32, true);
    const lho = dv.getUint32(off + 42, true);
    const name = dec.decode(bytes.subarray(off + 46, off + 46 + nameLen));
    const lNameLen = dv.getUint16(lho + 26, true);
    const lExtraLen = dv.getUint16(lho + 28, true);
    const dataStart = lho + 30 + lNameLen + lExtraLen;
    const comp = bytes.subarray(dataStart, dataStart + compSize);
    if (!name.endsWith("/")) {
      let data;
      if (method === 0) data = comp;
      else if (method === 8) data = await inflateRaw(comp);
      else throw new Error(`unsupported .zip compression (method ${method}) for ${name}`);
      out[baseName(name)] = data;
    }
    off += 46 + nameLen + extraLen + commentLen;
  }
  return out;
}

// Build a deflated .zip Blob from [{name, bytes}].
async function makeZipBlob(files) {
  const enc = new TextEncoder();
  const chunks = [], central = [];
  let offset = 0;
  for (const f of files) {
    const nameBytes = enc.encode(f.name);
    const crc = crc32(f.bytes);
    const comp = await deflateRaw(f.bytes);
    const lh = new Uint8Array(30 + nameBytes.length);
    const ldv = new DataView(lh.buffer);
    ldv.setUint32(0, 0x04034b50, true);
    ldv.setUint16(4, 20, true);
    ldv.setUint16(8, 8, true);
    ldv.setUint32(14, crc, true);
    ldv.setUint32(18, comp.length, true);
    ldv.setUint32(22, f.bytes.length, true);
    ldv.setUint16(26, nameBytes.length, true);
    lh.set(nameBytes, 30);
    chunks.push(lh, comp);
    const cd = new Uint8Array(46 + nameBytes.length);
    const cdv = new DataView(cd.buffer);
    cdv.setUint32(0, 0x02014b50, true);
    cdv.setUint16(4, 20, true);
    cdv.setUint16(6, 20, true);
    cdv.setUint16(10, 8, true);
    cdv.setUint32(16, crc, true);
    cdv.setUint32(20, comp.length, true);
    cdv.setUint32(24, f.bytes.length, true);
    cdv.setUint16(28, nameBytes.length, true);
    cdv.setUint32(42, offset, true);
    cd.set(nameBytes, 46);
    central.push(cd);
    offset += lh.length + comp.length;
  }
  const cdStart = offset;
  let cdSize = 0;
  for (const cd of central) { chunks.push(cd); cdSize += cd.length; }
  const eocd = new Uint8Array(22);
  const edv = new DataView(eocd.buffer);
  edv.setUint32(0, 0x06054b50, true);
  edv.setUint16(8, central.length, true);
  edv.setUint16(10, central.length, true);
  edv.setUint32(12, cdSize, true);
  edv.setUint32(16, cdStart, true);
  chunks.push(eocd);
  return new Blob(chunks, {type: "application/zip"});
}

// Export a part as a zip: the .obj (its mtllib pointed at our .mtl), a generated
// .mtl, and a PNG per material that currently has a resolved texture. Materials
// with no texture are still declared (colour only), so the bundle stays a
// faithful description even where a skin was never found.
async function exportPartBundle(partName, objText) {
  const base = partName.replace(/\.mod$/i, "");
  const mtlName = `${base}.mtl`;
  const objOut = `mtllib ${mtlName}\n` + objText.replace(/^\s*mtllib.*\r?\n?/im, "");
  const files = [];
  const mtl = ["# generated by vrmod"];
  for (const mat of objMaterials(objText)) {
    mtl.push(`newmtl ${mat}`, "Ka 1.000 1.000 1.000", "Kd 1.000 1.000 1.000", "d 1.000", "illum 1");
    const dataUri = TEXTURES[mat];
    if (dataUri) {
      const png = `${sanitizeFilename(base)}_${sanitizeFilename(mat)}.png`;
      files.push({name: png, bytes: await dataUriToBytes(dataUri)});
      mtl.push(`map_Kd ${png}`);
    }
    mtl.push("");
  }
  const enc = new TextEncoder();
  files.unshift({name: `${base}.obj`, bytes: enc.encode(objOut)},
                {name: mtlName, bytes: enc.encode(mtl.join("\n") + "\n")});
  downloadBytes(await makeZipBlob(files), `${base}.zip`);
}

// Lazily-created mini scene for the Parts drawer's live preview -- a WebGL context
// is real overhead, so it's only ever created the first time a part is actually
// clicked, not up front on page load.
let partPreview = null;
let selectedPartName = null;  // which Parts-drawer row is selected, for the import input
// What Save (see commitChanges()) will actually send -- every
// successfully reimported part/texture lands here regardless of whether it had
// a live destination to preview against (see applyLiveReimport's docstring: "no
// live preview" is a viewport limitation, not a reason to drop the edit).
const pendingPartEdits = {};     // {realFilename: objText}
const pendingTextureEdits = {};  // {materialName: decoded TGA base64}
const pendingSfxEdits = {};      // {realFilename: raw uploaded WAV bytes, base64}
// Support for discarding a staged part edit and rolling baselines forward on Save.
const originalTextures = {};        // material -> its pre-import TEXTURES value (undefined if it had none)
const importedTexturesByPart = {};  // partName -> [materials its OBJ import staged], so Discard drops exactly those
const pendingPartRemovals = new Set();  // member names staged for deletion (optional slots / reverted overrides)
let rebuildPartsDrawer = null;      // set by buildPartsDrawer so Save can redraw with fresh present/empty states
let rebuildTextureDrawer = null;    // set in main() so Save/revert can redraw the active tab's swatches
let getActiveKey = null;            // set in main() so a rebuild can re-apply the in-view (.rendered) highlight
let partsFilterOn = true;           // default: show only what's on the car; the filter toggle reveals add-only slots

// Apply the parts filter. Filtered (default) shows only rows whose `view` is the
// current 3D tab -- so the list is curated to what you're looking at and adapts
// when you switch Car/Cockpit/Horn Ball. Off shows the whole catalog. Either way,
// a group header with no visible rows is hidden. Uses a `filter-hidden` class
// (not inline display) so it composes with the detail boxes' own collapsed state.
function applyPartsFilter() {
  const list = document.getElementById("parts-list");
  if (!list) return;
  const key = getActiveKey ? getActiveKey() : null;
  const showAll = !partsFilterOn;
  // In Show all, the blue "in view" highlight marks the current tab's parts (what
  // the filter would keep); in filtered mode it'd be every row, so it's suppressed.
  list.classList.toggle("show-all", showAll);
  let header = null, hasVisible = false;
  const flush = () => { if (header) header.classList.toggle("filter-hidden", !hasVisible); };
  for (const el of list.children) {
    if (el.classList.contains("part-grp")) { flush(); header = el; hasVisible = false; continue; }
    const show = showAll || (el.dataset.view || "") === key;
    el.classList.toggle("filter-hidden", !show);
    if (show && el.classList.contains("part-row")) hasVisible = true;
  }
  flush();
}

// Undo the texture side of a part's OBJ import: restore each material this part
// staged to its pre-import state and drop its pending write. The mesh itself is
// reverted separately by the caller (applyLiveReimport with MOD_PARTS[name]).
function revertPartTextures(partName) {
  for (const mat of importedTexturesByPart[partName] || []) {
    if (mat in originalTextures) {
      if (originalTextures[mat] === undefined) delete TEXTURES[mat];
      else TEXTURES[mat] = originalTextures[mat];
      delete originalTextures[mat];
    }
    delete pendingTextureEdits[mat];
  }
  delete importedTexturesByPart[partName];
}

function ensurePartPreview() {
  if (partPreview) return partPreview;
  const wrap = document.getElementById("part-preview-canvas");
  const W = wrap.clientWidth || 280, H = wrap.clientHeight || 170;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x14161c);
  scene.add(new THREE.AmbientLight(0xffffff, 0.8));
  const dl = new THREE.DirectionalLight(0xffffff, 0.9);
  dl.position.set(3, 5, 4);
  scene.add(dl);
  const camera = new THREE.PerspectiveCamera(45, W / H, 0.01, 1000);
  const renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setSize(W, H);
  wrap.appendChild(renderer.domElement);
  partPreview = {scene, camera, renderer, group: null, angle: 0};
  function animate() {
    requestAnimationFrame(animate);
    if (partPreview.group) {
      partPreview.angle += 0.008;
      partPreview.group.rotation.y = partPreview.angle;
    }
    renderer.render(scene, camera);
  }
  animate();
  return partPreview;
}

// Slow auto-rotate instead of drag-to-orbit -- this is a quick "what is this"
// look, not a full viewer; keeping it passive avoids a second set of mouse
// handlers fighting the main viewport's for drag events.
function previewPart(name, objText) {
  const p = ensurePartPreview();
  const label = document.getElementById("part-preview-label");
  label.textContent = name;
  if (p.group) p.scene.remove(p.group);
  const {group} = buildPartGroup(objText);
  p.group = group;
  p.angle = 0;
  p.scene.add(group);
  const box = new THREE.Box3().setFromObject(group);
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z, 0.01) * 2.3;
  p.camera.position.set(center.x + radius * 0.6, center.y + radius * 0.45, center.z + radius * 0.7);
  p.camera.lookAt(center);
}

// Which real MOD_PARTS names are actually rendered in tab `key` right now -- used
// to highlight the Parts drawer (see updatePartsHighlight) so it's obvious which
// of a car's real files you're looking at vs. real files that exist but aren't
// shown anywhere in the default view (LOD1-7, Needle.mod, etc. stay listed, just
// not highlighted -- same "show what's real" choice as everywhere else here).
// Reads straight from CAR_ROLES, the same source buildTabGroup/applyLiveReimport
// already use to know which named piece maps to which tab.
function activePartNames(key) {
  const names = new Set();
  if (key === "car" && CAR_ROLES.car) {
    for (const v of Object.values(CAR_ROLES.car)) if (typeof v === "string") names.add(v);
  } else if (key === "cockpit" && CAR_ROLES.cockpit) {
    if (CAR_ROLES.cockpit.dash) names.add(CAR_ROLES.cockpit.dash);
    if (CAR_ROLES.cockpit.wheel) names.add(CAR_ROLES.cockpit.wheel);
    // The needle is instanced twice (tach + speedo) via addNeedle, so it's not in
    // meshesByMaterial, but it IS rendered -- include it so its row highlights too.
    if (CAR_ROLES.cockpit.needle) names.add(CAR_ROLES.cockpit.needle);
  } else if (key === "hornball" && CAR_ROLES.hornball) {
    names.add(CAR_ROLES.hornball);
  }
  return names;
}

function updatePartsHighlight(key) {
  const active = activePartNames(key);
  document.querySelectorAll("#parts-list .part-row").forEach(row => {
    row.classList.toggle("rendered", active.has(row.dataset.part));
  });
}

// Takes applyLiveReimport so a row's own Import/Discard can swap the live mesh --
// it lives inside main()'s closure (it needs built/activeKey/refitAndRefresh),
// while this drawer is built top-level. Import/Export/Discard live on each row
// (mirroring the Textures drawer) so an edit is always bound to the row you acted
// on -- no separate "selected part" to get wrong.
// The car's fixed slot vocabulary, in display order (see car.py / format-reference
// §3.5). Each part of a real car maps to one of these; unknown owned members fall
// into a catch-all "Other parts" group so nothing is ever hidden. suffix builds the
// member name as <prefix><suffix>.mod; fixedName is a car-agnostic literal.
// `view` = which of the three 3D tabs actually renders this part, so the filter
// can curate the list to whatever tab you're looking at.
const SLOT_DEFS = [
  {group: "Body",               label: "Body",               suffix: "0", structural: true, view: "car"},
  {group: "Exterior add-ons",   label: "Brake lights",       suffix: "b", removable: true, view: "car"},
  {group: "Exterior add-ons",   label: "Spoiler",            suffix: "s", removable: true, view: "car"},
  {group: "Interior · primary car", label: "Dashboard",      suffix: "c", removable: true, view: "cockpit"},
  {group: "Interior · primary car", label: "Speedometer needle", fixedName: "Needle.mod", removable: true, view: "cockpit"},
  {group: "Interior · primary car", label: "Steering wheel", suffix: "w", removable: true, view: "cockpit"},
];

// The shared race.res assets a car can override, in display order. Names/roles
// confirmed from each mesh's size/shape/material (wheels are wheels.tex; the rest
// are the XRAY.tex chassis/X-ray-view parts). `members` lists a mesh's detail
// variants (collapsed like body LODs). `core:true` = wheels + horn ball, the ones
// the car actually renders, so they show in the default (filtered) view; the rest
// are add-only (revealed only when the "show all" filter is off).
const SHARED_SLOTS = [
  {label: "Horn ball",       members: ["ball.mod"], core: true, view: "hornball"},
  {label: "Front wheel",     members: ["fwheel_1.mod", "fwheel_2.mod", "fwheel_3.mod"], core: true, view: "car"},
  {label: "Rear wheel",      members: ["wheel_1.mod", "wheel_2.mod", "wheel_3.mod"], core: true, view: "car"},
  {label: "Brake lights",    members: ["brakelt.mod"]},
  {label: "Brake disc glow", members: ["diskglow.mod"]},
  {label: "X-ray body",      members: ["Xray.mod"]},
  {label: "Lower control arm (L)", members: ["arm_ll.mod"]},
  {label: "Lower control arm (R)", members: ["arm_lr.mod"]},
  {label: "Upper control arm (L)", members: ["arm_ul.mod"]},
  {label: "Upper control arm (R)", members: ["arm_ur.mod"]},
  {label: "Strut (L)",       members: ["arm_sl.mod"]},
  {label: "Strut (R)",       members: ["arm_sr.mod"]},
  {label: "Wheel spin (L)",  members: ["spin_l.mod"]},
  {label: "Wheel spin (R)",  members: ["spin_r.mod"]},
];

function buildPartsDrawer(applyLiveReimport, removeLivePart, highlightPart) {
  rebuildPartsDrawer = () => { buildPartsDrawer(applyLiveReimport, removeLivePart, highlightPart); if (getActiveKey) updatePartsHighlight(getActiveKey()); };
  const root = document.getElementById("parts-list");
  const status = document.getElementById("import-obj-status");
  root.innerHTML = "";

  const ownByLower = {};
  for (const k of Object.keys(MOD_PARTS)) ownByLower[k.toLowerCase()] = k;
  const owns = n => ownByLower[String(n).toLowerCase()];   // actual owned member name, or undefined
  const bodyName = (CAR_ROLES.car && CAR_ROLES.car.body) || Object.keys(MOD_PARTS)[0] || "car0.mod";
  const prefix = bodyName.replace(/0\.mod$/i, "");
  const claimed = new Set();

  // Set a row's staged appearance without rebuilding it (rebuild only happens on
  // Save, when ownership actually changes). state: "none" | "edited" | "added" | "removing".
  function setStaged(row, state, tag) {
    const base = row.dataset.base;   // "present" | "empty"
    row.classList.toggle("staged", state !== "none");
    row.classList.toggle("removing", state === "removing");
    row.classList.toggle("added", state === "added");
    // The empty (dashed/dimmed) look applies only to an unstaged empty slot; a
    // staged add/edit/removal is drawn as a filled row.
    row.classList.toggle("empty", state === "none" && base === "empty");
    const rev = row.querySelector(".part-revert");
    if (rev) rev.hidden = (state === "none");
    const tg = row.querySelector(".part-tag");
    if (tg) { tg.textContent = tag ? ("→ " + tag) : ""; if (tag) tg.title = tag; }
  }

  async function importOntoMember(member, fileList, row, addMode) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    status.textContent = "Reading import…";
    try {
      const bag = {};
      for (const f of files) {
        const bytes = new Uint8Array(await f.arrayBuffer());
        if (/\.zip$/i.test(f.name)) Object.assign(bag, await unzipFlat(bytes));
        else bag[baseName(f.name)] = bytes;
      }
      const dec = new TextDecoder();
      const objKey = Object.keys(bag).find(k => /\.obj$/i.test(k));
      if (!objKey) { status.textContent = "No .obj found in the selection."; return; }
      const objTextRaw = dec.decode(bag[objKey]);
      // Normalise material names to the .tex convention up front, then use the
      // normalised OBJ for preview, live re-import and the staged edit so the
      // 3D lookup, the .mod, and the texture members all key off the same name.
      const objText = normalizeObjMaterials(objTextRaw);
      if (importedTexturesByPart[member]) revertPartTextures(member);
      const mtlKey = Object.keys(bag).find(k => /\.mtl$/i.test(k));
      const notes = [], stagedMats = [];
      if (mtlKey) {
        const matToInfo = parseMtl(dec.decode(bag[mtlKey]));  // {mat: {img, kd}}, original names
        for (const rawMat of objMaterials(objTextRaw)) {
          const mat = normalizeMaterialName(rawMat);   // stage/report under the normalised name
          const info = matToInfo[rawMat] || {};
          let imgData = null;
          if (info.img) {
            const imgBytes = bag[info.img] || bag[baseName(info.img)];
            if (imgBytes) {
              try { imgData = await decodeImageBytes(info.img, imgBytes); }
              catch (err) { notes.push(`${mat}: ${err.message}`); continue; }
            } else if (!info.kd) {
              notes.push(`${mat}: image "${info.img}" not in the selection`); continue;
            }
          }
          // Colour-only material (no map_Kd, or its image wasn't in the bundle):
          // synthesise a flat swatch from Kd so it imports in its real colour.
          if (!imgData && info.kd) imgData = solidColorImageData(info.kd);
          if (!imgData) { notes.push(`${mat}: no map_Kd or Kd colour in the .mtl`); continue; }
          const problem = stageMaterialTexture(mat, imgData);
          if (problem) notes.push(problem); else stagedMats.push(mat);
        }
      }
      if (stagedMats.length) importedTexturesByPart[member] = stagedMats;
      pendingPartRemovals.delete(member);   // an import supersedes a staged removal
      previewPart(member, objText);
      const changedTab = applyLiveReimport(member, objText);
      pendingPartEdits[member] = objText;
      setStaged(row, addMode ? "added" : "edited", objKey);
      updateCommitStatus();
      let msg = `Staged ${objKey} → ${member}`;
      msg += stagedMats.length ? ` with ${stagedMats.length} texture(s)` : (mtlKey ? " (no textures staged)" : " (mesh only)");
      msg += changedTab ? ` — updated the ${TAB_LABELS[changedTab] || changedTab} view.` : " — shown in the preview; the full car updates on Save.";
      if (notes.length) msg += " " + String.fromCharCode(0x26A0) + " " + notes.join("; ");
      status.textContent = msg;
    } catch (err) { status.textContent = "Import failed: " + (err && err.message ? err.message : err); }
  }

  function revertRow(member, row) {
    if (pendingPartRemovals.has(member)) {
      pendingPartRemovals.delete(member);
      if (owns(member)) applyLiveReimport(member, MOD_PARTS[member]);  // put the piece back live
      setStaged(row, "none");
      status.textContent = `Kept ${member}.`;
    } else {
      const wasAdd = row.dataset.base === "empty";
      revertPartTextures(member);
      delete pendingPartEdits[member];
      if (wasAdd) { removeLivePart(member); }        // undo a live-added slot
      else { previewPart(member, MOD_PARTS[member]); applyLiveReimport(member, MOD_PARTS[member]); }
      setStaged(row, "none");
      status.textContent = `Reverted ${member} to the car's original.`;
    }
    updateCommitStatus();
  }

  function stageRemoval(member, row) {
    delete pendingPartEdits[member];   // removal supersedes any staged edit
    revertPartTextures(member);
    pendingPartRemovals.add(member);
    removeLivePart(member);
    setStaged(row, "removing", "will remove");
    updateCommitStatus();
    status.textContent = `${member} will be removed on Save.`;
  }

  const mkImport = (member, row, addMode, cls, text, title) => {
    const lbl = document.createElement("label");
    lbl.className = cls;
    lbl.textContent = text;
    lbl.title = title;
    const inp = document.createElement("input");
    inp.type = "file"; inp.multiple = true;
    inp.accept = ".obj,.mtl,.png,.jpg,.jpeg,.bmp,.webp,.gif,.tga,.zip";
    lbl.addEventListener("click", e => e.stopPropagation());
    inp.addEventListener("change", async e => { await importOntoMember(member, e.target.files, row, addMode); e.target.value = ""; });
    lbl.appendChild(inp);
    return lbl;
  };

  // Build one row. Three states: present (car owns it), sharedDefault (a shared
  // race.res asset the car inherits -- Import creates a per-car override), or
  // empty (a per-car slot the car lacks -- Add creates it). cfg.view is the 3D
  // tab that renders this part (car/cockpit/hornball) or "" if none; the filter
  // shows only the current tab's parts, and "" rows appear only when filter is off.
  function makeRow(cfg) {
    const stateClass = cfg.present ? "" : cfg.sharedDefault ? " shared-default" : " empty";
    const row = document.createElement("div");
    row.className = "part-row selectable" + stateClass;
    row.dataset.part = cfg.member;
    row.dataset.base = cfg.present ? "present" : "empty";
    row.dataset.view = cfg.view || "";
    const dot = document.createElement("span"); dot.className = "dot"; row.appendChild(dot);
    // Title (friendly name) over a muted subtitle (the real member name + any
    // shared-override note). Two lines so the always-visible buttons never crowd
    // the name or reflow. The subtitle is omitted when it would just repeat the
    // title (raw-name rows like LODs / Other parts).
    const main = document.createElement("span"); main.className = "part-main";
    const nm = document.createElement("span"); nm.className = "part-name"; nm.textContent = cfg.label; main.appendChild(nm);
    if (cfg.label !== cfg.member || cfg.sharedNote) {
      const sub = document.createElement("span"); sub.className = "part-sub";
      sub.textContent = (cfg.label !== cfg.member) ? cfg.member : "";
      if (cfg.sharedNote) { const n = document.createElement("span"); n.className = "note"; n.textContent = (sub.textContent ? " · " : "") + cfg.sharedNote; sub.appendChild(n); }
      main.appendChild(sub);
    }
    row.appendChild(main);
    const current = () => pendingPartEdits[cfg.member] || MOD_PARTS[cfg.member];
    row.addEventListener("click", () => {
      root.querySelectorAll(".part-row").forEach(r => r.classList.remove("selected"));
      row.classList.add("selected");
      selectedPartName = cfg.member;
      if (current()) previewPart(cfg.member, current());
    });
    // Hover glows this part in the live 3D view (no-op for off-tab/empty slots).
    if (highlightPart) {
      row.addEventListener("mouseenter", () => highlightPart(cfg.member, true));
      row.addEventListener("mouseleave", () => highlightPart(cfg.member, false));
    }

    // Staged-source tag ("→ boulder.obj") goes INSIDE the stacked name column, not
    // inline before the buttons -- inline it stole horizontal width and collapsed
    // the name to one-letter-per-line when a staged row also shows Import/Export/🗑.
    const tag = document.createElement("span"); tag.className = "part-tag"; main.appendChild(tag);
    // always-visible: revert, or the Add button for an empty slot
    const always = document.createElement("span"); always.className = "part-always";
    const rev = document.createElement("button");
    rev.className = "part-revert"; rev.textContent = "↺"; rev.hidden = true;
    rev.title = "Undo this staged change"; rev.setAttribute("aria-label", "undo");
    rev.addEventListener("click", e => { e.stopPropagation(); revertRow(cfg.member, row); });
    always.appendChild(rev);
    if (cfg.addable) always.appendChild(mkImport(cfg.member, row, true, "part-add", "+ Add", "Add this part: import an .obj (with its .mtl + textures, or a .zip)"));
    row.appendChild(always);

    // Import / Export / Remove for a present slot or a shared-default override.
    if (cfg.present || cfg.sharedDefault) {
      const act = document.createElement("span"); act.className = "part-actions";
      const importTitle = cfg.sharedDefault
        ? "Import an .obj to override this shared default with a per-car copy"
        : "Import an .obj (with its .mtl + textures, or a .zip) onto this part";
      act.appendChild(mkImport(cfg.member, row, cfg.sharedDefault, "part-import", "Import", importTitle));
      if (MOD_PARTS[cfg.member]) {   // only exportable if there's a real mesh to export (owned, or ball's added default)
        const exp = document.createElement("button"); exp.textContent = "Export";
        exp.title = "Download a .zip: the mesh (.obj), its .mtl, and a PNG per texture";
        exp.addEventListener("click", async e => {
          e.stopPropagation(); exp.disabled = true; const was = exp.textContent; exp.textContent = "Zipping…";
          try { await exportPartBundle(cfg.member, current()); }
          catch (err) { alert("Export failed: " + (err && err.message ? err.message : err)); }
          finally { exp.disabled = false; exp.textContent = was; }
        });
        act.appendChild(exp);
      }
      if (cfg.removable) {
        const rm = document.createElement("button"); rm.className = "part-remove";
        rm.textContent = "🗑";
        rm.title = cfg.sharedNote ? "Remove this override (revert to the shared default)" : "Remove this part from the car";
        rm.setAttribute("aria-label", "remove");
        rm.addEventListener("click", e => { e.stopPropagation(); stageRemoval(cfg.member, row); });
        act.appendChild(rm);
      }
      row.appendChild(act);
    }
    root.appendChild(row);
    // reflect any state already staged this session (rebuild after Save clears it)
    if (pendingPartRemovals.has(cfg.member)) setStaged(row, "removing", "will remove");
    else if (pendingPartEdits[cfg.member]) setStaged(row, cfg.present ? "edited" : "added", "edited");
    return row;
  }

  let lastGroup = null;
  function groupHeader(g) {
    if (g === lastGroup) return;
    lastGroup = g;
    const h = document.createElement("div"); h.className = "part-grp"; h.textContent = g;
    root.appendChild(h);
  }

  // Collapse extra detail variants (body LODs, or the wheels' _2/_3) under a
  // "N more detail levels" toggle, so they don't spam the list. Same pattern for
  // both. opts carries the label/removable/sharedNote for the collapsed rows.
  function addDetailChain(extras, opts) {
    opts = opts || {};
    if (!extras.length) return;
    const toggle = document.createElement("div"); toggle.className = "part-row part-lodtoggle";
    toggle.dataset.view = opts.view || "";
    toggle.innerHTML = `<span class="chev">▸</span><span class="part-name" style="color:#a8adc0">${extras.length} more detail level${extras.length > 1 ? "s" : ""}</span>`;
    const box = document.createElement("div"); box.className = "part-detail-box"; box.hidden = true;
    box.dataset.view = opts.view || "";
    toggle.addEventListener("click", () => {
      box.hidden = !box.hidden;
      toggle.querySelector(".chev").textContent = box.hidden ? "▸" : "▾";
    });
    root.appendChild(toggle);
    // makeRow appends to root and returns the row; move each into the collapsible box.
    extras.forEach(m => box.appendChild(makeRow({
      member: m, label: opts.label || m, present: true, importable: true, exportable: true,
      removable: !!opts.removable, sharedNote: opts.sharedNote || null, view: opts.view || "",
    })));
    root.appendChild(box);
  }

  // --- Body (LOD0) + collapsed LOD chain ---
  groupHeader("Body");
  claimed.add(bodyName.toLowerCase());
  makeRow({member: bodyName, label: "Body", present: true, removable: false, importable: true, exportable: true, view: "car"});
  const lods = [];
  for (let i = 1; i <= 9; i++) { const a = owns(`${prefix}${i}.mod`); if (a) { lods.push(a); claimed.add(a.toLowerCase()); } }
  addDetailChain(lods, {view: "car"});   // body LOD1-7: raw names, not removable (structural)

  // --- the remaining fixed slots ---
  for (const def of SLOT_DEFS) {
    if (def.suffix === "0") continue;   // body already done
    const member = def.fixedName ? (owns(def.fixedName) || def.fixedName) : `${prefix}${def.suffix}.mod`;
    const actual = owns(member) || (def.fixedName && owns(def.fixedName));
    const present = !!actual;
    if (actual) claimed.add(actual.toLowerCase());
    groupHeader(def.group);
    makeRow({
      member: actual || member,
      label: def.label,
      present,
      importable: true,
      exportable: present,
      addable: !present,
      removable: !!def.removable && present,
      view: present ? def.view : "",   // only rendered when actually present
    });
  }

  // --- Shared race.res assets (the full catalog). Owned => a per-car override
  //     (+ collapsed detail variants); otherwise the shared default with Import to
  //     override. Wheels + horn ball are `core` (the car renders them) so they show
  //     in the default filtered view; the chassis/X-ray parts are add-only. ---
  const sharedMembers = new Set();
  SHARED_SLOTS.forEach(s => s.members.forEach(m => sharedMembers.add(m.toLowerCase())));
  // A shared member counts as a real override only if the car owns it for real --
  // NOT if it's the shared default the page injected into MOD_PARTS (e.g. ball.mod,
  // flagged in SHARED_PART_NAMES). Otherwise the default would read as "override".
  const ownsReal = m => { const a = owns(m); return (a && !SHARED_PART_NAMES.has(a)) ? a : null; };
  for (const s of SHARED_SLOTS) {
    const owned = s.members.map(ownsReal).filter(Boolean);
    owned.forEach(m => claimed.add(m.toLowerCase()));
    groupHeader("Shared · from race.res");
    if (owned.length) {
      makeRow({member: owned[0], label: s.label, present: true, view: s.view || "",
               importable: true, exportable: true, removable: true, sharedNote: "override"});
      addDetailChain(owned.slice(1), {label: s.label, removable: true, sharedNote: "override", view: s.view || ""});
    } else {
      makeRow({member: s.members[0], label: s.label, present: false, sharedDefault: true,
               view: s.view || "", importable: true, removable: false, sharedNote: "shared default"});
    }
  }

  // --- anything owned but unrecognised: raw "Other parts" (always in use, never
  //     hidden) so nothing a car actually carries can disappear ---
  const others = Object.keys(MOD_PARTS).filter(n => !claimed.has(n.toLowerCase()) && !sharedMembers.has(n.toLowerCase()));
  for (const m of others) {
    groupHeader("Other parts");
    makeRow({member: m, label: m, present: true, view: "", importable: true, exportable: true, removable: true});
  }

  applyPartsFilter();   // hide add-only rows + empty group headers per the current filter
}

// Sound drawer -- one row per real .sfx entry in the car's own archive (see
// SFX_PARTS/_car_sfx_parts). PCM entries get a native <audio> player built from
// an embedded WAV data URI; ADPCM entries (format_tag=2, not yet decodable --
// see sfx.py's module docstring) still get listed, just without a player -- same
// "show what's real even if not fully actionable yet" choice buildPartsDrawer
// makes for a .mod entry that fails to parse.
function buildSoundDrawer() {
  const root = document.getElementById("sound-list");
  root.innerHTML = "";                              // rebuildable -- re-run on import, revert, and Save
  const names = Object.keys(SFX_PARTS);
  if (names.length === 0) {
    root.innerHTML = '<div class="empty">no .sfx entries found</div>';
    return;
  }
  names.forEach(name => {
    const info = SFX_PARTS[name];
    const pendingB64 = pendingSfxEdits[name];        // a staged replacement (mono 16-bit WAV), if any
    const row = document.createElement("div");
    row.className = "sound-row" + (pendingB64 ? " pending" : "");
    const label = document.createElement("div");
    label.className = "sound-name";
    label.textContent = name + (pendingB64 ? " (pending)" : (info && info.shared ? " (shared default)" : ""));
    row.appendChild(label);

    // Body: a pending replacement previews the CONVERTED wav (what actually gets
    // committed); otherwise the original entry, playable if PCM.
    if (pendingB64) {
      const meta = document.createElement("div");
      meta.className = "sound-meta";
      meta.textContent = "staged replacement — mono 16-bit, commits on Save";
      row.appendChild(meta);
      const audio = document.createElement("audio");
      audio.controls = true;
      audio.src = "data:audio/wav;base64," + pendingB64;
      row.appendChild(audio);
    } else if (info && info.wav_b64) {
      const meta = document.createElement("div");
      meta.className = "sound-meta";
      meta.textContent = `${info.sample_rate} Hz, ${info.bits_per_sample}-bit PCM, ${info.duration}s`;
      row.appendChild(meta);
      const audio = document.createElement("audio");
      audio.controls = true;
      audio.preload = "none";
      audio.src = "data:audio/wav;base64," + info.wav_b64;
      row.appendChild(audio);
    } else {
      const note = document.createElement("div");
      note.className = "sound-unplayable";
      note.textContent = info
        ? `${info.sample_rate} Hz -- ADPCM-encoded, not decodable yet`
        : "couldn't parse";
      row.appendChild(note);
    }

    const statusEl = document.createElement("div");
    statusEl.className = "sound-import-status";

    // Actions: Import (always) + ↺ Revert (only when a change is staged) --
    // parity with the Parts drawer's Import / ↺ pair. Import works on any row
    // (playable, ADPCM, or a shared default); the replacement is a fresh WAV
    // regardless, converted to the mono 16-bit .sfx server-side at commit
    // (sfx.from_wav_bytes()+build(), see cli.py's _apply_commit) via
    // archive.upsert_entry -- same shared-default-becomes-an-override pattern
    // proven for ball.mod and unowned textures.
    const actions = document.createElement("div");
    actions.className = "sound-actions";
    const importLabel = document.createElement("label");
    importLabel.className = "sound-import";
    importLabel.textContent = pendingB64 ? "Replace" : "Import";
    importLabel.title = "Import a sound (WAV, MP3, OGG, …) -- converted to the mono 16-bit .sfx the game needs";
    const importInput = document.createElement("input");
    importInput.type = "file";
    importInput.accept = ".wav,.mp3,.ogg,.m4a,.aac,.flac,.opus";
    importInput.addEventListener("change", async e => {
      const file = e.target.files[0];
      e.target.value = "";
      if (!file) return;
      statusEl.textContent = "Decoding…";
      try {
        // .sfx must be mono 16-bit (sfx.from_wav_bytes rejects otherwise), so decode
        // and re-encode to that shape at the original entry's sample rate. Handles
        // MP3/OGG/etc AND normalises a stereo/24-bit WAV that would otherwise fail.
        const rate = (info && info.sample_rate) || 22050;
        const wav = await decodeAudioToMonoWav(new Uint8Array(await file.arrayBuffer()), rate);
        pendingSfxEdits[name] = bytesToBase64(wav);
        updateCommitStatus();
        buildSoundDrawer();                          // redraw: this row now shows the staged preview + ↺
      } catch (err) {
        statusEl.textContent = `${file.name}: couldn't decode audio (${err && err.message ? err.message : err}).`;
      }
    });
    importLabel.appendChild(importInput);
    actions.appendChild(importLabel);

    if (pendingB64) {
      const rev = document.createElement("button");
      rev.className = "sound-revert";
      rev.textContent = "↺";
      rev.title = "Discard this staged sound and restore the original";
      rev.addEventListener("click", () => {
        delete pendingSfxEdits[name];
        updateCommitStatus();
        buildSoundDrawer();                          // redraw: back to the original row
      });
      actions.appendChild(rev);
    }
    row.appendChild(actions);
    row.appendChild(statusEl);
    root.appendChild(row);
  });
}

function main() {
  if (typeof THREE === "undefined") {
    const el = document.getElementById("fatal-error");
    el.style.display = "block";
    el.textContent = "three.js (bundled with this tool) didn't initialize -- the 3D "
      + "library failed to load. This shouldn't require internet; check the browser "
      + "console (F12) for the specific error.";
    return;
  }

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1a1a1a);
  const wrap = document.getElementById("canvas-wrap");
  const W = () => wrap.clientWidth, H = () => wrap.clientHeight;
  const camera = new THREE.PerspectiveCamera(45, W()/H(), 0.01, 1000);
  const renderer = new THREE.WebGLRenderer({antialias:true, preserveDrawingBuffer:true});
  renderer.setSize(W(), H());
  wrap.appendChild(renderer.domElement);

  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  const dl = new THREE.DirectionalLight(0xffffff, 0.9);
  dl.position.set(5,10,7);
  scene.add(dl);
  const dl2 = new THREE.DirectionalLight(0xffffff, 0.4);
  dl2.position.set(-5,3,-7);
  scene.add(dl2);

  const tabKeys = ["car"];
  if (CAR_ROLES.cockpit) tabKeys.push("cockpit");
  if (CAR_ROLES.hornball) tabKeys.push("hornball");
  const built = {};
  for (const key of tabKeys) built[key] = buildTabGroup(key);

  // The 4 wheels are separate live-positioned objects nested under the "car" tab's
  // group rather than baked into its mesh -- see assemble_car_live()'s docstring.
  // wheelBaseY holds each corner's own ground-touching Y offset -- normally 0
  // (already baked into CAR_WHEELS' vertex data server-side), but a live-
  // reimported wheel's raw geometry isn't pre-shifted, so its own freshly
  // computed offset lives here instead of being clobbered by updateWheelPositions.
  const wheelObjs = {};
  const wheelBaseY = {};
  // CAR_WHEELS is {} when the shared wheel meshes weren't available (no race.res);
  // the body still renders, just without wheels. updateWheelPositions() no-ops too.
  if (built.car && CAR_WHEELS && CAR_WHEELS.front_left) {
    for (const key of ["front_left", "front_right", "rear_left", "rear_right"]) {
      const {group, meshesByMaterial} = buildPartGroup(CAR_WHEELS[key]);
      built.car.group.add(group);
      wheelObjs[key] = group;
      wheelBaseY[key] = 0;
      // Fold the wheels' own materials into the Car tab's set too, so the
      // Textures drawer shows everything the tab actually displays, not just
      // the chassis's own materials.
      for (const [matName, meshes] of Object.entries(meshesByMaterial)) {
        (built.car.meshesByMaterial[matName] = built.car.meshesByMaterial[matName] || []).push(...meshes);
      }
    }
  }
  function updateWheelPositions() {
    if (!wheelObjs.front_left) return;
    const getStat = name => {
      const el = document.querySelector(`#sections input[data-field="${name}"]`);
      return el ? Number(el.value) : STATS[name];
    };
    const ftrackM = getStat("ftrack") * INCH_TO_M;
    const rtrackM = getStat("rtrack") * INCH_TO_M;
    const wheelbaseM = getStat("wheelbase") * INCH_TO_M;
    const frontZ = wheelbaseM / 2, rearZ = -wheelbaseM / 2;
    wheelObjs.front_left.position.set(-ftrackM / 2, wheelBaseY.front_left, frontZ);
    wheelObjs.front_right.position.set(ftrackM / 2, wheelBaseY.front_right, frontZ);
    wheelObjs.rear_left.position.set(-rtrackM / 2, wheelBaseY.rear_left, rearZ);
    wheelObjs.rear_right.position.set(rtrackM / 2, wheelBaseY.rear_right, rearZ);
  }
  updateWheelPositions();
  document.getElementById("sections").addEventListener("input", updateWheelPositions);

  // Swaps one live-rendered piece for a client-side-parsed reimport. Used for
  // body/sub_b/sub_s/dash/cockpit-wheel/hornball (single named piece, `role`
  // matches a key in that tab's `pieces`) -- wheel pairs go through
  // swapWheelPair() instead, since one reimported wheel file has to update two
  // mirrored corners with fresh ground-offset math, not just one static piece.
  function swapTabPiece(tabKey, role, objText, position) {
    const tabBuilt = built[tabKey];
    const old = tabBuilt.pieces[role];
    if (old) tabBuilt.group.remove(old.group);
    const piece = buildPartGroup(objText);
    if (position) piece.group.position.set(position[0], position[1], position[2]);
    tabBuilt.group.add(piece.group);
    tabBuilt.pieces[role] = piece;
    recomputeTabMaterials(tabBuilt);
    return tabKey;
  }

  function swapWheelPair(axle, objText) {
    if (!wheelObjs[axle + "_left"]) return null;
    for (const side of ["left", "right"]) {
      const key = axle + "_" + side;
      built.car.group.remove(wheelObjs[key]);
      const {group} = buildPartGroup(objText);
      // Ground-touching offset recomputed fresh from the new geometry's own
      // bounding box -- mirrors car.py's _ground_offset(), since a reimported
      // wheel's raw vertices aren't pre-shifted the way CAR_WHEELS' are.
      const box = new THREE.Box3().setFromObject(group);
      wheelBaseY[key] = -box.min.y;
      if (side === "left") group.scale.x = -1;  // mirror via scale, not vertex data --
                                                  // safe because every material here uses DoubleSide.
      built.car.group.add(group);
      wheelObjs[key] = group;
    }
    updateWheelPositions();
    recomputeTabMaterials(built.car);
    return "car";
  }

  // Returns the tab key that changed (so the caller can refresh the view if it's
  // the active one), or null if this part has no live destination -- most of a
  // real car's 13-21 parts don't (LOD1-7, Needle.mod, unused wheel LODs), and for
  // those the Parts-drawer preview is the only place a reimport can show up.
  // The exterior sub-part slot names (<prefix>b/s.mod), computed from the body so
  // ADDING a sub-part the car didn't ship (an empty slot) still lands in the Car
  // group live -- swapTabPiece already adds when the role is empty; this just lets
  // applyLiveReimport recognise the new member and claim the role for it.
  const _pfx = () => (CAR_ROLES.car.body || "").replace(/0\.mod$/i, "");
  const _isSlot = (partName, roleName, suffix) => {
    const cr = CAR_ROLES.car;
    return partName.toLowerCase() === (cr[roleName] || (_pfx() + suffix + ".mod")).toLowerCase();
  };
  function applyLiveReimport(partName, objText) {
    const cr = CAR_ROLES.car;
    let changedTab = null;
    if (partName === cr.body) changedTab = swapTabPiece("car", "body", objText);
    else if (_isSlot(partName, "sub_b", "b")) { changedTab = swapTabPiece("car", "sub_b", objText); cr.sub_b = partName; }
    else if (_isSlot(partName, "sub_s", "s")) { changedTab = swapTabPiece("car", "sub_s", objText); cr.sub_s = partName; }
    else if (cr.front_wheel && partName === cr.front_wheel) changedTab = swapWheelPair("front", objText);
    else if (cr.rear_wheel && partName === cr.rear_wheel) changedTab = swapWheelPair("rear", objText);
    else if (CAR_ROLES.cockpit && partName === CAR_ROLES.cockpit.dash) changedTab = swapTabPiece("cockpit", "dash", objText);
    else if (CAR_ROLES.cockpit && partName === CAR_ROLES.cockpit.wheel) {
      changedTab = swapTabPiece("cockpit", "wheel", objText, CAR_ROLES.cockpit.wheel_pos);
    } else if (CAR_ROLES.hornball && partName === CAR_ROLES.hornball) {
      changedTab = swapTabPiece("hornball", "ball", objText);
    }
    // Only re-fit/re-render if the changed tab is the one actually on screen --
    // a swap on a hidden tab still updates its scene graph (so switching to it
    // later shows the reimport), just doesn't need a redundant camera refit now.
    if (changedTab && changedTab === activeKey) refitAndRefresh(changedTab);
    return changedTab;
  }

  // Live counterpart to a staged removal: drop the piece from its tab group so the
  // 3D view reflects it immediately (mirrors applyLiveReimport). Structural pieces
  // (body/LODs) and shared tires are never removed here. Returns the changed tab.
  function removeTabPiece(tabKey, role) {
    const tb = built[tabKey];
    if (!tb || !tb.pieces[role]) return null;
    tb.group.remove(tb.pieces[role].group);
    delete tb.pieces[role];
    recomputeTabMaterials(tb);
    return tabKey;
  }
  function removeLivePart(partName) {
    const cr = CAR_ROLES.car;
    const lc = partName.toLowerCase();
    let changedTab = null;
    if (cr.sub_b && lc === cr.sub_b.toLowerCase()) { changedTab = removeTabPiece("car", "sub_b"); cr.sub_b = null; }
    else if (cr.sub_s && lc === cr.sub_s.toLowerCase()) { changedTab = removeTabPiece("car", "sub_s"); cr.sub_s = null; }
    else if (CAR_ROLES.cockpit && CAR_ROLES.cockpit.dash && lc === CAR_ROLES.cockpit.dash.toLowerCase()) changedTab = removeTabPiece("cockpit", "dash");
    else if (CAR_ROLES.cockpit && CAR_ROLES.cockpit.wheel && lc === CAR_ROLES.cockpit.wheel.toLowerCase()) changedTab = removeTabPiece("cockpit", "wheel");
    else if (CAR_ROLES.hornball && lc === CAR_ROLES.hornball.toLowerCase()) changedTab = removeTabPiece("hornball", "ball");
    if (changedTab && changedTab === activeKey) refitAndRefresh(changedTab);
    return changedTab;
  }

  // Hovering a part row tints its mesh in the live view (emissive glow), so you
  // can see which piece a row is. Only parts rendered in the CURRENT tab have a
  // target -- hovering an off-tab or empty slot is a no-op. Materials are fresh
  // per piece (buildPartGroup), so the tint is local; the animate() loop shows it.
  function partHighlightTargets(member) {
    const tab = built[activeKey];
    if (!tab) return [];
    const cr = CAR_ROLES.car, lc = String(member).toLowerCase();
    const grp = role => (tab.pieces && tab.pieces[role]) ? [tab.pieces[role].group] : [];
    if (activeKey === "car") {
      if (cr.body && lc === cr.body.toLowerCase()) return grp("body");
      if (cr.sub_b && lc === cr.sub_b.toLowerCase()) return grp("sub_b");
      if (cr.sub_s && lc === cr.sub_s.toLowerCase()) return grp("sub_s");
      if (/^f?wheel_\d+\.mod$/i.test(member)) return Object.values(wheelObjs);  // all 4 corners
    } else if (activeKey === "cockpit" && CAR_ROLES.cockpit) {
      const ck = CAR_ROLES.cockpit;
      if (ck.dash && lc === ck.dash.toLowerCase()) return grp("dash");
      if (ck.wheel && lc === ck.wheel.toLowerCase()) return grp("wheel");
      if (ck.needle && lc === ck.needle.toLowerCase()) return [...grp("needle_rpm"), ...grp("needle_mph")];
    } else if (activeKey === "hornball" && CAR_ROLES.hornball && lc === CAR_ROLES.hornball.toLowerCase()) {
      return grp("ball");
    }
    return [];
  }
  function highlightPart(member, on) {
    for (const g of partHighlightTargets(member)) g.traverse(o => {
      if (!o.isMesh || !o.material) return;
      for (const m of (Array.isArray(o.material) ? o.material : [o.material])) {
        if (!m.emissive) continue;
        if (on) {
          if (m.__origEmissive === undefined) m.__origEmissive = m.emissive.getHex();
          m.emissive.setHex(0x2a4a6a);   // subtle blue glow, matching the cyan accent
        } else if (m.__origEmissive !== undefined) {
          m.emissive.setHex(m.__origEmissive);
          delete m.__origEmissive;
        }
      }
    });
  }

  // Cockpit Configs' live links -- see COCKPIT_LIVE_RECORDS' comment for which
  // records these are and why. Both read the record's raw (native, left-handed)
  // values straight from the DOM and apply the same Z negation mod.to_obj() bakes
  // into every MOD_PARTS mesh (see build_shell_html's car_roles comment) -- the
  // stored/committed value stays native, only the on-screen placement converts.
  function updateCockpitWheelLive() {
    if (!built.cockpit || !built.cockpit.pieces.wheel) return;
    const [x, y, z] = getCockpitRecordValues("wheel");
    built.cockpit.pieces.wheel.group.position.set(x, y, -z);
    if (activeKey === "cockpit") refitAndRefresh("cockpit");
  }

  // Switches (or, once already switched, keeps updating) the Cockpit tab into
  // driver's-eye mode -- pins the camera at this record's real position rather
  // than just re-aiming the orbit toward it (see cockpitEyeMode's comment for
  // why that distinction matters: an orbit-only re-aim never actually moves the
  // camera to the eye point, just changes which direction it looks from at a
  // fixed pulled-back distance).
  function updateCockpitCameraLive() {
    if (activeKey !== "cockpit") return;
    const [x, y, z] = getCockpitRecordValues("camera");
    eyePos.set(x, y, -z);
    if (!cockpitEyeMode) enterCockpitEyeMode();
    updateCam();
  }

  // Tach + speedo needle live anchor. Each needle sits at its pivot (rpm pt /
  // mph pt, Z-negated like the wheel) and rotates in the dial plane by an angle
  // interpolated from its dat record (angle@0 -> angle@max across 0 -> max value)
  // at the current preview value (the sweep sliders). The rotation axis is
  // approximated as pivot->eye (the dial faces the driver); NEEDLE_REF_OFFSET is
  // the one tuning constant for where the dat's "0 degrees" points in 3D --
  // calibrate once against viper's known dat (-196/70/7000) so idle and redline
  // land on the painted marks, then it holds for every car (same convention).
  let needleRpmValue = 0, needleMphValue = 0;
  const NEEDLE_REF_OFFSET = 0;   // degrees; tune against viper, then leave it
  function orientNeedle(piece, pivotNative, dat, value) {
    if (!piece) return;
    const px = pivotNative[0], py = pivotNative[1], pz = -pivotNative[2];  // -> scene space
    piece.group.position.set(px, py, pz);
    const a0 = dat[0], amax = dat[1], maxv = dat[2] || 1;
    const t = Math.min(Math.max(value, 0), maxv) / maxv;
    const angleDeg = a0 + t * (amax - a0) + NEEDLE_REF_OFFSET;
    const eye = CAR_ROLES.cockpit.camera_pos;
    // Axis points from the eye INTO the dial (away from the viewer): with the
    // right-hand rule that makes a positive angle sweep clockwise as the driver
    // sees it, matching the game (an eye->pivot axis pointing at the viewer swept
    // counter-clockwise -- confirmed wrong in the viewer).
    const axis = new THREE.Vector3(px - eye[0], py - eye[1], pz - eye[2]).normalize();
    piece.group.setRotationFromAxisAngle(axis, THREE.MathUtils.degToRad(angleDeg));
  }
  function updateCockpitNeedleLive() {
    if (!built.cockpit || !built.cockpit.pieces.needle_rpm) return;
    orientNeedle(built.cockpit.pieces.needle_rpm, getCockpitRecordValues("rpm pt"),
                 getCockpitRecordValues("rpm dat"), needleRpmValue);
    orientNeedle(built.cockpit.pieces.needle_mph, getCockpitRecordValues("mph pt"),
                 getCockpitRecordValues("mph dat"), needleMphValue);
    if (activeKey === "cockpit") refitAndRefresh("cockpit");
  }

  // "Focus gauges": drive the driver's-eye view to look straight at the midpoint
  // of the two gauge pivots (near face-on), so you can align the needle to the
  // painted dial while dragging the sweep sliders. Reuses eye mode (the same view
  // the game's own cockpit uses) rather than a bespoke camera.
  function focusGauges() {
    if (!CAR_ROLES.cockpit) return;
    const eye = CAR_ROLES.cockpit.camera_pos;               // already scene-space
    const rp = getCockpitRecordValues("rpm pt"), mp = getCockpitRecordValues("mph pt");
    const mid = new THREE.Vector3((rp[0]+mp[0])/2, (rp[1]+mp[1])/2, -((rp[2]+mp[2])/2));  // scene
    // Stay at the REAL driver's eye and zoom with a narrow FOV (telephoto) instead
    // of moving the camera close. Moving close viewed each dial off-axis with a
    // wide lens, so the needle (which sits physically IN FRONT of the dial face)
    // parallaxed off its face. From the eye the parallax is already negligible
    // (the default view looks right), so magnifying that same view keeps the
    // needle on its face. Scroll adjusts FOV from here; leaving eye mode resets it.
    if (!cockpitEyeMode) enterCockpitEyeMode();
    eyePos.set(eye[0], eye[1], eye[2]);
    const a = directionAngles(new THREE.Vector3(eye[0], eye[1], eye[2]), [mid.x, mid.y, mid.z]);
    if (a) { eyeAz = a.az; eyeEl = a.el; }
    camera.fov = 34;                                        // ~2x zoom, frames both dials
    camera.updateProjectionMatrix();
    updateCam();
  }

  const COCKPIT_LIVE_RECORDS = {
    wheel: updateCockpitWheelLive, camera: updateCockpitCameraLive,
    "rpm pt": updateCockpitNeedleLive, "rpm dat": updateCockpitNeedleLive,
    "mph pt": updateCockpitNeedleLive, "mph dat": updateCockpitNeedleLive,
  };

  function buildCockpitConfigsPanel() {
    const root = document.getElementById("cockpit-sections");
    if (!COCKPIT_RECORDS) {
      root.innerHTML = '<div class="empty">this car has no cockpit.tab</div>';
      return;
    }
    // Gauge-preview controls: Focus button + RPM/MPH sweep sliders. Dragging a
    // slider sweeps that needle so you can calibrate its dat record against the
    // painted dial. Shown only if the car actually has needle calibration.
    if (COCKPIT_RECORDS["rpm dat"] || COCKPIT_RECORDS["mph dat"]) {
      const rpmMax = (COCKPIT_RECORDS["rpm dat"] || [0, 0, 8000])[2] || 8000;
      const mphMax = (COCKPIT_RECORDS["mph dat"] || [0, 0, 200])[2] || 200;
      const ctl = document.createElement("div");
      ctl.className = "gauge-preview";
      ctl.innerHTML =
        '<button id="focus-gauges" type="button">Focus gauges</button>' +
        '<label>RPM <input id="sweep-rpm" type="range" min="0" max="' + rpmMax + '" value="0" step="10">' +
        '<span id="sweep-rpm-val">0</span></label>' +
        '<label>MPH <input id="sweep-mph" type="range" min="0" max="' + mphMax + '" value="0" step="1">' +
        '<span id="sweep-mph-val">0</span></label>';
      root.appendChild(ctl);
      ctl.querySelector("#sweep-rpm").addEventListener("input", e => {
        needleRpmValue = Number(e.target.value);
        document.getElementById("sweep-rpm-val").textContent = needleRpmValue;
        updateCockpitNeedleLive();
      });
      ctl.querySelector("#sweep-mph").addEventListener("input", e => {
        needleMphValue = Number(e.target.value);
        document.getElementById("sweep-mph-val").textContent = needleMphValue;
        updateCockpitNeedleLive();
      });
      ctl.querySelector("#focus-gauges").addEventListener("click", focusGauges);
    }
    Object.entries(COCKPIT_RECORDS).forEach(([name, values]) => {
      const isLive = name in COCKPIT_LIVE_RECORDS;
      const rec = document.createElement("div");
      rec.className = "cockpit-record" + (isLive ? " live" : "");
      const h3 = document.createElement("h3");
      h3.textContent = name;
      if (isLive) h3.title = COCKPIT_LIVE_TITLES[name];
      rec.appendChild(h3);
      const fieldsWrap = document.createElement("div");
      fieldsWrap.className = "cockpit-fields";
      const labels = COCKPIT_FIELD_LABELS[name] || ["a", "b", "c"];
      values.forEach((v, i) => {
        const fieldDiv = document.createElement("div");
        fieldDiv.className = "cockpit-field";
        const label = document.createElement("label");
        label.textContent = labels[i];
        const input = document.createElement("input");
        input.type = "number";
        // Position records (meters) get a fine fixed 0.001 spinner/arrow-key
        // step -- useful for nudging "camera"/"wheel" precisely while comparing
        // against updateCamReadout's 3-decimal display. "rpm dat"/"mph dat" are
        // angle/rpm/mph calibration values, a different unit where that'd be too
        // fine -- fieldStep sizes those to their own magnitude instead.
        const step = POSITION_RECORDS.has(name) ? 0.001 : fieldStep(v);
        input.step = step;
        input.value = v;
        input.dataset.record = name;
        input.dataset.index = i;
        fieldDiv.appendChild(label);
        fieldDiv.appendChild(wrapWithStepper(input, step));
        fieldsWrap.appendChild(fieldDiv);
      });
      rec.appendChild(fieldsWrap);
      root.appendChild(rec);
    });
    root.addEventListener("input", e => {
      const recordName = e.target.dataset.record;
      if (!recordName) return;
      cockpitDirtyRecords.add(recordName);
      updateCommitStatus();
      const applyLive = COCKPIT_LIVE_RECORDS[recordName];
      if (applyLive) applyLive();
    });
  }

  function resetCockpitConfigs() {
    cockpitDirtyRecords.clear();
    // [data-record] only -- #cockpit-sections also holds the gauge-sweep preview
    // sliders (#sweep-rpm/#sweep-mph), which carry no record and must be skipped
    // (reading COCKPIT_RECORDS[undefined][NaN] otherwise throws).
    document.querySelectorAll("#cockpit-sections input[data-record]").forEach(inp => {
      const name = inp.dataset.record;
      if (!COCKPIT_RECORDS[name]) return;
      inp.value = COCKPIT_RECORDS[name][Number(inp.dataset.index)];
    });
    // Re-sync every live-linked view to the values just restored -- not just the
    // wheel mesh but the driver's-eye camera too, so "Reset to default" actually
    // shows the real in-game framing again instead of leaving it stuck wherever
    // your last edit had it.
    updateCockpitWheelLive();
    updateCockpitCameraLive();
    updateCockpitNeedleLive();
    updateCommitStatus();
  }

  buildCockpitConfigsPanel();
  document.getElementById("cockpit-reset").addEventListener("click", resetCockpitConfigs);

  window.__shellDebug = {
    scene, camera, built, wheelObjs, applyLiveReimport,
    commitChanges, pendingPartEdits, pendingTextureEdits, dirtyFields,
    cockpitDirtyRecords, updateCockpitWheelLive,
  };

  const tabsNav = document.getElementById("tabs");
  tabKeys.forEach(key => {
    const btn = document.createElement("button");
    btn.textContent = TAB_LABELS[key] || key;
    btn.dataset.tab = key;
    tabsNav.appendChild(btn);
  });

  let az = 0.7, el = 0.22, center = new THREE.Vector3(), radius = 5;
  // Cockpit "driver's-eye" mode -- pins the camera at cockpit.tab's real eye
  // position (the "camera" record) instead of orbiting an object; eyeAz/eyeEl
  // then mean gaze yaw/pitch from that fixed point, not an orbit angle around
  // `center`. Entered automatically on editing "camera" (see
  // updateCockpitCameraLive), left via the "Back to free orbit" button or by
  // switching to another tab, where a fixed eye position stops being meaningful.
  let cockpitEyeMode = false, eyeAz = 0, eyeEl = 0;
  const eyePos = new THREE.Vector3();

  function updateCam() {
    if (cockpitEyeMode) {
      camera.position.copy(eyePos);
      const dir = new THREE.Vector3(
        Math.cos(eyeEl)*Math.sin(eyeAz), Math.sin(eyeEl), Math.cos(eyeEl)*Math.cos(eyeAz),
      );
      camera.lookAt(eyePos.clone().add(dir));
    } else {
      camera.position.set(
        center.x + radius*Math.cos(el)*Math.sin(az),
        center.y + radius*Math.sin(el),
        center.z + radius*Math.cos(el)*Math.cos(az)
      );
      camera.lookAt(center);
    }
    updateCamReadout();
  }

  // Live camera-position readout, for comparing against Cockpit Configs' "camera"
  // record by eye -- converted back to the SAME native (left-handed) convention
  // those input fields use, so in eye mode (where camera.position is exactly
  // eyePos, itself set from those fields -- see updateCockpitCameraLive) this
  // reads back the identical numbers you typed, Z sign included. That round-trip
  // is the check that the conversion is applied consistently everywhere.
  function updateCamReadout() {
    const p = camera.position;
    document.getElementById("cam-readout").textContent =
      `viewer camera (native xyz, compare to "camera" fields)\n` +
      `x ${p.x.toFixed(3)}  y ${p.y.toFixed(3)}  z ${(-p.z).toFixed(3)}` +
      (cockpitEyeMode ? `\nfov ${camera.fov.toFixed(0)}°` : "");
  }

  // Real anchor points (not fixed cameras by default -- see cockpitEyeMode for
  // the opt-in exception) for which DIRECTION a tab's free orbit should default
  // to starting from, on its first visit only. Without this, Cockpit's generic
  // default angle (same one every tab uses) can end up looking through the
  // dash's own visor/overhang edge-on, occluding the wheel even though the
  // wheel's own position is correct -- confirmed by comparing against
  // cockpit.tab's real "camera" eye position directly.
  const TAB_DEFAULT_DIRECTIONS = {
    cockpit: CAR_ROLES.cockpit ? CAR_ROLES.cockpit.camera_pos : null,
  };
  const visitedTabs = new Set();

  // The az/el (yaw/pitch) that looking from `from` toward `to` works out to --
  // shared by snapOrbitToward (orbit angle around `center`) and
  // updateCockpitCameraLive (gaze angle from a fixed eyePos). Both points must
  // already be in scene space (Z-negated relative to cockpit.tab's native
  // left-handed values -- see the car_roles comment in build_shell_html).
  // Returns null for a degenerate (coincident) pair.
  function directionAngles(from, to) {
    const dir = new THREE.Vector3(to[0], to[1], to[2]).sub(from);
    const horiz = Math.sqrt(dir.x * dir.x + dir.z * dir.z);
    if (horiz <= 1e-6 && Math.abs(dir.y) <= 1e-6) return null;
    return {
      az: Math.atan2(dir.x, dir.z),
      el: Math.max(-1.4, Math.min(1.4, Math.atan2(dir.y, horiz))),
    };
  }

  // Points the free-orbit view (az/el) at `center` from `anchor`'s direction --
  // used for refitAndRefresh's first-visit default angle. Doesn't touch radius,
  // so drag-to-orbit still works normally afterward, just starting from here.
  function snapOrbitToward(anchor) {
    if (!anchor) return;
    const a = directionAngles(center, anchor);
    if (a) { az = a.az; el = a.el; }
  }

  const ORBIT_FOV = 45;
  // The game's own cockpit view is visibly wider than this tool's default 3D-
  // inspection FOV -- confirmed by comparing a viewer screenshot against a real
  // in-game one at the same (correct) eye position: the game shows several more
  // dash gauges in the same frame width, the signature of a wider lens, not a
  // position error. Not the real number (that's not stored anywhere this tool
  // reads), just a wider starting point -- scroll (see the wheel listener) to
  // dial it in further; updateCamReadout shows the live value while you do.
  const EYE_MODE_FOV = 75;

  function enterCockpitEyeMode() {
    cockpitEyeMode = true;
    camera.fov = EYE_MODE_FOV;
    camera.updateProjectionMatrix();
    // "Straight ahead" -- NOT aimed exactly at the wheel hub: on viper.car the
    // hub sits ~8cm off the eye's own X (eye x=-0.408, wheel x=-0.491), which
    // biases a direct aim by several degrees at this distance -- confirmed by
    // comparing a viewer screenshot against a real in-game one, and measured
    // directly (~7.4 deg) by checking this car's own numbers. (An earlier attempt
    // to fix this by assuming the Car tab's +Z-is-front convention applied here
    // too was wrong -- confirmed by it pointing the camera at nothing -- because
    // that axis belongs to a synthetic frame built from wheelbase spacing, with
    // no relation to this dash/wheel mesh's own local origin.) Instead: use only
    // *which* pure Z half the wheel is on relative to the eye (dash and wheel
    // agree on this, checked directly), discarding the hub's own X entirely.
    if (built.cockpit && built.cockpit.pieces.wheel) {
      eyeAz = (built.cockpit.pieces.wheel.group.position.z - eyePos.z) >= 0 ? 0 : Math.PI;
    }
    eyeEl = 0;
    document.getElementById("hint").style.display = "none";
    document.getElementById("eye-mode-bar").style.display = "flex";
  }

  function exitCockpitEyeMode() {
    if (!cockpitEyeMode) return;
    cockpitEyeMode = false;
    camera.fov = ORBIT_FOV;
    camera.updateProjectionMatrix();
    document.getElementById("hint").style.display = "block";
    document.getElementById("eye-mode-bar").style.display = "none";
    updateCam();
  }

  // Re-fits the camera to whatever's currently in view and refreshes the Textures
  // drawer -- shared by tab switches and by a live reimport landing on the tab
  // that's already active (where the scene graph changed under the camera).
  function refitAndRefresh(key) {
    const box = new THREE.Box3().setFromObject(built[key].group);
    center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    radius = Math.max(size.x, size.y, size.z) * 2.3 || 5;
    if (!visitedTabs.has(key)) {
      visitedTabs.add(key);
      snapOrbitToward(TAB_DEFAULT_DIRECTIONS[key]);
    }
    updateCam();
    buildTextureDrawer(built[key].meshesByMaterial);
  }

  let activeKey = null;
  updateCockpitNeedleLive();   // initial needle orientation (pieces positioned at build)
  let modMode = false;

  // Mutually exclusive drawers -- opening one closes whichever other is open.
  // "Configs" is CONTEXTUAL: it opens Car Configs (.cf stats) on the Car tab and
  // Cockpit Configs (cockpit.tab) on the Cockpit tab -- one button instead of two.
  // Textures/Parts/Sound each own their button. All are Mod-mode-only (CSS).
  const configsBtn = document.getElementById("configs-btn");
  const allDrawers = ["stats-drawer", "cockpit-configs-drawer", "textures-drawer",
                      "parts-drawer", "sound-drawer"].map(id => document.getElementById(id));
  function activeConfigDrawer() {
    return activeKey === "cockpit" ? document.getElementById("cockpit-configs-drawer")
         : activeKey === "car"     ? document.getElementById("stats-drawer") : null;
  }
  const drawerButtons = [
    {btn: configsBtn, get: activeConfigDrawer},
    {btn: document.getElementById("textures-btn"), get: () => document.getElementById("textures-drawer")},
    {btn: document.getElementById("parts-btn"),    get: () => document.getElementById("parts-drawer")},
    {btn: document.getElementById("sound-btn"),     get: () => document.getElementById("sound-drawer")},
  ];
  function closeAllDrawers() {
    allDrawers.forEach(d => d.classList.remove("open"));
    drawerButtons.forEach(({btn}) => btn.classList.remove("active"));
  }
  drawerButtons.forEach(({btn, get}) => {
    btn.addEventListener("click", () => {
      const drawer = get();
      if (!drawer) return;
      const opening = !drawer.classList.contains("open");
      closeAllDrawers();
      drawer.classList.toggle("open", opening);
      btn.classList.toggle("active", opening);
    });
  });

  // Configs shows only in Mod mode on the Car/Cockpit tabs (nothing to configure
  // on Horn Ball). If it was open, switching Car<->Cockpit keeps it open and
  // swaps to the right panel; switching to Horn Ball just closes it.
  function updateConfigButtonsVisibility() {
    const show = modMode && (activeKey === "car" || activeKey === "cockpit");
    configsBtn.style.display = show ? "" : "none";
    const wasActive = configsBtn.classList.contains("active");
    document.getElementById("stats-drawer").classList.remove("open");
    document.getElementById("cockpit-configs-drawer").classList.remove("open");
    configsBtn.classList.remove("active");
    if (show && wasActive) {
      const d = activeConfigDrawer();
      if (d) { d.classList.add("open"); configsBtn.classList.add("active"); }
    }
  }

  // Mod mode's Cockpit tab opens straight into driver's-eye view at cockpit.tab's
  // real stored eye position, instead of free orbit -- that position is exactly
  // what the "camera" record holds, so landing on it already showing that view
  // (rather than requiring an edit first) is the more useful default while
  // modding. Re-locks every time the conditions become true, even if "Back to
  // free orbit" was used before -- View mode still gets free orbit (no Cockpit
  // Configs there to edit "camera" from anyway). Called both from setActiveTab
  // (switching TO Cockpit while already in Mod mode) and from the "Mod it!"
  // toggle (turning Mod mode on while already sitting on the Cockpit tab, which
  // a tab switch never happens for, so setActiveTab alone used to miss it).
  function lockCockpitEyeViewIfApplicable() {
    if (activeKey === "cockpit" && modMode && CAR_ROLES.cockpit && CAR_ROLES.cockpit.camera_pos) {
      eyePos.set(...CAR_ROLES.cockpit.camera_pos);
      enterCockpitEyeMode();
    }
  }

  function setActiveTab(key) {
    if (activeKey === key) return;
    if (key !== "cockpit") exitCockpitEyeMode();  // a fixed eye position only means anything on Cockpit's own scene
    if (activeKey) scene.remove(built[activeKey].group);
    activeKey = key;
    scene.add(built[key].group);
    tabsNav.querySelectorAll("button").forEach(b => b.classList.toggle("active", b.dataset.tab === key));
    lockCockpitEyeViewIfApplicable();
    refitAndRefresh(key);
    updateConfigButtonsVisibility();
    updatePartsHighlight(key);
    applyPartsFilter();   // the filtered list follows the active tab
  }
  tabsNav.addEventListener("click", e => {
    if (e.target.dataset.tab) setActiveTab(e.target.dataset.tab);
  });
  setActiveTab(tabKeys[0]);

  buildStatsPanel();
  const nameInput = document.getElementById("car-name-input");
  if (nameInput) {
    nameInput.value = CAR_NAME;
    nameInput.addEventListener("input", updateCommitStatus);
  }
  document.getElementById("export").addEventListener("click", exportTxt);
  document.getElementById("reset-stats").addEventListener("click", resetStats);
  document.getElementById("commit-btn").addEventListener("click", commitChanges);

  // Global "Discard all" -- the counterpart to Save. Composes the per-domain
  // reverts (stats, cockpit, parts, textures, sounds) so one click returns the
  // whole tool to the car as saved on disk. Per-item ↺ stays for surgical undo;
  // this is the "start over" escape hatch, so it confirms first.
  function discardAllChanges() {
    if (!confirm("Discard ALL staged changes and return to the car as saved on disk?")) return;
    resetStats();                                  // stat inputs -> STATS, clears dirtyFields
    resetCockpitConfigs();                         // cockpit inputs -> cockpit, clears cockpitDirtyRecords
    // Parts: undo staged edits/adds and removals live.
    for (const m of Object.keys(pendingPartEdits)) {
      if (m in MOD_PARTS) applyLiveReimport(m, MOD_PARTS[m]);   // undo an edit to an existing part
      else removeLivePart(m);                                    // undo an added slot
      delete pendingPartEdits[m];
    }
    for (const m of Array.from(pendingPartRemovals)) applyLiveReimport(m, MOD_PARTS[m]);  // put removed parts back
    pendingPartRemovals.clear();
    for (const k of Object.keys(importedTexturesByPart)) delete importedTexturesByPart[k];
    // Textures: restore each staged material's pre-import value and re-apply to
    // every built tab's meshes that use it.
    const revertedMats = Object.keys(pendingTextureEdits);
    for (const name of revertedMats) {
      if (name in originalTextures) {
        const orig = originalTextures[name];
        if (orig === undefined) delete TEXTURES[name]; else TEXTURES[name] = orig;
      }
      delete pendingTextureEdits[name];
      delete originalTextures[name];
    }
    for (const key of Object.keys(built)) {
      const mbm = built[key].meshesByMaterial || {};
      for (const name of revertedMats) {
        const meshes = mbm[name];
        if (!meshes) continue;
        const t = TEXTURES[name] ? loadTexture(TEXTURES[name]) : null;
        meshes.forEach(m => { m.material.map = t; m.material.needsUpdate = true; });
      }
    }
    for (const k of Object.keys(pendingSfxEdits)) delete pendingSfxEdits[k];  // sounds
    if (rebuildPartsDrawer) rebuildPartsDrawer();
    if (rebuildTextureDrawer) rebuildTextureDrawer();
    buildSoundDrawer();
    updateCommitStatus();
    const s = document.getElementById("commit-status");
    if (s) { s.className = "pending"; s.textContent = "Discarded all staged changes — back to the saved car."; }
  }
  // ⋯ overflow menu (Discard all / Restore original). Toggle on click, close on
  // an outside click or after choosing an item.
  const moreBtn = document.getElementById("more-btn");
  const moreMenu = document.getElementById("more-menu");
  function closeMoreMenu() { moreMenu.hidden = true; moreBtn.setAttribute("aria-expanded", "false"); }
  moreBtn.addEventListener("click", e => {
    e.stopPropagation();
    const open = moreMenu.hidden;
    moreMenu.hidden = !open;
    moreBtn.setAttribute("aria-expanded", String(open));
  });
  moreMenu.addEventListener("click", e => e.stopPropagation());
  document.addEventListener("click", closeMoreMenu);

  document.getElementById("discard-btn").addEventListener("click", () => { closeMoreMenu(); discardAllChanges(); });

  // Restore original: revert the car ON DISK to its pristine pre-edit backup,
  // then reload so the whole tool rebuilds from the restored car. Discards saved
  // changes too (not just staged ones), so it confirms first.
  document.getElementById("restore-btn").addEventListener("click", async () => {
    closeMoreMenu();
    if (!confirm("Restore this car to its ORIGINAL (pre-edit) state?\n\nThis reverts the file on disk to its first backup, discarding ALL changes you've saved, and reloads.")) return;
    const s = document.getElementById("commit-status");
    s.className = "pending"; s.style.display = "block"; s.textContent = "Restoring original…";
    try {
      const resp = await fetch(COMMIT_ROUTE, {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({car_path: CAR_PATH, action: "restore"}),
      });
      const r = await resp.json();
      if (r.ok) {
        s.className = "ok";
        s.textContent = "Restored from " + r.backup_path + " — reloading…";
        setTimeout(() => location.reload(), 800);
      } else {
        s.className = "error"; s.textContent = "Restore failed: " + r.error;
      }
    } catch (e) {
      s.className = "error"; s.textContent = "Restore failed: " + (e && e.message ? e.message : e);
    }
  });
  updateCommitStatus();

  getActiveKey = () => activeKey;  // lets a Save-triggered rebuild re-highlight the in-view slot
  rebuildTextureDrawer = () => { if (activeKey && built[activeKey]) buildTextureDrawer(built[activeKey].meshesByMaterial); };
  buildPartsDrawer(applyLiveReimport, removeLivePart, highlightPart);  // each row's own Import/Remove drives the live mesh
  updatePartsHighlight(activeKey);  // setActiveTab's own call ran before these rows existed

  // Filter toggle: default shows only what's on the car; click to reveal every
  // addable slot (empty per-car slots + all overridable shared assets).
  const filterBtn = document.getElementById("parts-filter-btn");
  if (filterBtn) filterBtn.addEventListener("click", () => {
    partsFilterOn = !partsFilterOn;
    filterBtn.classList.toggle("active", partsFilterOn);
    filterBtn.setAttribute("aria-pressed", String(partsFilterOn));
    filterBtn.title = partsFilterOn
      ? "Showing parts in this view — click to show all slots"
      : "Showing all slots — click to show only this view's parts";
    applyPartsFilter();
  });
  buildSoundDrawer();

  // "Mod it!" -- a page-wide mode toggle, not a drawer: reveals the Car Configs/
  // Cockpit Configs/Textures/Parts drawer buttons (see updateConfigButtonsVisibility
  // for the tab-scoping) -- real filenames (a material's, or a .mod part's) and raw
  // stat fields are only actually useful once you're about to act on them via
  // modretex/obj2mod/txt2cf, not for casual viewing.
  const modToggle = document.getElementById("mod-toggle");
  modToggle.addEventListener("click", () => {
    modMode = !modMode;
    document.body.classList.toggle("mod-mode", modMode);
    modToggle.textContent = modMode ? "‹ Back to viewing" : "Mod it! ✎";
    updateConfigButtonsVisibility();
    if (!modMode) {
      // Textures'/Parts' trigger buttons are about to disappear -- don't leave
      // either drawer stranded open with no way to close it, or a driver's-eye
      // view active with no Cockpit Configs drawer open to get back out of it.
      closeAllDrawers();
      exitCockpitEyeMode();
    } else {
      // Unlike setActiveTab, nothing else here calls refitAndRefresh/updateCam()
      // -- enterCockpitEyeMode() only sets state (eyePos/eyeAz/eyeEl/fov), it
      // doesn't move the actual THREE.js camera itself, so this needs its own
      // explicit render update or the view wouldn't visibly snap until some
      // unrelated action (a drag, a tab switch) happened to call updateCam() next.
      lockCockpitEyeViewIfApplicable();
      updateCam();
      // Mod mode opens the Configs/Textures/Parts drawers down the side, so
      // claim the full window on the way IN -- matching drive mode in the track
      // viewer. One-way: leaving Mod keeps the width. Guarded so an already-wide
      // pane isn't disturbed; the canvas refits on the iframe's own resize.
      if(HOST && !HOST.isExpanded()){
        HOST.setExpanded(true);
        const eb = document.getElementById("expand-btn");
        if(eb) eb.textContent = "⇲ Show library";
      }
    }
  });
  document.getElementById("exit-eye-mode").addEventListener("click", exitCockpitEyeMode);

  let isDown = false, lastX = 0, lastY = 0;
  renderer.domElement.addEventListener("mousedown", e => { isDown = true; lastX = e.clientX; lastY = e.clientY; });
  window.addEventListener("mouseup", () => isDown = false);
  window.addEventListener("mousemove", e => {
    if (!isDown) return;
    if (cockpitEyeMode) {
      eyeAz += (e.clientX - lastX) * 0.01;
      eyeEl = Math.max(-1.4, Math.min(1.4, eyeEl + (e.clientY - lastY) * 0.01));
    } else {
      az += (e.clientX - lastX) * 0.01;
      el = Math.max(-1.4, Math.min(1.4, el + (e.clientY - lastY) * 0.01));
    }
    lastX = e.clientX; lastY = e.clientY;
    updateCam();
  });
  // Zoom -- orbit mode dollies (changes radius, same object-inspection framing
  // otherwise); eye mode narrows/widens the lens (FOV) instead of moving the
  // camera, so it stays exactly at the eye position being tested against the
  // "camera" record (see updateCamReadout) rather than drifting off it.
  renderer.domElement.addEventListener("wheel", e => {
    e.preventDefault();
    if (cockpitEyeMode) {
      camera.fov = Math.max(10, Math.min(100, camera.fov + e.deltaY * 0.05));
      camera.updateProjectionMatrix();
    } else {
      radius = Math.max(0.05, radius * (1 + e.deltaY * 0.001));
    }
    updateCam();
  }, {passive: false});
  window.addEventListener("resize", () => {
    camera.aspect = W()/H();
    camera.updateProjectionMatrix();
    renderer.setSize(W(), H());
  });

  function animate(){ requestAnimationFrame(animate); renderer.render(scene, camera); }
  animate();
}
window.addEventListener("load", main);
</script>
</body></html>
"""


def build_shell_html(
    car_path: str | Path, paint_dir: str | Path | None = None, title: str | None = None,
    view_only: bool = False,
) -> str:
    """The integrated mod-tool shell: a Car/Cockpit/Horn Ball tab strip over one 3D
    view, with drawers (Car Configs, Cockpit Configs, Textures, Parts, Sound) as
    slide-outs rather than persistent panels (mutually exclusive -- opening one
    closes another). Single self-contained HTML file -- every tab's meshes/
    textures/sounds are embedded up front and switched client-side by toggling
    which THREE.Group is in the scene.

    Defaults to View mode: just the 3D tab strip, no Car Configs/Cockpit
    Configs/Textures/Parts/Sound/Save button at all -- the real spec numbers are
    already visible in-game (the "garage" spec sheet), so this view is for looking
    at the car, not its stat block. Clicking "Mod it!" reveals Car Configs
    (editable inputs, wheelbase/ftrack/rtrack move the wheels live) plus Export/
    Reset, Cockpit Configs (only on the Cockpit tab -- cockpit.tab's 6 records;
    "wheel" moves the steering wheel live, "camera" switches the Cockpit tab into
    a driver's-eye view live from that stored position -- which is also what
    clicking the Cockpit tab opens into automatically while in Mod mode, see
    setActiveTab/enterCockpitEyeMode -- the other 4 records have no on-screen
    anchor yet), Textures (export or live-preview-reimport a TGA on the active
    tab's meshes), Parts (every real .mod file in the car's own archive, plus the
    shared default ball.mod when the car doesn't own its own -- see
    SHARED_PART_NAMES -- export or live-preview-reimport an OBJ, updating the
    actual Car/Cockpit/Horn Ball view wherever CAR_ROLES gives it a live
    destination, the isolated preview canvas otherwise), Sound (every real .sfx
    file in the car's own archive, played directly via an embedded WAV data URI
    -- PCM only, ADPCM entries are listed but not yet playable, see sfx.py --
    and replaceable via "Import WAV", 16-bit mono PCM only), and "Save" --
    collects every pending edit and POSTs it to this server's own COMMIT_PATH
    (see cli.py's _CommitHandler/_apply_commit), which writes the edits back
    under the car's own real filename (backing up the pre-edit file first,
    never blindly overwriting) rather than to a renamed copy -- deliberate, see
    _apply_commit's own docstring for the real, in-game-crash-confirmed reasons
    a renamed car breaks. That last part only works when the page was opened via
    `--serve` specifically; everything else here is pure client-side JS and works
    from any static host.

    The Horn Ball tab is included only if a ball.mod is found -- checking the car's
    own archive first, then the shared resource archives (see car.find_shared): most
    cars use the shared race.res default, but plenty of real cars (several of the
    Mario-Kart-character conversion mods, for instance) ship their own. Either way
    it's a real Parts-drawer row (own file or shared default, labeled accordingly),
    export/live-reimport works the same for both, and committing an edit to the
    shared default creates a genuine new per-car override rather than failing.
    """
    car_path = Path(car_path)
    data_dir = car_path.parent

    # The body's real paint material can't be resolved from a car's own archive or
    # the shared ones (see car.resolve_textures's docstring) -- it's a runtime
    # placeholder the retail game swaps for a player's chosen paintN.tex. paint_dir,
    # if given, just supplies ONE such texture (paint0.tex if present) as a stand-in
    # so the body isn't flat gray; it's no longer a multi-swatch picker (an earlier
    # version of this let you click among paint0..8 to preview each -- dropped along
    # with the rest of Paint-drawer click-to-apply, see buildTextureDrawer).
    default_paint_texture = None
    if paint_dir is not None:
        candidate = Path(paint_dir) / "paint0.tex"
        if candidate.exists():
            default_paint_texture = candidate

    # assemble_car_live(), not assemble_car(): keeps the 4 wheels as their own
    # objects (chassis-local origin, X/Z not baked in) instead of one static merged
    # mesh, so the shell can reposition them live as wheelbase/ftrack/rtrack are
    # edited in the Stats drawer instead of needing a fresh Python call per edit.
    live = car.assemble_car_live(car_path)

    try:
        cockpit_result = car.assemble_cockpit(car_path)
    except ValueError:
        # Not every car has a real cockpit -- confirmed on real data: 4 of 5
        # non-Viper cars in the stock USA disc's Data/ (exotic, plane, sedan,
        # sports) have no <prefix>c.mod/<prefix>w.mod at all (likely AI-only/
        # spectator vehicles with no driver view). Omit the Cockpit tab for these,
        # same graceful-if-missing treatment Horn Ball already gets, rather than
        # failing the whole page over one missing part.
        cockpit_result = None

    entries = archive.read(car_path)
    # find_shared(), not find_in_shared_archives(): ball.mod really does get per-car
    # overrides in practice (see car.find_shared's docstring) -- checking only the
    # shared archives would silently show the wrong horn ball for a car that has
    # its own.
    ball_raw = car.find_shared(car_path, entries, "ball.mod")
    ball_mesh = mod.parse(ball_raw) if ball_raw is not None else None

    # Every real .mod entry in the car's own archive, individually -- the Parts
    # drawer's material, separate from the curated tabs above (see its docstring).
    mod_parts = _car_mod_parts(car_path)

    # Every real .sfx entry in the car's own archive, individually -- the Sound
    # drawer's material, same "one real file, unmerged" approach as mod_parts.
    sfx_parts = _car_sfx_parts(car_path)

    # One texture map for the ENTIRE page, not one per tab/part: early versions of
    # this resolved (and separately base64-embedded) textures per tab, then again
    # per wheel, then again per Parts-drawer entry -- since most parts share the
    # same handful of materials (every LOD level reuses the body's own material,
    # for instance), that meant the same PNG data was duplicated dozens of times
    # over. On a real 25-car folder that bloated total output from 22.8MB to
    # 68.3MB. Resolving every material name used ANYWHERE up front, once, and
    # having every consumer (tabs, wheels, Parts preview) share that single lookup
    # brought it back down -- see buildPartGroup's use of the global TEXTURES.
    all_material_names = {m.name for m in live.chassis.materials}
    if live.has_wheels:
        all_material_names |= {m.name for m in live.front_wheel_left.materials}
        all_material_names |= {m.name for m in live.rear_wheel_left.materials}
    if cockpit_result is not None:
        all_material_names |= {m.name for m in cockpit_result.mesh.materials}
    if ball_mesh is not None:
        all_material_names |= {m.name for m in ball_mesh.materials}
    for entry in mod_parts.values():
        if entry is not None:
            all_material_names |= entry[1]
    all_textures = _build_texture_map(car_path, all_material_names, paint_texture=default_paint_texture)

    # No shared wheel meshes (viewed without race.res) -> an empty wheel set; the
    # client renders the body without wheels rather than failing to build at all.
    car_wheels = {
        "front_left": mod.to_obj(live.front_wheel_left, "car.mtl")[0],
        "front_right": mod.to_obj(live.front_wheel_right, "car.mtl")[0],
        "rear_left": mod.to_obj(live.rear_wheel_left, "car.mtl")[0],
        "rear_right": mod.to_obj(live.rear_wheel_right, "car.mtl")[0],
    } if live.has_wheels else {}

    mod_parts_obj = {name: (entry[0] if entry is not None else None) for name, entry in mod_parts.items()}

    def _resolve_case(name: str | None, available: dict) -> str | None:
        # parts_found records the *queried* filename pattern (e.g. car.py builds
        # "Vipers.mod" from f"{prefix}s.mod"), which can differ in case from the
        # real archive entry it matched case-insensitively (the actual file is
        # "vipers.mod") -- MOD_PARTS keys are the real, exact-case entry names, so
        # a naive lookup would silently miss this. Confirmed on real viper.car.
        if name is None:
            return None
        for k in available:
            if k.lower() == name.lower():
                return k
        return None

    # Which MOD_PARTS entry (if any -- only ones the car actually owns, per
    # _car_mod_parts's own-archive-only scope) plugs into which live-rendered
    # role. This is what makes "reimport this real file, see it on the actual
    # car" possible: the Car/Cockpit tabs below are built from these SAME named
    # pieces (instead of one pre-merged mesh each) specifically so any one piece
    # can be swapped out live without touching its siblings -- the exact same
    # pattern the 4 wheel corners already used before this existed.
    car_roles = {
        "car": {
            "body": _resolve_case(live.parts_found.get("body"), mod_parts_obj),
            "sub_b": _resolve_case(live.parts_found.get("sub_b"), mod_parts_obj),
            "sub_s": _resolve_case(live.parts_found.get("sub_s"), mod_parts_obj),
            "front_wheel": _resolve_case(live.parts_found.get("wheel_front"), mod_parts_obj),
            "rear_wheel": _resolve_case(live.parts_found.get("wheel_rear"), mod_parts_obj),
        },
        "cockpit": None,
        "hornball": None,
    }
    if cockpit_result is not None:
        # cockpit.tab's positions are in Viper's native left-handed space, and
        # mod.to_obj() converts every mesh to right-handed by negating Z. Any
        # position used to place one of those converted meshes needs the same
        # negation, or it lands mirrored -- confirmed against real data:
        # cockpit.tab stores wheel z=-0.15, and +0.15 is where the wheel sits in
        # the dash opening once converted. Without it the driver's-eye view comes
        # out mirrored: wheel and A-pillar on the right, gauge faces reversed.
        wx, wy, wz = cockpit_result.cockpit_records["wheel"]
        # "camera" is cockpit.tab's real stored eye position for the game's own
        # static cockpit view (see cockpit_tab.py) -- not used as a fixed camera
        # here (that approach was tried and deliberately dropped in favor of free
        # orbit), but it's a good real-data anchor for which DIRECTION the free-
        # orbit view should default to starting from, since the generic default
        # angle used for every other tab can end up looking through the dash's
        # own visor/overhang edge-on and occluding the wheel. Also live-linked to
        # the "camera" field in Cockpit Configs -- see updateCockpitCameraLive.
        cx, cy, cz = cockpit_result.cockpit_records["camera"]
        # The tach/speedo needle pivots (rpm pt / mph pt) get the same Z-negation
        # as wheel/camera so Needle.mod lands correctly once mod.to_obj converts it.
        # dat records (rpm dat / mph dat = angle@0, angle@max, max) are angles, not
        # positions, so the JS reads them straight from COCKPIT_RECORDS unchanged.
        rpx, rpy, rpz = cockpit_result.cockpit_records.get("rpm pt", [0.0, 0.0, 0.0])
        mpx, mpy, mpz = cockpit_result.cockpit_records.get("mph pt", [0.0, 0.0, 0.0])
        car_roles["cockpit"] = {
            "dash": _resolve_case(cockpit_result.parts_found.get("dash"), mod_parts_obj),
            "wheel": _resolve_case(cockpit_result.parts_found.get("wheel"), mod_parts_obj),
            "wheel_pos": [wx, wy, -wz],
            "camera_pos": [cx, cy, -cz],
            # Needle.mod is a fixed shared name (see primarycar.py); one mesh,
            # instanced at both pivots for the tach and speedo.
            "needle": _resolve_case("Needle.mod", mod_parts_obj),
            "rpm_pt": [rpx, rpy, -rpz],
            "mph_pt": [mpx, mpy, -mpz],
        }
    # Horn Ball is live-reimportable either way now: an owned ball.mod plugs into
    # MOD_PARTS/car_roles like any other part; an unowned one gets its shared
    # race.res default ADDED to MOD_PARTS too (flagged in shared_part_names so the
    # Parts drawer can label it, same "(shared default)" treatment SHARED_SFX_ROLES
    # gets in the Sound drawer) rather than falling back to a separate, non-
    # reimportable embedded OBJ the way this used to work -- someone modding a car
    # that's still using the default horn ball is exactly who'd want to edit it.
    # Committing an edit to it upserts a new, real per-car override rather than
    # failing to find something to replace (see cli.py's _apply_commit, which uses
    # archive.upsert_entry for parts for exactly this reason -- the same fix
    # already made for an unowned texture).
    shared_part_names: list[str] = []
    if ball_mesh is not None:
        ball_key = _resolve_case("ball.mod", mod_parts_obj)
        if ball_key is not None:
            car_roles["hornball"] = ball_key
        else:
            mod_parts_obj["ball.mod"] = mod.to_obj(ball_mesh, "ball.mtl")[0]
            shared_part_names.append("ball.mod")
            car_roles["hornball"] = "ball.mod"

    html = _SHELL_TEMPLATE
    html = html.replace("__BODY_CLASS__", "view-only" if view_only else "")
    html = html.replace("__TITLE__", title or f"{live.prefix} mod tool")
    html = html.replace("__CAR_TITLE__", live.prefix)
    html = html.replace("__CAR_FILE__", html_escape.escape(Path(car_path).name))
    html = html.replace("__CAR_ROLES_JSON__", json.dumps(car_roles))
    html = html.replace("__CAR_PATH_JSON__", json.dumps(str(car_path)))
    html = html.replace("__CAR_WHEELS_JSON__", json.dumps(car_wheels))
    html = html.replace("__TEXTURES_JSON__", json.dumps(all_textures))
    try:
        provenance = car.texture_provenance(car_path)
    except Exception:
        provenance = {"verdict": "unknown", "own": [], "shared": [], "paint": [], "missing": []}
    html = html.replace("__PROVENANCE_JSON__", json.dumps(provenance))
    html = html.replace("__STATS_JSON__", json.dumps(live.stats))
    html = html.replace("__CAR_NAME_JSON__", json.dumps(car.read_car_name(entries) or ""))
    html = html.replace("__SECTIONS_JSON__", json.dumps(_SECTIONS))
    html = html.replace("__STOCK_RANGES_JSON__", json.dumps(STOCK_STAT_RANGES))
    html = html.replace("__MOD_PARTS_JSON__", json.dumps(mod_parts_obj))
    html = html.replace("__SHARED_PART_NAMES_JSON__", json.dumps(shared_part_names))
    html = html.replace("__SFX_PARTS_JSON__", json.dumps(sfx_parts))
    html = html.replace(
        "__COCKPIT_RECORDS_JSON__",
        json.dumps(cockpit_result.cockpit_records if cockpit_result is not None else None),
    )
    return html


def write_shell_html(
    car_path: str | Path, out_path: str | Path,
    paint_dir: str | Path | None = None, title: str | None = None,
) -> None:
    html = build_shell_html(car_path, paint_dir=paint_dir, title=title)
    Path(out_path).write_text(html, encoding="utf-8")


_TRACK_TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>__TITLE__</title>
<style>
  html,body{margin:0;height:100%;background:#1a1a1a;font-family:system-ui,sans-serif;overflow:hidden}
  /* The drawer is closed by default so the 3D view gets the whole window --
     it is what you came for, and this page is often embedded in a pane much
     narrower than a full browser window (see switcher_ui). Opening it is the
     same "Mod it!" gesture the car shell uses, so both views behave alike. */
  #canvas-wrap{position:absolute;top:0;left:0;right:0;bottom:0;transition:right .18s ease}
  body.modding #canvas-wrap{right:320px}
  #panel{display:none}
  body.modding #panel{display:block}
  /* View-only (public gallery): no "Mod it!" (so the Textures panel and its
     Save are unreachable) and no "Save menu picture" writes. */
  body.view-only #mod-btn,body.view-only #shot-btn,body.view-only #shot-btn2{display:none!important}
  #corner{position:absolute;top:14px;right:16px;z-index:6;display:flex;gap:8px;
    transition:right .18s ease}
  body.modding #corner{right:336px}
  #corner button{background:#2a2f3a;color:#e8eaf2;border:1px solid #3a4150;
    border-radius:6px;padding:6px 12px;font:inherit;font-size:.78rem;cursor:pointer}
  #corner button:hover{background:#333a47;border-color:#4a5566}
  #corner button[hidden]{display:none}
  /* Controls the mod-manager host offers itself. Hidden only when embedded --
     a standalone page from `vrmod trackview` still needs every one of them. */
  body.embedded .host-dup{display:none}
  #label{position:absolute;top:16px;left:16px;color:#e8eaf2;font-size:1.1rem;font-weight:600;
    line-height:1.25;text-shadow:0 1px 3px rgba(0,0,0,.55)}
  #label .file{display:block;color:#aeb4c6;font-size:.75rem;font-weight:400;
    font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
  /* This sits over whatever the camera happens to be pointing at -- bright sky
     as often as dark terrain -- so it carries its own ground rather than
     relying on a colour that only works against one of them. */
  #hint{position:absolute;bottom:16px;left:74px;color:#c9cedd;font-size:.75rem;
    background:rgba(14,16,21,.72);border:1px solid rgba(255,255,255,.07);
    border-radius:6px;padding:5px 10px;max-width:calc(100% - 90px);
    backdrop-filter:blur(3px)}
  #hint button, #drivebar button{background:#2a2f3a;color:#e6e8ec;border:1px solid #3a4150;
    border-radius:5px;padding:3px 9px;font:inherit;font-size:.75rem;cursor:pointer}
  #hint button:hover, #drivebar button:hover:not(:disabled){background:#333a47;border-color:#4a5364}
  #hint button:disabled{opacity:.4;cursor:default}
  /* A single round control instead of a full-width bar: at a narrow pane the
     old bar ran off both edges. The wheel opens a fixed-size square panel, so
     the controls stay put whatever the viewport does. */
  #wheel-btn{position:absolute;left:16px;bottom:16px;width:46px;height:46px;
    border-radius:50%;display:flex;align-items:center;justify-content:center;
    background:rgba(20,22,28,.9);border:1px solid #3a4150;color:#e6e8ec;
    cursor:pointer;z-index:7;backdrop-filter:blur(3px);padding:0}
  #wheel-btn:hover{background:#2a2f3a;border-color:#5aa9e6}
  #wheel-btn.on{background:#5aa9e6;border-color:#5aa9e6;color:#0d1620}
  #wheel-btn svg{width:26px;height:26px}
  #drivebar{position:absolute;left:16px;bottom:74px;width:236px;
    display:grid;gap:9px;z-index:7;padding:12px;border-radius:10px;
    background:rgba(20,22,28,.92);border:1px solid #333a47;color:#e6e8ec;
    font-size:.75rem;backdrop-filter:blur(4px)}
  /* Author display:grid on an id outranks the UA stylesheet's [hidden] rule
     regardless of specificity, so this is what actually hides the panel. */
  #drivebar[hidden]{display:none}
  /* Top-left, under the track name: the right side of the window is taken by
     the Textures panel, which would hide it. */
  /* Bottom right: the drive controls own the bottom left, and the top is where
     the title and the corner tools live. */
  #minimap{position:absolute;right:16px;bottom:16px;border:1px solid #333a47;
    border-radius:8px;background:rgba(12,14,18,.82);backdrop-filter:blur(3px)}
  #minimap[hidden]{display:none}
  #drivebar button.primary{background:#5aa9e6;border-color:#5aa9e6;color:#0d1620;font-weight:600}
  #drivebar button.primary:hover{background:#6fb6ea}
  #scrub{width:230px;accent-color:#5aa9e6;cursor:pointer}
  #drive-readout{font-variant-numeric:tabular-nums;text-align:center;color:#c9cedd;
    font-size:.75rem}
  #drivebar select{background:#2a2f3a;color:#e6e8ec;border:1px solid #3a4150;
    border-radius:5px;padding:2px 4px;font:inherit;font-size:.75rem;width:100%}
  #drivebar label{display:grid;gap:3px;font-size:.7rem;color:#9aa1ad}
  #drivebar .row{display:flex;gap:8px;align-items:center}
  #drivebar .row > *{flex:1}
  #drivebar #scrub{width:100%}
  #drivebar #play-btn{flex:none;min-width:62px}
  #fatal-error{position:absolute;top:0;left:0;right:320px;padding:16px;background:#3a1414;
               color:#ffd9d9;font-family:monospace;font-size:.85rem;white-space:pre-wrap;
               z-index:10;display:none}
  #panel{position:absolute;top:0;right:0;width:320px;height:100%;background:#20242c;color:#e8eaf2;
         box-sizing:border-box;padding:16px;overflow-y:auto;border-left:1px solid #333}
  #panel h2{margin:0 0 4px;font-size:1.1rem}
  #panel .hint{font-size:.75rem;color:#8a90a4;margin-bottom:14px}
  #texture-list{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  /* The sky is a 4:1 strip, so its swatch spans both columns -- squeezed into
     one it is illegible and the caption wraps to four lines. */
  .swatch.wide{grid-column:1 / -1}
  .swatch.wide img{aspect-ratio:4 / 1;object-fit:cover;width:100%}
  .swatch .sub{font-size:.65rem;color:#8a90a4;margin-top:2px}
  .swatch{background:#14161c;border:1px solid #3a3f4e;border-radius:6px;padding:8px;text-align:center}
  .swatch.pending{border-color:#e0a83a}
  .swatch img{width:100%;height:64px;object-fit:contain;background:#0a0b0e;border-radius:4px}
  .swatch .missing{width:100%;height:64px;display:flex;align-items:center;justify-content:center;
                    background:#0a0b0e;border-radius:4px;color:#666;font-size:.65rem}
  .swatch .name{font-size:.68rem;color:#c4c8d8;margin:6px 0;word-break:break-all}
  .swatch-actions{display:flex;flex-direction:row-reverse;margin-top:4px;border-top:1px solid #2a2e3a}
  .swatch-export,.swatch-import{flex:1;text-align:center;cursor:pointer;font-size:.7rem;
                  padding:5px 4px;box-sizing:border-box}
  .swatch-export{background:#14161c;color:#c5cbd8;border-left:1px solid #2a2e3a}
  .swatch-export:hover{background:#2a2f3a}
  .swatch-import{background:#1c1f4a;color:#8ecfff}
  .swatch-import:hover{background:#252a5c}
  .swatch-import input{display:none}
  #commit-bar{position:sticky;bottom:0;background:#20242c;padding-top:12px;margin-top:14px;
              border-top:1px solid #333}
  #commit-btn{width:100%;padding:10px;background:#3a6fa0;color:#fff;border:none;border-radius:6px;
              font-size:.85rem;cursor:pointer}
  #commit-btn:disabled{background:#3a3f4e;color:#777;cursor:default}
  #commit-status{font-size:.72rem;margin-top:8px;color:#8a90a4}
  #commit-status.ok{color:#7fd67f}
  #commit-status.error{color:#e08a8a}
  #commit-status.pending{color:#e0c87a}
</style>
<script>
  window.addEventListener("error", (e) => {
    const el = document.getElementById("fatal-error");
    el.style.display = "block";
    el.textContent += "ERROR: " + (e.error ? (e.error.stack || e.error.message) : e.message) + "\n";
  });
</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head><body class="__BODY_CLASS__">
<div id="canvas-wrap"></div>
<div id="corner">
  <!-- Sizing and driving are things you do to the VIEW, so they live on the
       view. #expand-btn only appears when embedded, since standalone there is
       nothing to expand into. -->
  <button id="expand-btn" type="button" hidden></button>
  <button id="mod-btn" type="button">Mod it! &#9998;</button>
</div>
<div id="fatal-error"></div>
<div id="label">__TITLE__<span class="file">__TRACK_FILE__</span></div>
<div id="hint">Drag to orbit &middot; right-drag (or shift-drag) to pan &middot; scroll to zoom &middot; R to reset
  <span class="host-dup"> &middot; <button id="shot-btn" type="button">Save menu picture</button></span> <span id="lap-info"></span> <span id="shot-status"></span></div>
<canvas id="minimap" width="190" height="150" hidden></canvas>
<!-- Steering wheel: opens drive view, and toggles the control panel once in
     it. One 46px control instead of a bar that overflowed a narrow pane. -->
<button id="wheel-btn" type="button" title="Drive this track" hidden>
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
    <circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.6"/>
    <path d="M12 3v6.4M4.2 16.5l5.6-3.2M19.8 16.5l-5.6-3.2"/>
  </svg>
</button>
<div id="drivebar" hidden>
  <div id="drive-readout"></div>
  <input id="scrub" type="range" min="0" max="1000" value="0" step="1" aria-label="Position on lap">
  <div class="row">
    <button id="play-btn" type="button" class="primary">Pause</button>
    <label>Speed
      <select id="speed-sel">
        <option value="0.25">0.25&times;</option>
        <option value="0.5">0.5&times;</option>
        <option value="1" selected>1&times;</option>
        <option value="2">2&times;</option>
        <option value="4">4&times;</option>
      </select>
    </label>
  </div>
  <label>Direction
    <select id="dir-sel">
      <option value="forward" selected>Forward</option>
      <option value="reverse">Reverse</option>
    </select>
  </label>
  <div class="row">
    <button id="shot-btn2" class="host-dup" type="button">Save picture</button>
    <button id="exit-btn" type="button">Track view</button>
  </div>
</div>
<div id="panel">
  <h2>Textures</h2>
  <div class="hint">Export a texture as .tga to edit in an image editor, or import a .tga to preview a swap live on the track, then Save to write it back into the .trk (backs up the original first).</div>
  <div id="texture-list"></div>
  <div id="commit-bar">
    <button id="commit-btn" disabled>Save (backs up original)</button>
    <div id="commit-status"></div>
  </div>
</div>
<script>
const OBJ_TEXT = __OBJ_JSON__;
const TEXTURES = __TEXTURES_JSON__;
const TEXTURE_WRAPS = __TEXTURE_WRAPS_JSON__;
const SKY_URI = __SKY_URI_JSON__;
const TRACK_MI = __TRACK_MI_JSON__;   // length the game itself reports, in miles
const PATHS = __PATHS_JSON__;  // {forward:{points,speeds}, reverse:{...}}, or null   // sky1-4.tex composited into one 360-degree strip, or null
const TRACK_PATH = __TRACK_PATH_JSON__;
const pendingTextureEdits = {};

function parseObj(text) {
  const positions = [], uvs = [], normals = [], groups = [];
  let current = null;
  for (const line of text.split("\n")) {
    const parts = line.trim().split(/\s+/);
    if (parts[0] === "v") positions.push(parts.slice(1).map(Number));
    else if (parts[0] === "vt") uvs.push(parts.slice(1).map(Number));
    else if (parts[0] === "vn") normals.push(parts.slice(1).map(Number));
    else if (parts[0] === "usemtl") { current = {material: parts[1], faces: []}; groups.push(current); }
    else if (parts[0] === "f") {
      const idx = parts.slice(1).map(p => p.split("/").map(x => parseInt(x,10)-1));
      current.faces.push(idx);
    }
  }
  return {positions, uvs, normals, groups};
}

async function downloadBytes(blobOrBytes, filename) {
  const blob = blobOrBytes instanceof Blob ? blobOrBytes : new Blob([blobOrBytes], {type: "application/octet-stream"});
  // Desktop app path: the embedded webview (pywebview) silently ignores an
  // <a download>, so when the Python bridge is present hand it the bytes and let
  // the OS save dialog write them. The bridge is injected only into the TOP
  // window, but this viewer runs inside the switcher's same-origin iframe, so
  // reach through window.parent too. A plain browser (the CLI-served page, the
  // gallery) has no bridge and falls through to the anchor download below.
  let api = null;
  try {
    api = (window.pywebview && window.pywebview.api)
       || (window.parent && window.parent.pywebview && window.parent.pywebview.api)
       || null;
  } catch (e) { /* cross-origin parent -- no bridge, use the anchor path */ }
  if (api && api.save_file) {
    const buf = new Uint8Array(await blob.arrayBuffer());
    let bin = "";
    for (let i = 0; i < buf.length; i++) bin += String.fromCharCode(buf[i]);
    try { await api.save_file(filename, btoa(bin)); return; }
    catch (e) { /* bridge failed -- fall through to the anchor download */ }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Defer the revoke: calling it synchronously after click() can abort the
  // download before the browser has read the blob.
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

function bytesToBase64(bytes) {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

// Same TGA codec as the car shell (viewer.py's _SHELL_TEMPLATE) -- see that
// file's decodeTga/encodeTga for the format notes; kept identical here so a
// texture round-tripped through either page behaves the same way.
function encodeTga(imageData) {
  const {data, width, height} = imageData;
  const header = new Uint8Array(18);
  header[2] = 2;
  new DataView(header.buffer).setUint16(12, width, true);
  new DataView(header.buffer).setUint16(14, height, true);
  header[16] = 32;
  header[17] = 0x28;
  const pixelCount = width * height;
  const body = new Uint8Array(pixelCount * 4);
  for (let i = 0; i < pixelCount; i++) {
    const o = i * 4;
    body[o] = data[o + 2];
    body[o + 1] = data[o + 1];
    body[o + 2] = data[o];
    body[o + 3] = data[o + 3];
  }
  const out = new Uint8Array(header.length + body.length);
  out.set(header, 0);
  out.set(body, header.length);
  return out;
}

function decodeTga(arrayBuffer) {
  const data = new Uint8Array(arrayBuffer);
  const idLen = data[0], cmapType = data[1], imgType = data[2];
  if (cmapType !== 0 || imgType !== 2) {
    throw new Error("only uncompressed truecolor TGA (no color map) is supported");
  }
  const view = new DataView(data.buffer, data.byteOffset, data.byteLength);
  const width = view.getUint16(12, true);
  const height = view.getUint16(14, true);
  const depth = data[16];
  const desc = data[17];
  if (depth !== 24 && depth !== 32) throw new Error(`unsupported bit depth ${depth}`);
  const channels = depth / 8;
  const topToBottom = !!(desc & 0x20);
  const off = 18 + idLen;
  const rowBytes = width * channels;
  const rows = [];
  for (let y = 0; y < height; y++) rows.push(data.subarray(off + y * rowBytes, off + (y + 1) * rowBytes));
  if (!topToBottom) rows.reverse();
  const out = new Uint8ClampedArray(width * height * 4);
  let oi = 0;
  for (const row of rows) {
    for (let x = 0; x < width; x++) {
      const si = x * channels;
      out[oi++] = row[si + 2];
      out[oi++] = row[si + 1];
      out[oi++] = row[si];
      out[oi++] = channels === 4 ? row[si + 3] : 255;
    }
  }
  return {data: out, width, height};
}

// Decode any browser-supported image (png/jpg/bmp/webp/gif) to canvas ImageData;
// TGA goes through decodeTga above. (Track-viewer copy of the shell's helper.)
async function decodeImageBytes(name, bytes) {
  if (/\.tga$/i.test(name)) {
    const d = decodeTga(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
    return new ImageData(d.data, d.width, d.height);
  }
  const url = URL.createObjectURL(new Blob([bytes]));
  try {
    const img = await new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = () => rej(new Error("couldn't decode image " + name)); im.src = url; });
    const c = document.createElement("canvas"); c.width = img.naturalWidth; c.height = img.naturalHeight;
    c.getContext("2d").drawImage(img, 0, 0);
    return c.getContext("2d").getImageData(0, 0, c.width, c.height);
  } finally { URL.revokeObjectURL(url); }
}
function imageDataHasAlpha(imgData) {
  const d = imgData.data;
  for (let i = 3; i < d.length; i += 4) if (d[i] < 255) return true;
  return false;
}
async function dataUriHasAlpha(dataUri) {
  const img = await new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = dataUri; });
  const c = document.createElement("canvas"); c.width = img.naturalWidth; c.height = img.naturalHeight;
  c.getContext("2d").drawImage(img, 0, 0);
  return imageDataHasAlpha(c.getContext("2d").getImageData(0, 0, c.width, c.height));
}

function exportTextureAsTga(name, dataUri) {
  const img = new Image();
  img.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0);
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    downloadBytes(encodeTga(imageData), name.replace(/\.tex$/i, ".tga"));
  };
  img.src = dataUri;
}

function updateCommitStatus() {
  const btn = document.getElementById("commit-btn");
  // The sky is not one of pendingTextureEdits -- it is not a material -- so it
  // has to be counted separately or Save stays disabled after a sky import.
  btn.disabled = Object.keys(pendingTextureEdits).length === 0 && !pendingSkyEdit;
}

async function importTextureAsTga(name, file, meshesByMaterial, loadTexture) {
  const statusEl = document.getElementById("commit-status");
  let imgData;
  try {
    imgData = await decodeImageBytes(file.name, new Uint8Array(await file.arrayBuffer()));
  } catch (err) {
    statusEl.textContent = `${file.name}: ${err && err.message ? err.message : err}`;
    return;
  }
  // Same transparency gate as the car textures: a no-alpha format (JPG) onto a
  // texture that had transparency would silently flatten it.
  if (!imageDataHasAlpha(imgData) && TEXTURES[name] && await dataUriHasAlpha(TEXTURES[name])) {
    if (!confirm(`"${name}" has transparency that ${file.name} can't carry (no alpha channel -- typical of JPG). Import anyway and make it fully opaque?`)) {
      statusEl.textContent = `Import cancelled -- ${name} kept. Use a PNG or TGA to preserve transparency.`;
      return;
    }
  }
  const canvas = document.createElement("canvas");
  canvas.width = imgData.width;
  canvas.height = imgData.height;
  canvas.getContext("2d").putImageData(imgData, 0, 0);
  const dataUri = canvas.toDataURL("image/png");
  TEXTURES[name] = dataUri;
  const newTexture = loadTexture(dataUri, TEXTURE_WRAPS[name]);
  const meshes = meshesByMaterial[name] || [];
  meshes.forEach(m => { m.material.map = newTexture; m.material.needsUpdate = true; });
  pendingTextureEdits[name] = bytesToBase64(encodeTga(imgData));
  updateCommitStatus();
  const swatch = document.querySelector(`.swatch[data-name="${CSS.escape(name)}"]`);
  if (swatch) {
    swatch.classList.add("pending");
    const img = swatch.querySelector("img");
    if (img) img.src = dataUri;
    const label = swatch.querySelector(".name");
    if (label) label.textContent = `${name} → ${file.name} (pending)`;
    const sub = swatch.querySelector(".sub");
    if (sub) sub.textContent = `${imgData.width}×${imgData.height}`;
  }
}

// The sky is four .tex tiles, but they are four slices of ONE image, so the
// drawer offers it as one entry. Exposing sky1-4 separately would invite
// edits that break the seam between them, and there is no reason to want it.
// Textures arrive as data URIs, so the decoded image is the only place their
// real dimensions exist client-side -- and reading them there also covers an
// imported TGA, which never round-trips through the server until Save.
function attachDims(el, img, extra) {
  const line = el.querySelector(".sub") || (() => {
    const d = document.createElement("div");
    d.className = "sub";
    el.insertBefore(d, el.querySelector(".swatch-actions"));
    return d;
  })();
  const write = () => {
    const dims = img.naturalWidth ? `${img.naturalWidth}×${img.naturalHeight}` : "";
    line.textContent = extra ? `${dims} · ${extra}` : dims;
  };
  if (img.complete && img.naturalWidth) write(); else img.addEventListener("load", write);
}

function buildSkySwatch(root) {
  if (!SKY_URI || !skySetStrip) return;
  const el = document.createElement("div");
  el.className = "swatch wide";
  el.dataset.name = "__sky__";
  const img = document.createElement("img");
  img.src = SKY_URI;
  el.appendChild(img);
  const label = document.createElement("div");
  label.className = "name";
  label.textContent = "Sky (all 4 panels)";
  el.appendChild(label);
  const note = document.createElement("div");
  note.className = "sub";
  el.appendChild(note);
  const actions = document.createElement("div");
  actions.className = "swatch-actions";
  // The sky is a composite of sky1-4.tex, so export the whole panorama as one
  // .tga (the same form Import expects, and what skyexport/skyimport round-trip).
  const exportBtn = document.createElement("div");
  exportBtn.className = "swatch-export";
  exportBtn.textContent = "Export TGA";
  exportBtn.addEventListener("click", () => exportTextureAsTga("sky.tex", SKY_URI));
  actions.appendChild(exportBtn);
  const importLabel = document.createElement("label");
  importLabel.className = "swatch-import";
  importLabel.textContent = "Import";
  importLabel.title = "Import a PNG, TGA, or other image for the sky strip";
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".png,.tga,.jpg,.jpeg,.bmp,.webp,.gif";
  input.addEventListener("change", e => {
    const file = e.target.files[0];
    if (file) importSkyAsTga(file);
    e.target.value = "";
  });
  importLabel.appendChild(input);
  actions.appendChild(importLabel);
  el.appendChild(actions);
  attachDims(el, img, "a quarter of the horizon, repeated 4×");
  root.appendChild(el);
}

async function importSkyAsTga(file) {
  const statusEl = document.getElementById("commit-status");
  let imgData;
  try {
    imgData = await decodeImageBytes(file.name, new Uint8Array(await file.arrayBuffer()));
  } catch (err) {
    statusEl.textContent = `${file.name}: ${err && err.message ? err.message : err}`;
    return;
  }
  const canvas = document.createElement("canvas");
  canvas.width = imgData.width;
  canvas.height = imgData.height;
  canvas.getContext("2d").putImageData(imgData, 0, 0);
  const dataUri = canvas.toDataURL("image/png");
  skySetStrip(dataUri);                      // live preview on the cylinder
  pendingSkyEdit = bytesToBase64(encodeTga(imgData));
  updateCommitStatus();
  const el = document.querySelector('.swatch[data-name="__sky__"]');
  if (el) {
    el.classList.add("pending");
    el.querySelector("img").src = dataUri;
    el.querySelector(".name").textContent = `Sky → ${file.name} (pending)`;
    const off = Math.abs(imgData.width / imgData.height - 4) > 0.01;
    el.querySelector(".sub").textContent = `${imgData.width}×${imgData.height} · ` +
      (off ? "not 4:1 — it will be resampled"
           : "a quarter of the horizon, repeated 4×");
  }
}

function buildTextureDrawer(meshesByMaterial, loadTexture) {
  const root = document.getElementById("texture-list");
  root.innerHTML = "";
  buildSkySwatch(root);
  const names = Object.keys(meshesByMaterial).sort();
  if (names.length === 0) {
    if (!root.children.length) root.innerHTML = '<div class="hint">no textures found</div>';
    return;
  }
  names.forEach(name => {
    const dataUri = TEXTURES[name];
    const el = document.createElement("div");
    el.className = "swatch";
    el.dataset.name = name;
    let img = null;
    if (dataUri) {
      img = document.createElement("img");
      img.src = dataUri;
      el.appendChild(img);
    } else {
      const missing = document.createElement("div");
      missing.className = "missing";
      missing.textContent = "no texture found";
      el.appendChild(missing);
    }
    const label = document.createElement("div");
    label.className = "name";
    label.textContent = name;
    el.appendChild(label);
    if (dataUri) {
      const actions = document.createElement("div");
      actions.className = "swatch-actions";
      const exportBtn = document.createElement("div");
      exportBtn.className = "swatch-export";
      exportBtn.textContent = "Export TGA";
      exportBtn.addEventListener("click", () => exportTextureAsTga(name, dataUri));
      actions.appendChild(exportBtn);
      const importLabel = document.createElement("label");
      importLabel.className = "swatch-import";
      importLabel.textContent = "Import";
      importLabel.title = "Import a PNG, TGA, or other image (JPG warns before flattening transparency)";
      const importInput = document.createElement("input");
      importInput.type = "file";
      importInput.accept = ".png,.tga,.jpg,.jpeg,.bmp,.webp,.gif";
      importInput.addEventListener("change", e => {
        const file = e.target.files[0];
        if (file) importTextureAsTga(name, file, meshesByMaterial, loadTexture);
        e.target.value = "";
      });
      importLabel.appendChild(importInput);
      actions.appendChild(importLabel);
      el.appendChild(actions);
    }
    if (img) attachDims(el, img);
    root.appendChild(el);
  });
}

const COMMIT_ROUTE = "/__vrmod_commit__";
let pendingSkyEdit = null;
// Set by buildSky(), which runs inside the scene scope; the drawer lives at
// top level and cannot see the sky group itself.
let skySetStrip = null;

async function commitChanges() {
  const statusEl = document.getElementById("commit-status");
  const payload = {track_path: TRACK_PATH, textures: pendingTextureEdits};
  if (pendingSkyEdit) payload.sky = pendingSkyEdit;
  statusEl.className = "pending";
  statusEl.textContent = "Saving...";
  let result;
  try {
    const resp = await fetch(COMMIT_ROUTE, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
    });
    result = await resp.json();
  } catch (err) {
    statusEl.className = "error";
    statusEl.textContent = "Couldn't reach the local save endpoint -- this only works when the page "
      + 'was opened via "python -m vrmod.cli trackview ... --serve".';
    return;
  }
  if (result.ok) {
    statusEl.className = "ok";
    // Say so when an import was fitted to the size the game already expects --
    // silently resizing someone's artwork is the kind of thing they should hear
    // about, and it is also the moment to learn a texture is not what they think.
    const fitted = (result.resized || []).length
      ? ` — resized to fit: ${result.resized.join(", ")}` : "";
    statusEl.textContent =
      `Saved to ${result.out_path} (original backed up to ${result.backup_path})${fitted}`;
    // Over-budget geometry is a different class of message: the save WORKED,
    // but the game may not load the result. It gets its own warning styling
    // rather than being appended to a success line.
    const warn = result.warnings || [];
    if (warn.length) {
      statusEl.className = "pending";
      // Built from character codes rather than escapes: this line has been
      // mangled once already by a quoting layer collapsing its \n.
      const bullet = String.fromCharCode(10, 0x26A0, 32);
      statusEl.textContent += bullet + warn.join(bullet);
    }
  } else {
    statusEl.className = "error";
    statusEl.textContent = `Save failed: ${result.error}`;
  }
}

function main() {
  if (typeof THREE === "undefined") {
    const el = document.getElementById("fatal-error");
    el.style.display = "block";
    el.textContent = "three.js failed to load from the CDN -- needs internet access, "
      + "or open this via a local server instead of double-clicking the file.";
    return;
  }
  const parsed = parseObj(OBJ_TEXT);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1a1a1a);
  let sky = null;
  const wrap = document.getElementById("canvas-wrap");
  const W = () => wrap.clientWidth, H = () => wrap.clientHeight;
  const camera = new THREE.PerspectiveCamera(50, W()/H(), 0.1, 100000);
  // preserveDrawingBuffer lets the canvas be read back with toDataURL after
  // the frame has been presented, which is what thumbnail capture needs.
  const renderer = new THREE.WebGLRenderer({antialias:true, preserveDrawingBuffer:true});
  renderer.setSize(W(), H());
  wrap.appendChild(renderer.domElement);

  scene.add(new THREE.AmbientLight(0xffffff, 0.8));
  const dl = new THREE.DirectionalLight(0xffffff, 0.7);
  dl.position.set(5, 10, 7);
  scene.add(dl);

  const loader = new THREE.TextureLoader();
  const maxAniso = renderer.capabilities.getMaxAnisotropy();
  const textureCache = {};
  function loadTexture(dataUri, wrap) {
    const key = dataUri + "|" + wrap;
    if (!textureCache[key]) {
      const t = loader.load(dataUri);
      // Track UVs routinely run well outside 0..1 (real values seen include
      // 4.24 and 53.4) -- those are tiling coordinates. three.js defaults to
      // ClampToEdgeWrapping, which stretches the edge pixel across the whole
      // surface instead of repeating, smearing every tiled road/grandstand
      // face. Repeat is safe to apply unconditionally: where UVs already sit
      // inside 0..1 it renders identically to clamp, so it only changes the
      // out-of-range case, which is exactly where tiling is intended. (The
      // .tex format does carry its own wrap flag, but it reads 0 even for
      // surfaces that demonstrably tile, so it isn't usable for this.)
      // Always repeat. The .tex `wrap` flag looks like it should decide this
      // but measurably does NOT: on a real track nearly every wrap=0
      // material still has UVs far outside 0..1 and so plainly needs
      // tiling -- arch1.tex (buildings) spans u -0.20..24.00, brk1.tex
      // -19.33..56.82, concr.tex -1242..358, and the main ground texy.tex
      // -168..107. Clamping those collapses each face to one stretched edge
      // pixel, which turned every building into a flat white box. Repeat is
      // safe for the rest: where UVs already sit inside 0..1 the two modes
      // render identically. (An earlier revision clamped on wrap=0 after
      // wrongly blaming wrapping for mangled terrain -- that was really the
      // fan-triangulation fallback, fixed separately in grf.py.)
      t.wrapS = THREE.RepeatWrapping;
      t.wrapT = THREE.RepeatWrapping;
      // Ground/road surfaces tile their texture hundreds of times and are
      // usually viewed at a very shallow angle, which without anisotropic
      // filtering smears them into long radiating streaks -- the single
      // most obvious difference against 3DSimED's render of the same
      // terrain. Mipmapping alone can't fix it (it picks one level for the
      // whole fragment, blurring along the wrong axis).
      t.anisotropy = maxAniso;
      textureCache[key] = t;
    }
    return textureCache[key];
  }

  const fallbackColors = [0x8899aa, 0x778866, 0x998877];
  const root = new THREE.Group();
  const meshesByMaterial = {};
  parsed.groups.forEach((g, gi) => {
    if (g.faces.length === 0) return;
    const posArr = [], uvArr = [];
    for (const face of g.faces) for (const [pi, ui] of face) {
      const p = parsed.positions[pi];
      posArr.push(p[0], p[1], p[2]);
      const uv = ui != null ? parsed.uvs[ui] : [0, 0];
      uvArr.push(uv[0], uv[1]);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(posArr, 3));
    geo.setAttribute("uv", new THREE.Float32BufferAttribute(uvArr, 2));
    geo.computeVertexNormals();

    const dataUri = TEXTURES[g.material];
    const matOpts = {side: THREE.DoubleSide};
    if (dataUri) {
      matOpts.map = loadTexture(dataUri, TEXTURE_WRAPS[g.material]);
      // Colorkey/alpha textures (trees, signs, crowd billboards) are flat
      // quads whose real silhouette only shows once fully-transparent
      // texels are discarded -- without this they render as solid
      // rectangles. Harmless on fully-opaque textures, where every texel
      // passes the test anyway. Same treatment the car shell gives them.
      matOpts.alphaTest = 0.5;
    } else {
      matOpts.color = fallbackColors[gi % fallbackColors.length];
    }
    const meshObj = new THREE.Mesh(geo, new THREE.MeshStandardMaterial(matOpts));
    root.add(meshObj);
    (meshesByMaterial[g.material] = meshesByMaterial[g.material] || []).push(meshObj);
  });
  scene.add(root);

  const box = new THREE.Box3().setFromObject(root);
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z, 1);
  let radius = maxDim * 1.5;

  // Sized off the track, not the camera: big enough that the sky always sits
  // outside the geometry, small enough to stay well inside the camera's far plane.
  buildSky(maxDim * 4);
  const skyGroundY = box.min.y;
  if(sky) sky.position.y = skyGroundY;

  // After buildSky, not before: the drawer leads with the sky swatch, and that
  // needs skySetStrip to exist. buildSky in turn needs the bounding box above,
  // so this is the earliest the drawer can be built with the sky in it.
  buildTextureDrawer(meshesByMaterial, loadTexture);
  document.getElementById("commit-btn").addEventListener("click", commitChanges);

  const grid = new THREE.GridHelper(maxDim * 2, 20, 0x555555, 0x333333);
  grid.position.set(center.x, box.min.y, center.z);
  scene.add(grid);

  let az = 0.7, el = 0.5;
  function updateCam() {
    camera.position.set(
      center.x + radius*Math.cos(el)*Math.sin(az),
      center.y + radius*Math.sin(el),
      center.z + radius*Math.cos(el)*Math.cos(az)
    );
    camera.lookAt(center);
  }
  updateCam();

  // Pan moves the orbit TARGET (not the camera) along the camera's own
  // right/up axes, so dragging feels the same from any angle. Without this
  // the view can only ever circle one fixed point, which makes lining a
  // shot up against an external reference (e.g. 3DSimED) painful.
  function panBy(dxPix, dyPix) {
    const forward = new THREE.Vector3().subVectors(center, camera.position).normalize();
    const right = new THREE.Vector3().crossVectors(forward, camera.up).normalize();
    const up = new THREE.Vector3().crossVectors(right, forward).normalize();
    // Scale with distance so the drag tracks the cursor at any zoom level.
    const k = radius / H() * 1.5;
    center.addScaledVector(right, -dxPix * k);
    center.addScaledVector(up, dyPix * k);
    updateCam();
  }

  let isDown = false, panning = false, lastX = 0, lastY = 0;
  renderer.domElement.addEventListener("contextmenu", e => e.preventDefault());
  renderer.domElement.addEventListener("mousedown", e => {
    isDown = true;
    panning = (e.button === 2 || e.button === 1 || e.shiftKey);
    lastX = e.clientX; lastY = e.clientY;
  });
  window.addEventListener("mouseup", () => { isDown = false; panning = false; });
  window.addEventListener("mousemove", e => {
    if (!isDown) return;
    const dx = e.clientX - lastX, dy = e.clientY - lastY;
    lastX = e.clientX; lastY = e.clientY;
    if (driveMode) {
      // In drive view a drag looks around from where you are on the track,
      // rather than orbiting -- the camera's position belongs to the path.
      lookYaw -= dx * 0.005;
      lookPitch = Math.max(-1.0, Math.min(1.0, lookPitch - dy * 0.005));
      placeDriveCam();
      return;
    }
    if (panning) { panBy(dx, dy); return; }
    az += dx * 0.01;
    // Allow dipping below the horizon -- ground-level shots are exactly the
    // ones worth comparing against another renderer.
    el = Math.max(-1.2, Math.min(1.5, el + dy * 0.01));
    updateCam();
  });
  window.addEventListener("keydown", e => {
    if (driveMode) {
      if (e.key === " ") { e.preventDefault(); setPlaying(!playing); return; }
      if (e.key === "Escape") { setDrive(false); return; }
    }
    // R re-frames on the whole track, for when a pan wanders off into space.
    if (e.key === "r" || e.key === "R") {
      center.copy(box.getCenter(new THREE.Vector3()));
      radius = maxDim * 1.5;
      updateCam();
    }
  });
  renderer.domElement.addEventListener("wheel", e => {
    e.preventDefault();
    radius = Math.max(maxDim * 0.05, Math.min(maxDim * 8, radius * (1 + e.deltaY * 0.001)));
    updateCam();
  }, {passive: false});
  function fitCanvas(){
    camera.aspect = W()/H();
    camera.updateProjectionMatrix();
    renderer.setSize(W(), H());
  }
  window.addEventListener("resize", fitCanvas);

  // Opening or closing the drawer resizes the canvas, so the camera has to be
  // refitted -- and only after the CSS transition has run, or it measures the
  // old width. Matches the .18s in #canvas-wrap.
  // Embedded in the mod manager? Then it provides Drive and the menu-picture
  // action in its own bar, and showing ours too means two controls for one
  // job. Hide rather than remove: the host still clicks #shot-btn directly.
  // Same-origin, so the host's controls are reachable directly -- no message
  // protocol. Absent (standalone page) everything below degrades to a no-op.
  const HOST = (() => {
    try { return window.self !== window.top ? window.parent.vrmodHost : null; }
    catch(e) { return null; }          // cross-origin: behave as standalone
  })();
  if(window.self !== window.top) document.body.classList.add("embedded");

  const expandBtn = document.getElementById("expand-btn");
  function syncExpandBtn(){
    if(!HOST) return;
    expandBtn.hidden = false;
    expandBtn.textContent = HOST.isExpanded() ? "⇲ Show library" : "⇱ Full width";
  }
  if(HOST){
    syncExpandBtn();
    expandBtn.addEventListener("click", () => {
      HOST.setExpanded(!HOST.isExpanded());
      // The host animates its grid; refit once it has settled.
      setTimeout(() => { fitCanvas(); syncExpandBtn(); }, 220);
    });
  }

  const modBtn = document.getElementById("mod-btn");
  modBtn.addEventListener("click", () => {
    const on = document.body.classList.toggle("modding");
    modBtn.innerHTML = on ? "‹ Back to viewing" : "Mod it! ✎";
    // Modding opens the Textures panel down the right side, so claim the full
    // window on the way IN -- same as entering drive mode. One-way: leaving Mod
    // leaves the width as-is. Guarded so a deliberate split isn't stomped.
    if(on && HOST && !HOST.isExpanded()){ HOST.setExpanded(true); syncExpandBtn(); }
    setTimeout(fitCanvas, 220);
  });

  // ---- track-select thumbnail -------------------------------------------
  // The game's track-select screenshot is a 180x120 stamp. Grab the current
  // view at exactly that size: crop the rendered frame to 3:2 about its
  // centre, scale it down, and hand the raw RGB back to the local server,
  // which encodes the .stp. Raw RGB rather than a PNG so nothing has to
  // decode an image format on the way back.
  const SHOT_W = 180, SHOT_H = 120;

  function shotStatus(msg, bad){
    for(const id of ["shot-status"]){
      const el = document.getElementById(id);
      if(el){ el.textContent = msg; el.style.color = bad ? "#e08a8a" : "#7fd67f"; }
    }
  }

  async function saveThumbnail(){
    try{
      const cv = renderer.domElement;
      const ar = SHOT_W / SHOT_H;
      let sw = cv.width, sh = Math.round(cv.width / ar);
      if(sh > cv.height){ sh = cv.height; sw = Math.round(cv.height * ar); }
      const sx = Math.round((cv.width - sw) / 2), sy = Math.round((cv.height - sh) / 2);
      const out = document.createElement("canvas");
      out.width = SHOT_W; out.height = SHOT_H;
      const g = out.getContext("2d");
      g.imageSmoothingEnabled = true; g.imageSmoothingQuality = "high";
      g.drawImage(cv, sx, sy, sw, sh, 0, 0, SHOT_W, SHOT_H);
      const d = g.getImageData(0, 0, SHOT_W, SHOT_H).data;
      const rgb = new Uint8Array(SHOT_W * SHOT_H * 3);
      for(let i = 0, o = 0; i < d.length; i += 4){
        rgb[o++] = d[i]; rgb[o++] = d[i+1]; rgb[o++] = d[i+2];
      }
      let bin = "";
      for(let i = 0; i < rgb.length; i++) bin += String.fromCharCode(rgb[i]);
      const res = await fetch("/api/thumbnail", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({track: TRACK_PATH, width: SHOT_W, height: SHOT_H, rgb: btoa(bin)})
      });
      const j = await res.json();
      shotStatus(j.ok ? ("saved " + j.wrote) : j.error, !j.ok);
    }catch(e){
      shotStatus("capture failed: " + e.message + " (needs the served viewer, not a local file)", true);
    }
  }

  for(const id of ["shot-btn", "shot-btn2"]){
    const el = document.getElementById(id);
    if(el) el.addEventListener("click", saveThumbnail);
  }

  // Every sky texture -- the original and any imported replacement -- must be
  // set up identically, so this is the single place that knows how.
  function skyTexture(uri){
    const t = new THREE.TextureLoader().load(uri);
    t.wrapS = THREE.RepeatWrapping;
    t.wrapT = THREE.ClampToEdgeWrapping;
    t.colorSpace = THREE.SRGBColorSpace ?? t.colorSpace;
    t.anisotropy = maxAniso;
    t.repeat.x = -4;      // 4x around the horizon, mirrored for BackSide
    t.offset.x = 1;
    return t;
  }

  function buildSky(radius){
    if(!SKY_URI) return;
    const tex = skyTexture(SKY_URI);

    // The strip is NOT a 360-degree panorama. It spans about 90 degrees and
    // TILES FOUR TIMES around the horizon.
    //
    // CONFIRMED DIRECTLY: turning a full circle in game on Telly shows FOUR
    // baby-face suns. That settles it; everything below is corroboration.
    //   * one 640x480 in-game frame shows ~655px of the 1024px strip at once,
    //     which at that game's ~58-degree hFOV makes the whole strip ~90
    //     degrees, i.e. 3.98 repeats.
    //   * the sun is 200x110 in the source art (aspect 1.82) but renders ROUND
    //     in game. A perspective camera preserves angular aspect, so a single
    //     360-degree wrap would need the strip to span ~148 degrees vertically
    //     -- past the zenith, impossible.
    //
    // Note this does NOT contradict the community sky tool taking one image and
    // splitting it into four .tex panels: those four panels really are one
    // continuous strip (see _build_sky_panorama's seam measurements). The tool
    // defines the strip; it does not define how many times the game wraps it.
    //
    // Wrapping it once made every feature four times too wide: the baby-face
    // sun filled 40% of the frame instead of ~16%.
    //
    // The sign is the other half of the story. CylinderGeometry lays its UVs
    // out to be seen from OUTSIDE, and this renders with side:BackSide because
    // the camera is inside it, so a positive repeat reads left-for-right --
    // on Telly the Teletubbies came out purple-yellow-green-red instead of
    // red-green-yellow-purple.
    // (applied in skyTexture() above)
    // The strip's vertical extent AND where its horizon sits, both measured
    // against the running game on Telly.
    //
    // The base is BELOW eye level, which is the part that took longest to see.
    // The lower half of the art is hillside and hobbit-holes; in game those are
    // under the horizon, hidden behind real terrain, and only the crest and sky
    // show. Anchoring the strip's base to the track's ground plane (which is
    // what "start the sky at the plane the track sits on" produced) lifted all
    // of that into view and made the backdrop tower over the road.
    //
    // From the sun: it renders ~9.8 degrees above the horizon and ~9.4 degrees
    // tall, and in the art it is 110px of 256 centred 0.695 up the strip. That
    // puts the whole strip at ~21.8 degrees with its base ~5.3 degrees under
    // the horizon. Independently, SQUARE texels at the 4x tiling above want
    // 21.4 degrees -- agreeing to 0.4 -- so the texels really are square and
    // the values below use that.
    const SKY_ABOVE_DEGREES = 16.1;   // visible above the horizon
    const SKY_BELOW_DEGREES = 5.3;    // tucked under it, behind the terrain
    const deg = (d) => d * Math.PI / 180;
    const SKY_DROP = radius * Math.tan(deg(SKY_BELOW_DEGREES));
    const SKY_H = radius * Math.tan(deg(SKY_ABOVE_DEGREES)) + SKY_DROP;
    const geo = new THREE.CylinderGeometry(radius, radius, SKY_H, 64, 1, true);
    const mat = new THREE.MeshBasicMaterial({
      map: tex, side: THREE.BackSide, depthWrite: false, fog: false,
    });
    sky = new THREE.Group();
    const wall = new THREE.Mesh(geo, mat);
    // The panorama's bottom edge is the horizon, so sit the cylinder's base
    // at eye level rather than centring it on the origin.
    // The panorama's bottom edge is the horizon, and the group is positioned
    // at the track's ground plane (box.min.y), so putting the wall's own
    // centre half a height up sits that bottom edge exactly on the plane the
    // track rests on -- the horizon meets the ground rather than floating
    // above it or sinking below it.
    wall.position.y = SKY_H * 0.5;
    sky.add(wall);
    // Cap the top with the panorama's own zenith colour so looking straight
    // up shows sky rather than the page background through the open end.
    // The cap's colour is sampled from the panorama's own top row rather than
    // hardcoded, so a sunset or overcast track caps in its own sky rather than
    // a fixed daylight blue. Sampled from the decoded image because the strip
    // is a data: URI, so there is no cross-origin restriction on reading it.
    const capMat = new THREE.MeshBasicMaterial({
      color: 0x6ba4d8, side: THREE.BackSide, depthWrite: false, fog: false });
    const probe = new Image();
    probe.onload = () => {
      try {
        const c = document.createElement("canvas");
        c.width = probe.width; c.height = 1;
        const g = c.getContext("2d");
        g.drawImage(probe, 0, 0, probe.width, 1, 0, 0, probe.width, 1);
        const px = g.getImageData(0, 0, probe.width, 1).data;
        let r = 0, gg = 0, b = 0;
        for(let i = 0; i < px.length; i += 4){ r += px[i]; gg += px[i+1]; b += px[i+2]; }
        const n = px.length / 4;
        capMat.color.setRGB(r/n/255, gg/n/255, b/n/255);
      } catch(e) { /* keep the default blue */ }
    };
    probe.src = SKY_URI;
    const cap = new THREE.Mesh(new THREE.CircleGeometry(radius, 64), capMat);
    cap.rotation.x = -Math.PI / 2;
    cap.position.y = SKY_H;
    sky.add(cap);
    // Sample the real zenith colour off the loaded image and apply it to the cap.
    const img = new Image();
    img.onload = () => {
      try{
        const c = document.createElement("canvas");
        c.width = img.width; c.height = img.height;
        const g = c.getContext("2d");
        g.drawImage(img, 0, 0);
        const rowAvg = (y) => {
          const d = g.getImageData(0, y, img.width, 1).data;
          let r = 0, gg = 0, b = 0;
          for(let i = 0; i < img.width; i++){ r += d[i*4]; gg += d[i*4+1]; b += d[i*4+2]; }
          return [r/img.width/255, gg/img.width/255, b/img.width/255];
        };
        const zenith = rowAvg(0), horizon = rowAvg(img.height - 1);
        cap.material.color.setRGB(zenith[0], zenith[1], zenith[2]);
        scene.background = new THREE.Color(horizon[0], horizon[1], horizon[2]);
      }catch(e){ /* canvas may be tainted; the fallback colour already looks right */ }
    };
    img.src = SKY_URI;
    sky.renderOrder = -1;
    sky.userData.drop = SKY_DROP;
    skySetStrip = (uri) => { mat.map = skyTexture(uri); mat.needsUpdate = true; };
    scene.add(sky);
  }

  // ---- drive view: a second camera mode that follows the racing line ------
  // Distinct from the orbit view rather than a temporary override: the two
  // own the camera exclusively, so they never fight over it frame to frame.
  // Position along the lap is arc length (getPointAt/getTangentAt), not
  // waypoint index -- waypoints bunch up in corners, and stepping by index
  // makes the camera lurch through them and crawl down the straights.
  let lapCurve = null, lapLen = 0, lapT = 0;
  const lines = {};          // "forward" / "reverse" -> {curve, len, ribbon}
  let dirKey = "forward";
  let driveMode = false, playing = false, lapPrev = 0, speedMul = 1;
  let lookYaw = 0, lookPitch = 0;          // free look, relative to the track direction
  // World units are METRES, not feet: Viper0.mod measures 4.43 x 1.92 x 1.10,
  // matching the real Dodge Viper GTS (4.45 x 1.92 x 1.12 m) exactly, and cars
  // and tracks necessarily share one coordinate space. Bemidji's lines come to
  // 1.41-1.44 miles read as metres, against the 1.5 the game's Track Info
  // screen reports -- a centreline runs a little longer than any driving line.
  const EYE = 1.6;            // metres above the road: about eye height in a car
  const MPS_TO_MPH = 2.23694;
  // The line's own per-waypoint speed sets the SHAPE of the pace -- slower
  // through corners, faster down straights -- and this constant sets the
  // overall scale. Integrating the stored speeds directly gives a 24.7 s lap
  // on Bemidji, but a real lap there is about 50 s, so the stored figures run
  // about 2x optimistic against actual driving (whether the distance unit is
  // not quite feet, the speed field is not quite mph, or nobody actually
  // drives the AI's target speeds, is unresolved). Calibrated to that single
  // measured lap; adjust here if other tracks turn out to want a different
  // factor.
  // field[6] carries the line's intended speed and gives the pace its SHAPE
  // (slower through corners, faster on straights); this converts it into
  // metres per second. Scaled so Bemidji lands on the ~50 s lap measured in
  // game. The stored figures don't reduce to a clean unit: matching that lap
  // needs an average of 45 m/s (101 mph) over 2,268 m, while field[6] averages
  // 62.7 there -- so it is neither mph nor m/s outright. Treated as a relative
  // profile with an empirical scale rather than a real unit.
  const SPEED_SCALE = 0.7245;

  // Forward and reverse are different lines, so each gets its own curve and
  // its own drawn ribbon; switching just swaps which is active and visible.
  // Red and dashed, so the path never reads as painted-on track marking the
  // way a solid yellow line did. Dash sizes are world metres: 4 on / 3 off is
  // about a car length, short enough to stay dashed through the tightest
  // hairpin and long enough not to alias into a solid line down a straight.
  // Only one direction is ever visible at a time, so both share the colour.
  const RIBBON_COLOR = 0xe02b2b;
  const DASH_ON = 4.0, DASH_OFF = 3.0;
  for(const key of ["forward", "reverse"]){
    const entry = PATHS && PATHS[key];
    const pts = entry && entry.points;
    if(!pts || pts.length < 4) continue;
    const curve = new THREE.CatmullRomCurve3(
      pts.map(p => new THREE.Vector3(p[0], p[1] + EYE, p[2])), true, "catmullrom", 0.5);
    const ribbon = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(curve.getPoints(pts.length * 6)),
      new THREE.LineDashedMaterial({color: RIBBON_COLOR, dashSize: DASH_ON, gapSize: DASH_OFF})
    );
    // LineDashedMaterial reads a per-vertex distance attribute that only this
    // call fills in; without it every segment starts at 0 and the whole line
    // draws solid.
    ribbon.computeLineDistances();
    ribbon.position.y = 0.15 - EYE;  // ~15 cm above the road, clear of z-fighting
    ribbon.visible = false;
    scene.add(ribbon);
    lines[key] = {curve: curve, len: curve.getLength(), ribbon: ribbon,
                  speeds: entry.speeds || [], normals: entry.normals || []};
  }

  if(!lines.forward && lines.reverse) dirKey = "reverse";
  let hasLine = true;
  if(lines[dirKey]){
    lapCurve = lines[dirKey].curve;
    lapLen = lines[dirKey].len;
  } else {
    // No racing line means nothing to follow, so the wheel never appears.
    hasLine = false;
  }

  const el$ = (id) => document.getElementById(id);

  function showRibbon(on){
    for(const key of Object.keys(lines)) lines[key].ribbon.visible = on && key === dirKey;
  }

  function setDirection(key){
    if(!lines[key]) return;
    dirKey = key;
    lapCurve = lines[key].curve;
    lapLen = lines[key].len;
    showRibbon(!driveMode);
    if(driveMode){ buildMinimap(); drawMinimap(); }
    // Estimated lap time = sum over waypoints of segment length / local speed.
    let secs = 0;
    const n = 240;
    for(let i = 0; i < n; i++) secs += (lapLen / n) / speedAt(i / n);
    el$("lap-info").textContent =
      (TRACK_MI ? TRACK_MI.toFixed(1) + " mi track, " : "")
      + (lapLen / 1609.34).toFixed(2) + " mi " + key + " line, ~"
      + Math.round(secs) + "s";
    if(driveMode){ drawDriveReadout(); placeDriveCam(); }
  }

  // Speed at a point on the lap, interpolated between the two waypoints it
  // falls between. Returns METRES PER SECOND.
  function speedAt(u){
    const sp = lines[dirKey].speeds;
    if(!sp.length) return 45;
    const f = ((u % 1) + 1) % 1 * sp.length;
    const i = Math.floor(f), frac = f - i;
    const a = sp[i % sp.length], b = sp[(i + 1) % sp.length];
    return (a + (b - a) * frac) * SPEED_SCALE;
  }

  // Road surface normal at a point on the lap, interpolated between the two
  // waypoints it falls between. This is what lets the camera bank: these
  // tracks are steeply cambered (Bemidji reaches 17 degrees), and a camera
  // held level against that tips the road out of frame through the turns.
  const WORLD_UP = new THREE.Vector3(0, 1, 0);

  function normalAt(u){
    const ns = lines[dirKey].normals;
    if(!ns.length) return WORLD_UP.clone();
    const f = ((u % 1) + 1) % 1 * ns.length;
    const i = Math.floor(f), frac = f - i;
    const a = ns[i % ns.length], b = ns[(i + 1) % ns.length];
    return new THREE.Vector3(
      a[0] + (b[0] - a[0]) * frac,
      a[1] + (b[1] - a[1]) * frac,
      a[2] + (b[2] - a[2]) * frac
    ).normalize();
  }

  // ---- minimap: the track outline with the car's position on it ----------
  // Drawn in JS from the same points the drive camera follows, rather than
  // reusing the generated Trackmap image, so the dot and the outline are
  // guaranteed to share one projection -- no risk of the marker drifting off
  // a map that was fitted differently.
  const MM_MARGIN = 12;
  const MM_TRACK = "#f0c000";       // the stock map's yellow
  let mmProj = null, mmBase = null;

  // The minimap is drawn in NATIVE (left-handed) coordinates, not scene ones,
  // so it comes out the same way round as the game's own Track Info map --
  // trackmap.py generates that straight from the .ili without ever going
  // through mod.to_obj()'s handedness conversion. Scene Z is the negation of
  // native Z, so everything entering the projection gets flipped back here.
  const mmNativeZ = (z) => -z;

  function mmProject(pts, w, h){
    // Same orientation rule the map generator uses: whichever of the two
    // top-down orientations fills the canvas better.
    let best = null;
    for(const swap of [false, true]){
      const us = pts.map(p => swap ? p[2] : p[0]);
      const vs = pts.map(p => swap ? p[0] : p[2]);
      const u0 = Math.min(...us), v0 = Math.min(...vs);
      const du = Math.max(...us) - u0, dv = Math.max(...vs) - v0;
      if(du <= 0 || dv <= 0) continue;
      const scale = Math.min((w - 2*MM_MARGIN)/du, (h - 2*MM_MARGIN)/dv);
      if(!best || scale > best.scale) best = {swap, scale, u0, v0, du, dv};
    }
    if(best){
      // Centre whichever axis has slack, so the outline sits in the canvas.
      best.ox = (w - best.du * best.scale) / 2;
      best.oy = (h - best.dv * best.scale) / 2;
    }
    return best;
  }

  function mmPoint(x, z){
    const u = mmProj.swap ? z : x, v = mmProj.swap ? x : z;
    return [mmProj.ox + (u - mmProj.u0) * mmProj.scale,
            mmProj.oy + (v - mmProj.v0) * mmProj.scale];
  }

  function buildMinimap(){
    const cv = el$("minimap");
    const pts = (PATHS && PATHS[dirKey] && PATHS[dirKey].points) || null;
    if(!cv || !pts){ mmProj = null; return; }
    mmProj = mmProject(pts.map(p => [p[0], p[1], mmNativeZ(p[2])]), cv.width, cv.height);
    if(!mmProj) return;
    // Cache the outline once per direction; only the dot changes per frame.
    mmBase = document.createElement("canvas");
    mmBase.width = cv.width; mmBase.height = cv.height;
    const g = mmBase.getContext("2d");
    g.strokeStyle = MM_TRACK; g.lineWidth = 3;
    g.lineJoin = "round"; g.lineCap = "round";
    g.beginPath();
    pts.forEach((p, i) => {
      const [x, y] = mmPoint(p[0], mmNativeZ(p[2]));
      i ? g.lineTo(x, y) : g.moveTo(x, y);
    });
    g.closePath();
    g.stroke();
    // Start/finish tick, so the lap's origin is visible.
    const [sx, sy] = mmPoint(pts[0][0], mmNativeZ(pts[0][2]));
    g.fillStyle = "#ffffff";
    g.fillRect(sx - 2, sy - 2, 4, 4);
  }

  function drawMinimap(){
    const cv = el$("minimap");
    if(!cv || !mmProj || !mmBase) return;
    const g = cv.getContext("2d");
    g.clearRect(0, 0, cv.width, cv.height);
    g.drawImage(mmBase, 0, 0);
    const here = lapCurve.getPointAt(lapT);
    const tan = lapCurve.getTangentAt(lapT);
    const [x, y] = mmPoint(here.x, mmNativeZ(here.z));
    // A short whisker along the direction of travel: which way the car is
    // going round is exactly what a plain dot cannot tell you.
    const [hx, hy] = mmPoint(here.x + tan.x * 40, mmNativeZ(here.z + tan.z * 40));
    const dx = hx - x, dy = hy - y, len = Math.hypot(dx, dy) || 1;
    g.strokeStyle = "#ffffff"; g.lineWidth = 2;
    g.beginPath();
    g.moveTo(x, y);
    g.lineTo(x + dx / len * 9, y + dy / len * 9);
    g.stroke();
    g.fillStyle = "#ff4d4d";
    g.beginPath(); g.arc(x, y, 4, 0, Math.PI * 2); g.fill();
    g.strokeStyle = "#ffffff"; g.lineWidth = 1.5; g.stroke();
  }

  function placeDriveCam(){
    const pos = lapCurve.getPointAt(lapT);
    const tan = lapCurve.getTangentAt(lapT);
    const up = normalAt(lapT);
    // Yaw about the ROAD's up, then pitch about the resulting right vector, so
    // looking around stays level with the track rather than with the world.
    const dir = tan.clone().applyAxisAngle(up, lookYaw);
    const right = new THREE.Vector3().crossVectors(dir, up).normalize();
    dir.applyAxisAngle(right, lookPitch);
    camera.up.copy(up);
    camera.position.copy(pos);
    camera.lookAt(pos.clone().add(dir));
  }

  function drawDriveReadout(){
    el$("drive-readout").textContent =
      Math.round(lapT * lapLen).toLocaleString() + " / " + Math.round(lapLen).toLocaleString() + " m"
      + "  \u00b7  " + Math.round(speedAt(lapT) * MPS_TO_MPH) + " mph";
    el$("scrub").value = String(Math.round(lapT * 1000));
  }

  function setPlaying(on){
    playing = on;
    el$("play-btn").textContent = on ? "Pause" : "Play";
    lapPrev = performance.now();
  }

  function setDrive(on){
    if(on && !lapCurve) return;
    driveMode = on;
    el$("drivebar").hidden = !on || !panelOpen;
    el$("wheel-btn").classList.toggle("on", on);
    el$("hint").style.display = on ? "none" : "";
    showRibbon(!on);                     // in drive view you are standing on it
    el$("minimap").hidden = !on;
    // Both sit top-right, and modding has no meaning while driving anyway.
    el$("mod-btn").hidden = on;
    if(on){
      lookYaw = lookPitch = 0;
      buildMinimap();
      setPlaying(true);
      placeDriveCam();
      drawDriveReadout();
      drawMinimap();
    } else {
      playing = false;
      camera.up.copy(WORLD_UP);          // orbit controls assume a level horizon
      updateCam();                       // hand the camera back to the orbit view
    }
  }

  function stepDrive(now){
    const dt = Math.min((now - lapPrev) / 1000, 0.1);  // clamp so a backgrounded
    lapPrev = now;                                      // tab cannot jump ahead
    if(playing){
      // Advance by DISTANCE covered, not by a fixed fraction of the lap, so
      // the camera slows for corners the way the racing line intends.
      lapT = (lapT + (speedAt(lapT) * dt * speedMul) / lapLen) % 1;
      drawDriveReadout();
    }
    placeDriveCam();
    drawMinimap();
  }

  for(const opt of el$("dir-sel").options){
    if(!lines[opt.value]){ opt.disabled = true; opt.textContent += " (none)"; }
  }
  el$("dir-sel").value = dirKey;
  if(lapCurve) setDirection(dirKey);
  showRibbon(true);

  el$("dir-sel").addEventListener("change", (e) => setDirection(e.target.value));
  // The wheel does double duty: it enters drive view, and once you are in it
  // it shows/hides the control panel so the road can be seen unobstructed.
  let panelOpen = true;
  el$("wheel-btn").hidden = !hasLine;
  el$("wheel-btn").addEventListener("click", () => {
    if(driveMode){
      panelOpen = !panelOpen;
      el$("drivebar").hidden = !panelOpen;
      return;
    }
    panelOpen = true;
    // Driving wants the whole window, so claim it from the host on the way in
    // (see HOST above). Standalone there is nothing to claim.
    if(HOST && !HOST.isExpanded()){
      HOST.setExpanded(true);
      syncExpandBtn();
      // Enter only once the host's resize has landed, or the camera keeps the
      // narrow aspect until something else nudges it.
      setTimeout(() => { fitCanvas(); setDrive(true); }, 220);
      return;
    }
    setDrive(true);
  });
  el$("exit-btn").addEventListener("click", () => setDrive(false));
  el$("play-btn").addEventListener("click", () => setPlaying(!playing));
  el$("speed-sel").addEventListener("change", (e) => { speedMul = parseFloat(e.target.value); });
  el$("scrub").addEventListener("input", (e) => {
    // Scrubbing is a deliberate reposition, so it pauses rather than fighting
    // playback for control of lapT.
    if(playing) setPlaying(false);
    lapT = parseInt(e.target.value, 10) / 1000;
    drawDriveReadout();
    placeDriveCam();
    drawMinimap();
  });

  function animate(){
    requestAnimationFrame(animate);
    // Keep the sky centred on the viewer horizontally so it reads as
    // infinitely distant; leave Y alone so the horizon stays put.
    if(driveMode && lapCurve) stepDrive(performance.now());
    if(sky){
      sky.position.x = camera.position.x;
      sky.position.z = camera.position.z;
      // Driving, the horizon belongs at EYE level with the strip's base tucked
      // below it -- that is what matches the game, and it also keeps the
      // horizon steady over crests instead of sliding with the terrain.
      // Orbiting, keep the base on the track's ground plane: from outside, a
      // sky that follows the camera up would leave the track hanging under it.
      sky.position.y = driveMode ? camera.position.y - sky.userData.drop : skyGroundY;
    }
    renderer.render(scene, camera);
  }
  animate();
}
window.addEventListener("load", main);
</script>
</body></html>
"""


def _build_sky_panorama(trk_path: str | Path) -> str | None:
    """Composite a track's sky1-4.tex into one panoramic strip PNG.

    Every track archive carries exactly four square opaque sky textures, and
    they are four consecutive slices of a single panoramic image: measured
    seam continuity between adjacent faces (including sky4 -> sky1, which
    closes the loop) is a mean edge difference of only 1-7 out of 255 across
    every stock track. The community sky tool works the same way round --
    it takes ONE panoramic source image per track and splits it into these
    four files -- which independently confirms the arrangement.

    The strip is NOT one full turn of the horizon, though it closes seamlessly
    as if it were: it spans about 90 degrees and the game tiles it FOUR TIMES
    around. Confirmed by turning a full circle in game on Telly and counting
    four copies of its baby-face sun. See the repeat.x note in buildSky().

    Returned as a single wide image so the viewer can wrap it around a
    cylinder in one piece, rather than mapping four separate faces onto a
    cube and having to get each face's UV handedness right.

    Returns None if the track has no usable sky (nothing is drawn then).
    """
    try:
        entries = archive.read(trk_path)
    except Exception:
        return None
    by_name = {e.name.lower(): e for e in entries}
    tiles = []
    for i in (1, 2, 3, 4):
        entry = by_name.get(f"sky{i}.tex")
        if entry is None:
            return None
        try:
            info = tex.parse(envelope.build(entry.tag, entry.version, entry.payload))
            pixels = tex.decode_base_level(info)
        except Exception:
            return None
        size = 1 << (info.mip_count - 1)
        if size <= 0 or len(pixels) % (size * size):
            return None
        # decode_base_level returns RGB for opaque textures and RGBA for
        # colorkey/alpha ones -- sky tiles are opaque, but don't assume it.
        tiles.append((size, len(pixels) // (size * size), pixels))
    if len({t[0] for t in tiles}) != 1:
        return None

    size = tiles[0][0]
    rows = []
    for y in range(size):
        row = bytearray()
        for tile_size, bpp, pixels in tiles:
            for x in range(tile_size):
                o = (y * tile_size + x) * bpp
                row += pixels[o:o + 3]
        rows.append(row)
    png = _rgb_png(size * len(tiles), size, rows)
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _rgb_png(width: int, height: int, rows: list[bytearray]) -> bytes:
    """Minimal 8-bit RGB PNG encoder, so a generated image needs no image library.

    Byte constants are spelled as integers rather than escape sequences
    deliberately -- an earlier version written with escapes was corrupted by an
    editing pass that collapsed them into real control bytes, which silently
    produced an unparseable module.
    """
    filter_none = bytes([0])
    raw = b"".join(filter_none + bytes(r) for r in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    signature = bytes([137, 80, 78, 71, 13, 10, 26, 10])
    return (
        signature
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _track_length_miles(entries) -> float | None:
    """The track length the game itself displays, in miles. See track.py."""
    from . import track as track_mod
    return track_mod.length_miles(entries)


def _build_track_path(trk_path, mesh) -> dict | None:
    """The track's AI racing lines as {"forward": [[x,y,z],...], "reverse": ...}.

    Both directions ship with every track: `default.ili` is the forward line
    and `rdefault.ili` the reverse one. They are SEPARATELY AUTHORED, not one
    walked backwards -- point overlap between them is 0-1% on every stock
    track and the point counts differ (Bemidji has 72 forward, 66 reverse) --
    because the quick way round changes when you drive the other way. The
    game's reverse-race option uses the second one.

    Height is sampled from `mesh` per line, since the line format stores no Y
    (see ili.py). A direction missing from the archive is simply omitted.
    """
    try:
        entries = archive.read(trk_path)
    except Exception:
        return None
    if not mesh.vertices:
        return None
    by_name = {e.name.lower(): e for e in entries}
    entry = by_name.get("default.ili")
    if entry is None:
        return None
    try:
        forward = ili.parse(envelope.build(entry.tag, entry.version, entry.payload))
    except Exception:
        return None
    if len(forward) < 4:
        return None

    # Reverse is the forward line walked backwards, NOT the archive's own
    # rdefault.ili. The game ships that as its reverse-direction AI line, and
    # on most tracks it follows the road as well as the forward one does --
    # but on Bemidji it cuts straight across the tri-oval bulge, putting 14 of
    # its 66 waypoints over grass (26% on the road surface against the forward
    # line's 72%). Whatever that line is for, it is not a path a camera can
    # drive. Reversing the forward line is on-road by construction, on every
    # track and any future one.
    reversed_pts = [
        ili.Waypoint(x=p.x, z=p.z, speed=p.speed, distance=0.0)
        for p in reversed(forward)
    ]
    run = 0.0
    for i, wp in enumerate(reversed_pts):
        nxt = reversed_pts[(i + 1) % len(reversed_pts)]
        wp.distance = run
        run += math.hypot(nxt.x - wp.x, nxt.z - wp.z)

    # default.ili's stored order matches the direction the game races the
    # track, so "forward" follows the file and "reverse" walks it backwards.
    # (This was briefly inverted while the scene was accidentally mirrored --
    # a reflection reverses which way a loop appears to be travelled, so the
    # labels had to be swapped to compensate. Restoring the handedness
    # conversion in mod.to_obj() restores the honest mapping.)
    out: dict[str, dict] = {}
    for key, points in (("forward", forward), ("reverse", reversed_pts)):
        # Subdivide before sampling so the path follows crests rather than
        # cutting the chord between sparse waypoints -- see ili.densify().
        points = ili.densify(points)
        # Sampling happens in NATIVE space, against the unconverted mesh, so
        # the .ili's own coordinates are used as-is here...
        heights, normals = ili.sample_surface(points, mesh)
        # ...and only the emitted geometry is converted to the scene's
        # right-handed space, matching what mod.to_obj() does to the mesh. Z
        # negates on positions and on normals alike; Y is untouched, so the
        # sampled heights carry over directly.
        out[key] = {
            "points": [[pt.x, y, -pt.z] for pt, y in zip(points, heights)],
            "speeds": [pt.speed for pt in points],
            # Road surface normal per point, so the drive camera can roll with
            # the banking instead of staying stubbornly level.
            "normals": [[round(n[0], 4), round(n[1], 4), round(-n[2], 4)] for n in normals],
        }
    return out or None


def _build_track_texture_map(trk_path: str | Path, texture_names: set[str]) -> dict[str, str | None]:
    """Like _build_texture_map(), but for a track archive -- a track's textures
    always live in its own .trk (no shared-archive resolution like a car's
    ball.mod/paint texture), so this just looks each name up directly."""
    entries = archive.read(trk_path)
    by_name = {e.name.lower(): e for e in entries}
    data_uris: dict[str, str | None] = {}
    wraps: dict[str, int] = {}
    for name in texture_names:
        entry = by_name.get(name.lower())
        if entry is None:
            data_uris[name] = None
            continue
        raw = envelope.build(entry.tag, entry.version, entry.payload)
        try:
            info = tex.parse(raw)
            png_bytes = tex.tex_to_png_bytes(raw)
        except Exception:
            # Not every material references a .tex -- checkpt1.mod points at
            # .stp (STAMP) entries, for instance. Fall back to a flat color
            # for those rather than failing the whole page.
            data_uris[name] = None
            continue
        data_uris[name] = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
        wraps[name] = info.wrap
    return data_uris, wraps


def _drop_out_of_range_faces(mesh: mod.Mesh) -> mod.Mesh:
    """Return `mesh` with any face referencing a nonexistent vertex removed,
    material face-ranges rebuilt to match.

    Real files can carry junk here: dundas's ground.mod declares 811 faces
    but the first ~126 records hold float data (recognisable 2.0f bit
    patterns) rather than indices, while the remaining 685 are perfectly
    valid and run right up to vertex V-1. Left alone those bogus indices
    reach far past the vertex list and crash the page's mesh builder
    outright, taking the whole track's geometry with them.
    """
    n = len(mesh.vertices)

    def ok(face: tuple[int, int, int]) -> bool:
        # Both bounds matter: face indices are read as SIGNED int16, so junk
        # records holding values above 32767 come back NEGATIVE. Checking
        # only the upper bound lets those straight through, and they surface
        # later as negative OBJ indices that crash the page's mesh builder.
        return min(face) >= 0 and max(face) < n

    if all(ok(f) for f in mesh.faces):
        return mesh
    kept: list[tuple[int, int, int]] = []
    materials: list[mod.Material] = []
    for mat in mesh.materials:
        start = len(kept)
        for face in mesh.faces[mat.face_start:mat.face_end]:
            if ok(face):
                kept.append(face)
        materials.append(mod.Material(mat.name, mat.vertex_start, mat.vertex_end, start, len(kept)))
    return mod.Mesh(vertices=mesh.vertices, materials=materials, faces=kept, version=mesh.version)


def _track_display_name(trk_path: Path) -> str:
    """The slot's in-game name, or the filename stem if it can't be read."""
    try:
        from . import switcher
        name = switcher.read_display_name(trk_path.parent, trk_path.stem)
    except Exception:
        return trk_path.stem
    return name or trk_path.stem


def _track_render_mesh(trk_path: str | Path) -> "mod.Mesh":
    """The track's full drawable mesh: track.grf plus every standalone .mod whose
    materials all resolve to a texture present in the archive, merged into one.

    Shared by the 3D track viewer and the track thumbnail (carshot.track_to_png)
    so both draw exactly the same geometry from one definition.
    """
    trk_path = Path(trk_path)
    entries = archive.read(trk_path)
    grf_entry = next((e for e in entries if e.name.lower() == "track.grf"), None)
    if grf_entry is None:
        raise ValueError(f"no track.grf entry found in {trk_path}")
    grf_mesh = grf.parse(envelope.build(grf_entry.tag, grf_entry.version, grf_entry.payload))

    have = {e.name.lower() for e in entries}
    parts = [grf_mesh.mesh]
    for entry in entries:
        if not entry.name.lower().endswith(".mod"):
            continue
        try:
            part = mod.parse(envelope.build(entry.tag, entry.version, entry.payload))
        except Exception:
            continue  # one odd .mod shouldn't sink the whole page
        # Only merge a standalone .mod if every material it uses resolves to
        # a texture actually present in this archive. dundas's ground.mod
        # fails that test -- its material name is a corrupted "\x00exture.bmp"
        # (leading NUL) pointing at a .bmp that isn't in the archive at all --
        # and merging it painted a huge untextured slab across the whole
        # scene that has no counterpart in 3DSimED's render of the same
        # track. If we can't texture it and the game evidently can, we're
        # misreading it, so leaving it out beats covering the track with it.
        if not part.materials or not all(m.name.lower() in have for m in part.materials):
            continue
        parts.append(_drop_out_of_range_faces(part))
    return mod.merge(parts) if len(parts) > 1 else grf_mesh.mesh


def build_track_viewer_html(trk_path: str | Path, title: str | None = None,
                            view_only: bool = False) -> str:
    """Assemble a track's visual mesh (grf.py, read-only -- see that module's
    docstring for what is and isn't understood yet) into a free-orbit viewer
    with a Textures drawer, mirroring the car shell's Textures drawer/Save
    flow but scoped to just textures (no stats/parts/sounds -- there's no
    write path for the mesh itself yet, only for texture entries).

    track.grf isn't always the whole visible scene: some tracks also carry
    standalone .mod entries in the same archive (dundas has a ground.mod
    holding a big terrain/road slab squarely inside the track's own bounds,
    plus four tracks carry a checkpt1.mod). Those are merged in here, since
    leaving them out shows up directly as missing road/terrain when
    comparing against 3DSimED."""
    trk_path = Path(trk_path)
    entries = archive.read(trk_path)          # kept for the length readout below
    combined = _track_render_mesh(trk_path)

    obj_text, _mtl_text = mod.to_obj(combined, "track.mtl")
    texture_names = {m.name for m in combined.materials if m.name}
    textures, texture_wraps = _build_track_texture_map(trk_path, texture_names)

    html = _TRACK_TEMPLATE
    html = html.replace("__BODY_CLASS__", "view-only" if view_only else "")
    # Label the track the way the switcher does: the in-game display name
    # from english.lng over the actual filename. They diverge as soon as
    # anything is installed into a slot -- a modded track sitting in the
    # bemidji slot is still bemidji.trk on disk -- and the filename is what
    # you need when reaching for the file, while the name is what you
    # recognise. Falls back to the stem when there's no .lng alongside
    # (a .trk opened from anywhere but a game Data folder).
    display_title = title or _track_display_name(trk_path)
    html = html.replace("__TITLE__", html_escape.escape(display_title))
    html = html.replace("__TRACK_FILE__", html_escape.escape(trk_path.name))
    html = html.replace("__OBJ_JSON__", json.dumps(obj_text))
    html = html.replace("__TEXTURES_JSON__", json.dumps(textures))
    html = html.replace("__TEXTURE_WRAPS_JSON__", json.dumps(texture_wraps))
    html = html.replace("__SKY_URI_JSON__", json.dumps(_build_sky_panorama(trk_path)))
    html = html.replace("__PATHS_JSON__", json.dumps(_build_track_path(trk_path, combined)))
    html = html.replace("__TRACK_MI_JSON__", json.dumps(_track_length_miles(entries)))
    html = html.replace("__TRACK_PATH_JSON__", json.dumps(str(trk_path)))
    return html


def write_track_viewer_html(trk_path: str | Path, out_path: str | Path, title: str | None = None) -> None:
    html = build_track_viewer_html(trk_path, title=title)
    Path(out_path).write_text(html, encoding="utf-8")


def write_viewer_html(
    car_path: str | Path, out_path: str | Path, z_offset: float = 0.0,
    wheel_radius: float | None = None, paint_texture: str | Path | None = None,
) -> None:
    html = build_viewer_html(
        car_path, z_offset=z_offset, wheel_radius=wheel_radius, paint_texture=paint_texture
    )
    Path(out_path).write_text(html, encoding="utf-8")


@dataclass
class GalleryCarEntry:
    display_name: str
    car_path: Path
    html_filename: str
    error: str | None = None  # set if this car failed to assemble -- shown, not hidden


@dataclass
class GalleryTrackEntry:
    display_name: str
    track_path: Path
    html_filename: str
    error: str | None = None  # set if this track failed to parse -- shown, not hidden


@dataclass
class GalleryResult:
    cars: list[GalleryCarEntry] = field(default_factory=list)
    tracks: list[GalleryTrackEntry] = field(default_factory=list)
    resource_archive_count: int = 0

    @property
    def track_files(self) -> list[Path]:
        """Back-compat with callers that just wanted the paths."""
        return [t.track_path for t in self.tracks]


_GALLERY_TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8">
<title>__TITLE__</title>
<style>
  html,body{margin:0;background:#1a1a1a;color:#e8eaf2;font-family:system-ui,sans-serif}
  body{padding:24px 32px 48px}
  h1{margin:0 0 4px;font-size:1.4rem}
  .source{font-size:.8rem;color:#8a90a4;margin-bottom:24px;word-break:break-all}
  h2{font-size:.85rem;text-transform:uppercase;letter-spacing:.05em;color:#8a90a4;
     margin:28px 0 12px;border-bottom:1px solid #333;padding-bottom:6px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}
  .card{background:#20242c;border:1px solid #333;border-radius:8px;padding:14px;
        text-decoration:none;color:#e8eaf2;display:block}
  .card:hover{border-color:#1911ab;background:#242836}
  .card .name{font-weight:600;font-size:.95rem;margin-bottom:4px}
  .card .path{font-size:.7rem;color:#8a90a4;word-break:break-all}
  .card.error{border-color:#5a2020;background:#241a1a;cursor:default}
  .card.error .name{color:#d99}
  .card.error .path{color:#a88}
  ul{margin:0;padding-left:20px;font-size:.85rem;color:#c4c8d8}
  li{margin-bottom:4px;word-break:break-all}
  .note{font-size:.8rem;color:#8a90a4}
  .empty{font-size:.85rem;color:#8a90a4;font-style:italic}
</style>
</head><body>
<h1>__TITLE__</h1>
<div class="source">scanned __DATA_DIR__</div>

<h2>Cars (__CAR_OK_COUNT__/__CAR_TOTAL_COUNT__)</h2>
__CARS_HTML__

<h2>Tracks (__TRACK_OK_COUNT__/__TRACK_TOTAL_COUNT__)</h2>
__TRACKS_HTML__

<h2>Shared resource archives</h2>
<div class="note">__RES_COUNT__ found (race.res, common.res, etc.) -- these hold assets shared across cars/tracks rather than being browsable on their own; use <code>unpack</code>/<code>list</code>/<code>partview</code> to dig into one directly.</div>
</body></html>
"""


def _render_gallery_index(data_dir: Path, result: GalleryResult, title: str) -> str:
    def esc(s: str) -> str:
        return html_escape.escape(str(s))

    if result.cars:
        cards = []
        for c in result.cars:
            rel = c.car_path.relative_to(data_dir)  # always a descendant -- came from data_dir.rglob()
            if c.error is None:
                cards.append(
                    f'<a class="card" href="{esc(c.html_filename)}">'
                    f'<div class="name">{esc(c.display_name)}</div>'
                    f'<div class="path">{esc(rel)}</div></a>'
                )
            else:
                cards.append(
                    f'<div class="card error">'
                    f'<div class="name">{esc(c.display_name)} (failed)</div>'
                    f'<div class="path">{esc(rel)}<br>{esc(c.error)}</div></div>'
                )
        cars_html = f'<div class="grid">{"".join(cards)}</div>'
    else:
        cars_html = '<div class="empty">no .car files found</div>'

    if result.tracks:
        cards = []
        for t in result.tracks:
            rel = t.track_path.relative_to(data_dir)
            if t.error is None:
                cards.append(
                    f'<a class="card" href="{esc(t.html_filename)}">'
                    f'<div class="name">{esc(t.display_name)}</div>'
                    f'<div class="path">{esc(rel)}</div></a>'
                )
            else:
                cards.append(
                    f'<div class="card error">'
                    f'<div class="name">{esc(t.display_name)} (failed)</div>'
                    f'<div class="path">{esc(rel)}<br>{esc(t.error)}</div></div>'
                )
        tracks_html = f'<div class="grid">{"".join(cards)}</div>'
    else:
        tracks_html = '<div class="empty">no .trk files found</div>'

    ok_count = sum(1 for c in result.cars if c.error is None)
    track_ok = sum(1 for t in result.tracks if t.error is None)
    html_out = _GALLERY_TEMPLATE
    html_out = html_out.replace("__TITLE__", esc(title))
    html_out = html_out.replace("__DATA_DIR__", esc(data_dir))
    html_out = html_out.replace("__CAR_OK_COUNT__", str(ok_count))
    html_out = html_out.replace("__CAR_TOTAL_COUNT__", str(len(result.cars)))
    html_out = html_out.replace("__CARS_HTML__", cars_html)
    html_out = html_out.replace("__TRACK_OK_COUNT__", str(track_ok))
    html_out = html_out.replace("__TRACK_TOTAL_COUNT__", str(len(result.tracks)))
    html_out = html_out.replace("__TRACKS_HTML__", tracks_html)
    html_out = html_out.replace("__RES_COUNT__", str(result.resource_archive_count))
    return html_out


def build_gallery(
    data_dir: str | Path, out_dir: str | Path,
    paint_dir: str | Path | None = None, title: str | None = None,
) -> GalleryResult:
    """Scan data_dir (recursively, no assumptions about folder layout or naming --
    real installs mix stock and user-modded files side by side with nothing
    distinguishing them) for .car AND .trk files, write one page per car (the
    full shell) and one per track (the free-orbit track viewer with its
    Textures drawer), plus an index.html gallery linking to all of them.
    Shared .res archives are just counted, since they're not meaningful to
    browse from an index (that's what unpack/list/partview are for).

    A car or track that fails to load (missing .cf, unexpected layout, an
    unparsable track.grf, etc.) is recorded with its error rather than
    silently dropped or aborting the whole scan -- one bad file in a folder
    full of good ones shouldn't hide the rest.

    Car and track pages share one filename pool, so a bemidji.car sitting
    next to a bemidji.trk can't silently overwrite each other's page.
    """
    data_dir = Path(data_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    car_paths = sorted(data_dir.rglob("*.car"))
    # .tra is the same 0TSR container as .trk, just a different extension --
    # confirmed byte-identical in structure against a real fan-made track
    # (Telly), which carries the same track.grf/.bpp/.sol/.obt members.
    track_paths = sorted([*data_dir.rglob("*.trk"), *data_dir.rglob("*.tra")])
    resource_paths = sorted(data_dir.rglob("*.res"))

    used_names: set[str] = set()

    def _claim(stem: str) -> str:
        name, i = stem, 2
        while name in used_names:
            name = f"{stem}_{i}"
            i += 1
        used_names.add(name)
        return f"{name}.html"

    cars: list[GalleryCarEntry] = []
    for car_path in car_paths:
        stem = car_path.stem
        html_filename = _claim(stem)
        try:
            write_shell_html(car_path, out_dir / html_filename, paint_dir=paint_dir)
            cars.append(GalleryCarEntry(display_name=stem, car_path=car_path, html_filename=html_filename))
        except Exception as e:
            cars.append(
                GalleryCarEntry(display_name=stem, car_path=car_path, html_filename=html_filename, error=str(e))
            )

    tracks: list[GalleryTrackEntry] = []
    for track_path in track_paths:
        stem = track_path.stem
        html_filename = _claim(stem)
        try:
            write_track_viewer_html(track_path, out_dir / html_filename)
            tracks.append(
                GalleryTrackEntry(display_name=stem, track_path=track_path, html_filename=html_filename)
            )
        except Exception as e:
            tracks.append(
                GalleryTrackEntry(
                    display_name=stem, track_path=track_path, html_filename=html_filename, error=str(e)
                )
            )

    result = GalleryResult(cars=cars, tracks=tracks, resource_archive_count=len(resource_paths))
    index_html = _render_gallery_index(data_dir, result, title or f"{data_dir.name} gallery")
    (out_dir / "index.html").write_text(index_html, encoding="utf-8")
    return result


# ---------------------------------------------------------------------------
# Bundle three.js for offline use.
#
# Every 3D template loads three.js r128 from cdnjs. For the standalone app (and
# any offline use) we inline a bundled copy at import time so the viewers work
# with no internet. If the bundled file is missing, the original CDN <script src>
# is left untouched, so an online run still works -- nothing is lost either way.
# This runs once here, after all templates are defined, and every build_* helper
# inherits the inlined version because they read these module globals at call time.
# ---------------------------------------------------------------------------
_THREE_CDN_TAG = (
    '<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>'
)


def _threejs_inline_tag() -> str | None:
    """The bundled three.js wrapped in an inline <script>, or None if absent."""
    p = Path(__file__).parent / "assets" / "three.min.js"
    try:
        return "<script>" + p.read_text(encoding="utf-8") + "</script>"
    except OSError:
        return None


_three_inline = _threejs_inline_tag()
if _three_inline is not None:
    _TEMPLATE = _TEMPLATE.replace(_THREE_CDN_TAG, _three_inline)
    _PART_TEMPLATE = _PART_TEMPLATE.replace(_THREE_CDN_TAG, _three_inline)
    _SHELL_TEMPLATE = _SHELL_TEMPLATE.replace(_THREE_CDN_TAG, _three_inline)
    _TRACK_TEMPLATE = _TRACK_TEMPLATE.replace(_THREE_CDN_TAG, _three_inline)
