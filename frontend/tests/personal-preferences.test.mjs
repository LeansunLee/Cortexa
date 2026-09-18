import { test } from 'node:test'
import assert from 'node:assert/strict'
import { activatePreferences } from '../src/utils/preferences.js'
import { readTheme, saveTheme, themeGroups, themeVariables, normalizeTheme } from '../src/utils/theme.js'
import { readAppearance, saveAppearance } from '../src/utils/appearance.js'

test('migrates legacy preferences once and keeps account settings isolated', () => {
 const values = new Map([['themeColor', '#49695E'], ['ui-appearance', 'dark']])
 globalThis.localStorage = { getItem:k=>values.get(k)??null, setItem:(k,v)=>values.set(k,v), removeItem:k=>values.delete(k) }
 globalThis.document = { documentElement:{dataset:{},style:{setProperty(){}}} }
 globalThis.window = { dispatchEvent(){}, matchMedia:()=>({matches:false}) }
 globalThis.CustomEvent = class {}
 activatePreferences('alice')
 assert.equal(readTheme(), '#49695E'); assert.equal(readAppearance(), 'dark')
 const presets=themeGroups.find(g=>g.id==='texture').colors
 assert.equal(presets.length,25)
 for(const preset of presets) {
  saveTheme(preset)
  assert.deepEqual(readTheme(), normalizeTheme(preset))
  assert.match(themeVariables(readTheme())['--theme-gradient'], /data:image\/svg\+xml/)
  assert.notEqual(themeVariables(readTheme())['--theme-gradient-hover'], themeVariables(readTheme())['--theme-gradient'])

 }
 const glasses=themeGroups.find(g=>g.id==='glass').colors
 assert.equal(glasses.length,14)
 for(const glass of glasses) {
  saveTheme(glass)
  assert.deepEqual(readTheme(),normalizeTheme(glass))
  const variables=themeVariables(readTheme())
  assert.match(variables['--theme-gradient'],/radial-gradient/)
  assert.match(variables['--theme-button-background'],/rgba\(255,255,255/)
  assert.equal(variables['--theme-gradient'],variables['--theme-gradient-hover'])
 }
 assert.deepEqual(normalizeTheme({value:'#009EFF',mode:'glass'}),{value:'#009EFF',mode:'glass',finish:'clear'})
 const clearGlass=themeVariables({value:'#009EFF',mode:'glass',finish:'clear'})
 const frostedGlass=themeVariables({value:'#009EFF',mode:'glass',finish:'frosted'})
 const blur=value=>Number(value.match(/blur\((\d+)px\)/)[1])
 assert.ok(blur(clearGlass['--theme-backdrop']) < blur(frostedGlass['--theme-backdrop']), 'frosted glass must diffuse more than clear glass')
 values.set('theme-color:user:alice',JSON.stringify({value:'#123456',accent:'#abcdef',tertiary:'#987654',mode:'tricolor'}))
 assert.deepEqual(readTheme(),{value:'#123456',mode:'texture',texture:'wood'})
 saveTheme(readTheme())
 assert.equal(JSON.parse(values.get('theme-color:user:alice')).mode,'texture')
 assert.deepEqual(normalizeTheme({value:'#123456',mode:'texture',texture:'invalid'}),{value:'#123456',mode:'texture',texture:'wood'})
 const aliceTheme=readTheme()
 activatePreferences('bob')
 assert.equal(readTheme(), '#7C3AED'); assert.equal(readAppearance(),'system')
 saveTheme('#2563EB'); saveAppearance('light')
 activatePreferences('alice')
 assert.deepEqual(readTheme(),aliceTheme); assert.equal(readAppearance(),'dark')
 saveTheme({value:'#2563EB',accent:'#9333EA',mode:'gradient'})
 assert.equal(readTheme().tertiary,undefined)
 saveTheme('#2563EB')
 assert.equal(themeVariables(readTheme())['--theme-gradient'],'none')
})
