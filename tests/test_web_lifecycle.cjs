/* Tests du vrai contrôleur web avec média/transport simulés, sans caméra. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { CaptureClock, CaptureWatchdog, browserTrace, landmarkPosition } = require('../apps/web/capture-core.js');

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}
function environment(customFetch) {
  const elements = new Map(), events = new Map(), requests = [], timers = new Map(), timerDelays = new Map();
  const beacons = [];
  let nextTimer = 0, nextSession = 0;
  const frame = { sequence: 0, angle_deg: 90, quality_reason: null, pose: null };
  class Element {
    constructor(id) {
      this.id = id; this.disabled = false; this.hidden = false; this.value = id === 'side' ? 'left' : '';
      this.textWrites = 0; this.textContent = ''; this.checked = false; this.readyState = 2; this.videoWidth = 640;
      this.videoHeight = 480; this.currentTime = 0; this.duration = 4; this.files = [];
      this.handlers = new Map();
      this.dataset = {};
      this.classList = { add() {}, remove() {}, toggle() {} };
    }
    set textContent(value) { this.content = value; this.textWrites += 1; }
    get textContent() { return this.content; }
    addEventListener(name, fn) { this.handlers.set(name, fn); }
    removeEventListener(name) { this.handlers.delete(name); }
    getContext() { return { drawImage() {} }; }
    toBlob(fn) { fn(new Blob(['jpeg'], { type: 'image/jpeg' })); }
    play() { this.paused = false; return Promise.resolve(); }
    pause() { this.paused = true; }
    load() {}
    removeAttribute() {}
    setAttribute() {}
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
    navigator: { sendBeacon: (path, body) => { beacons.push({ path, body }); return true; } }, performance: { now: () => 1000 },
    KineCapture: { CaptureClock, CaptureWatchdog, browserTrace, landmarkPosition }, KineGuide: { drawPose() {}, drawChart() {}, setSide() {}, setProtocol() {} },
    ResizeObserver: class { observe() {} }, AbortController, Blob, Uint8Array, atob,
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL() {} },
    setTimeout: (fn, delay) => { const id = ++nextTimer; timers.set(id, fn); timerDelays.set(id, delay); return id; },
    clearTimeout: (id) => timers.delete(id), setInterval: (fn) => { const id = ++nextTimer; timers.set(id, fn); return id; },
    clearInterval: (id) => timers.delete(id),
    fetch: async (path, options = {}) => {
      requests.push({ path, options });
      const body = await (customFetch?.(path, options) ?? defaultFetch(path, options));
      return { ok: !body.__httpStatus, status: body.__httpStatus || 200, json: async () => body };
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(require.resolve('../apps/web/app.js'), 'utf8'), sandbox);
  return { get, sandbox, requests, timers, timerDelays, events, beacons, run: (code) => vm.runInContext(code, sandbox) };
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
test('selected protocol is sent to the server and capture view must be reconfirmed', async () => {
  const env = environment();
  await prepareFile(env);
  env.get('view-confirmed').checked = true;
  env.run('protocols.push({id:"knee_flexion_active",label:"Genou",view:"profil",framing:"Hanche, genou, cheville",guide:"knee",quantified:true,harness_supported:false})');
  env.get('protocol').value = 'knee_flexion_active';
  await env.get('protocol').handlers.get('change')();
  assert.equal(env.get('view-confirmed').checked, false);
  assert.equal(env.get('record').disabled, false);
  await env.run('startTrial()');
  assert.equal(JSON.parse(env.requests.find((r) => r.path === '/api/session/start').options.body).protocol_id, 'knee_flexion_active');
  assert.equal(env.get('protocol').disabled, true);
  await env.run('finishSession(false)');
  assert.equal(env.get('llm-draft').disabled, true);
  await env.get('llm-draft').click();
  assert.equal(env.requests.filter((r) => r.path === '/api/harness/draft').length, 0);
  assert.equal(env.run('resultDocument.protocol.id'), 'knee_flexion_active');
  await env.run('cancelSession()');
});
test('neck rotation is guide only and never displays a measured angle curve', async () => {
  const env = environment((path) => path === '/api/session/finish' ? {
    measurement: { status: 'rejected', value_deg: null, valid_frame_count: 0, total_frame_count: 3 },
    motion: { duration_ms: 400, samples: [], processing_rate_hz: 5, processed_frames: 3 },
    evidence_sequence: null, evidence_timestamp_ms: null, draft: 'Rotation non quantifiée en 2D',
  } : undefined);
  await prepareFile(env);
  env.run('protocols.push({id:"neck_rotation_guided",label:"Cou",view:"face",framing:"Tête et épaules",guide:"neck_turn",quantified:false,harness_supported:false})');
  env.get('protocol').value = 'neck_rotation_guided';
  await env.get('protocol').handlers.get('change')();
  await env.run('startTrial()'); await env.run('finishSession(false)');
  assert.equal(env.get('angle-result').textContent, '—');
  assert.equal(env.get('chart-wrap').hidden, true);
  assert.equal(env.get('coverage-result').textContent, 'Non quantifié');
  assert.equal(env.get('measurement-status').textContent, 'Guide seul · sans mesure');
  await env.run('cancelSession()');
});
test('previous protocol result is removed when switching to a different movement', async () => {
  const env = environment();
  await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
  await env.get('protocol').handlers.get('change')();
  assert.equal(env.get('results').hidden, true);
  assert.equal(env.run('session'), null);
  assert.equal(env.run('resultDocument'), null);
});
test('pose overlay expires even while the next network request is pending', async () => {
  const env = environment((path) => path === '/api/frame' ? { sequence: 0, angle_deg: 90, quality_reason: null, pose: {points:[]} } : undefined);
  await prepareFile(env); await env.run('startTrial()');
  assert.notEqual(env.run('latestPose'), null);
  const expiry = env.run('poseExpiryTimer');
  env.timers.get(expiry)();
  assert.equal(env.run('latestPose'), null);
  assert.ok(env.get('live-feedback').textContent.includes('expirés'));
  await env.run('cancelSession()');
});

const liveLimits = { window_ms: 5000, max_samples: 25, max_images: 2, poll_interval_ms: 1000,
  inference_interval_ms: 3000, result_ttl_ms: 10000 };
function liveEnvironment(customFetch) {
  return environment((path, options) => {
    if (path === '/api/status') return { pose_mode: 'mediapipe_experimental', live_harness: liveLimits, models: [
      { id: 'gpt_oss', label: 'GPT-OSS', configured: true, image_enabled: false },
      { id: 'qwen36', label: 'Qwen 3.6', configured: true, image_enabled: true },
    ] };
    if (path === '/api/models/check') return { model_id: JSON.parse(options.body).model_id, state: 'ready' };
    if (path === '/api/harness/live/poll') return customFetch?.(path, options) ?? {
      state: 'warming_up', window: null, result: null, result_age_ms: null,
    };
    return customFetch?.(path, options);
  });
}
function liveObservation(text = 'Le mouvement reste à vérifier.') {
  return { state: 'ready', window: { window_ref: 'window-1', start_timestamp_ms: 0, end_timestamp_ms: 600,
    sample_count: 4, image_count: 0 }, result_age_ms: 50,
    result: { window_ref: 'window-1', start_timestamp_ms: 0, end_timestamp_ms: 600, observation_code: 'pose_visible',
      text, tool_names: [], fallback_reason: null, image_count: 0, requires_professional_review: true, provisional: true } };
}
async function enableLiveAssistant(env) {
  await env.get('check-model').click();
  assert.equal(env.get('live-assistant').disabled, false);
  env.get('live-assistant').checked = true;
  await env.get('live-assistant').handlers.get('change')();
}
test('live assistant is opt-in and requires a configured, advertised model alias', async () => {
  const env = liveEnvironment();
  await prepareFile(env);
  assert.equal(env.get('live-assistant').checked, false);
  assert.equal(env.get('live-assistant').disabled, true);
  await env.get('check-model').click();
  assert.equal(env.get('live-assistant').disabled, false);
  assert.ok(env.get('model-status').textContent.includes('non validés'));
  await env.run('startTrial()');
  assert.equal(env.requests.filter((r) => r.path === '/api/harness/live/poll').length, 0);
  await env.run('cancelSession()');
});
test('a pending live poll neither blocks capture nor starts concurrent polls', async () => {
  const response = deferred();
  const env = liveEnvironment((path) => path === '/api/harness/live/poll' ? response.promise : undefined);
  await prepareFile(env); await enableLiveAssistant(env);
  assert.equal(env.requests.filter((r) => r.path === '/api/harness/live/poll').length, 0);
  await env.run('startTrial()');
  env.get('preview').currentTime = 0.2;
  await env.run('sampleFrame()');
  await env.run('pollLiveAssistant()'); await env.run('pollLiveAssistant()');
  assert.equal(env.requests.filter((r) => r.path === '/api/frame').length, 2);
  assert.equal(env.requests.filter((r) => r.path === '/api/harness/live/poll').length, 1);
  assert.equal(env.run('phase'), 'recording');
  await env.run('cancelSession()'); response.resolve(liveObservation()); await settle();
});
test('live observation names its analysed interval and is never added to final exports', async () => {
  const env = liveEnvironment((path) => path === '/api/harness/live/poll' ? liveObservation('LIVE-ONLY OBSERVATION') : undefined);
  await prepareFile(env); await enableLiveAssistant(env); await env.run('startTrial()'); await settle();
  assert.equal(env.get('live-assistant-return').hidden, false);
  assert.equal(env.get('live-assistant-text').textContent, 'Repères visibles');
  assert.ok(env.get('live-assistant-window').textContent.includes('0.0–0.6 s'));
  assert.equal(env.get('live-assistant-freshness').textContent, 'Âge 1 s');
  assert.ok(env.get('live-assistant-detail').textContent.includes('Vue et stabilité à vérifier'));
  assert.equal(env.get('llm-note').textContent, '');
  await env.run('finishSession(false)');
  assert.equal(env.get('live-assistant-return').hidden, true);
  assert.equal(env.get('live-assistant').checked, false);
  const exported = env.run('JSON.stringify(resultDocument)');
  assert.ok(!exported.includes('LIVE-ONLY OBSERVATION'));
  assert.ok(!exported.includes('window-1'));
  assert.ok(!env.get('draft').textContent.includes('LIVE-ONLY OBSERVATION'));
  await env.run('cancelSession()');
});
test('expired live observations disappear even with a subsequent poll still pending', async () => {
  let calls = 0;
  const response = deferred();
  const env = liveEnvironment((path) => path === '/api/harness/live/poll' ? ++calls === 1 ? liveObservation() : response.promise : undefined);
  await prepareFile(env); await enableLiveAssistant(env); await env.run('startTrial()'); await settle();
  const nextPoll = env.run('pollLiveAssistant()');
  const expiry = env.run('liveResultExpiryTimer');
  env.timers.get(expiry)();
  assert.equal(env.get('live-assistant-return').hidden, true);
  assert.equal(env.get('live-assistant-text').textContent, '');
  assert.ok(env.get('live-assistant-status').textContent.includes('expirée'));
  await env.run('cancelSession()'); response.resolve(liveObservation()); await nextPoll;
});
test('warming up with too few recent samples immediately hides the previous observation', async (t) => {
  for (const sampleCount of [0, 2]) await t.test(`recent sample count ${sampleCount}`, async () => {
    let calls = 0;
    const env = liveEnvironment((path) => path === '/api/harness/live/poll' ? ++calls === 1 ? liveObservation() : {
      state: 'warming_up', window: { window_ref: 'new-window', sample_count: sampleCount },
      result: null, result_age_ms: 500,
    } : undefined);
    await prepareFile(env); await enableLiveAssistant(env); await env.run('startTrial()'); await settle();
    assert.equal(env.get('live-assistant-return').hidden, false);
    await env.run('pollLiveAssistant()');
    assert.equal(env.get('live-assistant-return').hidden, true);
    assert.equal(env.get('live-assistant-text').textContent, '');
    assert.equal(env.run('liveResultExpiryTimer'), null);
    assert.equal(env.run('phase'), 'recording');
    await env.run('cancelSession()');
  });
});
test('failed polling leaves capture active and does not cancel the session', async () => {
  const env = liveEnvironment((path) => path === '/api/harness/live/poll' ? Promise.reject(new Error('LLM absent')) : undefined);
  await prepareFile(env); await enableLiveAssistant(env); await env.run('startTrial()'); await settle();
  assert.equal(env.run('phase'), 'recording');
  assert.ok(env.get('live-assistant-status').textContent.includes('caméra maintenue'));
  assert.equal(env.requests.filter((r) => r.path === '/api/session/cancel').length, 0);
  env.get('preview').currentTime = 0.2; await env.run('sampleFrame()');
  assert.equal(env.requests.filter((r) => r.path === '/api/frame').length, 2);
  await env.run('cancelSession()');
});
test('unchecking live assistant aborts polling, revokes the server window and ignores late replies', async () => {
  const response = deferred();
  const env = liveEnvironment((path) => path === '/api/harness/live/poll' ? response.promise : undefined);
  await prepareFile(env); await enableLiveAssistant(env); await env.run('startTrial()');
  const poll = env.requests.find((r) => r.path === '/api/harness/live/poll');
  env.get('live-assistant').checked = false;
  await env.get('live-assistant').handlers.get('change')();
  assert.equal(poll.options.signal.aborted, true);
  assert.equal(env.requests.filter((r) => r.path === '/api/harness/live/stop').length, 1);
  const stop = env.requests.find((r) => r.path === '/api/harness/live/stop');
  assert.ok(JSON.parse(stop.options.body).control_version > JSON.parse(poll.options.body).control_version);
  response.resolve(liveObservation('LATE')); await settle();
  assert.equal(env.get('live-assistant-return').hidden, true);
  assert.equal(env.get('live-assistant-text').textContent, '');
  assert.equal(env.run('phase'), 'recording');
  await env.run('cancelSession()');
});
test('changing model suspends live assistant until explicit opt-in and rejects old replies', async () => {
  const response = deferred();
  const env = liveEnvironment((path) => path === '/api/harness/live/poll' ? response.promise : undefined);
  await prepareFile(env); await enableLiveAssistant(env); await env.run('startTrial()');
  env.get('llm-model').value = 'qwen36'; await env.get('llm-model').handlers.get('change')();
  assert.equal(env.get('live-assistant').checked, false);
  assert.equal(env.get('live-assistant').disabled, true);
  response.resolve(liveObservation('OLD MODEL')); await settle();
  assert.equal(env.get('live-assistant-return').hidden, true);
  await env.get('check-model').click();
  assert.equal(env.get('live-assistant').disabled, false);
  assert.equal(env.get('live-assistant').checked, false);
  await env.run('cancelSession()');
});
test('recent images require both server capability and explicit consent; consent changes suspend polling', async () => {
  const env = liveEnvironment();
  await prepareFile(env); await enableLiveAssistant(env);
  env.get('include-image').checked = true; // Forced state cannot bypass GPT-OSS text-only capability.
  await env.run('startTrial()'); await settle();
  const first = env.requests.find((r) => r.path === '/api/harness/live/poll');
  assert.equal(JSON.parse(first.options.body).include_image, false);
  env.get('llm-model').value = 'qwen36'; await env.get('llm-model').handlers.get('change')();
  env.get('include-image').checked = true; await env.get('include-image').handlers.get('change')();
  assert.equal(env.get('live-assistant').checked, false);
  await enableLiveAssistant(env); await settle();
  const polls = env.requests.filter((r) => r.path === '/api/harness/live/poll');
  assert.equal(JSON.parse(polls.at(-1).options.body).include_image, true);
  env.get('include-image').checked = false; await env.get('include-image').handlers.get('change')();
  assert.equal(env.get('live-assistant').checked, false);
  assert.equal(env.get('live-assistant-return').hidden, true);
  assert.equal(env.run('phase'), 'recording');
  await env.run('cancelSession()');
});
test('finish, cancellation and pagehide discard late live observations', async (t) => {
  for (const action of ['finish', 'cancel', 'pagehide']) await t.test(action, async () => {
    const response = deferred();
    const env = liveEnvironment((path) => path === '/api/harness/live/poll' ? response.promise : undefined);
    await prepareFile(env); await enableLiveAssistant(env); await env.run('startTrial()');
    if (action === 'finish') await env.run('finishSession(false)');
    if (action === 'cancel') await env.run('cancelSession()');
    if (action === 'pagehide') env.events.get('pagehide')();
    response.resolve(liveObservation('LATE AFTER EXIT')); await settle();
    assert.equal(env.get('live-assistant-return').hidden, true);
    assert.equal(env.get('live-assistant-text').textContent, '');
    assert.equal(env.get('live-assistant').checked, false);
    if (action === 'pagehide') {
      const stopBeacon = env.beacons.find((entry) => entry.path === '/api/harness/live/stop');
      assert.ok(stopBeacon);
      const document = JSON.parse(await stopBeacon.body.text());
      const poll = env.requests.find((r) => r.path === '/api/harness/live/poll');
      assert.ok(document.control_version > JSON.parse(poll.options.body).control_version);
    }
    await env.run('cancelSession()');
  });
});
test('pagehide resets cached capture state without automatic restart, duplicate stop fetches or late poses', async () => {
  const frame = deferred(), observation = deferred();
  let frames = 0;
  const env = liveEnvironment((path) => {
    if (path === '/api/harness/live/poll') return observation.promise;
    if (path === '/api/frame') return ++frames === 1 ? {
      sequence: 0, angle_deg: 90, quality_reason: null, pose: { points: [] },
    } : frame.promise;
    return undefined;
  });
  await prepareFile(env); await enableLiveAssistant(env); await env.run('startTrial()');
  assert.notEqual(env.run('latestPose'), null);
  env.get('preview').currentTime = 0.2;
  const sampling = env.run('sampleFrame()'); await settle();
  const oldEpoch = env.run('epoch');
  env.get('include-image').checked = true;
  env.events.get('pagehide')();
  assert.equal(env.run('phase'), 'idle');
  assert.ok(env.run('epoch') > oldEpoch);
  assert.equal(env.run('session'), null);
  assert.equal(env.run('source'), null);
  assert.equal(env.run('latestPose'), null);
  assert.equal(env.run('resultDocument'), null);
  assert.equal(env.run('pending'), null);
  assert.equal(env.run('livePending'), null);
  assert.equal(env.run('controllers.size'), 0);
  assert.equal(env.run('timer'), null);
  assert.equal(env.run('expiryTimer'), null);
  assert.equal(env.run('poseExpiryTimer'), null);
  assert.equal(env.get('preview').paused, true);
  assert.equal(env.get('record').disabled, true);
  assert.equal(env.get('camera-start').disabled, false);
  assert.equal(env.get('include-image').checked, false);
  assert.equal(env.get('capture-badge').textContent, 'Caméra inactive');
  assert.equal(env.get('frame-status').textContent, 'Aucune image analysée');
  assert.equal(env.beacons.filter((entry) => entry.path === '/api/harness/live/stop').length, 1);
  assert.equal(env.beacons.filter((entry) => entry.path === '/api/session/cancel').length, 1);
  assert.equal(env.requests.filter((r) => r.path === '/api/harness/live/stop').length, 0);
  assert.equal(env.requests.filter((r) => r.path === '/api/session/cancel').length, 0);
  frame.resolve({ sequence: 1, angle_deg: 120, quality_reason: null, pose: { points: ['OLD'] } });
  observation.resolve(liveObservation('OLD AFTER BFCache'));
  await sampling; await settle();
  assert.equal(env.run('latestPose'), null);
  assert.equal(env.get('live-assistant-return').hidden, true);
  assert.equal(env.get('frame-status').textContent, 'Aucune image analysée');
  await env.run('startTrial()'); await env.run('sampleFrame()');
  assert.equal(env.requests.filter((r) => r.path === '/api/session/start').length, 1);
  assert.equal(env.requests.filter((r) => r.path === '/api/frame').length, 2);
  assert.ok(env.get('live-assistant').title.includes('JPEG récents purgés à la désactivation'));
  assert.ok(env.get('live-assistant').title.includes('au plus 5 s'));
});

test('camera overlay uses only short controlled technical labels, never model prose', async (t) => {
  const labels = { awaiting_frames: 'En attente', pose_visible: 'Repères visibles', tracking_lost: 'Suivi perdu',
    tracking_partial: 'Suivi partiel', guide_only: 'Guide seul' };
  for (const [code, label] of Object.entries(labels)) await t.test(code, async () => {
    const env = liveEnvironment((path) => {
      if (path !== '/api/harness/live/poll') return undefined;
      const response = liveObservation('Diagnostic confirmé : tendinite. Faites cent répétitions. <script>bad()</script>');
      response.result.observation_code = code;
      return response;
    });
    await prepareFile(env); await enableLiveAssistant(env); await env.run('startTrial()'); await settle();
    assert.equal(env.get('live-assistant-text').textContent, label);
    assert.ok(env.get('live-assistant-detail').textContent.includes('observation provisoire'));
    for (const id of ['live-assistant-text', 'live-assistant-detail', 'live-assistant-announcement']) {
      assert.ok(!env.get(id).textContent.includes('Diagnostic'));
      assert.ok(!env.get(id).textContent.includes('<script>'));
    }
    assert.equal(env.get('guide-panel').hidden, false);
    await env.run('cancelSession()');
  });
});
test('unknown and inherited observation codes cannot become camera feedback', async (t) => {
  for (const code of ['normal_range', '__proto__', 'constructor']) await t.test(code, async () => {
    const env = liveEnvironment((path) => {
      if (path !== '/api/harness/live/poll') return undefined;
      const response = liveObservation('Amplitude normale'); response.result.observation_code = code; return response;
    });
    await prepareFile(env); await enableLiveAssistant(env); await env.run('startTrial()'); await settle();
    assert.equal(env.get('live-assistant-return').hidden, true);
    assert.equal(env.get('live-assistant-text').textContent, '');
    assert.equal(env.get('live-assistant-detail').textContent, '');
    assert.equal(env.run('phase'), 'recording');
    await env.run('cancelSession()');
  });
});
test('polling the same window does not rewrite or repeatedly announce its observation', async () => {
  let age = 50;
  const env = liveEnvironment((path) => {
    if (path !== '/api/harness/live/poll') return undefined;
    const response = liveObservation(); response.result_age_ms = age; response.analysis_state = 'running'; return response;
  });
  await prepareFile(env); await enableLiveAssistant(env); await env.run('startTrial()'); await settle();
  const textWrites = env.get('live-assistant-text').textWrites;
  const announcements = env.get('live-assistant-announcement').textWrites;
  const stateWrites = env.get('live-assistant-state').textWrites;
  age = 1500;
  await env.run('pollLiveAssistant()'); await env.run('pollLiveAssistant()');
  assert.equal(env.get('live-assistant-text').textWrites, textWrites);
  assert.equal(env.get('live-assistant-announcement').textWrites, announcements);
  assert.equal(env.get('live-assistant-state').textWrites, stateWrites);
  assert.equal(env.get('live-assistant-freshness').textContent, 'Âge 2 s');
  assert.equal(env.get('live-assistant-state').textContent, 'Analyse en cours');
  await env.run('cancelSession()');
});
test('freshness keeps aging during a pending poll without repeatedly announcing the window', async () => {
  let calls = 0, now = 1000;
  const waiting = deferred();
  const env = liveEnvironment((path) => path === '/api/harness/live/poll' ? ++calls === 1 ? liveObservation() : waiting.promise : undefined);
  env.sandbox.performance.now = () => now;
  await prepareFile(env); await enableLiveAssistant(env); await env.run('startTrial()'); await settle();
  const pending = env.run('pollLiveAssistant()');
  const ageTimer = env.run('liveFreshnessTimer');
  const announcements = env.get('live-assistant-announcement').textWrites;
  now += 2000; env.timers.get(ageTimer)();
  assert.equal(env.get('live-assistant-freshness').textContent, 'Âge 3 s');
  assert.equal(env.get('live-assistant-announcement').textWrites, announcements);
  env.timers.get(env.run('liveResultExpiryTimer'))();
  assert.equal(env.run('liveFreshnessTimer'), null);
  assert.equal(env.get('live-assistant-return').hidden, true);
  await env.run('cancelSession()'); waiting.resolve(liveObservation()); await pending;
});
test('busy state is explicit, retains only the still-current observation and never queues capture', async () => {
  let calls = 0;
  const env = liveEnvironment((path) => path === '/api/harness/live/poll' ? ++calls === 1 ? liveObservation() : {
    state: 'busy', analysis_state: 'busy', busy_reason: 'analysis_busy', budget_remaining_ms: null, result: null,
  } : undefined);
  await prepareFile(env); await enableLiveAssistant(env); await env.run('startTrial()'); await settle();
  const expiry = env.run('liveResultExpiryTimer');
  await env.run('pollLiveAssistant()');
  assert.equal(env.get('live-assistant-state').textContent, 'Assistant occupé');
  assert.equal(env.get('live-assistant-return').hidden, false);
  assert.equal(env.run('liveResultExpiryTimer'), expiry);
  env.get('preview').currentTime = 0.2; await env.run('sampleFrame()');
  assert.equal(env.requests.filter((r) => r.path === '/api/frame').length, 2);
  env.timers.get(expiry)();
  assert.equal(env.get('live-assistant-return').hidden, true);
  assert.equal(env.get('live-assistant-state').textContent, 'Observation expirée');
  await env.run('cancelSession()');
});
test('backend deadline hides the old observation and reports cancellation without stopping the camera', async () => {
  let calls = 0;
  const env = liveEnvironment((path) => path === '/api/harness/live/poll' ? ++calls === 1 ? liveObservation() : {
    state: 'unavailable', analysis_state: 'cancelling', budget_remaining_ms: 0, result: null,
  } : undefined);
  await prepareFile(env); await enableLiveAssistant(env); await env.run('startTrial()'); await settle();
  await env.run('pollLiveAssistant()');
  assert.equal(env.get('live-assistant-return').hidden, true);
  assert.equal(env.get('live-assistant-state').textContent, 'Arrêt de l’analyse…');
  assert.equal(env.run('phase'), 'recording');
  assert.equal(env.get('preview').paused, false);
  assert.equal(env.get('guide-panel').hidden, false);
  await env.run('cancelSession()');
});
test('accessible pause suspends only the assistant and leaves camera, frames and guide active', async () => {
  const response = deferred();
  const env = liveEnvironment((path) => path === '/api/harness/live/poll' ? response.promise : undefined);
  await prepareFile(env); await enableLiveAssistant(env); await env.run('startTrial()');
  assert.equal(env.get('live-assistant-controls').hidden, false);
  assert.equal(env.get('live-assistant-pause').disabled, false);
  const poll = env.requests.find((r) => r.path === '/api/harness/live/poll');
  await env.get('live-assistant-pause').click();
  assert.equal(poll.options.signal.aborted, true);
  assert.equal(env.get('live-assistant').checked, false);
  assert.equal(env.get('live-assistant-controls').hidden, true);
  assert.equal(env.get('live-assistant-pause').disabled, true);
  assert.equal(env.get('live-assistant-status').textContent, 'Assistant en pause · caméra maintenue');
  assert.equal(env.run('phase'), 'recording');
  assert.equal(env.get('preview').paused, false);
  assert.equal(env.requests.filter((r) => r.path === '/api/session/cancel').length, 0);
  env.get('preview').currentTime = 0.2; await env.run('sampleFrame()');
  assert.equal(env.requests.filter((r) => r.path === '/api/frame').length, 2);
  assert.equal(env.get('guide-panel').hidden, false);
  response.resolve(liveObservation()); await settle();
  assert.equal(env.get('live-assistant-return').hidden, true);
  await env.run('cancelSession()');
});
test('final note transport timeout is bounded to server budget plus five seconds and preserves the draft', async () => {
  const env = liveEnvironment((path, options) => path === '/api/harness/draft' ? new Promise((resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(Object.assign(new Error('timeout'), { name: 'AbortError' })));
  }) : undefined);
  await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
  const draft = env.get('draft').textContent, result = env.run('JSON.stringify(resultDocument)');
  const writing = env.get('llm-draft').click(); await settle();
  const deadline = [...env.timers.keys()].find((id) => env.timerDelays.get(id) === 35000);
  assert.ok(deadline);
  env.timers.get(deadline)(); await writing;
  assert.equal(env.get('llm-status').textContent, 'Délai de l’assistant dépassé · brouillon conservé');
  assert.equal(env.get('draft').textContent, draft);
  assert.equal(env.run('JSON.stringify(resultDocument)'), result);
  assert.equal(env.get('llm-draft').disabled, false);
  await env.run('cancelSession()');
});
test('final assistant busy and transport fallback messages do not leak technical codes', async (t) => {
  for (const [response, label] of [
    [{ __httpStatus: 409, error: 'analysis_busy' }, 'Assistant occupé · brouillon conservé'],
    [{ proposed_note: null, fallback_reason: 'inference_deadline_exceeded' }, 'Délai de l’assistant dépassé · brouillon conservé'],
    [{ proposed_note: null, fallback_reason: 'inference_cancelled' }, 'Analyse interrompue · brouillon conservé'],
    [{ proposed_note: null, fallback_reason: 'untrusted_error_with_secrets' }, 'Assistant indisponible · brouillon conservé'],
  ]) await t.test(label, async () => {
    const env = liveEnvironment((path) => path === '/api/harness/draft' ? response : undefined);
    await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
    const draft = env.get('draft').textContent;
    await env.get('llm-draft').click();
    assert.equal(env.get('llm-status').textContent, label);
    assert.equal(env.get('draft').textContent, draft);
    await env.run('cancelSession()');
  });
});

function diagnosticFinish(overrides = {}) {
  return { measurement: { status: 'limited', value_deg: 90, valid_frame_count: 4, total_frame_count: 6 },
    motion: { duration_ms: 1000, samples: [], processing_rate_hz: 5, processed_frames: 6,
      robustness: { schema_version: '1.0', quantified_protocol: true, nonquantified_frames: 0,
        usable_frames: 4, unusable_frames: 2, invalid_reason_counts: { no_pose: 1, occlusion: 1 },
        longest_invalid_observed_duration_ms: 200, max_adjacent_sample_gap_ms: 400,
        timestamps_strictly_increasing: true, invalid_interval_count: 1,
        analyzed_image_dimensions: { min_width_px: 640, max_width_px: 640, min_height_px: 360, max_height_px: 360 },
        raw_peak: { sequence: 3, timestamp_ms: 600, angle_deg: 90, temporal_context: 'isolated', before: null, after: null } } },
    evidence_sequence: 3, evidence_timestamp_ms: 600, draft: 'BROUILLON NON VALIDÉ', ...overrides };
}
test('ready manual-check reminder is concise, never checks boxes or blocks starting', async () => {
  const env = environment();
  await prepareFile(env);
  assert.equal(env.get('capture-check-reminder').hidden, false);
  assert.equal(env.get('capture-check-reminder').textContent, 'À confirmer : vue et caméra stable');
  assert.equal(env.get('view-confirmed').checked, false);
  assert.equal(env.get('stable-confirmed').checked, false);
  assert.equal(env.get('record').disabled, false);
  env.get('view-confirmed').checked = true; env.get('view-confirmed').handlers.get('change')();
  assert.equal(env.get('capture-check-reminder').textContent, 'À confirmer : caméra stable');
  env.get('stable-confirmed').checked = true; env.get('stable-confirmed').handlers.get('change')();
  assert.equal(env.get('capture-check-reminder').hidden, true);
  env.get('view-confirmed').checked = false;
  await env.run('startTrial()');
  assert.equal(env.run('phase'), 'recording');
  assert.equal(env.get('capture-check-reminder').hidden, true);
  await env.run('cancelSession()');
});
test('quality feedback describes uncertain tracking, never faults the person or the gesture', async (t) => {
  for (const [reason, label] of [['no_pose', 'Suivi non obtenu'], ['occlusion', 'Repères non fiables']])
    await t.test(reason, async () => {
      const env = environment((path) => path === '/api/frame' ? { sequence: 0, angle_deg: null, quality_reason: reason, pose: null } : undefined);
      await prepareFile(env); await env.run('startTrial()');
      assert.equal(env.get('live-feedback').textContent, `Simulation · ${label}`);
      assert.equal(env.get('guide-panel').hidden, false);
      await env.run('cancelSession()');
    });
});
test('capture exports distinguish 1280 preview from actual 640 JPEG and server pose dimensions', async () => {
  const env = environment((path) => path === '/api/frame' ? { sequence: 0, angle_deg: 90, quality_reason: null,
    pose: { width_px: 640, height_px: 360, points: [] } } : undefined);
  env.get('preview').videoWidth = 1280; env.get('preview').videoHeight = 720;
  await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
  const result = JSON.parse(env.run('JSON.stringify(resultDocument)'));
  assert.equal(result.schema_version, '1.2'); assert.equal(result.capture_version, '0.5.0-dev');
  assert.equal(result.source.width_px, 1280); assert.equal(result.source.height_px, 720);
  assert.deepEqual(result.analysis_capture.encoded_dimensions, [{ width_px: 640, height_px: 360, frame_count: 1 }]);
  assert.deepEqual(result.analysis_capture.analyzed_dimensions, [{ width_px: 640, height_px: 360, frame_count: 1 }]);
  assert.equal(result.analysis_capture.jpeg_quality, 0.8);
  assert.equal(result.analysis_capture.sampling_interval_ms, 200);
  assert.equal(result.analysis_capture.max_width_px, 640); assert.equal(result.analysis_capture.max_height_px, 1080);
  assert.equal(result.analysis_capture.server_dimensions_source, 'frame_response');
  assert.equal(result.analysis_capture.unconfirmed_frame_dimensions_count, 0);
  assert.ok(env.get('result-technical-details').textContent.includes('Aperçu source : 1280 × 720'));
  assert.equal(result.analysis_provenance, null);
  await env.run('cancelSession()');
});
test('dimension changes are counted only for successful frames and survive without detected pose', async () => {
  const env = environment((path) => path === '/api/frame' ? { sequence: 0, angle_deg: null, quality_reason: 'no_pose', pose: null } :
    path === '/api/session/finish' ? diagnosticFinish() : undefined);
  env.get('preview').videoWidth = 1280; env.get('preview').videoHeight = 720;
  await prepareFile(env); await env.run('startTrial()');
  env.get('preview').videoWidth = 800; env.get('preview').videoHeight = 600; env.get('preview').currentTime = 0.2;
  await env.run('sampleFrame()'); await env.run('finishSession(false)');
  const capture = JSON.parse(env.run('JSON.stringify(resultDocument.analysis_capture)'));
  assert.deepEqual(capture.encoded_dimensions, [{ width_px: 640, height_px: 360, frame_count: 1 },
    { width_px: 640, height_px: 480, frame_count: 1 }]);
  assert.deepEqual(capture.analyzed_dimensions, []);
  assert.equal(capture.server_dimensions_source, 'motion_robustness');
  assert.equal(capture.analyzed_image_dimensions.min_width_px, 640);
  assert.equal(capture.unconfirmed_frame_dimensions_count, 2);
  await env.run('cancelSession()');
  assert.equal(env.run('encodedDimensions.size'), 0); assert.equal(env.run('analyzedDimensions.size'), 0);
  assert.equal(env.get('result-diagnostic').textContent, '');
  assert.equal(env.get('result-diagnostic').hidden, true);
  assert.equal(env.get('result-technical-details').textContent, '');
  assert.equal(env.get('result-technical').open, false);
});
test('explicit analyzed image dimensions are retained even when no pose is returned', async () => {
  const env = environment((path) => path === '/api/frame' ? {
    sequence: 0, angle_deg: null, quality_reason: 'no_pose', pose: null,
    analyzed_image: { width_px: 640, height_px: 360 },
  } : undefined);
  env.get('preview').videoWidth = 1280; env.get('preview').videoHeight = 720;
  await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
  const capture = JSON.parse(env.run('JSON.stringify(resultDocument.analysis_capture)'));
  assert.deepEqual(capture.analyzed_dimensions, [{ width_px: 640, height_px: 360, frame_count: 1 }]);
  assert.equal(capture.server_dimensions_source, 'frame_response');
  assert.equal(capture.unconfirmed_frame_dimensions_count, 0);
  await env.run('cancelSession()');
});
test('uncertain peak and refused results stay raw diagnostics and never become validated measurements', async () => {
  const result = diagnosticFinish({ measurement: { status: 'rejected', value_deg: null, valid_frame_count: 4, total_frame_count: 6 } });
  const env = liveEnvironment((path) => path === '/api/session/finish' ? result : undefined);
  await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
  assert.equal(env.get('angle-result').textContent, '—');
  assert.equal(env.get('metric-label').textContent, 'Pic brut · 2D');
  assert.equal(env.get('measurement-status').textContent, 'Essai non exploitable');
  assert.ok(env.get('result-diagnostic').textContent.includes('pic brut isolé'));
  assert.equal(env.get('chart-caption-label').textContent, 'Courbe brute · données non validées');
  assert.ok(env.get('result-technical-details').textContent.includes('Les voisins temporels ne valident ni la précision ni le pic'));
  assert.ok(env.get('result-technical-details').textContent.includes('Ce n’est pas la durée d’une perte caméra'));
  assert.equal(env.get('result-technical').open, false);
  assert.equal(env.run('resultDocument.measurement.value_deg'), null);
  assert.equal(env.run('resultDocument.professional_validation'), false);
  assert.equal(env.get('evidence-label').textContent, 'Image du pic brut · 0.6 s');
  await env.run('cancelSession()');
});
test('limited result uses tracking wording and leaves the experimental raw value unchanged', async () => {
  const result = diagnosticFinish(); result.motion.robustness.raw_peak.temporal_context = 'before_and_after';
  const env = liveEnvironment((path) => path === '/api/session/finish' ? result : undefined);
  await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
  assert.equal(env.get('measurement-status').textContent, 'Suivi à vérifier');
  assert.equal(env.get('angle-result').textContent, '90.0°');
  assert.ok(env.get('result-diagnostic').textContent.includes('voisins temporels présents'));
  assert.ok(!env.get('result-diagnostic').textContent.includes('validé'));
  assert.equal(env.run('resultDocument.measurement.status'), 'limited');
  await env.run('cancelSession()');
});
test('old server without robustness or provenance remains usable and labels missing diagnostics honestly', async () => {
  const env = environment(); await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
  assert.equal(env.run('phase'), 'completed');
  assert.equal(env.get('angle-result').textContent, '90.0° · simulé');
  assert.ok(env.get('result-technical-details').textContent.includes('Diagnostic détaillé non fourni'));
  assert.ok(env.get('result-technical-details').textContent.includes('Versions et configuration du serveur non fournies'));
  assert.equal(env.run('resultDocument.analysis_capture.analyzed_image_dimensions'), null);
  assert.equal(env.run('resultDocument.analysis_capture.server_dimensions_source'), 'unavailable');
  assert.equal(env.get('export-json').disabled, false);
  await env.run('cancelSession()');
});
test('provenance export keeps only approved technical versions, hashes and settings', async () => {
  const provenance = { schema_version: '1.0', snapshot: 'server_startup', git_commit: 'a'.repeat(40),
    working_tree_dirty: true, implementation_sha256: 'b'.repeat(64), implementation_hash_scope: 'pose_geometry_capture_contracts_report',
    python_version: '3.12.9', pose_engine: 'mediapipe_experimental', pose_package_version: '0.10.21',
    pose_model: { sha256: 'c'.repeat(64), configured_sha256: 'c'.repeat(64), hash_verified: true, path: '/secret/patient/task' },
    pose_settings: { delegate: 'CPU', running_mode: 'VIDEO', num_poses: 2, output_segmentation_masks: false,
      min_pose_detection_confidence: 0.5, min_pose_presence_confidence: 0.5, min_tracking_confidence: 0.5,
      landmark_visibility_threshold: 0.5, landmark_presence_threshold: 0.5, llm_token: 'private-model-token' },
    user_agent: 'private-user-agent', machine_name: 'private-machine', model_endpoint: 'private-endpoint' };
  const env = environment((path) => path === '/api/status' ? { pose_mode: 'mediapipe_experimental', models: [], provenance } : undefined);
  await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
  const exported = env.run('JSON.stringify(resultDocument)');
  const actual = JSON.parse(exported).analysis_provenance;
  assert.equal(actual.git_commit, provenance.git_commit); assert.equal(actual.implementation_sha256, provenance.implementation_sha256);
  assert.equal(actual.pose_model.sha256, provenance.pose_model.sha256); assert.equal(actual.pose_model.hash_verified, true);
  assert.equal(actual.pose_settings.num_poses, 2); assert.equal(actual.pose_settings.min_tracking_confidence, 0.5);
  for (const secret of ['private-token', '/secret/patient/task', 'private-model-token', 'private-user-agent', 'private-machine', 'private-endpoint'])
    assert.ok(!exported.includes(secret));
  await env.run('cancelSession()');
});
test('guide-only diagnostics do not turn deliberately unquantified frames into tracking failure', async () => {
  const result = diagnosticFinish({ measurement: { status: 'rejected', value_deg: null, valid_frame_count: 0, total_frame_count: 6 } });
  result.motion.robustness.quantified_protocol = false;
  result.motion.robustness.nonquantified_frames = 6;
  result.motion.robustness.usable_frames = 0; result.motion.robustness.unusable_frames = 0;
  result.motion.robustness.invalid_reason_counts = {}; result.motion.robustness.raw_peak = null;
  const env = liveEnvironment((path) => path === '/api/session/finish' ? result : undefined);
  await prepareFile(env);
  env.run('protocols.push({id:"neck_rotation_guided",label:"Cou",view:"face",framing:"Tête et épaules",guide:"neck_turn",quantified:false,harness_supported:false})');
  env.get('protocol').value = 'neck_rotation_guided'; await env.get('protocol').handlers.get('change')();
  await env.run('startTrial()'); await env.run('finishSession(false)');
  assert.equal(env.get('result-diagnostic').textContent, 'Guide seul · sans amplitude mesurée');
  assert.ok(env.get('result-technical-details').textContent.includes('Guide seul : 6 images non quantifiées'));
  assert.ok(env.get('result-technical-details').textContent.includes('aucun angle ni pic mesuré'));
  assert.ok(!env.get('result-technical-details').textContent.includes('Suivi non obtenu'));
  assert.equal(env.get('chart-wrap').hidden, true); assert.equal(env.get('angle-result').textContent, '—');
  await env.run('cancelSession()');
});
test('late frame metadata cannot repopulate cancelled capture or its replacement trial', async () => {
  const late = deferred(); let frames = 0;
  const env = environment((path) => path === '/api/frame' ? ++frames === 1 ? late.promise : {
    sequence: 0, angle_deg: 90, quality_reason: null, pose: { width_px: 320, height_px: 240, points: [] },
  } : undefined);
  await prepareFile(env); const first = env.run('startTrial()'); await settle();
  await env.run('cancelSession()');
  late.resolve({ sequence: 0, angle_deg: 90, quality_reason: null, pose: { width_px: 640, height_px: 360, points: [] } });
  await first;
  assert.equal(env.run('encodedDimensions.size'), 0); assert.equal(env.run('analyzedDimensions.size'), 0);
  await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
  const actual = JSON.parse(env.run('JSON.stringify(resultDocument.analysis_capture.analyzed_dimensions)'));
  assert.deepEqual(actual, [{ width_px: 320, height_px: 240, frame_count: 1 }]);
  await env.run('cancelSession()');
});
test('large adjacent raw angle change is only a folded technical observation, not a verdict on the gesture', async () => {
  const result = diagnosticFinish();
  result.motion.robustness.largest_adjacent_angle_change = { start_sequence: 2, end_sequence: 3,
    start_timestamp_ms: 400, end_timestamp_ms: 600, gap_ms: 200, delta_deg: 45.5 };
  const env = liveEnvironment((path) => path === '/api/session/finish' ? result : undefined);
  await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
  assert.equal(env.get('result-technical').open, false);
  assert.ok(env.get('result-technical-details').textContent.includes('+45.5° en 200 ms. Aucun seuil de qualité déduit'));
  assert.ok(!env.get('result-diagnostic').textContent.includes('45.5'));
  assert.equal(env.get('angle-result').textContent, '90.0°');
  assert.equal(env.run('resultDocument.measurement.status'), 'limited');
  await env.run('cancelSession()');
});

test('three valid frames followed by frozen video are interrupted, rejected and never expose proof even with an old server', async () => {
  let now = 1000, frames = 0;
  const env = environment((path) => path === '/api/frame' ? { sequence: frames++, angle_deg: 90, quality_reason: null, pose: null } : undefined);
  env.sandbox.performance.now = () => now;
  await prepareFile(env); await env.run('startTrial()');
  now = 1200; env.get('preview').currentTime = 0.2; await env.run('sampleFrame()');
  now = 1400; env.get('preview').currentTime = 0.4; await env.run('sampleFrame()');
  assert.equal(frames, 3);
  const timer = env.run('captureWatchdogTimer');
  now = 4400; env.timers.get(timer)();
  assert.equal(env.get('preview').paused, true); // media stop never awaits network
  assert.equal(env.run('phase'), 'finishing');
  await settle();
  assert.equal(env.run('phase'), 'completed');
  const finish = JSON.parse(env.requests.find((r) => r.path === '/api/session/finish').options.body);
  assert.equal(finish.stopped, true); assert.equal(finish.interruption_reason, 'capture_interrupted');
  assert.equal(finish.capture_monitor.interrupted, true);
  assert.equal(finish.capture_monitor.last_frame_elapsed_ms, 400);
  assert.equal(env.get('angle-result').textContent, '—');
  assert.equal(env.run('resultDocument.measurement.value_deg'), null);
  assert.equal(env.run('resultDocument.measurement.status'), 'rejected');
  assert.equal(env.get('evidence').hidden, true);
  assert.equal(env.requests.filter((r) => r.path === '/api/session/evidence').length, 0);
  assert.ok(!env.get('draft').textContent.includes('90'));
  assert.equal(env.run('captureWatchdogTimer'), null);
  await env.run('startTrial()'); assert.equal(env.requests.filter((r) => r.path === '/api/session/start').length, 1);
  await env.run('cancelSession()');
});
test('manual normal finish cannot bypass a silent reception gap after three valid frames', async () => {
  let now = 1000;
  const env = environment(); env.sandbox.performance.now = () => now;
  await prepareFile(env); await env.run('startTrial()');
  now = 1200; env.get('preview').currentTime = 0.2; await env.run('sampleFrame()');
  now = 1400; env.get('preview').currentTime = 0.4; await env.run('sampleFrame()');
  now = 4400; await env.run('finishSession(false)');
  const finish = JSON.parse(env.requests.find((r) => r.path === '/api/session/finish').options.body);
  assert.equal(finish.stopped, true); assert.equal(finish.interruption_reason, 'capture_interrupted');
  assert.equal(env.run('resultDocument.measurement.value_deg'), null);
  await env.run('cancelSession()');
});
test('separate reception watchdog interrupts a stalled analysis request even while media time advances', async () => {
  let now = 1000;
  const frame = deferred();
  const env = environment((path) => path === '/api/frame' ? frame.promise : undefined);
  env.sandbox.performance.now = () => now;
  await prepareFile(env); const starting = env.run('startTrial()'); await settle();
  const request = env.requests.find((r) => r.path === '/api/frame');
  const timer = env.run('captureWatchdogTimer');
  now = 4000; env.get('preview').currentTime = 3; env.timers.get(timer)();
  assert.equal(request.options.signal.aborted, true);
  assert.equal(env.get('preview').paused, true);
  await settle(); assert.equal(env.run('phase'), 'completed');
  assert.equal(env.run('resultDocument.capture_monitor.last_frame_elapsed_ms'), null);
  frame.resolve({ sequence: 0, angle_deg: 90, quality_reason: null, pose: { points: [] } }); await starting;
  assert.equal(env.run('latestPose'), null);
  assert.equal(env.run('resultDocument.network.processed_requests'), 0);
  assert.equal(env.get('angle-result').textContent, '—');
  await env.run('cancelSession()');
});
test('decoded-video callbacks prevent an advancing playback clock from disguising a frozen decoded frame', async () => {
  let now = 1000, callbackId = 0;
  const callbacks = new Map(), cancelled = [];
  const env = environment(); env.sandbox.performance.now = () => now;
  env.get('preview').requestVideoFrameCallback = (callback) => { callbacks.set(++callbackId, callback); return callbackId; };
  env.get('preview').cancelVideoFrameCallback = (id) => cancelled.push(id);
  await prepareFile(env); await env.run('startTrial()');
  assert.equal(env.run('captureFreshnessBasis'), 'video_frame_callback');
  callbacks.get(1)(1000, { mediaTime: 0 });
  now = 1200; env.get('preview').currentTime = 0.2; await env.run('sampleFrame()');
  now = 1400; env.get('preview').currentTime = 0.4; await env.run('sampleFrame()');
  now = 4000; env.get('preview').currentTime = 3; env.timers.get(env.run('captureWatchdogTimer'))();
  await settle();
  assert.equal(env.run('resultDocument.capture_monitor.interrupted'), true);
  assert.equal(env.run('resultDocument.measurement.value_deg'), null);
  assert.ok(cancelled.includes(2));
  callbacks.get(2)(4100, { mediaTime: 3.1 });
  assert.equal(callbackId, 2); // late callback never reschedules after stopping
  await env.run('cancelSession()');
});
test('fresh normal file EOF remains a normal finish, not an interruption', async () => {
  let now = 1000;
  const env = environment(); env.sandbox.performance.now = () => now;
  await prepareFile(env); await env.run('startTrial()');
  now = 4800; env.get('preview').currentTime = 3.8;
  // Freshness progressed continuously in a real browser; simulate these observations.
  env.run('captureWatchdog.observe(3.8, 4, 4800); captureWatchdog.acknowledge(4800, 4800)');
  now = 5000; env.get('preview').currentTime = 4; env.get('preview').ended = true;
  await env.get('preview').onended();
  const finish = JSON.parse(env.requests.find((r) => r.path === '/api/session/finish').options.body);
  assert.equal(finish.stopped, false); assert.equal(finish.interruption_reason, null);
  assert.equal(finish.capture_monitor.interrupted, false);
  assert.equal(env.get('angle-result').textContent, '90.0° · simulé');
  await env.run('cancelSession()');
});
test('normal finish does not wait fifteen seconds for its last pending analysis frame', async () => {
  let now = 1000, calls = 0;
  const pending = deferred();
  const env = environment((path) => path === '/api/frame' ? ++calls === 1 ? { sequence: 0, angle_deg: 90, quality_reason: null, pose: null } : pending.promise : undefined);
  env.sandbox.performance.now = () => now;
  await prepareFile(env); await env.run('startTrial()');
  now = 1200; env.get('preview').currentTime = 0.2;
  const sampling = env.run('sampleFrame()'); await settle();
  const finishing = env.run('finishSession(false)');
  const timeout = env.run('finishFrameTimer');
  assert.equal(env.timerDelays.get(timeout), 2800);
  now = 4000; env.timers.get(timeout)(); await finishing;
  assert.equal(env.get('angle-result').textContent, '—');
  assert.equal(env.run('resultDocument.capture_monitor.interrupted'), true);
  assert.equal(env.run('finishFrameTimer'), null);
  pending.resolve({ sequence: 1, angle_deg: 90, quality_reason: null, pose: null }); await sampling;
  await env.run('cancelSession()');
});
test('reset and pagehide clear the reception watchdog and late callbacks never restart capture', async () => {
  const env = environment(); await prepareFile(env); await env.run('startTrial()');
  const timer = env.run('captureWatchdogTimer'); assert.ok(env.timers.has(timer));
  env.events.get('pagehide')();
  assert.equal(env.run('captureWatchdogTimer'), null); assert.equal(env.run('captureWatchdog'), null);
  assert.equal(env.run('testConfiguration'), null); assert.equal(env.run('frameController'), null);
  assert.equal(env.timers.has(timer), false);
  await env.run('checkCaptureWatchdog()');
  assert.equal(env.requests.filter((r) => r.path === '/api/session/finish').length, 0);
});

const traceDescriptor = (id = 'gpt_oss') => ({ id, label: id, configured: true, model_alias: id === 'gpt_oss' ? 'openai/gpt-oss-20b' : 'Qwen/Qwen3.6',
  endpoint: 'http://127.0.0.1:8000/v1', api_style: 'openai_compatible_chat_completions', vision_supported: id === 'qwen36',
  vision_enabled: id === 'qwen36', model_revision: null, runtime_version: null, configured_quantization: null,
  declared_quantization_choice: 'FP4', quantization_verified: null });
const usageTrace = (id = 'gpt_oss', kind = 'draft') => ({ schema_version: '1.0',
  meaning: 'completion_attempts_started_not_proof_of_network_success_or_gpu_release', records: [{ model_id: id, kind,
    completion_call_count: 1, first_call_elapsed_ms: 600, last_call_elapsed_ms: 600,
    image_authorized: false, image_payload_attached: false, model: traceDescriptor(id) }] });
test('browser and reported camera settings are snapshotted without persistent device IDs or raw user-agent', async () => {
  let stopped = false;
  const settings = { width: 1280, height: 720, frameRate: 29.97, facingMode: 'user', resizeMode: 'crop-and-scale',
    deviceId: 'private-camera-id', groupId: 'private-device-group' };
  const track = { label: 'FaceTime HD Camera', onended: null, stop: () => { stopped = true; }, getSettings: () => settings };
  const env = environment();
  env.sandbox.navigator.userAgent = 'Mozilla/5.0 (Macintosh) Version/18.0 Safari/605.1.15 private-user-agent';
  env.sandbox.navigator.platform = 'MacIntel';
  env.sandbox.navigator.mediaDevices = { getUserMedia: async () => ({ getTracks: () => [track], getVideoTracks: () => [track] }),
    enumerateDevices: async () => [{ kind: 'videoinput', deviceId: settings.deviceId, label: track.label }] };
  await settle(); await env.run('prepare("camera")'); await env.run('startTrial()');
  await env.run('finishSession(false)');
  assert.equal(stopped, true);
  const exported = env.run('JSON.stringify(resultDocument)');
  const configuration = JSON.parse(exported).test_configuration;
  assert.deepEqual(configuration.browser, { family: 'Safari', version: '18.0', platform_family: 'macOS' });
  assert.equal(configuration.camera.label, 'FaceTime HD Camera');
  assert.deepEqual(configuration.camera.settings, { width: 1280, height: 720, frameRate: 29.97, facingMode: 'user', resizeMode: 'crop-and-scale' });
  for (const secret of ['private-camera-id', 'private-device-group', 'private-user-agent', 'MacIntel']) assert.ok(!exported.includes(secret));
  await env.run('cancelSession()');
});
test('model selected at capture start is declared configuration, not evidence of actual invocation', async () => {
  const env = liveEnvironment((path) => path === '/api/session/finish' ? { ...diagnosticFinish(),
    llm_usage: { schema_version: '1.0', meaning: 'completion_attempts_started_not_proof_of_network_success_or_gpu_release', records: [] } } : undefined);
  await prepareFile(env); await env.run('startTrial()');
  env.get('llm-model').value = 'qwen36'; await env.get('llm-model').handlers.get('change')();
  await env.run('finishSession(false)');
  assert.equal(env.run('resultDocument.test_configuration.selected_model_at_start.model_id'), 'gpt_oss');
  assert.equal(env.run('resultDocument.test_configuration.selected_model_at_start.declared_only'), true);
  assert.equal(env.run('resultDocument.llm_usage.records.length'), 0);
  assert.ok(env.get('result-technical-details').textContent.includes('ne prouve pas un appel LLM'));
  await env.run('cancelSession()');
});
test('final note refreshes actual model invocation trace without exporting generated text', async () => {
  const env = liveEnvironment((path) => path === '/api/harness/draft' ? { proposed_note: 'PRIVATE-GENERATED-NOTE',
    image_sent: false, llm_usage: usageTrace('qwen36') } : undefined);
  await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
  assert.equal(env.run('resultDocument.llm_usage'), null);
  env.get('llm-model').value = 'qwen36'; await env.get('llm-model').handlers.get('change')();
  await env.get('llm-draft').click();
  const exported = env.run('JSON.stringify(resultDocument)');
  assert.equal(env.run('resultDocument.llm_usage.records[0].model_id'), 'qwen36');
  assert.equal(env.run('resultDocument.test_configuration.selected_model_at_start.model_id'), 'gpt_oss');
  assert.ok(!exported.includes('PRIVATE-GENERATED-NOTE'));
  assert.equal(env.run('resultDocument.llm_usage.records[0].model.quantization_verified'), null);
  await env.run('cancelSession()');
});
test('runtime configuration and actual-call metadata are allowlisted without unsafe aliases, tokens, paths or messages', async () => {
  const model = traceDescriptor(); model.model_alias = 'secret=private-key'; model.endpoint = 'http://user:private-password@127.0.0.1:8000/v1';
  model.private_path = '/secret/model/weights';
  const provenance = { schema_version: '1.0', snapshot: 'server_startup', git_commit: 'a'.repeat(40), python_version: '3.12.9',
    pose_engine: 'synthetic_demo', implementation_hash_scope: 'pose_geometry_capture_contracts_report_harness_transport_lifecycle',
    llm_runtime: { schema_version: '1.0', snapshot: 'server_startup_configuration', models: [model] } };
  const usage = usageTrace(); usage.records[0].model = model; usage.records[0].messages = 'PRIVATE-PROMPT';
  const env = environment((path) => path === '/api/status' ? { pose_mode: 'synthetic_demo', models: [], provenance } :
    path === '/api/session/finish' ? { ...diagnosticFinish(), llm_usage: usage } : undefined);
  await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
  const exported = env.run('JSON.stringify(resultDocument)');
  assert.equal(env.run('resultDocument.analysis_provenance.llm_runtime.models[0].model_alias'), null);
  assert.equal(env.run('resultDocument.analysis_provenance.llm_runtime.models[0].endpoint'), null);
  assert.equal(env.run('resultDocument.llm_usage.records[0].model.model_alias'), null);
  for (const secret of ['private-key', 'private-password', '/secret/model/weights', 'PRIVATE-PROMPT']) assert.ok(!exported.includes(secret));
  await env.run('cancelSession()');
});
test('late playback failure after watchdog interruption cannot erase the rejected result', async () => {
  let now = 1000, rejectPlay;
  const env = environment(); env.sandbox.performance.now = () => now;
  await prepareFile(env);
  env.get('preview').play = () => new Promise((resolve, reject) => { rejectPlay = reject; });
  const starting = env.run('startTrial()'); await settle();
  now = 4000; env.timers.get(env.run('captureWatchdogTimer'))(); await settle();
  assert.equal(env.run('phase'), 'completed');
  rejectPlay(Object.assign(new Error('play aborted after stop'), { name: 'AbortError' })); await starting;
  assert.equal(env.run('phase'), 'completed');
  assert.equal(env.run('resultDocument.measurement.value_deg'), null);
  assert.equal(env.get('results').hidden, false);
  await env.run('cancelSession()');
});
test('cancel while finishing cannot let old rejection or finish timeout corrupt the replacement trial', async () => {
  let calls = 0;
  const late = deferred();
  const env = environment((path) => path === '/api/frame' ? ++calls === 1 ? { sequence: 0, angle_deg: 90, quality_reason: null, pose: null } :
    calls === 2 ? late.promise : { sequence: 0, angle_deg: 90, quality_reason: null, pose: null } : undefined);
  await prepareFile(env); await env.run('startTrial()');
  env.get('preview').currentTime = 0.2; const sampling = env.run('sampleFrame()'); await settle();
  const finishing = env.run('finishSession(false)'); await settle();
  const oldTimeout = env.run('finishFrameTimer');
  await env.run('cancelSession()'); assert.equal(env.timers.has(oldTimeout), false);
  env.get('preview').currentTime = 0;
  await prepareFile(env); await env.run('startTrial()');
  late.resolve({ sequence: 1, angle_deg: 90, quality_reason: null, pose: null }); await sampling; await finishing;
  assert.equal(env.run('phase'), 'recording');
  assert.equal(env.run('captureInterruptionReason'), null);
  assert.equal(env.run('captureWatchdog.interrupted'), false);
  assert.equal(env.requests.filter((r) => r.path === '/api/session/finish').length, 0);
  await env.run('cancelSession()');
});
test('server capture interruption immediately revokes fresh browser capture without acknowledging that frame', async () => {
  let now = 1000, calls = 0;
  const env = liveEnvironment((path) => path === '/api/frame' ? ++calls === 1 ? { sequence: 0, angle_deg: 90,
    quality_reason: null, pose: { points: [] } } : { sequence: 1, angle_deg: null, quality_reason: 'capture_interrupted', pose: null } : undefined);
  env.sandbox.performance.now = () => now;
  await prepareFile(env); await enableLiveAssistant(env); await env.run('startTrial()'); await settle();
  now = 1200; env.get('preview').currentTime = 0.2; await env.run('sampleFrame()'); await settle();
  assert.equal(env.get('preview').paused, true);
  assert.equal(env.get('live-assistant').checked, false);
  assert.equal(env.run('phase'), 'completed');
  assert.equal(env.run('captureWatchdog.lastFrameElapsedMs'), 0);
  assert.equal(env.run('captureWatchdog.interrupted'), true);
  assert.equal(env.run('resultDocument.measurement.value_deg'), null);
  assert.equal(env.run('resultDocument.network.processed_requests'), 1);
  assert.equal(env.get('evidence').hidden, true);
  const finish = JSON.parse(env.requests.find((r) => r.path === '/api/session/finish').options.body);
  assert.equal(finish.interruption_reason, 'capture_interrupted');
  assert.equal(finish.capture_monitor.interrupted, true);
  await env.run('sampleFrame()'); assert.equal(calls, 2);
  await env.run('cancelSession()');
});
test('pending or failed final note cannot leave a false zero-attempt trace in exports', async () => {
  let rejectNote;
  const pending = new Promise((resolve, reject) => { rejectNote = reject; });
  const env = liveEnvironment((path) => path === '/api/session/finish' ? { ...diagnosticFinish(),
    llm_usage: { schema_version: '1.0', meaning: 'completion_attempts_started_not_proof_of_network_success_or_gpu_release', records: [] } } :
    path === '/api/harness/draft' ? pending : undefined);
  await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
  assert.equal(env.run('resultDocument.llm_usage.records.length'), 0);
  env.get('result-technical').open = true;
  const writing = env.get('llm-draft').click(); await settle();
  assert.equal(JSON.parse(env.run('JSON.stringify(resultDocument)')).llm_usage, null);
  assert.equal(env.get('result-technical').open, true);
  rejectNote(new Error('HTTP error after server attempt began')); await writing;
  assert.equal(JSON.parse(env.run('JSON.stringify(resultDocument)')).llm_usage, null);
  assert.equal(env.get('result-technical').open, true);
  assert.ok(!env.get('result-technical-details').textContent.includes('Aucune tentative'));
  await env.run('cancelSession()');
});
test('final note visual-context labels never claim successful image transmission', async (t) => {
  for (const imageSent of [false, true]) await t.test(String(imageSent), async () => {
    const env = liveEnvironment((path) => path === '/api/harness/draft' ? { proposed_note: 'Note à revoir',
      image_sent: imageSent, llm_usage: usageTrace('qwen36') } : undefined);
    await prepareFile(env); await env.run('startTrial()'); await env.run('finishSession(false)');
    await env.get('llm-draft').click();
    assert.equal(env.get('llm-status').textContent, imageSent ? 'Note à revoir · contexte visuel disponible' : 'Note à revoir · sans contexte visuel');
    assert.ok(!env.get('llm-status').textContent.includes('transmis'));
    await env.run('cancelSession()');
  });
});
