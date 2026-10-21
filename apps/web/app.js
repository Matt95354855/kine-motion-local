"use strict";

const $ = (id) => document.getElementById(id);
const preview = $("preview");
const captureCanvas = document.createElement("canvas");
const captureContext = captureCanvas.getContext("2d");
const controllers = new Set();
const MAX_DURATION_MS = 120000;
const CAPTURE_WATCHDOG_TIMEOUT_MS = 3000;
const JPEG_QUALITY = 0.8, MAX_ANALYSIS_WIDTH_PX = 640, MAX_ANALYSIS_HEIGHT_PX = 1080;
let phase = "idle", epoch = 0, session = null, stream = null, source = null;
let fileUrl = null, evidenceUrl = null, timer = null, expiryTimer = null, pending = null;
let trialDeadlineTimer = null;
let captureWatchdog = null, captureWatchdogTimer = null, videoFrameCallbackId = null, frameController = null;
let finishFrameTimer = null;
let captureInterruptionReason = null, captureFreshnessBasis = "media_clock", testConfiguration = null;
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
let encodedDimensions = new Map(), analyzedDimensions = new Map(), analysisProvenance = null;
const qualityLabels = {
  no_pose: "Suivi non obtenu", multiple_people: "Plusieurs poses détectées",
  occlusion: "Repères non fiables", out_of_frame: "Repères hors du cadre",
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
  const missingView = !$("view-confirmed").checked, missingStable = !$("stable-confirmed").checked;
  $("capture-check-reminder").hidden = phase !== "ready" || !(missingView || missingStable);
  writeText("capture-check-reminder", `À confirmer : ${missingView && missingStable ? "vue et caméra stable" : missingView ? "vue" : "caméra stable"}`);
}
function setPhase(value) { phase = value; controls(); }
function writeText(id, value) {
  if ($(id).textContent !== value) $(id).textContent = value;
}
function positivePixel(value) { return Number.isInteger(value) && value > 0 && value <= 16384; }
function recordDimensions(target, width, height) {
  if (!positivePixel(width) || !positivePixel(height)) return;
  const key = `${width}x${height}`, previous = target.get(key);
  target.set(key, { width_px: width, height_px: height, frame_count: (previous?.frame_count || 0) + 1 });
}
function safeModelDescriptor(value) {
  if (!value || typeof value !== "object" || typeof value.id !== "string" || !/^[A-Za-z0-9_.-]{1,64}$/.test(value.id)) return null;
  const text = (item, maximum = 256) => typeof item === "string" && item.length > 0 && item.length <= maximum &&
    !/[\p{C}]/u.test(item) ? item : null;
  const alias = text(value.model_alias);
  const boolean = (item) => typeof item === "boolean" ? item : null;
  return { id: value.id, label: text(value.label, 128), configured: boolean(value.configured),
    model_alias: alias && !/^(?:[\/\\~]|\.\.?[\/\\]|[A-Za-z]:[\/\\]|Bearer\s|Basic\s)|[\\?#]|:\/\/|\b(?:api[_-]?key|token|password|secret)\s*[=:]/i.test(alias) &&
      !(alias.includes("@") && alias.split("@", 1)[0].includes(":")) ? alias : null,
    endpoint: typeof value.endpoint === "string" && /^http:\/\/(?:127\.0\.0\.1|localhost|\[::1\])(?::\d{1,5})?\/v1\/?$/.test(value.endpoint) ? value.endpoint : null,
    api_style: value.api_style === "openai_compatible_chat_completions" ? value.api_style : null,
    vision_supported: boolean(value.vision_supported), vision_enabled: boolean(value.vision_enabled),
    model_revision: text(value.model_revision), runtime_version: text(value.runtime_version, 64),
    configured_quantization: text(value.configured_quantization, 32),
    declared_quantization_choice: value.declared_quantization_choice === "FP4" ? "FP4" : null,
    quantization_verified: boolean(value.quantization_verified) };
}
function safeLLMUsage(value) {
  if (value?.schema_version !== "1.0" || value.meaning !== "completion_attempts_started_not_proof_of_network_success_or_gpu_release" ||
    !Array.isArray(value.records) || value.records.length > 6) return null;
  const records = [];
  for (const item of value.records) {
    if (!item || typeof item.model_id !== "string" || !/^[A-Za-z0-9_.-]{1,64}$/.test(item.model_id) || !["live", "draft"].includes(item.kind) ||
      !Number.isSafeInteger(item.completion_call_count) || item.completion_call_count < 1 ||
      !Number.isFinite(item.first_call_elapsed_ms) || item.first_call_elapsed_ms < 0 ||
      !Number.isFinite(item.last_call_elapsed_ms) || item.last_call_elapsed_ms < item.first_call_elapsed_ms) return null;
    records.push({ model_id: item.model_id, kind: item.kind, completion_call_count: item.completion_call_count,
      first_call_elapsed_ms: item.first_call_elapsed_ms, last_call_elapsed_ms: item.last_call_elapsed_ms,
      image_authorized: item.image_authorized === true, image_payload_attached: item.image_payload_attached === true,
      model: safeModelDescriptor(item.model) });
  }
  return { schema_version: "1.0", meaning: value.meaning, records };
}
function safeCaptureIntegrity(value) {
  if (value?.schema_version !== "1.0") return null;
  const result = { schema_version: "1.0", watchdog_timeout_ms: value.watchdog_timeout_ms === 3000 ? 3000 : null,
    interrupted: value.interrupted === true, reason: value.reason === "capture_interrupted" ? value.reason : null,
    limitation: value.limitation === "fresh_received_frames_do_not_prove_complete_motion_or_pixel_changes" ? value.limitation : null };
  for (const key of ["server_observed_duration_ms", "received_frame_count", "max_receive_gap_ms", "max_source_gap_ms",
    "last_received_age_ms", "source_span_ms"]) result[key] = Number.isFinite(value[key]) && value[key] >= 0 ? value[key] : null;
  const monitor = value.client_monitor;
  result.client_monitor = monitor?.schema_version === "1.0" && monitor.watchdog_timeout_ms === 3000 &&
    Number.isFinite(monitor.expected_duration_ms) && monitor.expected_duration_ms >= 0 && monitor.expected_duration_ms <= 135000 &&
    (monitor.last_frame_elapsed_ms === null || Number.isFinite(monitor.last_frame_elapsed_ms) && monitor.last_frame_elapsed_ms >= 0 &&
      monitor.last_frame_elapsed_ms <= monitor.expected_duration_ms) ? {
      schema_version: "1.0", watchdog_timeout_ms: 3000, expected_duration_ms: monitor.expected_duration_ms,
      last_frame_elapsed_ms: monitor.last_frame_elapsed_ms, interrupted: monitor.interrupted === true } : null;
  return result;
}
function cameraTrace() {
  if (source?.type !== "camera") return null;
  const track = stream?.getVideoTracks()[0], settings = track?.getSettings() || {};
  const label = typeof track?.label === "string" ? track.label.replace(/[\u0000-\u001f\u007f]/g, "").slice(0, 160) : null;
  return { label: label || null, settings: { width: positivePixel(settings.width) ? settings.width : null,
    height: positivePixel(settings.height) ? settings.height : null,
    frameRate: Number.isFinite(settings.frameRate) && settings.frameRate > 0 && settings.frameRate <= 1000 ? settings.frameRate : null,
    facingMode: ["user", "environment", "left", "right"].includes(settings.facingMode) ? settings.facingMode : null,
    resizeMode: ["none", "crop-and-scale"].includes(settings.resizeMode) ? settings.resizeMode : null } };
}
function trialConfiguration() {
  const selected = models.find((item) => item.id === $("llm-model").value);
  const configured = analysisProvenance?.llm_runtime?.models.find((item) => item.id === selected?.id);
  return { browser: KineCapture.browserTrace(navigator.userAgent, navigator.platform), camera: cameraTrace(),
    selected_model_at_start: selected ? { model_id: selected.id, configuration: configured || null, declared_only: true } : null };
}
function safeProvenance(value) {
  if (!value || typeof value !== "object" || value.schema_version !== "1.0") return null;
  const digest = (item, length) => typeof item === "string" && new RegExp(`^[a-f0-9]{${length}}$`, "i").test(item) ? item : null;
  const version = (item) => typeof item === "string" && /^[a-zA-Z0-9.+_-]{1,64}$/.test(item) ? item : null;
  const boolean = (item) => typeof item === "boolean" ? item : null;
  let poseSettings = null;
  if (value.pose_settings && typeof value.pose_settings === "object") {
    const settings = value.pose_settings;
    poseSettings = { delegate: settings.delegate === "CPU" ? "CPU" : null,
      running_mode: ["VIDEO", "synthetic"].includes(settings.running_mode) ? settings.running_mode : null,
      num_poses: Number.isInteger(settings.num_poses) && settings.num_poses >= 1 && settings.num_poses <= 10 ? settings.num_poses : null,
      output_segmentation_masks: boolean(settings.output_segmentation_masks) };
    for (const key of ["min_pose_detection_confidence", "min_pose_presence_confidence", "min_tracking_confidence",
      "landmark_visibility_threshold", "landmark_presence_threshold"]) {
      poseSettings[key] = Number.isFinite(settings[key]) && settings[key] >= 0 && settings[key] <= 1 ? settings[key] : null;
    }
  }
  return { schema_version: "1.0", snapshot: value.snapshot === "server_startup" ? value.snapshot : null,
    git_commit: digest(value.git_commit, 40), working_tree_dirty: boolean(value.working_tree_dirty),
    implementation_sha256: digest(value.implementation_sha256, 64),
    implementation_hash_scope: ["pose_geometry_capture_contracts_report", "pose_geometry_capture_contracts_report_harness_transport_lifecycle"].includes(value.implementation_hash_scope) ? value.implementation_hash_scope : null,
    python_version: version(value.python_version),
    pose_engine: ["mediapipe_experimental", "synthetic_demo", "unknown"].includes(value.pose_engine) ? value.pose_engine : "unknown",
    pose_package_version: version(value.pose_package_version),
    pose_model: { sha256: digest(value.pose_model?.sha256, 64), configured_sha256: digest(value.pose_model?.configured_sha256, 64),
      hash_verified: boolean(value.pose_model?.hash_verified) }, pose_settings: poseSettings,
    llm_runtime: value.llm_runtime?.schema_version === "1.0" && Array.isArray(value.llm_runtime.models) ? {
      schema_version: "1.0", snapshot: value.llm_runtime.snapshot === "server_startup_configuration" ? value.llm_runtime.snapshot : null,
      models: value.llm_runtime.models.slice(0, 3).map(safeModelDescriptor).filter(Boolean) } : null };
}
function captureMetadata(motion) {
  const serverDimensions = motion.robustness?.analyzed_image_dimensions;
  const dimensionsValid = serverDimensions && [serverDimensions.min_width_px, serverDimensions.max_width_px,
    serverDimensions.min_height_px, serverDimensions.max_height_px].every(positivePixel);
  const confirmedCount = [...analyzedDimensions.values()].reduce((total, item) => total + item.frame_count, 0);
  return { jpeg_quality: JPEG_QUALITY, max_width_px: MAX_ANALYSIS_WIDTH_PX, max_height_px: MAX_ANALYSIS_HEIGHT_PX,
    sampling_interval_ms: limits.sampling_interval_ms, encoded_dimensions: [...encodedDimensions.values()],
    analyzed_dimensions: [...analyzedDimensions.values()],
    analyzed_image_dimensions: dimensionsValid ? { min_width_px: serverDimensions.min_width_px, max_width_px: serverDimensions.max_width_px,
      min_height_px: serverDimensions.min_height_px, max_height_px: serverDimensions.max_height_px } : null,
    server_dimensions_source: dimensionsValid ? "motion_robustness" : confirmedCount ? "frame_response" : "unavailable",
    unconfirmed_frame_dimensions_count: Math.max(0, networkSamples.length - confirmedCount), freshness_basis: captureFreshnessBasis };
}
function showResultDiagnostics(measurement, motion, stopped) {
  const robustness = motion.robustness;
  const peakContexts = { isolated: "Pic brut isolé", before_only: "Pic brut · voisinage partiel",
    after_only: "Pic brut · voisinage partiel", before_and_after: "Pic brut · voisins temporels présents" };
  const knownRobustness = robustness?.schema_version === "1.0";
  const peak = knownRobustness ? robustness.raw_peak : null;
  const peakLabel = typeof peak?.temporal_context === "string" && Object.hasOwn(peakContexts, peak.temporal_context) ? peakContexts[peak.temporal_context] : null;
  const rejected = stopped || measurement.status === "rejected";
  let diagnostic = !protocol.quantified ? "Guide seul · sans amplitude mesurée" : demo ? "Simulation · données brutes" :
    rejected ? "Essai non exploitable · données brutes" :
    measurement.status === "limited" || robustness?.unusable_frames > 0 ? "Suivi à vérifier" : "Suivi expérimental";
  if (protocol.quantified && peakLabel) diagnostic += ` · ${peakLabel.toLocaleLowerCase("fr")}`;
  writeText("result-diagnostic", diagnostic);
  $("result-diagnostic").hidden = false;
  writeText("chart-caption-label", rejected ? "Courbe brute · données non validées" : "Courbe brute · projection 2D à vérifier");
  const capture = resultDocument.analysis_capture;
  const formatDimensions = (items) => items.length ? items.map((item) => `${item.width_px} × ${item.height_px} (${item.frame_count} images)`).join(", ") : "non disponibles";
  const lines = ["Diagnostic technique du suivi, pas une évaluation du geste.",
    `Aperçu source : ${source.width_px} × ${source.height_px}. JPEG transmis : ${formatDimensions(capture.encoded_dimensions)}.`,
    `Compression JPEG : ${JPEG_QUALITY} · intervalle demandé : ${limits.sampling_interval_ms} ms. La cadence réelle peut être plus lente.`];
  if (capture.analyzed_image_dimensions) {
    const dims = capture.analyzed_image_dimensions;
    lines.push(`Images analysées (serveur) : largeur ${dims.min_width_px}–${dims.max_width_px} px, hauteur ${dims.min_height_px}–${dims.max_height_px} px.`);
  } else lines.push(`Dimensions confirmées par le serveur : ${formatDimensions(capture.analyzed_dimensions)}.`);
  if (!knownRobustness) lines.push("Diagnostic détaillé non fourni par ce serveur.");
  else {
    const count = (value) => Number.isInteger(value) && value >= 0 ? value : "non disponible";
    if (!protocol.quantified || robustness.quantified_protocol === false && robustness.nonquantified_frames > 0)
      lines.push(`Guide seul : ${count(robustness.nonquantified_frames)} images non quantifiées, sans calcul d’amplitude.`);
    else lines.push(`Suivi exploitable : ${count(robustness.usable_frames)} images · non exploitable : ${count(robustness.unusable_frames)} images.`);
    const reasons = Object.entries(qualityLabels).filter(([key]) => Number.isInteger(robustness.invalid_reason_counts?.[key]) && robustness.invalid_reason_counts[key] > 0)
      .map(([key, label]) => `${label} : ${robustness.invalid_reason_counts[key]}`);
    if (reasons.length) lines.push(`Motifs techniques : ${reasons.join(" · ")}.`);
    if (Number.isFinite(robustness.longest_invalid_observed_duration_ms) && robustness.longest_invalid_observed_duration_ms >= 0)
      lines.push(`Plus longue séquence d’images non exploitables reçues : ${(robustness.longest_invalid_observed_duration_ms / 1000).toFixed(1)} s. Ce n’est pas la durée d’une perte caméra.`);
    if (Number.isFinite(robustness.max_adjacent_sample_gap_ms) && robustness.max_adjacent_sample_gap_ms >= 0)
      lines.push(`Écart maximal entre images reçues : ${robustness.max_adjacent_sample_gap_ms} ms.`);
    const angleChange = robustness.largest_adjacent_angle_change;
    if (Number.isFinite(angleChange?.delta_deg) && Number.isFinite(angleChange.gap_ms) && angleChange.gap_ms > 0)
      lines.push(`Écart angulaire brut maximal entre images voisines : ${angleChange.delta_deg > 0 ? "+" : ""}${angleChange.delta_deg.toFixed(1)}° en ${angleChange.gap_ms} ms. Aucun seuil de qualité déduit.`);
    if (peakLabel) lines.push(`${peakLabel}. Les voisins temporels ne valident ni la précision ni le pic.`);
    if (robustness.timestamps_strictly_increasing === false) lines.push("Ordre temporel des images à vérifier.");
  }
  lines.push(!protocol.quantified ? "Guide seul : aucun angle ni pic mesuré." :
    rejected ? "Essai refusé : courbe et pic éventuel sont uniquement des diagnostics bruts, pas un résultat validé." :
    "Angle et image du pic sont bruts : aucun filtre temporel ni validation de précision.");
  if (analysisProvenance) lines.push(`Versions au démarrage serveur : ${analysisProvenance.pose_engine} · Python ${analysisProvenance.python_version || "non fourni"} · moteur ${analysisProvenance.pose_package_version || "non fourni"}.`,
    `Révision : ${analysisProvenance.git_commit || "non fournie"}${analysisProvenance.working_tree_dirty === true ? " · modifications locales présentes" : ""}.`);
  else lines.push("Versions et configuration du serveur non fournies.");
  const configuration = resultDocument.test_configuration;
  if (configuration?.browser) lines.push(`Navigateur : ${configuration.browser.family} ${configuration.browser.version || "version inconnue"} · ${configuration.browser.platform_family}.`);
  if (configuration?.camera) lines.push(`Caméra : ${configuration.camera.label || "nom non fourni"} · ${configuration.camera.settings.width || "?"} × ${configuration.camera.settings.height || "?"} · ${configuration.camera.settings.frameRate || "?"} images/s annoncées par le navigateur.`);
  if (configuration?.selected_model_at_start) lines.push(`Modèle choisi au démarrage : ${configuration.selected_model_at_start.model_id}. Ce choix ne prouve pas un appel LLM.`);
  if (resultDocument.capture_monitor?.interrupted || resultDocument.capture_integrity?.interrupted) lines.push("Capture interrompue : la fraîcheur des images reçues n’a pas été maintenue. Nouvel essai requis.");
  if (resultDocument.llm_usage === null) lines.push("Provenance des appels LLM non fournie par le serveur.");
  else if (!resultDocument.llm_usage.records.length) lines.push("Aucune tentative de génération LLM commencée sur cet essai, selon le serveur.");
  else for (const item of resultDocument.llm_usage.records) lines.push(`Tentatives LLM commencées : ${item.model_id} · ${item.kind === "live" ? "pendant l’essai" : "note finale"} · ${item.completion_call_count}. Ni émission réseau, ni succès du calcul, ni libération GPU prouvés.`);
  writeText("result-technical-details", lines.join("\n"));
  $("result-technical").open = false;
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
function fileEndedNormally() {
  return source?.type === "file" && !preview.error && (preview.ended === true ||
    Number.isFinite(preview.duration) && preview.currentTime >= preview.duration);
}
function clearCaptureWatchdogTimers() {
  clearInterval(captureWatchdogTimer); captureWatchdogTimer = null;
  if (videoFrameCallbackId !== null) preview.cancelVideoFrameCallback?.(videoFrameCallbackId);
  videoFrameCallbackId = null;
}
function checkCaptureWatchdog() {
  if (phase !== "recording" || !captureWatchdog || fileEndedNormally()) return;
  if (captureFreshnessBasis === "media_clock") captureWatchdog.observe(preview.currentTime, preview.readyState, performance.now());
  if (captureWatchdog.check(performance.now())) void finishSession(true, "capture_interrupted");
}
function startCaptureWatchdog() {
  const operation = epoch, currentWatchdog = captureWatchdog;
  captureFreshnessBasis = typeof preview.requestVideoFrameCallback === "function" ? "video_frame_callback" : "media_clock";
  if (captureFreshnessBasis === "video_frame_callback") {
    const observeFrame = (now, metadata) => {
      videoFrameCallbackId = null;
      if (operation !== epoch || phase !== "recording" || captureWatchdog !== currentWatchdog) return;
      currentWatchdog.observe(metadata.mediaTime, preview.readyState, performance.now());
      videoFrameCallbackId = preview.requestVideoFrameCallback(observeFrame);
    };
    videoFrameCallbackId = preview.requestVideoFrameCallback(observeFrame);
  } else currentWatchdog.observe(preview.currentTime, preview.readyState, performance.now());
  captureWatchdogTimer = setInterval(checkCaptureWatchdog, 100);
}
function releaseMedia() {
  clearCaptureWatchdogTimers();
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
  encodedDimensions.clear(); analyzedDimensions.clear();
  if (evidenceUrl) URL.revokeObjectURL(evidenceUrl);
  evidenceUrl = null;
  $("evidence").removeAttribute("src"); $("evidence").hidden = true;
  $("results").hidden = true;
  $("draft").textContent = $("llm-note").textContent = $("llm-status").textContent = "";
  writeText("result-diagnostic", ""); writeText("result-technical-details", "");
  $("result-diagnostic").hidden = true; $("result-technical").open = false;
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
  clearTimeout(finishFrameTimer); finishFrameTimer = null;
  frameController = null; captureWatchdog = null; captureInterruptionReason = null; testConfiguration = null;
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
        if (phase === "recording") finishSession(true, "capture_interrupted"); else cancelSession();
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
    preview.onerror = () => { $("capture-details").textContent = "Lecture interrompue"; if (phase === "recording") finishSession(true, "capture_interrupted"); else cancelSession(); };
    setPhase("ready");
  } catch (error) {
    if (operation !== epoch) return;
    await cancelSession();
    $("capture-details").textContent = message(error);
  }
}
function jpegBlob() {
  return new Promise((resolve, reject) => captureCanvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("Image indisponible")), "image/jpeg", JPEG_QUALITY));
}
async function sampleFrame() {
  checkCaptureWatchdog();
  if (phase !== "recording" || pending || preview.readyState < 2 || !session) return;
  const operation = epoch, currentSession = session;
  const capturedAt = performance.now();
  if (sequence >= limits.max_frames || performance.now() - startedAt >= MAX_DURATION_MS) { finishSession(false); return; }
  const timestamp = clock.next(preview.currentTime, performance.now());
  if (timestamp === null) return;
  const scale = Math.min(1, MAX_ANALYSIS_WIDTH_PX / preview.videoWidth, MAX_ANALYSIS_HEIGHT_PX / preview.videoHeight);
  captureCanvas.width = Math.max(1, Math.round(preview.videoWidth * scale));
  captureCanvas.height = Math.max(1, Math.round(preview.videoHeight * scale));
  captureContext.drawImage(preview, 0, 0, captureCanvas.width, captureCanvas.height);
  const encodedWidth = captureCanvas.width, encodedHeight = captureCanvas.height;
  const currentSequence = sequence++;
  const controller = new AbortController(); frameController = controller;
  const task = (async () => {
    const blob = await jpegBlob();
    if (operation !== epoch || captureInterruptionReason) return;
    const response = await request("/api/frame", { method: "POST", headers: {
      "Content-Type": "image/jpeg", "X-Session-Id": currentSession.session_id,
      "X-Session-Token": currentSession.token, "X-Sequence": String(currentSequence), "X-Timestamp-Ms": String(timestamp),
    }, body: blob }, 15000, controller);
    if (operation !== epoch || captureInterruptionReason) return;
    if (response.quality_reason === "capture_interrupted") {
      // Le verdict serveur est souverain, même si l'horloge du navigateur avance.
      void finishSession(true, "capture_interrupted");
      return;
    }
    captureWatchdog?.acknowledge(capturedAt, performance.now());
    const latencyMs = Math.round(performance.now() - capturedAt);
    networkSamples.push({ sequence: currentSequence, roundtrip_ms: latencyMs, jpeg_bytes: blob.size });
    recordDimensions(encodedDimensions, encodedWidth, encodedHeight);
    const analyzedImage = response.analyzed_image || response.pose;
    recordDimensions(analyzedDimensions, analyzedImage?.width_px, analyzedImage?.height_px);
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
    if (operation === epoch && phase === "recording") {
      void finishSession(true, "capture_interrupted");
      $("capture-details").textContent = `Capture interrompue : ${message(error)}`;
    }
  } finally {
    if (pending === task) pending = null;
    if (frameController === controller) frameController = null;
  }
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
    captureWatchdog = new KineCapture.CaptureWatchdog(startedAt, CAPTURE_WATCHDOG_TIMEOUT_MS);
    captureInterruptionReason = null; testConfiguration = trialConfiguration();
    expiryTimer = setTimeout(() => { cancelSession(); $("capture-details").textContent = "Séance expirée : données effacées"; }, 15 * 60 * 1000);
    setPhase("recording");
    startCaptureWatchdog();
    trialDeadlineTimer = setTimeout(() => finishSession(false), MAX_DURATION_MS);
    $("capture-badge").textContent = demo ? "Essai simulé" : "Suivi caméra";
    await preview.play();
    if (operation !== epoch || phase !== "recording") return;
    await sampleFrame();
    if (operation !== epoch || phase !== "recording") return;
    timer = setInterval(sampleFrame, limits.sampling_interval_ms);
  } catch (error) {
    if (operation === epoch && ["starting", "recording"].includes(phase) && !captureInterruptionReason) {
      await cancelSession(); $("capture-details").textContent = message(error);
    }
  }
}
async function finishSession(stopped, interruptionReason = null) {
  if (phase !== "recording" || !session) return;
  const operation = epoch, currentSession = session;
  const waiting = pending;
  const finishedAt = performance.now(), normalEOF = fileEndedNormally();
  if (!normalEOF && captureWatchdog) {
    if (captureFreshnessBasis === "media_clock") captureWatchdog.observe(preview.currentTime, preview.readyState, finishedAt);
    if (captureWatchdog.check(finishedAt)) interruptionReason = "capture_interrupted";
  }
  if (interruptionReason === "capture_interrupted") {
    stopped = true; captureInterruptionReason = interruptionReason;
    if (captureWatchdog) captureWatchdog.interrupted = true;
    frameController?.abort();
  }
  stopLiveAssistant();
  setPhase("finishing");
  // L'arrêt des pistes ne dépend pas du temps de réponse de l'analyse.
  releaseMedia();
  $("capture-badge").textContent = stopped ? "Essai interrompu" : "Calcul du résultat";
  try {
    if (waiting && !captureInterruptionReason) {
      const remainingAckBudget = Math.max(0, CAPTURE_WATCHDOG_TIMEOUT_MS - (finishedAt - captureWatchdog.lastAcknowledgedAt));
      let ownFinishTimer = null;
      try {
        const timedOut = await Promise.race([waiting.then(() => false), new Promise((resolve) => {
          ownFinishTimer = setTimeout(() => resolve(true), remainingAckBudget); finishFrameTimer = ownFinishTimer;
        })]);
        if (timedOut) throw new Error("capture_interrupted");
      } catch {
        if (operation !== epoch) return;
        stopped = true; captureInterruptionReason = "capture_interrupted";
        captureWatchdog.interrupted = true; frameController?.abort();
      } finally {
        clearTimeout(ownFinishTimer);
        if (finishFrameTimer === ownFinishTimer) finishFrameTimer = null;
      }
    }
    if (operation !== epoch) return;
    const captureMonitor = captureWatchdog?.snapshot(finishedAt) || null;
    const response = await jsonPost("/api/session/finish", { ...currentSession,
      view_confirmed: $("view-confirmed").checked, camera_stable_confirmed: $("stable-confirmed").checked, stopped,
      interruption_reason: captureInterruptionReason, capture_monitor: captureMonitor });
    if (operation !== epoch) return;
    const integrity = safeCaptureIntegrity(response.capture_integrity);
    if (integrity?.interrupted) { stopped = true; captureInterruptionReason = "capture_interrupted"; }
    if (captureInterruptionReason) {
      if (response.measurement.value_deg !== null || response.measurement.status !== "rejected")
        response.draft = "BROUILLON NON VALIDÉ\nCapture interrompue : aucune valeur publiée. Nouvel essai requis.";
      response.measurement = { ...response.measurement, status: "rejected", value_deg: null,
        quality_reasons: [...new Set([...(Array.isArray(response.measurement.quality_reasons) ? response.measurement.quality_reasons : []), "capture_interrupted"])] };
      response.evidence_sequence = response.evidence_timestamp_ms = null;
    }
    const sortedLatency = networkSamples.map((sample) => sample.roundtrip_ms).sort((a, b) => a - b);
    resultDocument = { schema_version: "1.2", capture_version: "0.5.0-dev", mode: demo ? "synthetic_demo" : "mediapipe_experimental", source,
      analysis_capture: captureMetadata(response.motion), analysis_provenance: analysisProvenance,
      test_configuration: { ...testConfiguration, capture_observed_duration_ms: Math.round(Math.max(0, finishedAt - startedAt)) },
      capture_monitor: captureMonitor, capture_integrity: integrity, llm_usage: safeLLMUsage(response.llm_usage),
      protocol: { ...protocol }, network: { processed_requests: networkSamples.length,
        total_jpeg_bytes: networkSamples.reduce((total, sample) => total + sample.jpeg_bytes, 0),
        roundtrip_p95_ms: sortedLatency.length ? sortedLatency[Math.ceil(sortedLatency.length * 0.95) - 1] : null },
      measurement: response.measurement, motion: response.motion, evidence_sequence: response.evidence_sequence,
      evidence_timestamp_ms: response.evidence_timestamp_ms, professional_validation: false };
    const measurement = response.measurement, motion = response.motion;
    $("results").hidden = false;
    $("metric-label").textContent = protocol.quantified ? "Pic brut · 2D" : protocol.metric_label;
    $("metric-label").title = protocol.metric_label;
    $("chart-wrap").hidden = !protocol.quantified;
    $("angle-result").textContent = measurement.value_deg === null ? "—" : `${measurement.value_deg.toFixed(1)}°${demo ? " · simulé" : ""}`;
    $("duration-result").textContent = `${(motion.duration_ms / 1000).toFixed(1)} s`;
    $("coverage-result").textContent = protocol.quantified ? `${measurement.valid_frame_count} / ${measurement.total_frame_count}` : "Non quantifié";
    $("measurement-status").textContent = stopped ? "Essai interrompu" : !protocol.quantified ? "Guide seul · sans mesure" : demo ? "Simulation — non clinique" :
      ({ valid: "Expérimental — à vérifier", limited: "Suivi à vérifier", rejected: "Essai non exploitable", not_performed: "Non réalisé" })[measurement.status];
    $("draft").textContent = (demo ? "SIMULATION : les pixels ne sont pas analysés.\n\n" : "") + response.draft;
    $("evidence-label").textContent = response.evidence_timestamp_ms === null ? "Aucune image du pic brut" :
      `Image du pic brut · ${(response.evidence_timestamp_ms / 1000).toFixed(1)} s`;
    showResultDiagnostics(measurement, motion, stopped);
    KineGuide.drawPose($("pose-overlay"), null, false);
    KineGuide.drawChart($("angle-chart"), motion.samples);
    $("export-report").disabled = $("export-json").disabled = false;
    $("capture-badge").textContent = stopped ? "Essai interrompu" : "Essai terminé";
    $("live-feedback").textContent = stopped ? "Essai interrompu · aucune valeur publiée" : measurement.value_deg === null ?
      (!protocol.quantified ? "Rotation guidée terminée · aucune amplitude mesurée" : "Mesure non disponible — consultez les limites") : "Résultat expérimental, à vérifier";
    $("frame-status").textContent = `${motion.processing_rate_hz} images/s · ${motion.processed_frames} traitées`;
    $("capture-details").textContent = captureInterruptionReason ? "Capture interrompue · nouvel essai requis" :
      "Caméra arrêtée · image du pic brut effacée au nouvel essai";
    setPhase("completed");
    if (captureInterruptionReason) { $("empty-state").hidden = false; return; }
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
for (const id of ["view-confirmed", "stable-confirmed"]) $(id).addEventListener("change", controls);
$("finish").addEventListener("click", () => finishSession(false));
$("stop").addEventListener("click", () => { if (phase === "recording") finishSession(true); else cancelSession(); });
$("restart").addEventListener("click", () => { cancelSession(); $("capture-details").textContent = "Prêt pour un nouvel essai"; $("frame-status").textContent = "Aucune image analysée"; });
$("side").addEventListener("change", async () => {
  if (phase === "completed") await cancelSession();
  $("view-confirmed").checked = false;
  KineGuide.setSide($("side").value);
  controls();
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
  if (resultDocument) {
    // Une tentative peut commencer côté serveur avant toute réponse HTTP.
    resultDocument.llm_usage = null;
    const wasOpen = $("result-technical").open;
    showResultDiagnostics(resultDocument.measurement, resultDocument.motion, resultDocument.capture_monitor?.interrupted === true ||
      resultDocument.capture_integrity?.interrupted === true);
    $("result-technical").open = wasOpen;
  }
  try {
    const response = await jsonPost("/api/harness/draft", { ...currentSession,
      model_id: $("llm-model").value, include_image: $("include-image").checked }, analysisLimits.draft_budget_ms + 5000);
    if (operation !== epoch) return;
    if (resultDocument) {
      resultDocument.llm_usage = safeLLMUsage(response.llm_usage);
      const wasOpen = $("result-technical").open;
      showResultDiagnostics(resultDocument.measurement, resultDocument.motion, resultDocument.capture_monitor?.interrupted === true ||
        resultDocument.capture_integrity?.interrupted === true);
      $("result-technical").open = wasOpen;
    }
    $("llm-note").textContent = response.proposed_note || "Brouillon déterministe conservé";
    const fallbackLabels = { deadline_exceeded: "Délai de l’assistant dépassé · brouillon conservé",
      analysis_deadline_exceeded: "Délai de l’assistant dépassé · brouillon conservé",
      inference_deadline_exceeded: "Délai de l’assistant dépassé · brouillon conservé",
      inference_cancelled: "Analyse interrompue · brouillon conservé",
      cancelled: "Analyse interrompue · brouillon conservé", analysis_busy: "Assistant occupé · brouillon conservé" };
    $("llm-status").textContent = response.fallback_reason ? fallbackLabels[response.fallback_reason] || "Assistant indisponible · brouillon conservé" :
      `Note à revoir${response.image_sent ? " · contexte visuel disponible" : " · sans contexte visuel"}`;
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
  analysisProvenance = safeProvenance(status.provenance);
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
