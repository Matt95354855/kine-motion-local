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
    KineCapture: { CaptureClock, landmarkPosition }, KineGuide: { drawPose() {}, drawChart() {}, setSide() {}, setProtocol() {} },
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
