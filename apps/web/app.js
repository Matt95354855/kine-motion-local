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
async function request(path, options = {}, timeout = 15000) {
  const controller = new AbortController();
  controllers.add(controller);
  const timeoutId = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(path, { cache: "no-store", ...options, signal: controller.signal });
    const body = await response.json();
    if (!response.ok) throw new Error(({ forbidden: "Séance expirée ou non autorisée",
      invalid_request: "Capture ou paramètres invalides", pose_engine_unavailable: "Moteur de pose indisponible",
      protocol_not_supported_by_harness: "L’assistant actuel prend en charge le coude uniquement" })[body.error] || `Erreur ${response.status}`);
    return body;
  } finally { clearTimeout(timeoutId); controllers.delete(controller); }
}
function jsonPost(path, document, timeout) {
  return request(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(document) }, timeout);
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
}
function setPhase(value) { phase = value; controls(); }
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
async function cancelSession() {
  ++epoch;
  const old = session;
  session = null; source = null; llmBusy = false;
  controllers.forEach((controller) => controller.abort());
  pending = null;
  clearTimeout(expiryTimer); expiryTimer = null;
  releaseMedia(); clearResults();
  preview.classList.remove("mirrored");
  $("empty-state").hidden = false;
  $("capture-badge").textContent = "Caméra inactive";
  $("elapsed").textContent = "00:00";
  setPhase("idle");
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
      $("live-feedback").textContent = "Repères expirés — attente de l’analyse";
    }, Math.max(0, 1000 - latencyMs));
    const feedback = response.quality_reason ? qualityLabels[response.quality_reason] || "Capture à vérifier" :
      !protocol.quantified ? "Observation guidée · aucun angle calculé" :
      response.angle_deg === null ? "Repères non exploitables" : `${Math.round(response.angle_deg)}° · projection 2D`;
    $("live-feedback").textContent = (demo ? "Simulation · " : "") +
      (delayed ? "Analyse retardée — repères masqués" : feedback);
    $("frame-status").textContent = `${response.sequence + 1} images · ${latencyMs} ms`;
    $("frame-status").title = `Aller-retour traitement : ${latencyMs} ms`;
    const seconds = Math.floor(timestamp / 1000);
    $("elapsed").textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
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
    $("capture-badge").textContent = demo ? "Essai simulé" : "Analyse en cours";
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
    resultDocument = { schema_version: "1.1", capture_version: "0.3.0-dev", mode: demo ? "synthetic_demo" : "mediapipe_experimental", source,
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
  $("model-status").textContent = !protocol.harness_supported ? "Assistant inchangé : disponible pour le coude uniquement. Brouillon descriptif pour ce mouvement." :
    selected?.configured ? "Serveur configuré, non encore vérifié" : "Sans serveur : brouillon déterministe disponible";
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
$("llm-model").addEventListener("change", updateModelSelection);
$("check-model").addEventListener("click", async () => {
  const selected = $("llm-model").value;
  $("model-status").textContent = "Vérification…";
  try {
    const response = await jsonPost("/api/models/check", { model_id: selected });
    const labels = { ready: "Modèle annoncé par le serveur local", model_not_advertised: "Alias absent du serveur",
      runtime_unreachable: "Serveur inaccessible", not_configured: "Serveur non configuré" };
    if ($("llm-model").value === selected) $("model-status").textContent = labels[response.state] || response.state;
  } catch (error) { $("model-status").textContent = message(error); }
});
$("llm-draft").addEventListener("click", async () => {
  if (phase !== "completed" || llmBusy || !session || !protocol.harness_supported) return;
  const operation = epoch, currentSession = session;
  llmBusy = true; controls(); $("llm-status").textContent = "Préparation de la note…";
  try {
    const response = await jsonPost("/api/harness/draft", { ...currentSession,
      model_id: $("llm-model").value, include_image: $("include-image").checked }, 120000);
    if (operation !== epoch) return;
    $("llm-note").textContent = response.proposed_note || "Brouillon déterministe conservé";
    $("llm-status").textContent = response.fallback_reason ? `Repli : ${response.fallback_reason}` :
      `Note à revoir${response.image_sent ? " · une image transmise localement" : " · aucune image transmise"}`;
  } catch (error) { if (operation === epoch) $("llm-status").textContent = message(error); }
  finally { if (operation === epoch) { llmBusy = false; controls(); } }
});
new ResizeObserver(() => {
  KineGuide.drawPose($("pose-overlay"), phase === "recording" ? latestPose : null, Boolean(source?.mirrored_preview));
  if (resultDocument) KineGuide.drawChart($("angle-chart"), resultDocument.motion.samples);
}).observe($("camera-stage"));
document.addEventListener("visibilitychange", () => { if (document.hidden && phase === "recording") finishSession(true); });
window.addEventListener("pagehide", () => {
  if (session) navigator.sendBeacon("/api/session/cancel", new Blob([JSON.stringify(session)], { type: "application/json" }));
  releaseMedia();
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
  $("llm-model").replaceChildren(...models.map((item) => {
    const option = document.createElement("option"); option.value = item.id; option.textContent = item.label; return option;
  }));
  $("llm-model").disabled = !models.length;
  const first = models.find((item) => item.configured); if (first) $("llm-model").value = first.id;
  updateModelSelection();
  $("engine-status").textContent = demo ? "Démo · pose simulée" : "Pose réelle · expérimental";
  serverReady = true; updateProtocol();
}).catch(() => { $("engine-status").textContent = "Serveur indisponible"; });
