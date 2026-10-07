/* Petites fonctions de capture partagées avec les tests, sans DOM. */
(function (root) {
  "use strict";
  class CaptureClock {
    constructor(source, startedAt = 0) {
      this.source = source;
      this.startedAt = startedAt;
      this.previous = -1;
      this.previousMedia = -1;
    }
    next(mediaSeconds, now) {
      const value = this.source === "file" ? mediaSeconds * 1000 : now - this.startedAt;
      if (!Number.isFinite(value) || value < 0) return null;
      if (!Number.isFinite(mediaSeconds) || mediaSeconds < 0 || mediaSeconds <= this.previousMedia) return null;
      const timestamp = Math.round(value);
      if (timestamp <= this.previous) return null;
      this.previous = timestamp;
      this.previousMedia = mediaSeconds;
      return timestamp;
    }
  }
  class CaptureWatchdog {
    constructor(startedAt, timeoutMs = 3000) {
      this.startedAt = startedAt;
      this.timeoutMs = timeoutMs;
      this.lastMediaTime = -1;
      this.lastSourceAt = startedAt;
      this.lastAcknowledgedAt = startedAt;
      this.lastFrameElapsedMs = null;
      this.interrupted = false;
    }
    observe(mediaSeconds, readyState, now) {
      if (this.interrupted || readyState < 2 || !Number.isFinite(now) || now < this.startedAt ||
        !Number.isFinite(mediaSeconds) || mediaSeconds < 0 || mediaSeconds <= this.lastMediaTime) return;
      this.lastMediaTime = mediaSeconds;
      this.lastSourceAt = now;
    }
    acknowledge(capturedAt, now) {
      if (this.interrupted || !Number.isFinite(capturedAt) || !Number.isFinite(now) ||
        capturedAt < this.startedAt || capturedAt > now) return;
      this.lastAcknowledgedAt = now;
      this.lastFrameElapsedMs = Math.round(capturedAt - this.startedAt);
    }
    check(now) {
      if (Number.isFinite(now) && (now - this.lastSourceAt >= this.timeoutMs ||
        now - this.lastAcknowledgedAt >= this.timeoutMs)) this.interrupted = true;
      return this.interrupted;
    }
    snapshot(now) {
      return { schema_version: "1.0", watchdog_timeout_ms: this.timeoutMs,
        expected_duration_ms: Math.min(135000, Math.round(Math.max(0, now - this.startedAt))),
        last_frame_elapsed_ms: this.lastFrameElapsedMs, interrupted: this.interrupted };
    }
  }
  function browserTrace(userAgent = "", platform = "") {
    const text = typeof userAgent === "string" ? userAgent : "";
    const patterns = [["Edge", /(?:Edg|EdgiOS|EdgA)\/([\d.]+)/], ["Opera", /(?:OPR|Opera)\/([\d.]+)/],
      ["Firefox", /(?:Firefox|FxiOS)\/([\d.]+)/], ["Chrome", /(?:Chrome|CriOS)\/([\d.]+)/],
      ["Safari", /Version\/([\d.]+).*Safari\//]];
    const match = patterns.map(([family, expression]) => ({ family, version: text.match(expression)?.[1] }))
      .find((item) => item.version);
    const system = /Android/.test(text) ? "Android" : /iPhone|iPad|iPod/.test(text) ? "iOS" :
      /Windows/.test(text) ? "Windows" : /Macintosh|Mac OS X/.test(text) ? "macOS" : /Linux/.test(text) ? "Linux" :
      typeof platform === "string" && /Mac/.test(platform) ? "macOS" : typeof platform === "string" && /Win/.test(platform) ? "Windows" : "unknown";
    return { family: match?.family || "unknown", version: match?.version?.slice(0, 32) || null, platform_family: system };
  }
  function landmarkPosition(point, sourceWidth, sourceHeight, width, height, mirrored = false) {
    if (!point || ![point.x, point.y].every(Number.isFinite) || point.x < 0 || point.x > 1 || point.y < 0 || point.y > 1) return null;
    if (![sourceWidth, sourceHeight, width, height].every((n) => Number.isFinite(n) && n > 0)) return null;
    const scale = Math.min(width / sourceWidth, height / sourceHeight);
    const fittedWidth = sourceWidth * scale;
    const fittedHeight = sourceHeight * scale;
    return {
      x: (width - fittedWidth) / 2 + (mirrored ? 1 - point.x : point.x) * fittedWidth,
      y: (height - fittedHeight) / 2 + point.y * fittedHeight,
    };
  }
  const api = { CaptureClock, CaptureWatchdog, browserTrace, landmarkPosition };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.KineCapture = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
