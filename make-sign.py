"""Create a carved text sign in Blender.

Run from Blender's Scripting workspace, or from a shell with:
    blender --background --python make-sign.py

Blender units are treated as inches.
"""

import os

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
BORDER_WIDTH = 0.13


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


def make_border_cutters():
    """Create four overlapping box cutters around the sign's border."""
    outer_half_width = SIGN_WIDTH / 2 - BORDER_INSET
    outer_half_height = SIGN_HEIGHT / 2 - BORDER_INSET
    inner_half_width = outer_half_width - BORDER_WIDTH
    inner_half_height = outer_half_height - BORDER_WIDTH

    if min(inner_half_width, inner_half_height) <= 0:
        raise ValueError("The sign is too small for the configured border")
    if BORDER_INSET < 0 or BORDER_WIDTH <= 0:
        raise ValueError("BORDER_INSET must be nonnegative and BORDER_WIDTH positive")

    outer_width = outer_half_width * 2
    outer_height = outer_half_height * 2
    cutter_height = CUT_DEPTH + Z_OVERSHOOT
    cutter_z = SIGN_DEPTH / 2 + Z_OVERSHOOT - cutter_height / 2

    # The horizontal pieces span the full border width. The vertical pieces
    # overlap their ends slightly, preventing tiny gaps at the four corners.
    specifications = (
        ("top", outer_width, BORDER_WIDTH, 0, outer_half_height - BORDER_WIDTH / 2),
        ("bottom", outer_width, BORDER_WIDTH, 0, -outer_half_height + BORDER_WIDTH / 2),
        ("left", BORDER_WIDTH, outer_height, -outer_half_width + BORDER_WIDTH / 2, 0),
        ("right", BORDER_WIDTH, outer_height, outer_half_width - BORDER_WIDTH / 2, 0),
    )

    cutters = []
    for name, width, height, x, y in specifications:
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, cutter_z))
        cutter = bpy.context.active_object
        cutter.name = f"cutter_border_{name}"
        cutter.dimensions = (width, height, cutter_height)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
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

    for cutter in cutters:
        subtract_cutter(sign, cutter)

    for cutter in cutters:
        delete_object(cutter)

    bpy.ops.object.select_all(action="DESELECT")
    sign.select_set(True)
    bpy.context.view_layer.objects.active = sign

    print(
        f'Done: {SIGN_WIDTH}" x {SIGN_HEIGHT}" sign with text {SIGN_TEXT!r}; '
        f'all cuts are {CUT_DEPTH}" deep'
    )


if __name__ == "__main__":
    main()
