// A small pool of render workers. Thumbnails are CPU-bound software renders, so
// running a worker per core turns a serial N-thumbnail wait into ~N/cores.
// De-risked at ~3.4x on 4 workers (see the project notes).
class RenderPool {
  constructor(workerUrl, size){
    this.workerUrl = workerUrl;
    this.size = size || Math.min(navigator.hardwareConcurrency || 4, 4);
    this.workers = [];
    this._job = 0;
    this._free = [];          // idle workers ready for a job
    this._waiting = [];       // resolvers waiting for a worker to free up
  }

  // Spin up the workers and load Pyodide+vrmod in each (parallel). raceRes (an
  // ArrayBuffer or null) is the shared car texture archive, written once per
  // worker so individual car renders only need to ship the .car itself.
  async init(raceRes){
    this.workers = Array.from({length:this.size}, () => new Worker(this.workerUrl));
    await Promise.all(this.workers.map((w, id) => new Promise((resolve, reject) => {
      w.onmessage = e => {
        if (e.data.type === "ready"){ w.onmessage = null; resolve(e.data.ms); }
        else if (e.data.type === "error"){ w.onmessage = null; reject(new Error(e.data.error)); }
      };
      // Each worker needs its own copy of race.res (structured-clone, so slice()).
      w.postMessage({type:"init", id, raceRes: raceRes ? raceRes.slice(0) : null});
    })));
    this._free = [...this.workers];
    return this.size;
  }

  async _acquire(){
    if (this._free.length) return this._free.pop();
    return new Promise(res => this._waiting.push(res));
  }
  _release(w){
    const next = this._waiting.shift();
    if (next) next(w); else this._free.push(w);
  }

  // Render one thumbnail. bytes is an ArrayBuffer (the .car/.trk); it's transferred
  // to the worker, so pass a copy if you still need it on this side.
  async render(kind, name, bytes){
    const w = await this._acquire();
    const jobId = this._job++;
    try {
      return await new Promise((resolve, reject) => {
        const h = e => {
          if (e.data.type === "result" && e.data.jobId === jobId){
            w.removeEventListener("message", h);
            e.data.error ? reject(new Error(e.data.error)) : resolve(e.data.png);
          }
        };
        w.addEventListener("message", h);
        w.postMessage({type:"render", jobId, kind, name, bytes}, [bytes]);
      });
    } finally {
      this._release(w);
    }
  }

  terminate(){ this.workers.forEach(w => w.terminate()); this.workers = []; this._free = []; }
}
