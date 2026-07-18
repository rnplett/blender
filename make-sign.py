"""Create a carved text sign in Blender.

Run from Blender's Scripting workspace, or from a shell with:
    blender --background --python make-sign.py

Blender units are treated as inches.
"""

import os
import math

import bpy


# Text displayed on the sign. Use ``\n`` to create additional lines.
SIGN_TEXT = "Airbnb\nParking"

# Sign dimensions and layout (inches).
SIGN_WIDTH = 12.0
SIGN_HEIGHT = 10.0
SIGN_DEPTH = 0.5
CUT_DEPTH = 0.125
MARGIN = 1.5
LINE_GAP_FACTOR = 0.35
Z_OVERSHOOT = 0.02

# Border dimensions (inches), measured inward from the sign's outside edge.
BORDER_INSET = 0.5
BORDER_WIDTH = 0.14

# Mounting holes. MOUNTING_HOLE_EDGE_OFFSET locates each hole's center from
# the nearest top/bottom edge. The border centerline uses the same offset.
MOUNTING_HOLE_DIAMETER = 0.25
MOUNTING_HOLE_EDGE_OFFSET = 0.5
MOUNTING_HOLE_BORDER_CLEARANCE = 0.08
MOUNTING_HOLE_SEGMENTS = 48

# Prebuilt lower-right branding, designed for a 0.06-inch CNC bit.
BRAND_SVG_FILENAME = "aspenhollow-logo.svg"
BRAND_MAX_WIDTH = 3.8
BRAND_MAX_HEIGHT = 0.75
BRAND_BORDER_GAP = 0.12
BRAND_TOOL_DIAMETER = 0.0625
BRAND_TOOL_SAFETY_FACTOR = 1.05
# Measured from the baked SVG: narrowest wordmark stroke / total logo height.
BRAND_MIN_FEATURE_RATIO = 0.0512 / 0.58


def find_font():
    """Load the first available sans-serif font, or use Blender's default."""
    font_paths = (
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for path in font_paths:
        if os.path.exists(path):
            print(f"Font: {path}")
            return bpy.data.fonts.load(path)

    print("No sans-serif font found; using Blender's default.")
    return None


def add_text_object(text, size, font, extrude):
    """Create centered text and convert it to a mesh."""
    bpy.ops.object.text_add(location=(0, 0, 0))
    obj = bpy.context.active_object
    obj.data.body = text
    obj.data.align_x = "CENTER"
    obj.data.align_y = "CENTER"
    obj.data.size = size
    obj.data.extrude = extrude
    if font:
        obj.data.font = font
    bpy.ops.object.convert(target="MESH")
    return obj


def mesh_bounds(obj):
    """Return the width, height, vertical center, and top of a mesh."""
    xs = [vertex.co.x for vertex in obj.data.vertices]
    ys = [vertex.co.y for vertex in obj.data.vertices]
    zs = [vertex.co.z for vertex in obj.data.vertices]
    return (
        max(xs) - min(xs),
        max(ys) - min(ys),
        (max(ys) + min(ys)) / 2,
        max(zs),
    )


def mesh_xy_bounds(obj):
    """Return the minimum and maximum local XY coordinates of a mesh."""
    xs = [vertex.co.x for vertex in obj.data.vertices]
    ys = [vertex.co.y for vertex in obj.data.vertices]
    return min(xs), max(xs), min(ys), max(ys)


def delete_object(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.ops.object.delete()


def measure_line(text, font):
    """Measure a line at text size 1 without leaving it in the scene."""
    obj = add_text_object(text, 1.0, font, 0.001)
    width, height, _, _ = mesh_bounds(obj)
    delete_object(obj)
    return width, height


def add_box_cutter(name, width, height, x, y, cutter_height, cutter_z):
    """Create one rectangular border cutter."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, cutter_z))
    cutter = bpy.context.active_object
    cutter.name = name
    cutter.dimensions = (width, height, cutter_height)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return cutter


def add_half_ring_cutter(name, center_y, inward_direction, inner_radius):
    """Create a flat-bottomed half-ring groove around a mounting hole."""
    outer_radius = inner_radius + BORDER_WIDTH
    if inward_direction < 0:
        start_angle, end_angle = math.pi, 2 * math.pi
    else:
        start_angle, end_angle = 0.0, math.pi

    angles = [
        start_angle + (end_angle - start_angle) * index / MOUNTING_HOLE_SEGMENTS
        for index in range(MOUNTING_HOLE_SEGMENTS + 1)
    ]
    points = [
        (outer_radius * math.cos(angle), center_y + outer_radius * math.sin(angle))
        for angle in angles
    ]
    points.extend(
        (inner_radius * math.cos(angle), center_y + inner_radius * math.sin(angle))
        for angle in reversed(angles)
    )

    curve_data = bpy.data.curves.new(name=f"{name}_curve", type="CURVE")
    curve_data.dimensions = "2D"
    curve_data.resolution_u = 1
    curve_data.fill_mode = "BOTH"
    curve_data.extrude = CUT_DEPTH + Z_OVERSHOOT
    spline = curve_data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, (x, y) in zip(spline.points, points):
        point.co = (x, y, 0.0, 1.0)
    spline.use_cyclic_u = True

    cutter = bpy.data.objects.new(name, curve_data)
    bpy.context.collection.objects.link(cutter)
    bpy.ops.object.select_all(action="DESELECT")
    cutter.select_set(True)
    bpy.context.view_layer.objects.active = cutter
    bpy.ops.object.convert(target="MESH")

    # Curve extrusion is symmetric about local Z in some Blender versions,
    # which can make the arc cut twice as deep as the box-based border. Force
    # the converted cutter to exactly the same height as every border box.
    cutter_height = CUT_DEPTH + Z_OVERSHOOT
    cutter.dimensions.z = cutter_height
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    _, _, _, z_top = mesh_bounds(cutter)
    cutter.location.z = SIGN_DEPTH / 2 + Z_OVERSHOOT - z_top
    return cutter


def make_border_cutters():
    """Create a border whose top and bottom wrap around the mounting holes."""
    half_width = SIGN_WIDTH / 2 - BORDER_INSET
    half_height = SIGN_HEIGHT / 2 - MOUNTING_HOLE_EDGE_OFFSET
    inner_radius = (
        MOUNTING_HOLE_DIAMETER / 2 + MOUNTING_HOLE_BORDER_CLEARANCE
    )

    if min(half_width, half_height) <= BORDER_WIDTH / 2:
        raise ValueError("The sign is too small for the configured border")
    if BORDER_INSET < 0 or BORDER_WIDTH <= 0:
        raise ValueError("BORDER_INSET must be nonnegative and BORDER_WIDTH positive")
    if inner_radius + BORDER_WIDTH >= half_width:
        raise ValueError("The sign is too narrow for the mounting-hole border arcs")

    cutter_height = CUT_DEPTH + Z_OVERSHOOT
    cutter_z = SIGN_DEPTH / 2 + Z_OVERSHOOT - cutter_height / 2

    # The straight top/bottom portions stop at the arcs. They overlap each
    # arc's radial end cap, preventing tiny Boolean gaps at the joins.
    # Extend each straight piece by half a border width past the adjacent
    # piece's centerline. This makes the outer corner edges meet cleanly rather
    # than leaving a one-half-width stair-step at each corner.
    vertical_height = 2 * half_height + BORDER_WIDTH
    side_segment_width = half_width - inner_radius + BORDER_WIDTH / 2
    side_segment_center = (
        half_width + inner_radius + BORDER_WIDTH / 2
    ) / 2
    cutters = [
        add_box_cutter(
            "cutter_border_left", BORDER_WIDTH, vertical_height,
            -half_width, 0, cutter_height, cutter_z,
        ),
        add_box_cutter(
            "cutter_border_right", BORDER_WIDTH, vertical_height,
            half_width, 0, cutter_height, cutter_z,
        ),
    ]
    for label, y in (("top", half_height), ("bottom", -half_height)):
        for side, x in (("left", -side_segment_center), ("right", side_segment_center)):
            cutters.append(
                add_box_cutter(
                    f"cutter_border_{label}_{side}",
                    side_segment_width,
                    BORDER_WIDTH,
                    x,
                    y,
                    cutter_height,
                    cutter_z,
                )
            )

    cutters.append(
        add_half_ring_cutter("cutter_border_top_arc", half_height, -1, inner_radius)
    )
    cutters.append(
        add_half_ring_cutter("cutter_border_bottom_arc", -half_height, 1, inner_radius)
    )
    return cutters


def make_mounting_hole_cutters():
    """Create two through-hole cutters on the sign's vertical centerline."""
    hole_y = SIGN_HEIGHT / 2 - MOUNTING_HOLE_EDGE_OFFSET
    cutter_depth = SIGN_DEPTH + 2 * Z_OVERSHOOT
    cutters = []
    for label, y in (("top", hole_y), ("bottom", -hole_y)):
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=MOUNTING_HOLE_SEGMENTS,
            radius=MOUNTING_HOLE_DIAMETER / 2,
            depth=cutter_depth,
            location=(0, y, 0),
        )
        cutter = bpy.context.active_object
        cutter.name = f"cutter_mounting_hole_{label}"
        cutters.append(cutter)
    return cutters


def find_brand_svg():
    """Find the reusable logo beside the project script or an ancestor of the blend."""
    candidates = [os.path.join(os.getcwd(), BRAND_SVG_FILENAME)]
    if "__file__" in globals():
        candidates.append(os.path.join(os.path.dirname(__file__), BRAND_SVG_FILENAME))

    directory = os.path.dirname(bpy.data.filepath)
    for _ in range(5):
        candidates.append(os.path.join(directory, BRAND_SVG_FILENAME))
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent

    for candidate in candidates:
        candidate = os.path.abspath(candidate)
        if os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError(
        f"Could not find {BRAND_SVG_FILENAME!r} beside the script or blend project"
    )


def make_brand_cutters():
    """Import, size, and place the prebuilt lower-right logo SVG."""
    filepath = find_brand_svg()
    before = set(bpy.data.objects)
    try:
        bpy.ops.import_curve.svg(filepath=filepath)
    except AttributeError:
        bpy.ops.wm.svg_import(filepath=filepath)

    curves = [
        obj for obj in bpy.data.objects
        if obj not in before and obj.type == "CURVE"
    ]
    if not curves:
        raise RuntimeError(f"No filled paths were imported from {filepath}")

    cutter_height = CUT_DEPTH + Z_OVERSHOOT
    cutters = []
    for index, curve in enumerate(curves):
        bpy.ops.object.select_all(action="DESELECT")
        curve.select_set(True)
        bpy.context.view_layer.objects.active = curve
        curve.data.dimensions = "2D"
        curve.data.fill_mode = "BOTH"
        curve.data.extrude = cutter_height
        bpy.ops.object.convert(target="MESH")
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        curve.name = f"cutter_brand_svg_{index}"
        cutters.append(curve)

    all_vertices = [vertex.co for cutter in cutters for vertex in cutter.data.vertices]
    min_x = min(vertex.x for vertex in all_vertices)
    max_x = max(vertex.x for vertex in all_vertices)
    min_y = min(vertex.y for vertex in all_vertices)
    max_y = max(vertex.y for vertex in all_vertices)
    source_width = max_x - min_x
    source_height = max_y - min_y
    if source_width <= 0 or source_height <= 0:
        raise RuntimeError("The brand SVG has zero width or height")

    scale = min(BRAND_MAX_WIDTH / source_width, BRAND_MAX_HEIGHT / source_height)
    fitted_width = source_width * scale
    fitted_height = source_height * scale
    fitted_min_feature = fitted_height * BRAND_MIN_FEATURE_RATIO
    required_feature = BRAND_TOOL_DIAMETER * BRAND_TOOL_SAFETY_FACTOR
    if fitted_min_feature < required_feature:
        required_height = required_feature / BRAND_MIN_FEATURE_RATIO
        required_width = required_height * source_width / source_height
        raise ValueError(
            f'The brand logo is too small for the {BRAND_TOOL_DIAMETER}" bit. '
            f'Increase BRAND_MAX_WIDTH to at least {required_width:.3f}" and '
            f'BRAND_MAX_HEIGHT to at least {required_height:.3f}".'
        )
    bottom_border_y = -SIGN_HEIGHT / 2 + MOUNTING_HOLE_EDGE_OFFSET
    brand_bottom = bottom_border_y + BORDER_WIDTH / 2 + BRAND_BORDER_GAP
    right_border_x = SIGN_WIDTH / 2 - BORDER_INSET
    brand_right = right_border_x - BORDER_WIDTH / 2 - BRAND_BORDER_GAP
    brand_left = brand_right - fitted_width
    top_z = SIGN_DEPTH / 2 + Z_OVERSHOOT
    bottom_z = top_z - cutter_height

    for cutter in cutters:
        source_zs = [vertex.co.z for vertex in cutter.data.vertices]
        min_z = min(source_zs)
        source_depth = max(source_zs) - min_z
        if source_depth <= 0:
            raise RuntimeError("Could not extrude a brand SVG path")
        for vertex in cutter.data.vertices:
            normalized_z = (vertex.co.z - min_z) / source_depth
            vertex.co.x = brand_left + (vertex.co.x - min_x) * scale
            vertex.co.y = brand_bottom + (vertex.co.y - min_y) * scale
            vertex.co.z = bottom_z + normalized_z * cutter_height

    print(
        f'Brand SVG: {fitted_width:.2f}" wide x {fitted_height:.2f}" high; '
        f'minimum feature {fitted_min_feature:.4f}" for '
        f'{BRAND_TOOL_DIAMETER}" bit; {len(cutters)} reusable path(s) from {filepath}'
    )
    return cutters


def subtract_cutter(sign, cutter):
    """Boolean-subtract one cutter from the sign."""
    bpy.context.view_layer.objects.active = sign
    sign.select_set(True)
    modifier = sign.modifiers.new(name=f"boolean_{cutter.name}", type="BOOLEAN")
    modifier.operation = "DIFFERENCE"
    modifier.object = cutter
    try:
        modifier.solver = "EXACT"
    except AttributeError:
        pass
    bpy.ops.object.modifier_apply(modifier=modifier.name)


def place_sign_at_origin(sign):
    """Place the sign in positive XY with its top at Z=0 and body below it."""
    min_x, _, min_y, _ = mesh_xy_bounds(sign)
    max_z = max(vertex.co.z for vertex in sign.data.vertices)
    sign.location = (-min_x, -min_y, -max_z)
    bpy.context.view_layer.objects.active = sign
    sign.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)


def main():
    lines = [line.strip() for line in SIGN_TEXT.splitlines() if line.strip()]
    if not lines:
        raise ValueError("SIGN_TEXT must contain at least one non-empty line")
    if MOUNTING_HOLE_DIAMETER <= 0:
        raise ValueError("MOUNTING_HOLE_DIAMETER must be greater than zero")
    if MOUNTING_HOLE_EDGE_OFFSET <= 0:
        raise ValueError("MOUNTING_HOLE_EDGE_OFFSET must be greater than zero")
    if MOUNTING_HOLE_BORDER_CLEARANCE < 0:
        raise ValueError("MOUNTING_HOLE_BORDER_CLEARANCE cannot be negative")
    if MOUNTING_HOLE_SEGMENTS < 8:
        raise ValueError("MOUNTING_HOLE_SEGMENTS must be at least 8")
    if min(BRAND_MAX_WIDTH, BRAND_MAX_HEIGHT) <= 0:
        raise ValueError("Brand dimensions must be greater than zero")
    if BRAND_BORDER_GAP < 0:
        raise ValueError("BRAND_BORDER_GAP cannot be negative")
    if min(BRAND_TOOL_DIAMETER, BRAND_TOOL_SAFETY_FACTOR, BRAND_MIN_FEATURE_RATIO) <= 0:
        raise ValueError("Brand tool-check values must be greater than zero")

    # This script builds a new scene, so remove all existing objects.
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()

    scene = bpy.context.scene
    scene.unit_settings.system = "IMPERIAL"
    scene.unit_settings.length_unit = "INCHES"
    scene.unit_settings.scale_length = 0.0254

    font = find_font()

    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
    sign = bpy.context.active_object
    blend_name = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
    sign.name = f"{blend_name or 'untitled'}-sign"
    sign.scale = (SIGN_WIDTH, SIGN_HEIGHT, SIGN_DEPTH)
    bpy.ops.object.transform_apply(scale=True)

    measurements = [measure_line(line, font) for line in lines]
    unit_width = max(width for width, _ in measurements)
    unit_text_height = sum(height for _, height in measurements)
    unit_gap = LINE_GAP_FACTOR * max(height for _, height in measurements)
    unit_total_height = unit_text_height + unit_gap * (len(lines) - 1)

    available_width = SIGN_WIDTH - 2 * MARGIN
    available_height = SIGN_HEIGHT - 2 * MARGIN
    scale = min(
        available_width / unit_width,
        available_height / unit_total_height,
    )

    cutters = []
    scaled_heights = [height * scale for _, height in measurements]
    gap = unit_gap * scale
    total_height = sum(scaled_heights) + gap * (len(lines) - 1)
    cursor_y = total_height / 2
    front_z = SIGN_DEPTH / 2

    for line, line_height in zip(lines, scaled_heights):
        cutter = add_text_object(line, scale, font, CUT_DEPTH + Z_OVERSHOOT)
        cutter.name = f"cutter_{line.lower().replace(' ', '_')}"
        _, actual_height, y_center, z_top = mesh_bounds(cutter)
        target_y = cursor_y - line_height / 2
        cutter.location = (
            0,
            target_y - y_center,
            front_z + Z_OVERSHOOT - z_top,
        )
        cutters.append(cutter)

        cursor_y -= line_height + gap

        print(f'{line}: height {actual_height:.2f}", center Y {target_y:.2f}"')

    cutters.extend(make_border_cutters())
    cutters.extend(make_mounting_hole_cutters())
    cutters.extend(make_brand_cutters())

    for cutter in cutters:
        subtract_cutter(sign, cutter)

    for cutter in cutters:
        delete_object(cutter)

    bpy.ops.object.select_all(action="DESELECT")
    sign.select_set(True)
    bpy.context.view_layer.objects.active = sign
    place_sign_at_origin(sign)

    print(
        f'Done: {SIGN_WIDTH}" x {SIGN_HEIGHT}" sign with text {SIGN_TEXT!r}; '
        f'carving is {CUT_DEPTH}" deep with two '
        f'{MOUNTING_HOLE_DIAMETER}" mounting holes'
    )


if __name__ == "__main__":
    main()
