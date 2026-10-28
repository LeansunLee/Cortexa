# Robot assistant art generator v2 — armless single-layer edition.
#
# Input:  frontend/public/themes/robot/base.png (the approved armless body,
#         720x560, produced by the v1 arm split — git history keeps that script).
# Output: the same file, re-cropped tight to the body (the v1 frame reserved
#         side room for the now-removed arms) with the baked face ERASED from
#         the visor — the frontend draws expressions dynamically on a canvas.
# Prints: frame geometry + the face-canvas rect (as % of frame) + palette hex
#         values for RobotArt.vue's CSS.
import math
from collections import Counter, deque

from PIL import Image

BASE = r"D:\MyPro\Cortexa\frontend\public\themes\robot\base.png"
MARGIN = 70
FEATHER = 28
ERASE_RING = 4

img = Image.open(BASE).convert("RGBA")
W, H = img.size
px = img.load()


def lum(r, g, b):
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# ---- 1. Tight re-crop: body bbox + margin, cosine feather on the new edges. ----
# bbox over SOLID pixels only — stray faint debris dots (alpha ~1) must not
# stretch the frame; the margin + feather band covers their soft remnants.
xs0, ys0, xs1, ys1 = W, H, -1, -1
for y in range(H):
    for x in range(W):
        if px[x, y][3] > 110:
            if x < xs0: xs0 = x
            if x > xs1: xs1 = x
            if y < ys0: ys0 = y
            if y > ys1: ys1 = y
cx0, cy0 = max(0, xs0 - MARGIN), max(0, ys0 - MARGIN)
cx1, cy1 = min(W - 1, xs1 + MARGIN), min(H - 1, ys1 + MARGIN)
frame = img.crop((cx0, cy0, cx1 + 1, cy1 + 1))
FW, FH = frame.size
fpx = frame.load()
# Feather only edges that came from the margin (never an old-image edge).
for yy in range(FH):
    for xx in range(FW):
        r, g, b, a = fpx[xx, yy]
        if not a: continue
        d = min(xx if cx0 > 0 else 1 << 30, FW - 1 - xx if cx1 < W - 1 else 1 << 30,
                yy if cy0 > 0 else 1 << 30, FH - 1 - yy if cy1 < H - 1 else 1 << 30)
        if d < FEATHER:
            f = (math.cos((d + 0.5) / FEATHER * math.pi) + 1) / 2
            fpx[xx, yy] = (r, g, b, int(a * f))
print(f"frame: {FW}x{FH} aspect {FW / FH:.4f} (was {W}/{H} = {W / H:.4f})")

# ---- 2. Find the visor (largest dark component) inside the new frame. ----
dark = {}
for y in range(FH):
    for x in range(FW):
        pr, pg, pb, pa = fpx[x, y]
        if pa > 200 and lum(pr, pg, pb) < 90:
            dark[(x, y)] = (pr, pg, pb)
seen, comps = set(), []
for p in dark:
    if p in seen: continue
    comp = set(); q = deque([p]); seen.add(p)
    while q:
        c = q.popleft(); comp.add(c)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (c[0] + dx, c[1] + dy)
                if n in dark and n not in seen:
                    seen.add(n); q.append(n)
    comps.append(comp)
comps.sort(key=len, reverse=True)
visor = comps[0]
vx0 = min(x for x, _ in visor); vy0 = min(y for _, y in visor)
vx1 = max(x for x, _ in visor); vy1 = max(y for _, y in visor)
visor_color = Counter(dark[p] for p in visor).most_common(1)[0][0]
print(f"visor: bbox=({vx0},{vy0})-({vx1},{vy1}) {vx1 - vx0 + 1}x{vy1 - vy0 + 1} color=#{visor_color[0]:02X}{visor_color[1]:02X}{visor_color[2]:02X}")

# ---- 3. Face features = non-visor holes inside the visor row spans. ----
light, pink = [], []
for y in range(vy0, vy1 + 1):
    row = [x for x, yy in visor if yy == y]
    if not row: continue
    lo, hi = min(row), max(row)
    for x in range(lo, hi + 1):
        if (x, y) in visor: continue
        pr, pg, pb, pa = fpx[x, y]
        if pa < 100: continue
        if pr > pb + 14 and pr > 150: pink.append((x, y))
        elif lum(pr, pg, pb) > 140: light.append((x, y))


def clusters(pts, gap=2):
    pts = set(pts); out = []
    while pts:
        p = pts.pop(); comp = [p]; q = deque([p])
        while q:
            c = q.popleft()
            for dx in range(-gap, gap + 1):
                for dy in range(-gap, gap + 1):
                    n = (c[0] + dx, c[1] + dy)
                    if n in pts:
                        pts.discard(n); q.append(n); comp.append(n)
        out.append(comp)
    return sorted(out, key=len, reverse=True)


eyes = [c for c in clusters(light) if len(c) > 100]
cheeks = [c for c in clusters(pink) if len(c) > 100]
assert len(eyes) == 2, f"expected 2 eyes, got {len(eyes)}"
assert len(cheeks) == 2, f"expected 2 cheeks, got {len(cheeks)}"
eyes.sort(key=lambda c: min(x for x, _ in c))
cheeks.sort(key=lambda c: min(x for x, _ in c))

eye_color = Counter(fpx[x, y] for c in eyes for x, y in c).most_common(1)[0][0][:3]
cheek_color = Counter(fpx[x, y] for c in cheeks for x, y in c).most_common(1)[0][0][:3]
print(f"eye color #{eye_color[0]:02X}{eye_color[1]:02X}{eye_color[2]:02X}  cheek color #{cheek_color[0]:02X}{cheek_color[1]:02X}{cheek_color[2]:02X}")

# ---- 4. Face frame math: untilt by the eye-line angle. ----
def center(c):
    return (sum(x for x, _ in c) / len(c), sum(y for _, y in c) / len(c))

el, er = center(eyes[0]), center(eyes[1])
tilt = math.atan2(er[1] - el[1], er[0] - el[0])
cth, sth = math.cos(tilt), math.sin(tilt)
ex, ey = (el[0] + er[0]) / 2, (el[1] + er[1]) / 2
eye_rx = max((max(x for x, _ in c) - min(x for x, _ in c)) / 2 for c in eyes)
eye_ry = max((max(y for _, y in c) - min(y for _, y in c)) / 2 for c in eyes)
cl, cr = center(cheeks[0]), center(cheeks[1])
cl_u = ((cl[0] - ex) * cth + (cl[1] - ey) * sth, -(cl[0] - ex) * sth + (cl[1] - ey) * cth)
cr_u = ((cr[0] - ex) * cth + (cr[1] - ey) * sth, -(cr[0] - ex) * sth + (cr[1] - ey) * cth)
cheek_rx = max((max(x for x, _ in c) - min(x for x, _ in c)) / 2 for c in cheeks)
cheek_ry = max((max(y for _, y in c) - min(y for _, y in c)) / 2 for c in cheeks)

# Untilted content extents: eyes + cheeks + mouth zone (the canvas draws the
# mouth ~46px below the eye line, ~8px tall).
MOUTH_DY = 46
top = -eye_ry - 4
bottom = MOUTH_DY + 8
left = min(cl_u[0], cr_u[0]) - cheek_rx - 5
right = max(cl_u[0], cr_u[0]) + cheek_rx + 5
fw_, fh_ = right - left, bottom - top
fcx_u, fcy_u = (left + right) / 2, (top + bottom) / 2
# Back to absolute coords (rotate the local center by tilt, about the eyes).
fcx = ex + fcx_u * cth - fcy_u * sth
fcy = ey + fcx_u * sth + fcy_u * cth
rect_x0, rect_y0 = fcx - fw_ / 2, fcy - fh_ / 2
print(f"tilt: {math.degrees(tilt):.2f} deg  eye gap {(er[0] - el[0]) * 1.0:.1f}px  eye {eye_rx * 2:.1f}x{eye_ry * 2:.1f}")
print("FACE_CANVAS (percent of frame):")
print(f"  left {(rect_x0 / FW) * 100:.2f}  top {(rect_y0 / FH) * 100:.2f}  width {(fw_ / FW) * 100:.2f}  height {(fh_ / FH) * 100:.2f}  rotate {math.degrees(tilt):.2f}")
# Features in the UNTILTED canvas frame (the CSS box is rotated by `tilt`,
# so the canvas draws upright coordinates).
el_u = ((el[0] - ex) * cth + (el[1] - ey) * sth, -(el[0] - ex) * sth + (el[1] - ey) * cth)
er_u = ((er[0] - ex) * cth + (er[1] - ey) * sth, -(er[0] - ex) * sth + (er[1] - ey) * cth)
ox, oy = left, top
print(f"FACE_LOCAL (px in a {fw_:.0f}x{fh_:.0f} canvas, untilted, origin at rect top-left):")
print(f"  eyeL ({el_u[0] - ox:.1f}, {el_u[1] - oy:.1f})  eyeR ({er_u[0] - ox:.1f}, {er_u[1] - oy:.1f})  r ({eye_rx:.1f}, {eye_ry:.1f})")
print(f"  cheekL ({cl_u[0] - ox:.1f}, {cl_u[1] - oy:.1f})  cheekR ({cr_u[0] - ox:.1f}, {cr_u[1] - oy:.1f})  r ({cheek_rx:.1f}, {cheek_ry:.1f})")

# ---- 5. Erase the baked features (+ring) with the visor color. ----
erase = set()
for c in eyes + cheeks:
    erase.update(c)
ring = set()
for (x, y) in erase:
    for dx in range(-ERASE_RING, ERASE_RING + 1):
        for dy in range(-ERASE_RING, ERASE_RING + 1):
            ring.add((x + dx, y + dy))
ring -= erase
for (x, y) in erase | ring:
    if 0 <= x < FW and 0 <= y < FH:
        pr, pg, pb, pa = fpx[x, y]
        if pa == 0: continue
        fpx[x, y] = (visor_color[0], visor_color[1], visor_color[2], pa)

# Sanity: no light/pink pixels may survive where the features were. Check only
# each feature's own bbox + ring slack — the shine specks near the visor's
# top-right are intentionally kept.
leftover = []
for c in eyes + cheeks:
    bx0 = min(x for x, _ in c) - ERASE_RING - 2
    by0 = min(y for _, y in c) - ERASE_RING - 2
    bx1 = max(x for x, _ in c) + ERASE_RING + 2
    by1 = max(y for _, y in c) + ERASE_RING + 2
    for y in range(max(0, by0), min(FH - 1, by1) + 1):
        for x in range(max(0, bx0), min(FW - 1, bx1) + 1):
            if (x, y) in visor: continue
            pr, pg, pb, pa = fpx[x, y]
            if pa < 100: continue
            if (pr > pb + 14 and pr > 150) or lum(pr, pg, pb) > 140:
                leftover.append((x, y))
assert not leftover, f"{len(leftover)} feature pixels survived the erase, e.g. {leftover[:8]}"
print(f"erase clean: {len(erase)} feature px + {len(ring)} ring px flattened to visor color")

frame.save(BASE)
print(f"saved {BASE}")
