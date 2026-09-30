"use strict";

const $ = (id) => document.getElementById(id);
const preview = $("preview");
const canvas = document.createElement("canvas");
const context = canvas.getContext("2d", { willReadFrequently: false });
let session = null;
let stream = null;
let fileUrl = null;
let timer = null;
let pending = null;
let sequence = 0;
let startedAt = 0;
let mode = null;
let ending = false;

async function request(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `Erreur HTTP ${response.status}`);
  return body;
}

function jsonPost(path, document) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(document),
  });
}

function releaseMedia() {
  if (timer) clearInterval(timer);
  timer = null;
  if (stream) stream.getTracks().forEach((track) => track.stop());
  stream = null;
  preview.pause();
  preview.srcObject = null;
  preview.removeAttribute("src");
  preview.onended = null;
  if (fileUrl) URL.revokeObjectURL(fileUrl);
  fileUrl = null;
  mode = null;
  preview.classList.remove("mirrored");
  $("finish").disabled = true;
  $("stop").disabled = true;
}

function jpegBlob() {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("Image non disponible")), "image/jpeg", 0.8);
  });
}

async function sampleFrame() {
  if (!session || !mode || pending || ending || preview.readyState < 2) return;
  const currentSession = session;
  const scale = Math.min(1, 640 / preview.videoWidth, 1080 / preview.videoHeight);
  const width = Math.round(preview.videoWidth * scale);
  const height = Math.round(preview.videoHeight * scale);
  if (!width || !height) return;
  canvas.width = width;
  canvas.height = height;
  context.drawImage(preview, 0, 0, width, height); // Jamais l'affichage miroir.
  const currentSequence = sequence++;
  const timestamp = Math.max(0, Math.round(performance.now() - startedAt));
  pending = (async () => {
    const blob = await jpegBlob();
    if (blob.type !== "image/jpeg") throw new Error("Format JPEG indisponible");
    const result = await request("/api/frame", {
      method: "POST",
      headers: {
        "Content-Type": "image/jpeg",
        "X-Session-Id": currentSession.session_id,
        "X-Session-Token": currentSession.token,
        "X-Sequence": String(currentSequence),
        "X-Timestamp-Ms": String(timestamp),
      },
      body: blob,
    });
    $("frame-status").textContent = `Image ${result.sequence + 1} traitée` +
      (result.quality_reason ? ` · ${result.quality_reason}` : "");
  })();
  try { await pending; }
  catch (error) {
    $("frame-status").textContent = `Capture interrompue : ${error.message}`;
    await cancelSession();
  } finally { pending = null; }
}

async function begin(source) {
  if (session || ending) await cancelSession();
  $("draft").textContent = "";
  $("llm-note").textContent = "";
  $("llm-draft").disabled = true;
  $("view-confirmed").checked = false;
  $("stable-confirmed").checked = false;
  try {
    if (source === "camera") {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("Caméra indisponible sur cette origine");
      stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } },
        audio: false,
      });
      preview.srcObject = stream;
      preview.classList.add("mirrored");
      stream.getVideoTracks()[0].addEventListener("ended", () => cancelSession());
      const settings = stream.getVideoTracks()[0].getSettings();
      $("capture-details").textContent = `Webcam : ${settings.width || "?"} × ${settings.height || "?"} pixels`;
    } else {
      const file = $("video-file").files[0];
      if (!file) return;
      fileUrl = URL.createObjectURL(file);
      preview.src = fileUrl;
      $("capture-details").textContent = `Vidéo locale : ${file.name}`;
      preview.onended = () => finishSession(false);
    }
    await preview.play();
    session = await jsonPost("/api/session/start", { side: $("side").value });
    mode = source;
    sequence = 0;
    startedAt = performance.now();
    $("finish").disabled = false;
    $("stop").disabled = false;
    $("frame-status").textContent = "Analyse en cours…";
    timer = setInterval(sampleFrame, 200);
  } catch (error) {
    $("capture-details").textContent = `Démarrage impossible : ${error.message}`;
    await cancelSession();
  }
}

async function finishSession(stopped) {
  if (!session || ending) return;
  ending = true;
  if (timer) clearInterval(timer);
  timer = null;
  if (stopped && stream) stream.getTracks().forEach((track) => track.stop());
  if (stopped) preview.pause();
  try {
    if (pending) await pending;
    if (!session) return;
    const result = await jsonPost("/api/session/finish", {
      ...session,
      view_confirmed: $("view-confirmed").checked,
      camera_stable_confirmed: $("stable-confirmed").checked,
      stopped,
    });
    $("measurement-status").textContent = `Statut : ${result.measurement.status}`;
    $("draft").textContent = result.draft;
    $("llm-draft").disabled = false;
    $("frame-status").textContent = "Essai terminé.";
  } catch (error) {
    $("frame-status").textContent = `Fin d'essai impossible : ${error.message}`;
    await cancelSession();
  } finally {
    releaseMedia();
    ending = false;
  }
}

async function cancelSession() {
  const old = session;
  session = null;
  releaseMedia();
  if (old) {
    try { await jsonPost("/api/session/cancel", old); } catch (_) { /* séance locale expirée */ }
  }
}

$("camera-start").addEventListener("click", () => begin("camera"));
$("video-file").addEventListener("change", () => begin("file"));
$("finish").addEventListener("click", () => finishSession(false));
$("stop").addEventListener("click", () => finishSession(true));
$("llm-draft").addEventListener("click", async () => {
  if (!session) return;
  $("llm-status").textContent = "Consultation du harness local…";
  try {
    const result = await jsonPost("/api/harness/draft", session);
    $("llm-note").textContent = result.proposed_note || "Aucune note du modèle ; brouillon déterministe conservé.";
    $("llm-status").textContent = result.fallback_reason ?
      `Repli utilisé : ${result.fallback_reason}` : "Note proposée pour revue professionnelle.";
  } catch (error) { $("llm-status").textContent = `Harness indisponible : ${error.message}`; }
});
window.addEventListener("pagehide", () => {
  if (session) {
    const body = new Blob([JSON.stringify(session)], { type: "application/json" });
    navigator.sendBeacon("/api/session/cancel", body);
  }
  releaseMedia();
});
request("/api/status").then((status) => {
  $("engine-status").textContent = `Pose : ${status.pose_mode} · LLM local : ${status.llm_configured ? "configuré" : "absent (repli disponible)"} · Image au LLM : ${status.llm_vision ? "activée" : "désactivée"}`;
}).catch(() => { $("engine-status").textContent = "Serveur local indisponible."; });
