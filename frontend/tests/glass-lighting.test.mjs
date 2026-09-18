import test from 'node:test'
import assert from 'node:assert/strict'
import { glassLightPosition, advanceGlassLight } from '../src/utils/glassLighting.js'

const rect = { left: 100, top: 200, width: 300, height: 160 }
test('interior pointers project onto their nearest edge, not their own position', () => {
  for (const [x, y, expectedX, expectedY] of [
    [80, 10, 80, 0], [290, 60, 300, 60], [120, 150, 120, 160],
    [10, 70, 0, 70], [150, 80, 150, 0], [10, 10, 10, 0],
  ]) {
    assert.deepEqual(glassLightPosition(rect, { x: 100 + x, y: 200 + y }),
      { x: expectedX, y: expectedY, distance: 0 })
  }
})

test('the broader light source stays outside on every side and through corner transitions', () => {
  for (const [width, height] of [[100, 40], [640, 400]]) {
    const box = { ...rect, width, height }
    for (const setback of [28, 36]) {
      let current = null
      for (let step = 0; step < 1000; step++) {
        const target = glassLightPosition(box, {
          x: rect.left + (step * 17) % width,
          y: rect.top + (step * 13) % height,
        })
        const light = advanceGlassLight(box, current, target, .18, setback)
        assert.ok(light.x < 0 || light.x > width || light.y < 0 || light.y > height)
        assert.ok(Number.isFinite(light.x) && Number.isFinite(light.y))
        current = light.position
      }
    }
  }
})
test('source setback and easing settle without perpetual animation', () => {
  const target = { x: 150, y: 0 }
  let light = advanceGlassLight(rect, null, target, 1, 28)
  assert.equal(light.x, 150)
  assert.equal(light.y, -28)
  assert.equal(light.moving, false)
  for (let i = 0; i < 100; i++) light = advanceGlassLight(rect, light.position, { x: 150, y: 160 }, .18, 28)
  assert.equal(light.moving, false)
  assert.equal(light.x, 150)
  assert.equal(light.y, 188)
})
test('exterior pointers retain distance falloff and corner projection', () => {
  assert.deepEqual(glassLightPosition(rect, { x: 420, y: 260 }), { x: 300, y: 60, distance: 20 })
  assert.deepEqual(glassLightPosition(rect, { x: 97, y: 196 }), { x: 0, y: 0, distance: 5 })
  assert.deepEqual(glassLightPosition(rect, { x: 100, y: 250 }), { x: 0, y: 50, distance: 0 })
})
test('all sampled positions land on the boundary of both a button and a large card', () => {
  for (const [width, height] of [[100, 40], [640, 400]]) {
    for (let x = -20; x <= width + 20; x += 7) for (let y = -20; y <= height + 20; y += 7) {
      const light = glassLightPosition({ ...rect, width, height }, { x: rect.left + x, y: rect.top + y })
      assert.ok(light.x === 0 || light.x === width || light.y === 0 || light.y === height)
      assert.ok(light.x >= 0 && light.x <= width && light.y >= 0 && light.y <= height)
    }
  }
})
