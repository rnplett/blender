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
    sign.name = "Carved_Text_Sign"
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

    for cutter in cutters:
        subtract_cutter(sign, cutter)

    for cutter in cutters:
        delete_object(cutter)

    bpy.ops.object.select_all(action="DESELECT")
    sign.select_set(True)
    bpy.context.view_layer.objects.active = sign

    print(
        f'Done: {SIGN_WIDTH}" x {SIGN_HEIGHT}" sign with text {SIGN_TEXT!r}; '
        f'carving is {CUT_DEPTH}" deep with two '
        f'{MOUNTING_HOLE_DIAMETER}" mounting holes'
    )


if __name__ == "__main__":
    main()
