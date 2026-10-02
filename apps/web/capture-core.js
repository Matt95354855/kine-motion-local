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
  const api = { CaptureClock, landmarkPosition };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.KineCapture = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
