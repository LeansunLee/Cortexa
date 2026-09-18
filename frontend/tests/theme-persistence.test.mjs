import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readTheme, saveTheme, themeVariables } from '../src/utils/theme.js'

test('saved preset and custom colors survive a fresh read on the next visit', () => {
  const values = new Map([['themeColor', '#49695E']])
  globalThis.localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
  const styles = new Map()
  globalThis.document = { documentElement: { style: { setProperty: (key, value) => styles.set(key, value) } } }
  globalThis.window = { dispatchEvent() {} }
  globalThis.CustomEvent = class { constructor(type, options) { this.type = type; this.detail = options.detail } }
  assert.equal(readTheme(), '#49695E')
  for (const color of ['#3478D4', '#a1b2c3']) {
    saveTheme(color)
    assert.equal(readTheme(), color.toUpperCase())
    assert.equal(styles.get('--primary'), themeVariables(readTheme())['--primary'])
    assert.equal(values.has('themeColor'), false)
  }
  saveTheme('invalid')
  assert.equal(readTheme(), '#A1B2C3')
})

test('unavailable storage does not prevent startup and save failures remain observable', () => {
  const storage = { getItem() { throw new Error('storage disabled') }, setItem() { throw new Error('storage disabled') } }
  assert.equal(readTheme(storage), '#7C3AED')
  globalThis.localStorage = storage
  assert.throws(() => saveTheme('#3478D4'), /storage disabled/)
})

test('duotone presets and custom pairs persist atomically and switching to a single color clears the accent', async () => {
  const { themeGroups } = await import('../src/utils/theme.js')
  const pairs = themeGroups.find(group => group.id === 'contrast').colors
  assert.equal(pairs.length, 14)
  assert.equal(new Set(pairs.map(pair => `${pair.value}/${pair.accent}`)).size, 14)
  const values = new Map()
  globalThis.localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
  const styles = new Map()
  globalThis.document = { documentElement: { style: { setProperty: (key, value) => styles.set(key, value) } } }
  globalThis.window = { dispatchEvent() {} }
  for (const pair of [...pairs, { value: '#abcdef', accent: '#fedcba' }]) {
    saveTheme(pair)
    const restored = readTheme()
    assert.deepEqual(restored, { value: pair.value.toUpperCase(), accent: pair.accent.toUpperCase() })
    assert.deepEqual(Object.fromEntries(styles), themeVariables(restored))
    for (const key of ['--primary', '--accent']) {
      const lightColor = styles.get(key).match(/#[\da-f]{6}/i)[0]
      const rgb = lightColor.slice(1).match(/[\da-f]{2}/gi).map(value => parseInt(value, 16) / 255)
      const linear = rgb.map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4)
      const luminance = linear.reduce((sum, value, i) => sum + value * [.2126, .7152, .0722][i], 0)
      assert.ok(1.05 / (luminance + .05) >= 4.5, `${pair.value} ${key}`)
    }
  }
  saveTheme('#0066FF')
  assert.equal(readTheme(), '#0066FF')
  assert.equal(styles.get('--primary'), styles.get('--accent'))
  saveTheme({ value: '#0066FF', accent: 'invalid' })
  assert.equal(readTheme(), '#0066FF')
  values.set('theme-color', '{broken')
  values.set('themeColor', '#49695E')
  assert.equal(readTheme(), '#49695E')
})

test('gradient mode persists separately from split colors and clears on single/duotone selection', async () => {
  const { themeGroups, swatchStyle } = await import('../src/utils/theme.js')
  const presets = themeGroups.find(group => group.id === 'gradient').colors
  assert.equal(presets.length, 14)
  const values = new Map()
  globalThis.localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
  const styles = new Map()
  globalThis.document = { documentElement: { style: { setProperty: (key, value) => styles.set(key, value) } } }
  globalThis.window = { dispatchEvent() {} }
  for (const preset of [...presets, { value: '#abcdef', accent: '#fedcba', mode: 'gradient' }]) {
    saveTheme(preset)
    assert.deepEqual(readTheme(), { value: preset.value.toUpperCase(), accent: preset.accent.toUpperCase(), mode: 'gradient' })
    assert.match(styles.get('--theme-gradient'), /linear-gradient/)
    assert.match(swatchStyle(preset).background, /linear-gradient/)
    const colors = styles.get('--theme-gradient').match(/#[\da-f]{6}/gi).map(hex => hex.slice(1).match(/../g).map(v => parseInt(v, 16)))
    for (let i = 0; i <= 20; i++) {
      const rgb = colors[0].map((v, c) => (v + (colors[1][c] - v) * i / 20) / 255)
      const luminance = rgb.map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4).reduce((s,v,c) => s + v * [.2126,.7152,.0722][c], 0)
      assert.ok(1.05 / (luminance + .05) >= 4.5)
    }
  }
  saveTheme({ value: '#2563EB', accent: '#9333EA' })
  assert.equal(readTheme().mode, undefined)
  assert.equal(styles.get('--theme-gradient'), 'none')
  saveTheme('#2563EB')
  assert.equal(styles.get('--theme-gradient-hover'), 'none')
  assert.equal(readTheme(), '#2563EB')
})
