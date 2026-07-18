import bpy
import os
from xml.sax.saxutils import escape


# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------

# Saves beside the .blend file.
SVG_FILENAME = "sign_cross_section.svg"

# Extra whitespace around the drawing.
MARGIN_MM = 2.0

# SVG line width. This does not affect CNC geometry.
STROKE_WIDTH_MM = 0.2


# ------------------------------------------------------------
# Get the cross-section curve
# ------------------------------------------------------------

obj = bpy.context.view_layer.objects.active

if obj is None:
    raise RuntimeError(
        "No active object. Select a cross-section Curve object before running "
        "this script."
    )

if obj.type != "CURVE":
    raise RuntimeError(
        f"The active object '{obj.name}' is not a Curve object."
    )

# The .blend file must be saved for // to resolve predictably.
if not bpy.data.filepath:
    raise RuntimeError(
        "Save the Blender file before exporting the SVG."
    )

filepath = bpy.path.abspath("//" + SVG_FILENAME)


# ------------------------------------------------------------
# Blender units to millimetres
# ------------------------------------------------------------

scene_scale = bpy.context.scene.unit_settings.scale_length

if scene_scale <= 0:
    scene_scale = 1.0

# One Blender unit represents scale_length metres.
blender_units_to_mm = scene_scale * 1000.0


# ------------------------------------------------------------
# Read all spline points
# ------------------------------------------------------------

paths = []
all_points = []

for spline in obj.data.splines:

    points = []

    if spline.type == "BEZIER":
        for bezier_point in spline.bezier_points:
            world_point = obj.matrix_world @ bezier_point.co

            x = world_point.x * blender_units_to_mm
            y = world_point.y * blender_units_to_mm

            points.append((x, y))
            all_points.append((x, y))

    else:
        for spline_point in spline.points:
            local_point = spline_point.co.xyz
            world_point = obj.matrix_world @ local_point

            x = world_point.x * blender_units_to_mm
            y = world_point.y * blender_units_to_mm

            points.append((x, y))
            all_points.append((x, y))

    if len(points) >= 2:
        paths.append({
            "points": points,
            "closed": spline.use_cyclic_u,
        })

if not all_points:
    raise RuntimeError("The curve contains no exportable points.")


# ------------------------------------------------------------
# Calculate SVG bounds
# ------------------------------------------------------------

min_x = min(point[0] for point in all_points)
max_x = max(point[0] for point in all_points)
min_y = min(point[1] for point in all_points)
max_y = max(point[1] for point in all_points)

drawing_width = max_x - min_x
drawing_height = max_y - min_y

svg_width = drawing_width + (2.0 * MARGIN_MM)
svg_height = drawing_height + (2.0 * MARGIN_MM)


# ------------------------------------------------------------
# Create SVG paths
# ------------------------------------------------------------

svg_path_elements = []

for path in paths:

    points = path["points"]

    # Shift geometry to the page origin.
    # SVG Y increases downward, so invert the Blender Y axis.
    converted_points = []

    for x, y in points:
        svg_x = x - min_x + MARGIN_MM
        svg_y = max_y - y + MARGIN_MM

        converted_points.append((svg_x, svg_y))

    first_x, first_y = converted_points[0]

    commands = [
        f"M {first_x:.6f},{first_y:.6f}"
    ]

    for x, y in converted_points[1:]:
        commands.append(f"L {x:.6f},{y:.6f}")

    if path["closed"]:
        commands.append("Z")

    path_data = " ".join(commands)

    svg_path_elements.append(
        f'  <path d="{escape(path_data)}" />'
    )


# ------------------------------------------------------------
# Write SVG
# ------------------------------------------------------------

svg_contents = f"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg
    xmlns="http://www.w3.org/2000/svg"
    width="{svg_width:.6f}mm"
    height="{svg_height:.6f}mm"
    viewBox="0 0 {svg_width:.6f} {svg_height:.6f}">
  <g
      id="{escape(obj.name)}"
      fill="none"
      stroke="#000000"
      stroke-width="{STROKE_WIDTH_MM:.6f}"
      vector-effect="non-scaling-stroke">
{os.linesep.join(svg_path_elements)}
  </g>
</svg>
"""

with open(filepath, "w", encoding="utf-8") as svg_file:
    svg_file.write(svg_contents)

print("SVG exported successfully:")
print(filepath)
print(
    f"Geometry size: "
    f"{drawing_width:.3f} mm × {drawing_height:.3f} mm"
)
