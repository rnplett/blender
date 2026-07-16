"""
Guest Parking Sign — offset (contour) toolpath G-code generator
Produces guest-parking-offset.nc by following letter outlines inward at
successive STEPOVER intervals using a miter polygon offset algorithm.

Run from Blender's Script Editor (Alt-P).
"""
import bpy, bmesh, os, math

OUTPUT_DIR  = r"C:\Users\rolan\projects\blender"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "gcode", "guest-parking-offset.nc")

# ── sign + carve parameters ────────────────────────────────────────────────────
SIGN_W, SIGN_H = 10.0, 12.0
CARVE_D    = 0.25
MARGIN     = 0.75
GAP_FACTOR = 0.35

# ── tool parameters ────────────────────────────────────────────────────────────
TOOL_DIA       = 0.125
TOOL_RAD       = TOOL_DIA / 2
STEPOVER       = TOOL_RAD       # 50 % — 0.0625" between contour passes
PASS_DEPTH     = 0.20
FEED_RATE      = 10.0
PLUNGE_RATE    = 5.0
SAFE_Z         = 0.25
MAX_MITER_MULT = 3.0   # max miter as multiple of STEPOVER (prevents sharp-corner spikes)
MIN_AREA_RATIO = 0.01  # stop offsetting when loop shrinks to < 1 % of original area

# ── font ────────────────────────────────────────────────────────────────────────
_font = None
for _fp in [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]:
    if os.path.exists(_fp):
        _font = bpy.data.fonts.load(_fp)
        print(f"Font: {_fp}")
        break

# ── 2-D geometry helpers ────────────────────────────────────────────────────────

def signed_area(pts):
    """Shoelace formula. Positive = CCW."""
    n = len(pts)
    return sum(pts[i][0] * pts[(i+1)%n][1] - pts[(i+1)%n][0] * pts[i][1]
               for i in range(n)) / 2.0


def point_in_polygon(px, py, polygon):
    """Ray-casting point-in-polygon test (winding-order independent)."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def offset_loop(pts, dist, miter_mult=None):
    """
    Miter-offset a 2-D polygon by *dist*.
    Positive dist moves in the left-normal direction — inward for CCW loops
    (outer letter boundary) and outward from the counter for CW loops (holes),
    which in both cases advances toward the centre of the carved region.

    miter_mult overrides MAX_MITER_MULT for this call (use 1.0 for a clean
    uniform offset with no spike amplification).

    Returns offset point list, or None when the loop has collapsed.
    """
    n = len(pts)
    if n < 3:
        return None

    orig_area = signed_area(pts)
    if abs(orig_area) < 1e-12:
        return None
    orig_sign = math.copysign(1.0, orig_area)

    max_miter = (miter_mult if miter_mult is not None else MAX_MITER_MULT) * dist
    out = []

    for i in range(n):
        p0 = pts[(i - 1) % n]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]

        e1x, e1y = p1[0] - p0[0], p1[1] - p0[1]   # incoming edge
        e2x, e2y = p2[0] - p1[0], p2[1] - p1[1]   # outgoing edge
        l1 = math.hypot(e1x, e1y)
        l2 = math.hypot(e2x, e2y)

        if l1 < 1e-10 or l2 < 1e-10:
            out.append(p1)
            continue

        # Left-hand unit normals for each edge
        n1x, n1y = -e1y / l1,  e1x / l1
        n2x, n2y = -e2y / l2,  e2x / l2

        # Bisector of the two normals
        bx, by   = n1x + n2x, n1y + n2y
        bl       = math.hypot(bx, by)

        if bl < 1e-9:
            # Anti-parallel edges (180° U-turn) — offset straight along either normal
            out.append((p1[0] + n1x * dist, p1[1] + n1y * dist))
            continue

        bux, buy = bx / bl, by / bl
        cos_half = n1x * bux + n1y * buy   # cos of angle between bisector and either normal

        if cos_half < 1e-3:
            miter = max_miter
        else:
            miter = min(dist / cos_half, max_miter)

        out.append((p1[0] + bux * miter, p1[1] + buy * miter))

    # Reject loops that have inverted (collapsed) or nearly vanished
    new_area = signed_area(out)
    if math.copysign(1.0, new_area) != orig_sign:
        return None
    if abs(new_area) < MIN_AREA_RATIO * abs(orig_area):
        return None

    return out


def chain_loops(bm):
    """
    Collect boundary edges into closed (x, y) point loops.
    Works for outer letter outlines and inner counter outlines (holes).
    """
    boundary  = [e for e in bm.edges if len(e.link_faces) == 1]
    if not boundary:
        return []

    edge_map  = {e.index: e for e in boundary}

    # vertex → list of boundary edge indices
    adj = {}
    for e in boundary:
        for v in e.verts:
            adj.setdefault(v.index, []).append(e.index)

    visited = set()
    loops   = []

    for start in boundary:
        if start.index in visited:
            continue

        # Orient starting vertex so the adjacent mesh face is on our left.
        # This gives CCW winding for outer letter boundaries and CW for counter holes,
        # which matches what offset_loop expects: CCW shrinks inward, CW expands outward.
        vert = start.verts[0]  # fallback
        face = start.link_faces[0]
        for fl in face.loops:
            if fl.edge.index == start.index:
                vert = fl.vert
                break

        loop   = []
        eidx   = start.index

        while eidx not in visited:
            visited.add(eidx)
            e = edge_map[eidx]
            loop.append((vert.co.x, vert.co.y))
            nv   = e.other_vert(vert)
            nxt  = [idx for idx in adj.get(nv.index, []) if idx not in visited]
            if not nxt:
                break
            vert = nv
            eidx = nxt[0]

        if len(loop) >= 3:
            loops.append(loop)

    return loops


# ── text measurement (same as other scripts) ────────────────────────────────────

def _word_bounds(word):
    bpy.ops.object.text_add(location=(0, 0, 0))
    obj = bpy.context.active_object
    obj.data.body    = word
    obj.data.align_x = 'CENTER'
    obj.data.align_y = 'CENTER'
    obj.data.size    = 1.0
    if _font:
        obj.data.font = _font
    obj.data.extrude = 0.001
    bpy.ops.object.convert(target='MESH')
    xs = [v.co.x for v in obj.data.vertices]
    ys = [v.co.y for v in obj.data.vertices]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.ops.object.delete()
    return w, h


def extract_offset_contours(word, sf, offset_x, offset_y):
    """
    Build a flat text mesh, extract all boundary loops, then generate
    successive inward offset contours for each outer (CCW) loop.

    Counter (CW) loops are used only to define a forbidden zone: each counter
    is expanded outward by TOOL_RAD so that outer passes stop before the tool
    edge would cut into the counter.

    Returns list of (y_centre, [(x,y), ...]) in G-code coordinates.
    """
    bpy.ops.object.text_add(location=(0, 0, 0))
    obj = bpy.context.active_object
    obj.name         = f"_off_{word}"
    obj.data.body    = word
    obj.data.align_x = 'CENTER'
    obj.data.align_y = 'CENTER'
    obj.data.size    = sf
    if _font:
        obj.data.font = _font
    obj.data.extrude   = 0.0
    obj.data.fill_mode = 'BOTH'
    bpy.ops.object.convert(target='MESH')

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    raw_loops = chain_loops(bm)
    bm.free()
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.ops.object.delete()

    # Separate outer (CCW) and counter (CW) loops in G-code coordinates
    outer_loops   = []
    counter_loops = []
    for raw in raw_loops:
        gloop = [(x + offset_x, y + offset_y) for x, y in raw]
        area  = signed_area(gloop)
        if abs(area) < 1e-6:
            continue
        (outer_loops if area > 0 else counter_loops).append(gloop)

    # Use the raw counter polygons as forbidden zones (no expansion).
    # Points register as "inside" only when they literally cross into the counter
    # hole — not merely when they are within TOOL_RAD of its boundary.  This lets
    # outer passes advance right up to the counter edge on thin-stroked letters
    # (a, g) while still stopping before genuinely entering the hole.
    forbidden = counter_loops

    contours = []

    for gloop in outer_loops:
        loop_area = signed_area(gloop)
        orig_area = abs(loop_area)

        for pass_num in range(30):
            dist = TOOL_RAD + pass_num * STEPOVER
            off  = offset_loop(gloop, dist)
            if off is None:
                break

            new_area = signed_area(off)
            if math.copysign(1.0, new_area) != math.copysign(1.0, loop_area):
                break
            if abs(new_area) < MIN_AREA_RATIO * orig_area:
                break
            if new_area > orig_area * 1.05:
                break

            xs = [p[0] for p in off]
            ys = [p[1] for p in off]
            if min(xs) < -0.5 or max(xs) > SIGN_W + 0.5:
                break
            if min(ys) < -0.5 or max(ys) > SIGN_H + 0.5:
                break

            # Stop if 3+ outer offset points have crossed into a counter hole.
            # Threshold of 2 absorbs isolated miter spike points that stray
            # just inside the boundary without genuine counter penetration.
            if any(
                sum(1 for px, py in off if point_in_polygon(px, py, zone)) > 2
                for zone in forbidden
            ):
                break

            y_ctr = (min(ys) + max(ys)) / 2.0
            contours.append((y_ctr, off))

    return contours


# ── scale + layout (matches the sign creation and raster scripts) ───────────────

w1, h1 = _word_bounds("Guest")
w2, h2 = _word_bounds("Parking")

avail_w = SIGN_W - 2 * MARGIN
avail_h = SIGN_H - 2 * MARGIN
sf      = min(avail_w / max(w1, w2),
              avail_h / (h1 + h2 + GAP_FACTOR * h1))

print(f"Scale: {sf:.4f}  Guest {w1*sf:.3f}\" x {h1*sf:.3f}\"  "
      f"Parking {w2*sf:.3f}\" x {h2*sf:.3f}\"")

gap      = GAP_FACTOR * h1 * sf
total_h  = h1 * sf + gap + h2 * sf
guest_cy =  total_h / 2 - (h1 * sf) / 2
park_cy  = -(total_h / 2 - (h2 * sf) / 2)

off_x = SIGN_W / 2
off_y = SIGN_H / 2

guest_contours   = extract_offset_contours("Guest",   sf, off_x, off_y + guest_cy)
parking_contours = extract_offset_contours("Parking", sf, off_x, off_y + park_cy)

all_contours = guest_contours + parking_contours

# Sort by Y centre so the tool works from bottom to top
all_contours.sort(key=lambda c: c[0])

print(f"Total contour loops: {len(all_contours)}")

# ── depth passes ────────────────────────────────────────────────────────────────
passes = []
depth  = 0.0
while depth < CARVE_D - 1e-9:
    depth = min(round(depth + PASS_DEPTH, 6), CARVE_D)
    passes.append(-depth)

print(f"Depth passes: {[abs(z) for z in passes]}\"")

# ── G-code ──────────────────────────────────────────────────────────────────────
lines = []
emit  = lines.append

emit("(Guest Parking Sign — offset contour toolpaths)")
emit(f"(Sign:  {SIGN_W}\" W x {SIGN_H}\" H x {CARVE_D}\" carve depth)")
emit(f"(Tool:  {TOOL_DIA}\" flat end mill)")
emit(f"(Feed:  {FEED_RATE} in/min cutting, {PLUNGE_RATE} in/min plunge)")
emit(f"(Zero:  top surface at bottom-left corner of sign)")
emit(f"(Passes: {[abs(z) for z in passes]}\"  Contours: {len(all_contours)})")
emit("")
emit("G90")       # absolute
emit("G20")       # inch
emit("G94")       # feed per minute
emit(f"G0 Z{SAFE_Z:.4f}")
emit("G0 X0.0000 Y0.0000")

for pass_idx, z_cut in enumerate(passes):
    emit("")
    emit(f"(===== Pass {pass_idx + 1}: Z = {z_cut:.4f}\" =====)")

    for _yctr, loop in all_contours:
        x0, y0 = loop[0]

        emit(f"G0 Z{SAFE_Z:.4f}")
        emit(f"G0 X{x0:.4f} Y{y0:.4f}")
        emit(f"G1 Z{z_cut:.4f} F{PLUNGE_RATE:.1f}")

        for x, y in loop[1:]:
            emit(f"G1 X{x:.4f} Y{y:.4f} F{FEED_RATE:.1f}")

        # Close the loop
        emit(f"G1 X{x0:.4f} Y{y0:.4f} F{FEED_RATE:.1f}")
        emit(f"G0 Z{SAFE_Z:.4f}")

    emit(f"G0 Z{SAFE_Z:.4f}")

emit("")
emit(f"G0 Z{SAFE_Z:.4f}")
emit("G0 X0.0000 Y0.0000")
emit("M30")

# ── write file ────────────────────────────────────────────────────────────────
os.makedirs(OUTPUT_DIR, exist_ok=True)
with open(OUTPUT_FILE, 'w', newline='\n') as fh:
    fh.write('\n'.join(lines) + '\n')

print(f"Written: {OUTPUT_FILE}  ({len(lines)} lines)")
