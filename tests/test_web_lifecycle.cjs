/* Tests du vrai contrôleur web avec média/transport simulés, sans caméra. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { CaptureClock, landmarkPosition } = require('../apps/web/capture-core.js');

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}
function environment(customFetch) {
  const elements = new Map(), events = new Map(), requests = [], timers = new Map();
  let nextTimer = 0, nextSession = 0;
  const frame = { sequence: 0, angle_deg: 90, quality_reason: null, pose: null };
  class Element {
    constructor(id) {
      this.id = id; this.disabled = false; this.hidden = false; this.value = id === 'side' ? 'left' : '';
      this.textContent = ''; this.checked = false; this.readyState = 2; this.videoWidth = 640;
      this.videoHeight = 480; this.currentTime = 0; this.duration = 4; this.files = [];
      this.handlers = new Map();
      this.classList = { add() {}, remove() {}, toggle() {} };
    }
    addEventListener(name, fn) { this.handlers.set(name, fn); }
    removeEventListener(name) { this.handlers.delete(name); }
    getContext() { return { drawImage() {} }; }
    toBlob(fn) { fn(new Blob(['jpeg'], { type: 'image/jpeg' })); }
    play() { this.paused = false; return Promise.resolve(); }
    pause() { this.paused = true; }
    load() {}
    removeAttribute() {}
    replaceChildren() {}
    click() { return this.handlers.get('click')?.(); }
  }
  const get = (id) => { if (!elements.has(id)) elements.set(id, new Element(id)); return elements.get(id); };
  const defaultFetch = async (path, options) => {
    if (path === '/api/status') return { pose_mode: 'synthetic_demo', models: [] };
    if (path === '/api/session/start') return { session_id: `session-${++nextSession}`, token: 'private-token' };
    if (path === '/api/frame') return frame;
    if (path === '/api/session/finish') return {
      measurement: { status: 'valid', value_deg: 90, valid_frame_count: 3, total_frame_count: 3 },
      motion: { duration_ms: 400, samples: [], processing_rate_hz: 5, processed_frames: 3 },
      evidence_sequence: null, evidence_timestamp_ms: null, draft: 'BROUILLON NON VALIDÉ',
    };
    if (path === '/api/session/evidence') return { jpeg_base64: null };
    return { cancelled: true };
  };
  const sandbox = {
    document: { getElementById: get, createElement: () => new Element(), hidden: false,
      addEventListener: (name, fn) => events.set(name, fn) },
    window: { addEventListener: (name, fn) => events.set(name, fn) },
    navigator: { sendBeacon() {} }, performance: { now: () => 1000 },
    KineCapture: { CaptureClock, landmarkPosition }, KineGuide: { drawPose() {}, drawChart() {}, setSide() {}, toggle() {} },
    ResizeObserver: class { observe() {} }, AbortController, Blob, Uint8Array, atob,
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL() {} },
    setTimeout: (fn) => { const id = ++nextTimer; timers.set(id, fn); return id; },
    clearTimeout: (id) => timers.delete(id), setInterval: (fn) => { const id = ++nextTimer; timers.set(id, fn); return id; },
    clearInterval: (id) => timers.delete(id),
    fetch: async (path, options = {}) => {
      requests.push({ path, options });
      const body = await (customFetch?.(path, options) ?? defaultFetch(path, options));
      return { ok: true, json: async () => body };
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(require.resolve('../apps/web/app.js'), 'utf8'), sandbox);
  return { get, sandbox, requests, run: (code) => vm.runInContext(code, sandbox) };
}
const settle = () => new Promise((resolve) => setImmediate(resolve));
async function prepareFile(env) {
  await settle();
  await env.run('prepare("file", {type:"video/mp4", size:100})');
  assert.equal(env.get('record').disabled, false);
}

test('preview does not create a session; file clock sends source timestamps', async () => {
  const env = environment();
  await prepareFile(env);
  assert.equal(env.requests.filter((r) => r.path === '/api/session/start').length, 0);
  await env.run('startTrial()');
  env.get('preview').currentTime = 0.2;
  await env.run('sampleFrame()');
  await env.run('sampleFrame()'); // same source frame is skipped
  const frames = env.requests.filter((r) => r.path === '/api/frame');
  assert.deepEqual(frames.map((r) => r.options.headers['X-Timestamp-Ms']), ['0', '200']);
  await env.run('cancelSession()');
});
test('double start is guarded even before session response', async () => {
  const response = deferred();
  const env = environment((path) => path === '/api/session/start' ? response.promise : undefined);
  await prepareFile(env);
  const first = env.run('startTrial()');
  await env.run('startTrial()');
  assert.equal(env.requests.filter((r) => r.path === '/api/session/start').length, 1);
  response.resolve({ session_id: 'one', token: 'secret' });
  await first;
  await env.run('cancelSession()');
});
test('cancel before camera permission completes stops the late stream', async () => {
  const camera = deferred();
  const env = environment();
  let stopped = false;
  env.sandbox.navigator.mediaDevices = { getUserMedia: () => camera.promise };
  await settle();
  const preparation = env.run('prepare("camera")');
  await settle();
  await env.run('cancelSession()');
  camera.resolve({ getTracks: () => [{ stop: () => { stopped = true; } }] });
  await preparation;
  assert.equal(stopped, true);
  assert.equal(env.get('record').disabled, true);
});
test('immediate stop releases media before pending frame response and rejects trial', async () => {
  const frame = deferred();
  const env = environment((path) => path === '/api/frame' ? frame.promise : undefined);
  await prepareFile(env);
  const starting = env.run('startTrial()');
  await settle();
  const finishing = env.run('finishSession(true)');
  assert.equal(env.get('preview').paused, true);
  frame.resolve({ sequence: 0, angle_deg: 90, quality_reason: null, pose: null });
  await starting; await finishing;
  const finishRequest = env.requests.find((r) => r.path === '/api/session/finish');
  assert.equal(JSON.parse(finishRequest.options.body).stopped, true);
  await env.run('cancelSession()');
});
test('late LLM response cannot populate the next trial', async () => {
  const note = deferred();
  const env = environment((path) => path === '/api/harness/draft' ? note.promise : undefined);
  await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
  const writing = env.get('llm-draft').click();
  await settle(); await env.run('cancelSession()');
  note.resolve({ proposed_note: 'OLD SESSION NOTE', image_sent: false });
  await writing;
  assert.equal(env.get('llm-note').textContent, '');
  assert.equal(env.get('results').hidden, true);
});
test('exportable structured result contains neither token nor pixels', async () => {
  const env = environment();
  await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
  const exported = env.run('JSON.stringify(resultDocument)');
  assert.ok(exported.includes('synthetic_demo'));
  assert.ok(!exported.includes('private-token'));
  assert.ok(!exported.includes('jpeg_base64'));
  await env.run('cancelSession()');
});
