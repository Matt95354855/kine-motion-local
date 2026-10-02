const { test } = require('node:test');
const assert = require('node:assert/strict');
const { CaptureClock, landmarkPosition } = require('../apps/web/capture-core.js');

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
