"use strict";

window.KineGuide = (() => {
  const avatar = document.getElementById("guide-avatar");
  const ctx = avatar.getContext("2d");
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  let visible = true;
  let animation = null;
  let side = "left";
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
    const bend = reduced.matches ? 1.5 : 0.2 + (1 - Math.cos(phase * Math.PI * 2)) * 1.12;
    ctx.clearRect(0, 0, 180, 240);
    ctx.save();
    if (side === "right") { ctx.translate(180, 0); ctx.scale(-1, 1); }
    // Une silhouette illustrative, indépendante des repères de la personne filmée.
    ctx.fillStyle = "#d2e6de";
    ctx.beginPath(); ctx.ellipse(90, 226, 47, 6, 0, 0, Math.PI * 2); ctx.fill();
    line(ctx, [82, 144], [76, 211], "#263f43", 18);
    line(ctx, [103, 144], [112, 211], "#365359", 18);
    line(ctx, [70, 217], [82, 217], "#172e32", 12);
    line(ctx, [108, 217], [123, 217], "#172e32", 12);
    line(ctx, [74, 79], [66, 119], "#84b3a4", 14);
    line(ctx, [66, 119], [68, 151], "#dec0a5", 12);
    ctx.fillStyle = "#20836c";
    ctx.beginPath(); ctx.roundRect(72, 68, 42, 86, 16); ctx.fill();
    line(ctx, [92, 61], [92, 73], "#edcbb1", 14);
    circle(ctx, 92, 42, 21, "#f1d1b5");
    ctx.fillStyle = "#314245";
    ctx.beginPath(); ctx.arc(90, 37, 21, Math.PI, 2 * Math.PI); ctx.fill();
    circle(ctx, 103, 42, 2, "#314245");
    line(ctx, [102, 55], [108, 53], "#c3957a", 2);
    const shoulder = [109, 79], elbow = [115, 122];
    const hand = [elbow[0] + 41 * Math.sin(bend), elbow[1] + 41 * Math.cos(bend)];
    line(ctx, shoulder, elbow, "#36a889", 17);
    line(ctx, elbow, hand, "#f1d1b5", 13);
    circle(ctx, ...hand, 8, "#f1d1b5");
    circle(ctx, ...elbow, 4, "#fff5e7");
    ctx.restore();
    const cue = reduced.matches ? "Flexion du coude" : phase < 0.5 ? "Pliez doucement" : "Revenez doucement";
    if (cue !== lastCue) document.getElementById("guide-cue").textContent = lastCue = cue;
    if (visible && !reduced.matches && !document.hidden) animation = requestAnimationFrame(drawAvatar);
  }
  function refresh() {
    if (animation !== null) cancelAnimationFrame(animation);
    animation = null;
    if (visible) drawAvatar(performance.now());
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
    const points = [pose.shoulder, pose.elbow, pose.wrist].map((p) =>
      KineCapture.landmarkPosition(p, pose.width_px, pose.height_px, width, height, mirrored));
    if (points.some((p) => !p)) return;
    for (let i = 0; i < 2; i++) {
      line(context, [points[i].x, points[i].y], [points[i + 1].x, points[i + 1].y], "#152d2f99", 9);
      line(context, [points[i].x, points[i].y], [points[i + 1].x, points[i + 1].y], "#71e0b5", 3);
    }
    for (const p of points) { circle(context, p.x, p.y, 6, "#183e34"); circle(context, p.x, p.y, 3.5, "#a8f4d4"); }
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
    toggle() {
      visible = !visible;
      document.getElementById("guide-panel").hidden = !visible;
      document.getElementById("guide-toggle").setAttribute("aria-pressed", String(visible));
      refresh();
    },
  };
})();
