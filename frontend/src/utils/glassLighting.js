// Project onto the nearest edge, including when the pointer is inside a surface.
export function glassLightPosition(rect, pointer) {
  let x = Math.max(0, Math.min(rect.width, pointer.x - rect.left))
  let y = Math.max(0, Math.min(rect.height, pointer.y - rect.top))
  const distance = Math.hypot(pointer.x - rect.left - x, pointer.y - rect.top - y)
  if (x > 0 && x < rect.width && y > 0 && y < rect.height) {
    const nearest = Math.min(y, rect.width - x, rect.height - y, x)
    // Fixed tie order avoids an ambiguous source at the centre/diagonals.
    if (nearest === y) y = 0
    else if (nearest === rect.width - x) x = rect.width
    else if (nearest === rect.height - y) y = rect.height
    else x = 0
  }
  return { x, y, distance }
}

function perimeterPosition(rect, { x, y }) {
  if (y === 0) return x
  if (x === rect.width) return rect.width + y
  if (y === rect.height) return 2 * rect.width + rect.height - x
  return 2 * (rect.width + rect.height) - y
}

// Follow the perimeter rather than interpolating through the surface on edge changes.
export function advanceGlassLight(rect, current, target, progress, setback) {
  const { width: w, height: h } = rect
  const perimeter = 2 * (w + h)
  const destination = perimeterPosition(rect, target)
  const start = current ?? destination
  const delta = ((destination - start + perimeter * 1.5) % perimeter) - perimeter / 2
  const moving = Math.abs(delta) > .3 && progress < 1
  const position = ((moving ? start + delta * progress : destination) + perimeter) % perimeter
  let x, y
  if (position < w) { x = position; y = 0 }
  else if (position < w + h) { x = w; y = position - w }
  else if (position < 2 * w + h) { x = 2 * w + h - position; y = h }
  else { x = 0; y = perimeter - position }
  // A rounded outer path keeps the source continuous as it flows around corners.
  const radius = Math.min(setback, w / 2, h / 2)
  const cx = Math.max(radius, Math.min(w - radius, x))
  const cy = Math.max(radius, Math.min(h - radius, y))
  const length = Math.hypot(x - cx, y - cy)
  const nx = (x - cx) / length
  const ny = (y - cy) / length
  return { position, moving, x: x + nx * setback, y: y + ny * setback, nx, ny }
}

// Each surface receives its own edge light and exterior distance falloff.
export function installGlassLighting() {
  const selector = ':is(.btn-primary, button.primary, .login-submit, .chat-send, .btn-create, .agent-btn-chat, .mem-edit-save, .validity-dialog .save, .upload-box .choose, .search-select-trigger, .legacy-search-select-trigger):not(:disabled), .nav-item.router-link-active, .page-tab.active, .theme-demo-button, .theme-color-item .color-preview:not(.custom-preview), .search-select-menu, .legacy-search-select-menu, .panel, .capability-panel, .debug-panel, .agent-status-panel, .chat-input-wrap, .modal, .dialog, .user-dropdown, .agent-dropdown, .mention-popover, .create-dialog, .push-dialog, .validity-dialog, .work-editor, .confirm-dialog, .summary-dialog, .textdoc-dialog, .document-preview, .modal-box, .preview-modal, .resource-editor'
  const lit = new Map()
  const tracks = new Map()
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
  let frame = 0
  let pointer = null
  let lastTime = 0
  const restore = () => {
    for (const [element, original] of lit) {
      if (original.value) element.style.setProperty('background-image', original.value, original.priority)
      else element.style.removeProperty('background-image')
    }
    lit.clear()
  }
  const render = time => {
    frame = 0
    restore()
    if (!pointer || document.documentElement.dataset.colorTheme !== 'glass') return
    const frosted = document.documentElement.dataset.glassFinish === 'frosted'
    const maxDistance = frosted ? 95 : 130
    const colorStrength = frosted ? .10 : .22
    const whiteStrength = frosted ? .12 : .20
    const setback = frosted ? 36 : 28
    const progress = reducedMotion.matches ? 1 : 1 - Math.exp(-Math.min(lastTime ? time - lastTime : 16, 50) / 150)
    lastTime = time
    let moving = false
    for (const element of document.querySelectorAll(selector)) {
      const rect = element.getBoundingClientRect()
      if (!rect.width || !rect.height || rect.bottom < 0 || rect.top > innerHeight) continue
      const target = glassLightPosition(rect, pointer)
      const { distance } = target
      if (distance >= maxDistance) continue
      const previous = tracks.get(element)
      const current = previous?.width === rect.width && previous?.height === rect.height ? previous.position : null
      const light = advanceGlassLight(rect, current, target, progress, setback)
      tracks.set(element, { position: light.position, width: rect.width, height: rect.height })
      moving ||= light.moving
      const x = light.x.toFixed(2)
      const y = light.y.toFixed(2)
      // Spread along the edge, with a shallower wash into the surface.
      const rx = (92 + 84 * Math.abs(light.ny)).toFixed(2)
      const ry = (92 + 84 * Math.abs(light.nx)).toFixed(2)
      const whiteRx = (52 + 38 * Math.abs(light.ny)).toFixed(2)
      const whiteRy = (52 + 38 * Math.abs(light.nx)).toFixed(2)
      const strength = (1 - distance / maxDistance) ** (frosted ? 2.4 : 1.7)
      const style = getComputedStyle(element)
      // Swatches define their own reflection color; other surfaces inherit the theme.
      const color = style.getPropertyValue('--glass-light-color').trim()
      if (!color) continue
      const base = style.backgroundImage
      lit.set(element, {
        value: element.style.backgroundImage,
        priority: element.style.getPropertyPriority('background-image'),
      })
      // Keep refraction local to the edge; an unbounded conic layer lights the whole card.
      const lens = frosted ? '' : ', radial-gradient(' + rx + 'px ' + ry + 'px at ' + x + 'px ' + y + 'px, rgba(255,255,255,' + (strength * .07) + '), transparent 82%)'
      // Dark panel adapters use !important; the temporary light must layer above them too.
      element.style.setProperty('background-image', 'radial-gradient(' + rx + 'px ' + ry + 'px at ' + x + 'px ' + y + 'px, rgba(' + color + ',' + (strength * colorStrength) + '), transparent 100%), radial-gradient(' + whiteRx + 'px ' + whiteRy + 'px at ' + x + 'px ' + y + 'px, rgba(255,255,255,' + (strength * whiteStrength) + '), transparent 100%)' + lens + (base === 'none' ? '' : ', ' + base), 'important')
    }
    for (const element of tracks.keys()) if (!lit.has(element)) tracks.delete(element)
    if (moving) schedule()
    else lastTime = 0
  }
  const schedule = () => { if (!frame) frame = requestAnimationFrame(render) }
  const move = event => {
    if (event.pointerType === 'touch') return
    pointer = { x: event.clientX, y: event.clientY }
    schedule()
  }
  const leave = () => {
    pointer = null
    cancelAnimationFrame(frame)
    frame = 0
    lastTime = 0
    restore()
    tracks.clear()
  }
  const out = event => { if (!event.relatedTarget) leave() }
  document.addEventListener('pointermove', move, { passive: true })
  document.addEventListener('pointerout', out)
  document.addEventListener('scroll', schedule, true)
  window.addEventListener('resize', schedule)
  window.addEventListener('blur', leave)
  window.addEventListener('theme-change', leave)
  window.addEventListener('appearance-change', leave)
  reducedMotion.addEventListener('change', schedule)
  return () => {
    leave()
    document.removeEventListener('pointermove', move)
    document.removeEventListener('pointerout', out)
    document.removeEventListener('scroll', schedule, true)
    window.removeEventListener('resize', schedule)
    window.removeEventListener('blur', leave)
    window.removeEventListener('theme-change', leave)
    window.removeEventListener('appearance-change', leave)
    reducedMotion.removeEventListener('change', schedule)
  }
}
