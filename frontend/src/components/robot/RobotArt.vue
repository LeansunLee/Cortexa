<template>
  <div class="robot-art" :data-anim="state" :class="{ still: !animations }">
    <img :src="src" class="robot-img" alt="" draggable="false" :style="glow ? { filter: glow } : null" @error="$emit('art-error')" />
    <canvas ref="face" class="robot-face" width="96" height="43"></canvas>
  </div>
</template>

<script setup>
// Shared mascot art: the armless body image plus a low-res pixel "face"
// canvas that expresses the business state (RobotController states). The
// face box sits on the visor and is rotated 8.17deg to match its tilt; the
// canvas is drawn at half resolution and upscaled with pixelated rendering
// so expressions keep the chunky pixel-art look. When a theme is given, the
// neutral body pixels are re-tinted toward the theme's primary color via
// robotTint (the canvas face keeps its own readable palette).
import { ref, watch, onBeforeUnmount } from 'vue'
import { normalizeTheme } from '../../utils/theme'
import { robotArtUrl, tintedRobotArt } from './robotTint.js'

const props = defineProps({
  state: { type: String, default: 'idle' },
  animations: { type: Boolean, default: true },
  theme: { type: [Object, String], default: null },
})
defineEmits(['art-error'])

const face = ref(null)
const src = ref(robotArtUrl('base.png'))
const glow = ref('')
let token = 0
let alive = true
let timer = 0

watch(() => props.theme, async theme => {
  const t = ++token
  const normalized = theme ? normalizeTheme(theme) : null
  if (!normalized) { src.value = robotArtUrl('base.png'); glow.value = ''; return }
  try {
    const art = await tintedRobotArt(normalized)
    if (alive && t === token) { src.value = art.base; glow.value = art.glow || '' }
  } catch {
    if (alive && t === token) { src.value = robotArtUrl('base.png'); glow.value = '' }
  }
}, { deep: true, immediate: true })

// ---- Pixel face. Low-res units: the 96x43 canvas maps onto the 191x84
// face rect, so 1 unit = ~2 art pixels. Geometry from the generator print. ----
const EYE = '#FBFAF8'
const CHEEK = '#FAA9B3'
const EYE_L = { x: 18.2, y: 14.8, rx: 6.5, ry: 12.8 }
const EYE_R = { x: 72.8, y: 14.8, rx: 6.5, ry: 12.8 }
const CHEEK_L = { x: 8.2, y: 28.4, rx: 5.8, ry: 4.0 }
const CHEEK_R = { x: 87.4, y: 27.1, rx: 5.8, ry: 4.0 }
const MOUTH = { x: 45.5, y: 37.8 }

function ellipse(ctx, x, y, rx, ry, color) {
  ctx.fillStyle = color
  ctx.beginPath()
  ctx.ellipse(x, y, Math.max(rx, 0.4), Math.max(ry, 0.4), 0, 0, Math.PI * 2)
  ctx.fill()
}

function line(ctx, x1, y1, x2, y2, w) {
  ctx.strokeStyle = EYE
  ctx.lineWidth = w
  ctx.lineCap = 'round'
  ctx.beginPath()
  ctx.moveTo(x1, y1)
  ctx.lineTo(x2, y2)
  ctx.stroke()
}

function drawEye(ctx, eye, mode) {
  // mode: 1 open, 0 closed, 0..1 squash factor, or the 'arc'/'x' shapes.
  if (mode <= 0.02) {
    ellipse(ctx, eye.x, eye.y + eye.ry * 0.75, eye.rx, 1.5, EYE)
  } else if (mode === 'arc') {
    ctx.strokeStyle = EYE
    ctx.lineWidth = 3.2
    ctx.lineCap = 'round'
    ctx.beginPath()
    ctx.arc(eye.x, eye.y + 3.5, eye.rx, Math.PI, Math.PI * 2)
    ctx.stroke()
  } else if (mode === 'x') {
    line(ctx, eye.x - 4.5, eye.y - 7, eye.x + 4.5, eye.y + 7, 3.2)
    line(ctx, eye.x + 4.5, eye.y - 7, eye.x - 4.5, eye.y + 7, 3.2)
  } else {
    ellipse(ctx, eye.x, eye.y + eye.ry * (1 - mode), eye.rx, eye.ry * mode, EYE)
  }
}

function cheeks(ctx, grow = 0) {
  ellipse(ctx, CHEEK_L.x, CHEEK_L.y, CHEEK_L.rx + grow, CHEEK_L.ry + grow * 0.5, CHEEK)
  ellipse(ctx, CHEEK_R.x, CHEEK_R.y, CHEEK_R.rx + grow, CHEEK_R.ry + grow * 0.5, CHEEK)
}

function zGlyph(ctx, x, y, s, alpha) {
  if (alpha <= 0) return
  ctx.globalAlpha = Math.min(1, alpha)
  ctx.fillStyle = EYE
  ctx.fillRect(x, y, 4.6 * s, 1.7 * s)
  ctx.fillRect(x + 2.9 * s, y + 1.7 * s, 1.7 * s, 1.7 * s)
  ctx.fillRect(x, y + 3.4 * s, 4.6 * s, 1.7 * s)
  ctx.globalAlpha = 1
}

// Each state: (ctx, t) with t in ms. Blink/phase cycles keep the mascot alive.
const DRAW = {
  idle(ctx, t) {
    const closed = t % 4200 < 170
    drawEye(ctx, EYE_L, closed ? 0 : 1)
    drawEye(ctx, EYE_R, closed ? 0 : 1)
    cheeks(ctx)
  },
  thinking(ctx, t) {
    const up = { ...EYE_L, y: EYE_L.y - 2.5, rx: EYE_L.rx * 0.9 }
    const upR = { ...EYE_R, y: EYE_R.y - 2.5, rx: EYE_R.rx * 0.9 }
    drawEye(ctx, up, 1)
    drawEye(ctx, upR, 1)
    cheeks(ctx)
    ellipse(ctx, MOUTH.x, MOUTH.y - 1, 2.0, 2.4, EYE)
    const phase = Math.floor(t / 420) % 4
    for (let i = 0; i < phase; i++) ellipse(ctx, 39 + i * 5.5, 6.5, 1.6, 1.6, EYE)
  },
  working(ctx, t) {
    const gaze = Math.floor(t / 650) % 2 ? 1.6 : -1.6
    drawEye(ctx, { ...EYE_L, x: EYE_L.x + gaze }, 0.55)
    drawEye(ctx, { ...EYE_R, x: EYE_R.x + gaze }, 0.55)
    cheeks(ctx)
    ctx.fillStyle = EYE
    ctx.fillRect(MOUTH.x - 5, MOUTH.y - 1.3, 10, 2.6)
  },
  success(ctx, t) {
    const pump = Math.floor(t / 360) % 2
    drawEye(ctx, EYE_L, 'arc')
    drawEye(ctx, EYE_R, 'arc')
    cheeks(ctx, 1)
    ellipse(ctx, MOUTH.x, MOUTH.y - 1, 5.5, pump ? 3.6 : 2.6, EYE)
  },
  notification(ctx, t) {
    const wink = t % 1800 > 1100
    drawEye(ctx, EYE_L, 1)
    drawEye(ctx, EYE_R, wink ? 0 : 1)
    cheeks(ctx)
    ellipse(ctx, MOUTH.x, MOUTH.y - 1, 2.2, 2.6, EYE)
  },
  waiting(ctx, t) {
    drawEye(ctx, EYE_L, 0.55)
    drawEye(ctx, EYE_R, 0.55)
    cheeks(ctx)
    ctx.fillStyle = EYE
    ctx.fillRect(MOUTH.x - 3.5, MOUTH.y - 1.2, 7, 2.4)
  },
  error(ctx, t) {
    const shake = Math.floor(t / 180) % 2 ? 0.6 : -0.6
    ctx.save()
    ctx.translate(shake, 0)
    drawEye(ctx, EYE_L, 'x')
    drawEye(ctx, EYE_R, 'x')
    cheeks(ctx)
    ctx.strokeStyle = EYE
    ctx.lineWidth = 2.8
    ctx.lineCap = 'round'
    ctx.beginPath()
    ctx.arc(MOUTH.x, MOUTH.y + 3.5, 4.5, Math.PI * 1.1, Math.PI * 1.9)
    ctx.stroke()
    ctx.restore()
  },
  sleeping(ctx, t) {
    drawEye(ctx, EYE_L, 0)
    drawEye(ctx, EYE_R, 0)
    cheeks(ctx)
    ellipse(ctx, MOUTH.x, MOUTH.y, 1.6, 1.8, EYE)
    const drift = (t % 2600) / 2600
    zGlyph(ctx, 76, 19 - drift * 14, 1.2, 1 - drift)
    zGlyph(ctx, 85, 11 - drift * 10, 0.9, 0.7 - drift * 0.7)
  },
}

function render(t) {
  const canvas = face.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ;(DRAW[props.state] || DRAW.idle)(ctx, t)
}

watch(() => [props.state, props.animations], () => {
  clearInterval(timer)
  if (props.animations && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    timer = setInterval(() => render(Date.now()), 110)
  }
  render(Date.now())
}, { immediate: true })

onBeforeUnmount(() => {
  alive = false
  clearInterval(timer)
})
</script>

<style scoped>
/* Art box keeps the body-frame aspect (540x477) printed by the generator. */
.robot-art { position: relative; width: 100%; aspect-ratio: 540 / 477;
  animation: robot-float 3.6s ease-in-out infinite; }
.robot-art.still { animation: none; }
.robot-img { position: absolute; inset: 0; width: 100%; height: 100%;
  filter: drop-shadow(0 5px 12px rgba(15, 23, 42, .2)); }
/* Face rect + tilt printed by make_assistant_layers.py (visor-local frame). */
.robot-face { position: absolute; left: 21.9%; top: 48.79%; width: 35.42%; height: 17.51%;
  transform: rotate(8.17deg); image-rendering: pixelated; }

@media (prefers-reduced-motion: reduce) {
  .robot-art { animation: none !important; }
}

@keyframes robot-float {
  0%, 100% { transform: translateY(0) rotate(0deg); }
  50% { transform: translateY(-5px) rotate(-2deg); }
}
</style>
