"use strict";

window.KineGuide = (() => {
  const avatar = document.getElementById("guide-avatar");
  const ctx = avatar.getContext("2d");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  let animation = null;
  let side = "left";
  let guide = "elbow", label = "Coude · flexion";
  let lastCue = "";

  function line(context, a, b, color, width) {
    context.strokeStyle = color;
    context.lineWidth = width;
    context.lineCap = "round";
    context.beginPath(); context.moveTo(...a); context.lineTo(...b); context.stroke();
  }
  function circle(context, x, y, radius, color) {
    context.fillStyle = color;
    context.beginPath(); context.arc(x, y, radius, 0, Math.PI * 2); context.fill();
  }
  function drawAvatar(now) {
    animation = null;
    const phase = (now % 7200) / 7200;
    const progress = reduced.matches ? 0.5 : (1 - Math.cos(phase * Math.PI * 2)) / 2;
    const bend = 0.2 + progress * 1.7;
    ctx.clearRect(0, 0, 180, 240);
    ctx.save();
    if (side === "right") { ctx.translate(180, 0); ctx.scale(-1, 1); }
    // Une silhouette illustrative, indépendante des repères de la personne filmée.
    ctx.fillStyle = "#d2e6de";
    ctx.beginPath(); ctx.ellipse(90, 226, 47, 6, 0, 0, Math.PI * 2); ctx.fill();
    line(ctx, [82, 144], [76, 211], "#263f43", 18);
    const knee = guide === "hip" ? [103 + progress * 36, 176 - progress * 20] : [108, 180];
    const ankle = guide === "knee" ? [108 + Math.sin(progress * 1.3) * 34, 180 + Math.cos(progress * 1.3) * 34] :
      guide === "hip" ? [knee[0] - 2, knee[1] + 35] : [112, 211];
    line(ctx, [103, 144], knee, "#365359", 18);
    line(ctx, knee, ankle, "#365359", 16);
    line(ctx, [70, 217], [82, 217], "#172e32", 12);
    line(ctx, [ankle[0] - 3, ankle[1] + 6], [ankle[0] + 12, ankle[1] + 6], "#172e32", 12);
    ctx.save();
    if (guide === "trunk") { ctx.translate(92, 145); ctx.rotate(progress * 0.28); ctx.translate(-92, -145); }
    line(ctx, [74, 79], [66, 119], "#84b3a4", 14);
    line(ctx, [66, 119], [68, 151], "#dec0a5", 12);
    ctx.fillStyle = "#20836c";
    ctx.beginPath(); ctx.roundRect(72, 68, 42, 86, 16); ctx.fill();
    line(ctx, [92, 61], [92, 73], "#edcbb1", 14);
    ctx.save();
    if (guide === "neck_tilt") { ctx.translate(92, 67); ctx.rotate(progress * 0.30); ctx.translate(-92, -67); }
    const headWidth = guide === "neck_turn" ? 21 - progress * 5 : 21;
    ctx.fillStyle = "#f1d1b5";
    ctx.beginPath(); ctx.ellipse(92, 42, headWidth, 21, 0, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#314245";
    ctx.beginPath(); ctx.ellipse(90, 37, headWidth, 21, 0, Math.PI, 2 * Math.PI); ctx.fill();
    // Le déplacement du visage illustre la rotation, sans en déduire un angle.
    const frontal = ["shoulder", "trunk", "neck_tilt"].includes(guide);
    const faceX = guide === "neck_turn" ? 98 + progress * 9 : frontal ? 98 : 103;
    circle(ctx, faceX, 42, 2, "#314245");
    if (frontal) circle(ctx, 86, 42, 2, "#314245");
    if (guide === "neck_turn" && progress < 0.65) circle(ctx, faceX - 12 * (1 - progress), 42, 2, "#314245");
    line(ctx, frontal ? [88, 54] : [102, 55], frontal ? [96, 54] : [108, 53], "#c3957a", 2);
    ctx.restore();
    const shoulder = [104, 79];
    const lift = guide === "shoulder" ? progress * 1.35 : 0.13;
    const elbow = [shoulder[0] + 36 * Math.sin(lift), shoulder[1] + 36 * Math.cos(lift)];
    const forearm = guide === "elbow" ? bend : lift;
    const hand = [elbow[0] + 32 * Math.sin(forearm), elbow[1] + 32 * Math.cos(forearm)];
    line(ctx, shoulder, elbow, "#36a889", 17);
    line(ctx, elbow, hand, "#f1d1b5", 13);
    circle(ctx, ...hand, 8, "#f1d1b5");
    circle(ctx, ...elbow, 4, "#fff5e7");
    ctx.restore();
    ctx.restore();
    const cues = { elbow: "Flexion", knee: "Flexion", shoulder: "Élévation latérale", hip: "Flexion",
      trunk: "Inclinaison", neck_tilt: "Inclinaison de la tête", neck_turn: "Rotation · guide seul" };
    const cue = reduced.matches ? "Illustration du geste" : phase < 0.5 ? cues[guide] : "Retour · à votre rythme";
    if (cue !== lastCue) document.getElementById("guide-cue").textContent = lastCue = cue;
    if (!reduced.matches && !document.hidden) animation = requestAnimationFrame(drawAvatar);
  }
  function refresh() {
    if (animation !== null) cancelAnimationFrame(animation);
    animation = null;
    drawAvatar(performance.now());
  }
  reduced.addEventListener("change", refresh);
  document.addEventListener("visibilitychange", refresh);
  refresh();

  function surface(canvas) {
    const rect = canvas.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(rect.width * ratio);
    canvas.height = Math.round(rect.height * ratio);
    const context = canvas.getContext("2d");
    context.scale(ratio, ratio);
    return { context, width: rect.width, height: rect.height };
  }
  function drawPose(canvas, pose, mirrored) {
    const { context, width, height } = surface(canvas);
    if (!pose) return;
    const points = (pose.points || [pose.shoulder, pose.elbow, pose.wrist]).map((p) =>
      KineCapture.landmarkPosition(p, pose.width_px, pose.height_px, width, height, mirrored));
    for (const [i, j] of pose.connections || [[0, 1], [1, 2]]) {
      if (!points[i] || !points[j]) continue;
      line(context, [points[i].x, points[i].y], [points[j].x, points[j].y], "#152d2f99", 9);
      line(context, [points[i].x, points[i].y], [points[j].x, points[j].y], "#71e0b5", 3);
    }
    if (pose.protocol_id === "trunk_lateral_inclination" && points.every(Boolean)) {
      const a = [(points[0].x + points[1].x) / 2, (points[0].y + points[1].y) / 2];
      const b = [(points[2].x + points[3].x) / 2, (points[2].y + points[3].y) / 2];
      line(context, a, b, "#71e0b5", 3);
      line(context, b, [b[0], a[1]], "#ffffff88", 1);
    }
    for (const p of points.filter(Boolean)) { circle(context, p.x, p.y, 6, "#183e34"); circle(context, p.x, p.y, 3.5, "#a8f4d4"); }
  }
  function drawChart(canvas, samples) {
    const { context, width, height } = surface(canvas);
    if (!width || !height) return;
    const left = 38, right = width - 12, top = 12, bottom = height - 26;
    context.font = "11px system-ui";
    context.fillStyle = "#77837e";
    for (const angle of [0, 60, 120, 180]) {
      const y = bottom - angle / 180 * (bottom - top);
      line(context, [left, y], [right, y], "#e4ebe6", 1);
      context.fillText(`${angle}°`, 3, y + 4);
    }
    if (!samples?.length) return;
    const start = samples[0].timestamp_ms, end = samples.at(-1).timestamp_ms;
    const x = (t) => left + (t - start) / Math.max(1, end - start) * (right - left);
    context.fillText("0 s", left, height - 6);
    context.fillText(`${((end - start) / 1000).toFixed(1)} s`, Math.max(left, right - 38), height - 6);
    context.strokeStyle = "#248368"; context.lineWidth = 2.5;
    context.beginPath();
    let connected = false;
    for (const sample of samples) {
      if (sample.angle_deg === null || sample.quality_reason) { connected = false; continue; }
      const px = x(sample.timestamp_ms), py = bottom - sample.angle_deg / 180 * (bottom - top);
      if (connected) context.lineTo(px, py); else context.moveTo(px, py);
      connected = true;
    }
    context.stroke();
  }
  return {
    drawPose, drawChart,
    setSide(value) { side = value; refresh(); },
    setProtocol(value, description) {
      guide = value; label = description;
      avatar.setAttribute("aria-label", `Personnage illustratif : ${label}. Pas une prescription.`);
      refresh();
    },
  };
})();
