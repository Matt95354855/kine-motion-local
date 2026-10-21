const { test } = require('node:test');
const assert = require('node:assert/strict');
const { CaptureClock, CaptureWatchdog, browserTrace, landmarkPosition } = require('../apps/web/capture-core.js');

test('video timestamps come from source time, not network or playback delay', () => {
  const clock = new CaptureClock('file', 999);
  assert.equal(clock.next(0, 3000), 0);
  assert.equal(clock.next(0.2, 10000), 200);
  assert.equal(clock.next(0.2, 11000), null);
  assert.equal(clock.next(0.1, 12000), null);
  assert.equal(clock.next(0.4, 99999), 400);
});
test('camera clock is relative and strictly monotonic', () => {
  const clock = new CaptureClock('camera', 5000);
  assert.equal(clock.next(10, 5000), 0);
  assert.equal(clock.next(11, 5200), 200);
  assert.equal(clock.next(11, 5200), null);
  assert.equal(clock.next(0, NaN), null);
  assert.equal(clock.next(11, 5400), null);
  assert.equal(clock.next(11.2, 5600), 600);
});
test('landmarks follow the contained image, including vertical letterboxing', () => {
  assert.deepEqual(landmarkPosition({ x: 0, y: 0 }, 640, 480, 800, 450), { x: 100, y: 0 });
  assert.deepEqual(landmarkPosition({ x: 1, y: 1 }, 640, 480, 800, 450), { x: 700, y: 450 });
  assert.deepEqual(landmarkPosition({ x: 0, y: 0 }, 1280, 720, 400, 400), { x: 0, y: 87.5 });
});
test('mirroring changes only display coordinates, never anatomical input', () => {
  const point = { x: 0.25, y: 0.5 };
  assert.deepEqual(landmarkPosition(point, 640, 480, 640, 480, true), { x: 480, y: 240 });
  assert.deepEqual(point, { x: 0.25, y: 0.5 });
});
test('missing, non-finite or out-of-frame landmarks are not drawn', () => {
  for (const point of [null, { x: NaN, y: 0.5 }, { x: 1.2, y: 0.5 }, { x: 0.2, y: -1 }]) {
    assert.equal(landmarkPosition(point, 640, 480, 640, 480), null);
  }
  assert.equal(landmarkPosition({ x: 0.5, y: 0.5 }, 0, 0, 640, 480), null);
});
test('three acknowledged frames never make a frozen media clock complete normally', () => {
  const watchdog = new CaptureWatchdog(1000);
  for (const [media, now] of [[0, 1000], [0.2, 1200], [0.4, 1400]]) {
    watchdog.observe(media, 2, now); watchdog.acknowledge(now, now);
  }
  watchdog.observe(0.4, 4, 4399); assert.equal(watchdog.check(4399), false);
  watchdog.observe(0.4, 4, 4400); assert.equal(watchdog.check(4400), true);
  assert.deepEqual(watchdog.snapshot(4400), { schema_version: '1.0', watchdog_timeout_ms: 3000,
    expected_duration_ms: 3400, last_frame_elapsed_ms: 400, interrupted: true });
  watchdog.observe(0.8, 4, 4500); watchdog.acknowledge(4500, 4500);
  assert.equal(watchdog.check(4500), true); // no automatic recovery
});
test('advancing video cannot hide an analysis request that never acknowledges an image', () => {
  const watchdog = new CaptureWatchdog(500);
  for (let now = 500; now <= 3500; now += 100) watchdog.observe((now - 500) / 1000, 4, now);
  assert.equal(watchdog.check(3499), false);
  assert.equal(watchdog.check(3500), true);
  assert.equal(watchdog.snapshot(3500).last_frame_elapsed_ms, null);
});
test('low readyState and repeated or regressing media timestamps do not count as fresh frames', () => {
  const watchdog = new CaptureWatchdog(0);
  watchdog.observe(10, 4, 0); watchdog.acknowledge(0, 0);
  watchdog.observe(11, 1, 2000); watchdog.observe(10, 4, 2200); watchdog.observe(9, 4, 2500);
  watchdog.acknowledge(2500, 2500);
  assert.equal(watchdog.check(3000), true);
});
test('browser trace keeps family/version and OS family but no raw user-agent or device IDs', () => {
  assert.deepEqual(browserTrace('Mozilla/5.0 (Windows NT 10.0) Chrome/140.0.1.2 Safari/537.36 Edg/140.0.2.3'),
    { family: 'Edge', version: '140.0.2.3', platform_family: 'Windows' });
  assert.deepEqual(browserTrace('Mozilla/5.0 (Macintosh) Version/18.0 Safari/605.1.15 private-machine-token'),
    { family: 'Safari', version: '18.0', platform_family: 'macOS' });
  assert.deepEqual(browserTrace(), { family: 'unknown', version: null, platform_family: 'unknown' });
});
