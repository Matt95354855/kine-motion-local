"use strict";

const $ = (id) => document.getElementById(id);
const preview = $("preview");
const captureCanvas = document.createElement("canvas");
const captureContext = captureCanvas.getContext("2d");
const controllers = new Set();
const MAX_DURATION_MS = 120000;
let phase = "idle", epoch = 0, session = null, stream = null, source = null;
let fileUrl = null, evidenceUrl = null, timer = null, expiryTimer = null, pending = null;
let trialDeadlineTimer = null;
let poseExpiryTimer = null;
let sequence = 0, startedAt = 0, clock = null, resultDocument = null, latestPose = null;
let models = [], demo = false, llmBusy = false, serverReady = false;
let liveHarnessLimits = null, liveGeneration = 0, liveTimer = null, livePending = null;
let liveController = null, liveResultExpiryTimer = null;
let liveFreshnessTimer = null;
let analysisLimits = { draft_budget_ms: 30000 };
let lastLiveObservation = "", lastLiveAnnouncement = "";
const liveObservationLabels = {
  awaiting_frames: "En attente", pose_visible: "Repères visibles", tracking_lost: "Suivi perdu",
  tracking_partial: "Suivi partiel", guide_only: "Guide seul",
};
const liveObservationDetails = {
  awaiting_frames: "En attente d’images récentes. Vue et stabilité à vérifier.",
  pose_visible: "Repères disponibles sur la fenêtre indiquée. Vue et stabilité à vérifier.",
  tracking_lost: "Suivi indisponible sur la fenêtre indiquée. Aucune mesure validée.",
  tracking_partial: "Suivi partiel sur la fenêtre indiquée. Vue et stabilité à vérifier.",
  guide_only: "Observation guidée uniquement, sans angle calculé. Vue et stabilité à vérifier.",
};
const readyModels = new Set();
let limits = { max_frames: 600, sampling_interval_ms: 200 };
let protocols = [{ id: "elbow_flexion_active", label: "Coude · flexion", view: "profil",
  framing: "Épaule, coude et poignet visibles", guide: "elbow", side_kind: "anatomical",
  metric_label: "Flexion apparente", quantified: true, harness_supported: true }];
let protocol = protocols[0], networkSamples = [];
const qualityLabels = {
  no_pose: "Personne non détectée", multiple_people: "Une seule personne dans le cadre",
  occlusion: "Repères masqués", out_of_frame: "Repères hors du cadre",
  degenerate_landmarks: "Repères insuffisants",
};
function message(error) {
  return ({ NotAllowedError: "Permission caméra refusée", NotFoundError: "Aucune caméra trouvée",
    NotReadableError: "Caméra occupée ou déconnectée", OverconstrainedError: "Cette caméra n’est plus disponible",
    AbortError: "Délai dépassé ou opération annulée" })[error.name] || error.message;
}
async function request(path, options = {}, timeout = 15000, ownedController = null) {
  const controller = ownedController || new AbortController();
  controllers.add(controller);
  const timeoutId = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(path, { cache: "no-store", ...options, signal: controller.signal });
    const body = await response.json();
    if (!response.ok) throw new Error(({ forbidden: "Séance expirée ou non autorisée",
      invalid_request: "Capture ou paramètres invalides", pose_engine_unavailable: "Moteur de pose indisponible",
      protocol_not_supported_by_harness: "L’assistant actuel prend en charge le coude uniquement",
      analysis_busy: "Assistant occupé · brouillon conservé",
      analysis_deadline_exceeded: "Délai de l’assistant dépassé · brouillon conservé" })[body.error] || `Erreur ${response.status}`);
    return body;
  } finally { clearTimeout(timeoutId); controllers.delete(controller); }
}
function jsonPost(path, document, timeout, controller) {
  return request(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(document) }, timeout, controller);
}
function controls() {
  const locked = !["idle", "ready", "completed"].includes(phase);
  $("camera-start").disabled = locked || !serverReady;
  $("video-file").disabled = locked || !serverReady;
  $("camera-device").disabled = locked;
  $("side").disabled = locked;
  $("protocol").disabled = locked || !serverReady;
  $("record").disabled = phase !== "ready";
  $("finish").disabled = phase !== "recording";
  $("stop").disabled = ["idle", "completed", "finishing"].includes(phase);
  $("llm-draft").disabled = phase !== "completed" || llmBusy || !protocol.harness_supported;
  const selected = models.find((item) => item.id === $("llm-model").value);
  $("live-assistant").disabled = !serverReady || !liveHarnessLimits || !selected?.configured ||
    !readyModels.has(selected.id) || !["idle", "ready", "recording"].includes(phase);
  $("live-assistant-controls").hidden = !liveAssistantEligible();
  $("live-assistant-pause").disabled = !liveAssistantEligible();
}
function setPhase(value) { phase = value; controls(); }
function writeText(id, value) {
  if ($(id).textContent !== value) $(id).textContent = value;
}
function announceLive(value) {
  if (lastLiveAnnouncement === value) return;
  lastLiveAnnouncement = value;
  writeText("live-assistant-announcement", value);
}
function setLiveState(value, { announce = false } = {}) {
  writeText("live-assistant-state", value);
  writeText("live-assistant-status", value);
  $("live-assistant-controls").hidden = !liveAssistantEligible();
  if (announce) announceLive(value);
}
function clearLiveResult() {
  clearTimeout(liveResultExpiryTimer); liveResultExpiryTimer = null;
  clearInterval(liveFreshnessTimer); liveFreshnessTimer = null;
  $("live-assistant-return").hidden = true;
  for (const id of ["live-assistant-text", "live-assistant-window", "live-assistant-freshness", "live-assistant-detail"]) writeText(id, "");
  lastLiveObservation = "";
}
function stopLiveAssistant({ clearOptIn = true, notify = true } = {}) {
  ++liveGeneration;
  clearInterval(liveTimer); liveTimer = null;
  liveController?.abort(); liveController = null;
  clearLiveResult();
  if (clearOptIn) $("live-assistant").checked = false;
  setLiveState("");
  lastLiveAnnouncement = "";
  writeText("live-assistant-announcement", "");
  controls();
  // Ce message ne bloque ni l'arrêt de la webcam ni la capture suivante.
  if (notify && session) fetch("/api/harness/live/stop", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...session, control_version: liveGeneration }), keepalive: true,
  }).catch(() => {});
}
function liveAssistantEligible() {
  const selected = models.find((item) => item.id === $("llm-model").value);
  return phase === "recording" && Boolean(session) && $("live-assistant").checked &&
    Boolean(liveHarnessLimits) && selected?.configured && readyModels.has(selected.id);
}
function showLiveResponse(response, generation, operation, roundtripMs) {
  const result = response.result;
  const age = response.result_age_ms;
  const ttl = liveHarnessLimits.result_ttl_ms;
  const warmingUp = response.state === "warming_up" && Number.isFinite(response.window?.sample_count) &&
    response.window.sample_count < 3;
  const valid = result?.provisional === true && result.requires_professional_review === true &&
    typeof result.window_ref === "string" && result.window_ref.length > 0 && result.window_ref.length <= 160 &&
    typeof result.observation_code === "string" && Object.hasOwn(liveObservationLabels, result.observation_code) &&
    Number.isFinite(result.start_timestamp_ms) && Number.isFinite(result.end_timestamp_ms) &&
    result.start_timestamp_ms >= 0 && result.end_timestamp_ms >= result.start_timestamp_ms &&
    Number.isFinite(age) && age >= 0;
  if (!valid || warmingUp || age + roundtripMs >= ttl || response.state === "stale" || response.state === "unavailable") {
    if (warmingUp || response.state === "stale" || response.state === "unavailable" || result) clearLiveResult();
    const labels = { warming_up: "En attente", running: "Analyse en cours", busy: "Assistant occupé",
      unavailable: "Assistant indisponible · caméra maintenue", stale: "Observation expirée" };
    const state = response.analysis_state === "busy" || response.busy_reason === "analysis_busy" ? "busy" : response.state;
    const label = response.analysis_state === "cancelling" ? "Arrêt de l’analyse…" : labels[state] || "En attente";
    setLiveState(label, { announce: $("live-assistant-return").hidden });
    return;
  }
  clearTimeout(liveResultExpiryTimer);
  clearInterval(liveFreshnessTimer);
  const label = liveObservationLabels[result.observation_code];
  const interval = `${(result.start_timestamp_ms / 1000).toFixed(1)}–${(result.end_timestamp_ms / 1000).toFixed(1)} s`;
  const fallbackLabels = { deadline_exceeded: "Délai atteint · observation du suivi uniquement.",
    inference_deadline_exceeded: "Délai atteint · observation du suivi uniquement.",
    inference_cancelled: "Analyse interrompue · observation du suivi uniquement.",
    cancelled: "Analyse interrompue · observation du suivi uniquement." };
  const sourceLabel = result.fallback_reason ? fallbackLabels[result.fallback_reason] || "Observation du suivi · assistant non utilisé." :
    "Assistant local · observation technique uniquement.";
  // Ni phrase libre du modèle ni code inconnu ne deviennent une consigne sur la caméra.
  writeText("live-assistant-text", (demo ? "Simulation · " : "") + label);
  writeText("live-assistant-window", `Fenêtre ${interval}`);
  const displayedAt = performance.now(), initialAge = age + roundtripMs;
  const refreshAge = () => {
    if (generation !== liveGeneration || operation !== epoch || !liveAssistantEligible()) return;
    writeText("live-assistant-freshness", `Âge ${Math.ceil((initialAge + Math.max(0, performance.now() - displayedAt)) / 1000)} s`);
  };
  refreshAge();
  liveFreshnessTimer = setInterval(refreshAge, 1000);
  writeText("live-assistant-detail", `${liveObservationDetails[result.observation_code]}\nFenêtre ${interval} · observation provisoire, distincte du compte rendu.\n${sourceLabel}`);
  $("live-assistant-return").hidden = false;
  const stateLabel = response.analysis_state === "busy" || response.state === "busy" ? "Assistant occupé" :
    response.analysis_state === "cancelling" ? "Arrêt de l’analyse…" :
    response.analysis_state === "running" || response.state === "running" ? "Analyse en cours" : "Observation récente";
  setLiveState(stateLabel);
  const observationKey = `${result.window_ref}:${result.observation_code}`;
  if (lastLiveObservation !== observationKey) {
    lastLiveObservation = observationKey;
    announceLive(`Observation provisoire : ${label}. Fenêtre ${interval}.`);
  }
  liveResultExpiryTimer = setTimeout(() => {
    if (generation !== liveGeneration || operation !== epoch || !liveAssistantEligible()) return;
    clearLiveResult();
    setLiveState("Observation expirée", { announce: true });
  }, Math.max(0, ttl - age - roundtripMs));
}
async function pollLiveAssistant() {
  if (!liveAssistantEligible() || livePending) return;
  const generation = liveGeneration, operation = epoch, currentSession = session;
  const selected = models.find((item) => item.id === $("llm-model").value);
  const controller = new AbortController(), polledAt = performance.now();
  liveController = controller;
  const task = jsonPost("/api/harness/live/poll", { ...currentSession, control_version: generation, model_id: selected.id,
    include_image: Boolean(selected.image_enabled && $("include-image").checked) }, 15000, controller);
  livePending = task;
  try {
    const response = await task;
    if (generation !== liveGeneration || operation !== epoch || !liveAssistantEligible()) return;
    showLiveResponse(response, generation, operation, Math.max(0, performance.now() - polledAt));
  } catch (error) {
    if (generation !== liveGeneration || operation !== epoch || !liveAssistantEligible()) return;
    clearLiveResult();
    setLiveState("Assistant indisponible · caméra maintenue", { announce: true });
  } finally {
    if (livePending === task) livePending = null;
    if (liveController === controller) liveController = null;
  }
}
function startLiveAssistant() {
  if (!liveAssistantEligible() || liveTimer || sequence === 0) return;
  setLiveState("Analyse en cours", { announce: true });
  // Le traitement du LLM et son transport restent indépendants de sampleFrame.
  void pollLiveAssistant();
  liveTimer = setInterval(pollLiveAssistant, liveHarnessLimits.poll_interval_ms);
}
function releaseMedia() {
  clearInterval(timer); timer = null;
  clearTimeout(trialDeadlineTimer); trialDeadlineTimer = null;
  clearTimeout(poseExpiryTimer); poseExpiryTimer = null;
  preview.onended = preview.onerror = null;
  if (stream) stream.getTracks().forEach((track) => { track.onended = null; track.stop(); });
  stream = null;
  preview.pause(); preview.srcObject = null; preview.removeAttribute("src"); preview.load();
  if (fileUrl) URL.revokeObjectURL(fileUrl);
  fileUrl = null;
}
function clearResults() {
  resultDocument = null; latestPose = null;
  networkSamples = [];
  if (evidenceUrl) URL.revokeObjectURL(evidenceUrl);
  evidenceUrl = null;
  $("evidence").removeAttribute("src"); $("evidence").hidden = true;
  $("results").hidden = true;
  $("draft").textContent = $("llm-note").textContent = $("llm-status").textContent = "";
  $("export-report").disabled = $("export-json").disabled = true;
  KineGuide.drawPose($("pose-overlay"), null, false);
}
function resetLocalCapture() {
  ++epoch;
  const old = session;
  session = null; source = null; llmBusy = false;
  controllers.forEach((controller) => controller.abort());
  controllers.clear();
  pending = null; livePending = null;
  sequence = 0; startedAt = 0; clock = null;
  clearTimeout(expiryTimer); expiryTimer = null;
  releaseMedia(); clearResults();
  preview.classList.remove("mirrored");
  $("empty-state").hidden = false;
  $("capture-badge").textContent = "Caméra inactive";
  $("elapsed").textContent = "00:00";
  $("frame-status").textContent = "Aucune image analysée";
  $("live-feedback").textContent = "Ouvrez la caméra pour un nouvel essai";
  setPhase("idle");
  return old;
}
async function cancelSession() {
  stopLiveAssistant();
  const old = resetLocalCapture();
  // La révocation n'appartient pas aux nouvelles opérations : une réponse tardive
  // ne peut ni effacer ni remplacer l'essai suivant.
  if (old) {
    fetch("/api/session/cancel", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(old), keepalive: true }).catch(() => {});
  }
}
function waitForVideo() {
  if (preview.readyState >= 2 && preview.videoWidth) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const clean = () => { clearTimeout(id); preview.removeEventListener("loadeddata", loaded); preview.removeEventListener("error", failed); };
    const loaded = () => { clean(); resolve(); };
    const failed = () => { clean(); reject(new Error("Vidéo illisible : essayez un MP4 H.264 ou WebM")); };
    const id = setTimeout(() => { clean(); reject(new Error("La vidéo ne répond pas")); }, 10000);
    preview.addEventListener("loadeddata", loaded, { once: true });
    preview.addEventListener("error", failed, { once: true });
  });
}
async function prepare(sourceType, file = null) {
  await cancelSession();
  const operation = epoch;
  setPhase("preparing");
  $("view-confirmed").checked = $("stable-confirmed").checked = false;
  $("frame-status").textContent = "Aucune image analysée";
  $("capture-details").textContent = "Préparation…";
  try {
    if (sourceType === "camera") {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("Utilisez l’adresse localhost pour la caméra");
      const deviceId = $("camera-device").value;
      const opened = await navigator.mediaDevices.getUserMedia({ audio: false, video: {
        width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 },
        ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
      } });
      if (operation !== epoch) { opened.getTracks().forEach((track) => track.stop()); return; }
      stream = opened; preview.srcObject = stream;
      preview.classList.add("mirrored");
      stream.getVideoTracks()[0].onended = () => {
        $("capture-details").textContent = "Caméra déconnectée — essai interrompu";
        if (phase === "recording") finishSession(true); else cancelSession();
      };
      await preview.play(); await waitForVideo();
      if (operation !== epoch) return;
      const devices = await navigator.mediaDevices.enumerateDevices();
      if (operation !== epoch) return;
      $("camera-device").replaceChildren(...devices.filter((device) => device.kind === "videoinput").map((device, i) => {
        const option = document.createElement("option"); option.value = device.deviceId;
        option.textContent = device.label || `Caméra ${i + 1}`; return option;
      }));
      $("camera-device").value = stream.getVideoTracks()[0].getSettings().deviceId || "";
    } else {
      if (!file || !file.type.startsWith("video/")) throw new Error("Choisissez un fichier vidéo");
      if (file.size > 200 * 1024 * 1024) throw new Error("Vidéo limitée à 200 Mo");
      fileUrl = URL.createObjectURL(file); preview.src = fileUrl; preview.load();
      await waitForVideo();
      if (operation !== epoch) return;
      if (!Number.isFinite(preview.duration) || preview.duration > 120) throw new Error("Choisissez un clip de 2 minutes maximum");
      preview.pause();
      preview.onended = () => finishSession(false);
    }
    if (operation !== epoch) return;
    source = { type: sourceType, width_px: preview.videoWidth, height_px: preview.videoHeight,
      mirrored_preview: sourceType === "camera", duration_ms: sourceType === "file" ? Math.round(preview.duration * 1000) : null };
    $("empty-state").hidden = true;
    $("capture-badge").textContent = sourceType === "camera" ? "Caméra prête" : "Vidéo prête";
    $("capture-details").textContent = `${source.width_px} × ${source.height_px} · ${sourceType === "camera" ? "aperçu miroir, analyse non inversée" : "lecture à vitesse normale"}`;
    $("live-feedback").textContent = "Vérifiez le cadrage, puis démarrez l’essai";
    preview.onerror = () => { $("capture-details").textContent = "Lecture interrompue"; if (phase === "recording") finishSession(true); else cancelSession(); };
    setPhase("ready");
  } catch (error) {
    if (operation !== epoch) return;
    await cancelSession();
    $("capture-details").textContent = message(error);
  }
}
function jpegBlob() {
  return new Promise((resolve, reject) => captureCanvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("Image indisponible")), "image/jpeg", 0.8));
}
async function sampleFrame() {
  if (phase !== "recording" || pending || preview.readyState < 2 || !session) return;
  const operation = epoch, currentSession = session;
  const capturedAt = performance.now();
  if (sequence >= limits.max_frames || performance.now() - startedAt >= MAX_DURATION_MS) { finishSession(false); return; }
  const timestamp = clock.next(preview.currentTime, performance.now());
  if (timestamp === null) return;
  const scale = Math.min(1, 640 / preview.videoWidth, 1080 / preview.videoHeight);
  captureCanvas.width = Math.max(1, Math.round(preview.videoWidth * scale));
  captureCanvas.height = Math.max(1, Math.round(preview.videoHeight * scale));
  captureContext.drawImage(preview, 0, 0, captureCanvas.width, captureCanvas.height);
  const currentSequence = sequence++;
  const task = (async () => {
    const blob = await jpegBlob();
    if (operation !== epoch) return;
    const response = await request("/api/frame", { method: "POST", headers: {
      "Content-Type": "image/jpeg", "X-Session-Id": currentSession.session_id,
      "X-Session-Token": currentSession.token, "X-Sequence": String(currentSequence), "X-Timestamp-Ms": String(timestamp),
    }, body: blob });
    if (operation !== epoch) return;
    const latencyMs = Math.round(performance.now() - capturedAt);
    networkSamples.push({ sequence: currentSequence, roundtrip_ms: latencyMs, jpeg_bytes: blob.size });
    if (phase !== "recording") return;
    const delayed = latencyMs > 1000;
    latestPose = response.quality_reason || delayed ? null : response.pose;
    KineGuide.drawPose($("pose-overlay"), latestPose, source.mirrored_preview);
    clearTimeout(poseExpiryTimer);
    if (latestPose) poseExpiryTimer = setTimeout(() => {
      if (operation !== epoch || phase !== "recording") return;
      latestPose = null; KineGuide.drawPose($("pose-overlay"), null, false);
      writeText("live-feedback", "Caméra · repères expirés");
    }, Math.max(0, 1000 - latencyMs));
    const feedback = response.quality_reason ? qualityLabels[response.quality_reason] || "Capture à vérifier" :
      !protocol.quantified ? "Guide seul" :
      response.angle_deg === null ? "Repères non exploitables" : `${Math.round(response.angle_deg)}° · 2D`;
    writeText("live-feedback", (demo ? "Simulation · " : "Caméra · ") +
      (delayed ? "Repères retardés" : feedback));
    $("frame-status").textContent = `${response.sequence + 1} images · ${latencyMs} ms`;
    $("frame-status").title = `Aller-retour traitement : ${latencyMs} ms`;
    const seconds = Math.floor(timestamp / 1000);
    $("elapsed").textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
    startLiveAssistant();
  })();
  pending = task;
  try { await task; }
  catch (error) {
    if (operation === epoch) { await cancelSession(); $("capture-details").textContent = `Essai interrompu : ${message(error)}`; }
  } finally { if (pending === task) pending = null; }
}
async function startTrial() {
  if (phase !== "ready") return;
  const operation = epoch;
  setPhase("starting");
  try {
    const created = await jsonPost("/api/session/start", { side: $("side").value, protocol_id: protocol.id });
    if (operation !== epoch) {
      fetch("/api/session/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(created), keepalive: true }); return;
    }
    session = created; sequence = 0; startedAt = performance.now();
    clock = new KineCapture.CaptureClock(source.type, startedAt);
    expiryTimer = setTimeout(() => { cancelSession(); $("capture-details").textContent = "Séance expirée : données effacées"; }, 15 * 60 * 1000);
    setPhase("recording");
    trialDeadlineTimer = setTimeout(() => finishSession(false), MAX_DURATION_MS);
    $("capture-badge").textContent = demo ? "Essai simulé" : "Suivi caméra";
    await sampleFrame();
    if (operation !== epoch || phase !== "recording") return;
    await preview.play();
    timer = setInterval(sampleFrame, limits.sampling_interval_ms);
  } catch (error) {
    if (operation === epoch) { await cancelSession(); $("capture-details").textContent = message(error); }
  }
}
async function finishSession(stopped) {
  if (phase !== "recording" || !session) return;
  const operation = epoch, currentSession = session;
  const waiting = pending;
  stopLiveAssistant();
  setPhase("finishing");
  // L'arrêt des pistes ne dépend pas du temps de réponse de l'analyse.
  releaseMedia();
  $("capture-badge").textContent = stopped ? "Essai interrompu" : "Calcul du résultat";
  try {
    if (waiting) await waiting;
    if (operation !== epoch) return;
    const response = await jsonPost("/api/session/finish", { ...currentSession,
      view_confirmed: $("view-confirmed").checked, camera_stable_confirmed: $("stable-confirmed").checked, stopped });
    if (operation !== epoch) return;
    const sortedLatency = networkSamples.map((sample) => sample.roundtrip_ms).sort((a, b) => a - b);
    resultDocument = { schema_version: "1.1", capture_version: "0.4.0-dev", mode: demo ? "synthetic_demo" : "mediapipe_experimental", source,
      protocol: { ...protocol }, network: { processed_requests: networkSamples.length,
        total_jpeg_bytes: networkSamples.reduce((total, sample) => total + sample.jpeg_bytes, 0),
        roundtrip_p95_ms: sortedLatency.length ? sortedLatency[Math.ceil(sortedLatency.length * 0.95) - 1] : null },
      measurement: response.measurement, motion: response.motion, evidence_sequence: response.evidence_sequence,
      evidence_timestamp_ms: response.evidence_timestamp_ms, professional_validation: false };
    const measurement = response.measurement, motion = response.motion;
    $("results").hidden = false;
    $("metric-label").textContent = protocol.metric_label;
    $("chart-wrap").hidden = !protocol.quantified;
    $("angle-result").textContent = measurement.value_deg === null ? "—" : `${measurement.value_deg.toFixed(1)}°${demo ? " · simulé" : ""}`;
    $("duration-result").textContent = `${(motion.duration_ms / 1000).toFixed(1)} s`;
    $("coverage-result").textContent = protocol.quantified ? `${measurement.valid_frame_count} / ${measurement.total_frame_count}` : "Non quantifié";
    $("measurement-status").textContent = stopped ? "Essai interrompu" : !protocol.quantified ? "Guide seul · sans mesure" : demo ? "Simulation — non clinique" :
      ({ valid: "Expérimental — à vérifier", limited: "Capture limitée", rejected: "Essai non exploitable", not_performed: "Non réalisé" })[measurement.status];
    $("draft").textContent = (demo ? "SIMULATION : les pixels ne sont pas analysés.\n\n" : "") + response.draft;
    $("evidence-label").textContent = response.evidence_timestamp_ms === null ? "Aucune image probante" :
      `Image du pic · ${(response.evidence_timestamp_ms / 1000).toFixed(1)} s`;
    KineGuide.drawPose($("pose-overlay"), null, false);
    KineGuide.drawChart($("angle-chart"), motion.samples);
    $("export-report").disabled = $("export-json").disabled = false;
    $("capture-badge").textContent = stopped ? "Essai interrompu" : "Essai terminé";
    $("live-feedback").textContent = stopped ? "Essai interrompu · aucune valeur publiée" : measurement.value_deg === null ?
      (!protocol.quantified ? "Rotation guidée terminée · aucune amplitude mesurée" : "Mesure non disponible — consultez les limites") : "Résultat expérimental, à vérifier";
    $("frame-status").textContent = `${motion.processing_rate_hz} images/s · ${motion.processed_frames} traitées`;
    $("capture-details").textContent = "Caméra arrêtée · une seule image de preuve en mémoire, effacée au nouvel essai";
    setPhase("completed");
    const evidence = await jsonPost("/api/session/evidence", currentSession);
    if (operation !== epoch) return;
    if (evidence.jpeg_base64) {
      const bytes = Uint8Array.from(atob(evidence.jpeg_base64), (char) => char.charCodeAt(0));
      evidenceUrl = URL.createObjectURL(new Blob([bytes], { type: "image/jpeg" }));
      $("evidence").src = evidenceUrl; $("evidence").hidden = false;
      $("evidence").classList.toggle("mirrored", source.mirrored_preview);
    } else { $("empty-state").hidden = false; }
  } catch (error) {
    if (operation !== epoch) return;
    if (phase === "completed") $("capture-details").textContent = `Résultat conservé · image indisponible : ${message(error)}`;
    else { await cancelSession(); $("capture-details").textContent = `Fin d’essai impossible : ${message(error)}`; }
  }
}
function download(contents, mime, extension) {
  const url = URL.createObjectURL(new Blob([contents], { type: mime }));
  const link = document.createElement("a"); link.href = url;
  link.download = `kine-brouillon-${new Date().toISOString().slice(0, 10)}.${extension}`;
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function updateModelSelection() {
  const selected = models.find((item) => item.id === $("llm-model").value);
  $("include-image").disabled = !selected?.image_enabled;
  if (!selected?.image_enabled) $("include-image").checked = false;
  $("check-model").disabled = !selected?.configured;
  $("model-status").textContent = selected?.configured ? readyModels.has(selected.id) ?
    "Alias annoncé · outils et vision restent à tester" : "Serveur configuré · vérifiez l’alias pour l’assistant pendant l’essai" :
    "Sans serveur : brouillon déterministe disponible";
  if (!protocol.harness_supported) $("model-status").textContent += " · note finale disponible pour le coude uniquement";
  controls();
}
function updateProtocol() {
  protocol = protocols.find((item) => item.id === $("protocol").value) || protocols[0];
  $("protocol-framing").textContent = `Vue de ${protocol.view} · ${protocol.framing}`;
  $("view-label").textContent = `Vue de ${protocol.view}`;
  $("framing-prompt").textContent = `Placez-vous de ${protocol.view}`;
  $("framing-label").textContent = protocol.framing;
  $("framing-guide").title = "Cadrage indicatif : ce dessin ne valide pas automatiquement votre position.";
  $("protocol").title = protocol.limitation || "Projection 2D expérimentale, à vérifier.";
  $("framing-guide").dataset.view = protocol.view;
  $("side").setAttribute("aria-label", protocol.side_kind === "direction" ? "Direction demandée au guide, non vérifiée automatiquement" : "Côté anatomique observé");
  $("view-confirmed").checked = $("stable-confirmed").checked = false;
  KineGuide.setProtocol(protocol.guide, protocol.label);
  $("live-feedback").textContent = !protocol.quantified ? "Guide seul · rotation non mesurable en 2D" : "Personnage illustratif · repères verts expérimentaux";
  updateModelSelection(); controls();
}
$("camera-start").addEventListener("click", () => prepare("camera"));
$("video-file").addEventListener("change", () => { const file = $("video-file").files[0]; $("video-file").value = ""; if (file) prepare("file", file); });
$("camera-device").addEventListener("change", () => { if (source?.type === "camera") prepare("camera"); });
$("record").addEventListener("click", startTrial);
$("finish").addEventListener("click", () => finishSession(false));
$("stop").addEventListener("click", () => { if (phase === "recording") finishSession(true); else cancelSession(); });
$("restart").addEventListener("click", () => { cancelSession(); $("capture-details").textContent = "Prêt pour un nouvel essai"; $("frame-status").textContent = "Aucune image analysée"; });
$("side").addEventListener("change", async () => {
  if (phase === "completed") await cancelSession();
  $("view-confirmed").checked = false;
  KineGuide.setSide($("side").value);
});
$("protocol").addEventListener("change", async () => {
  if (!["idle", "ready", "completed"].includes(phase)) return;
  if (phase === "completed") await cancelSession();
  latestPose = null; KineGuide.drawPose($("pose-overlay"), null, false);
  updateProtocol();
});
$("export-report").addEventListener("click", () => { if (resultDocument) download($("draft").textContent, "text/plain;charset=utf-8", "txt"); });
$("export-json").addEventListener("click", () => { if (resultDocument) download(JSON.stringify(resultDocument, null, 2), "application/json", "json"); });
$("llm-model").addEventListener("change", () => { stopLiveAssistant(); updateModelSelection(); });
$("include-image").addEventListener("change", () => { stopLiveAssistant(); controls(); });
$("live-assistant").addEventListener("change", () => {
  if (!$("live-assistant").checked) { stopLiveAssistant(); return; }
  const selected = models.find((item) => item.id === $("llm-model").value);
  if (!liveHarnessLimits || !selected?.configured || !readyModels.has(selected.id)) { stopLiveAssistant(); return; }
  ++liveGeneration;
  setLiveState(phase === "recording" ? "En attente" : "Activé pour cet essai");
  controls();
  startLiveAssistant();
});
$("live-assistant-pause").addEventListener("click", () => {
  if (!liveAssistantEligible()) return;
  stopLiveAssistant();
  writeText("live-assistant-status", "Assistant en pause · caméra maintenue");
  announceLive("Assistant en pause. La caméra continue.");
});
$("check-model").addEventListener("click", async () => {
  const selected = $("llm-model").value;
  $("model-status").textContent = "Vérification…";
  try {
    const response = await jsonPost("/api/models/check", { model_id: selected });
    const labels = { ready: "Modèle annoncé par le serveur local", model_not_advertised: "Alias absent du serveur",
      runtime_unreachable: "Serveur inaccessible", not_configured: "Serveur non configuré" };
    if (response.state === "ready") readyModels.add(selected); else readyModels.delete(selected);
    if ($("llm-model").value === selected) {
      if (response.state !== "ready") stopLiveAssistant();
      $("model-status").textContent = (labels[response.state] || response.state) + (response.state === "ready" ? " · outils et vision non validés" : "");
      controls();
    }
  } catch (error) {
    readyModels.delete(selected);
    if ($("llm-model").value === selected) { stopLiveAssistant(); $("model-status").textContent = message(error); controls(); }
  }
});
$("llm-draft").addEventListener("click", async () => {
  if (phase !== "completed" || llmBusy || !session || !protocol.harness_supported) return;
  const operation = epoch, currentSession = session;
  llmBusy = true; controls(); $("llm-status").textContent = "Préparation de la note…";
  try {
    const response = await jsonPost("/api/harness/draft", { ...currentSession,
      model_id: $("llm-model").value, include_image: $("include-image").checked }, analysisLimits.draft_budget_ms + 5000);
    if (operation !== epoch) return;
    $("llm-note").textContent = response.proposed_note || "Brouillon déterministe conservé";
    const fallbackLabels = { deadline_exceeded: "Délai de l’assistant dépassé · brouillon conservé",
      analysis_deadline_exceeded: "Délai de l’assistant dépassé · brouillon conservé",
      inference_deadline_exceeded: "Délai de l’assistant dépassé · brouillon conservé",
      inference_cancelled: "Analyse interrompue · brouillon conservé",
      cancelled: "Analyse interrompue · brouillon conservé", analysis_busy: "Assistant occupé · brouillon conservé" };
    $("llm-status").textContent = response.fallback_reason ? fallbackLabels[response.fallback_reason] || "Assistant indisponible · brouillon conservé" :
      `Note à revoir${response.image_sent ? " · une image transmise localement" : " · aucune image transmise"}`;
  } catch (error) { if (operation === epoch) $("llm-status").textContent = error.name === "AbortError" ?
    "Délai de l’assistant dépassé · brouillon conservé" : message(error); }
  finally { if (operation === epoch) { llmBusy = false; controls(); } }
});
new ResizeObserver(() => {
  KineGuide.drawPose($("pose-overlay"), phase === "recording" ? latestPose : null, Boolean(source?.mirrored_preview));
  if (resultDocument) KineGuide.drawChart($("angle-chart"), resultDocument.motion.samples);
}).observe($("camera-stage"));
document.addEventListener("visibilitychange", () => { if (document.hidden && phase === "recording") finishSession(true); });
window.addEventListener("pagehide", () => {
  stopLiveAssistant({ notify: false });
  if (session) navigator.sendBeacon("/api/harness/live/stop", new Blob([JSON.stringify({ ...session, control_version: liveGeneration })], { type: "application/json" }));
  if (session) navigator.sendBeacon("/api/session/cancel", new Blob([JSON.stringify(session)], { type: "application/json" }));
  // Un retour depuis le cache du navigateur ne reprend jamais l'essai ni ses
  // anciens repères. Les beacons sont les seuls messages d'arrêt sur ce chemin.
  resetLocalCapture();
  $("include-image").checked = false;
  $("capture-details").textContent = "Essai quitté · aucune reprise automatique";
});
controls();
request("/api/status").then((status) => {
  models = status.models || []; demo = status.pose_mode === "synthetic_demo";
  protocols = status.protocols?.length ? status.protocols : protocols;
  $("protocol").replaceChildren(...protocols.map((item) => {
    const option = document.createElement("option"); option.value = item.id; option.textContent = item.label; return option;
  }));
  $("protocol").value = protocols[0].id;
  $("connection-status").textContent = status.topology?.remote_client ? "Calcul distant · caméra ici" : "Caméra ici · calcul local";
  limits = { ...limits, ...status.capture_limits };
  if (Number.isFinite(status.analysis_limits?.draft_budget_ms) && status.analysis_limits.draft_budget_ms >= 1000 &&
    status.analysis_limits.draft_budget_ms <= 30000) analysisLimits.draft_budget_ms = status.analysis_limits.draft_budget_ms;
  if (status.live_harness) liveHarnessLimits = { window_ms: 5000, max_samples: 25, max_images: 2,
    poll_interval_ms: 1000, inference_interval_ms: 3000, result_ttl_ms: 10000, ...status.live_harness };
  $("live-assistant").title = liveHarnessLimits ? `JPEG récents purgés à la désactivation. Poses live conservées au plus ${liveHarnessLimits.window_ms / 1000} s, effacées à la fin de l’essai. Le résultat final reste séparé.` : "Assistant pendant l’essai indisponible sur ce serveur";
  $("llm-model").replaceChildren(...models.map((item) => {
    const option = document.createElement("option"); option.value = item.id; option.textContent = item.label; return option;
  }));
  $("llm-model").disabled = !models.length;
  const first = models.find((item) => item.configured); if (first) $("llm-model").value = first.id;
  updateModelSelection();
  $("engine-status").textContent = demo ? "Démo · pose simulée" : "Pose réelle · expérimental";
  serverReady = true; updateProtocol();
}).catch(() => { $("engine-status").textContent = "Serveur indisponible"; });
