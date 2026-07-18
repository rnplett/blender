import bpy
import bmesh
import os
from mathutils import Vector
from xml.sax.saxutils import escape


# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------

SLICE_DEPTH_MM = 1.0
CROSS_SECTION_NAME = "Cross_Section_1mm"

# The SVG is saved beside the current .blend file.
SVG_FILENAME = "sign_cross_section.svg"
MARGIN_MM = 2.0
STROKE_WIDTH_MM = 0.2


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def trace_edge_chains(vertices, edges):
    """
    Convert an unordered collection of edges into ordered vertex chains.
    Handles closed loops and open chains.
    """

    adjacency = {i: [] for i in range(len(vertices))}

    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)

    unused_edges = {
        tuple(sorted((a, b)))
        for a, b in edges
    }

    chains = []

    while unused_edges:
        first_edge = next(iter(unused_edges))
        a, b = first_edge

        # Prefer an endpoint for open chains.
        if len(adjacency[a]) == 1:
            start = a
        elif len(adjacency[b]) == 1:
            start = b
        else:
            start = a

        chain = [start]
        previous = None
        current = start

        while True:
            next_vertex = None

            for candidate in adjacency[current]:
                edge_key = tuple(sorted((current, candidate)))

                if edge_key in unused_edges and candidate != previous:
                    next_vertex = candidate
                    break

            if next_vertex is None:
                break

            edge_key = tuple(sorted((current, next_vertex)))
            unused_edges.remove(edge_key)

            chain.append(next_vertex)
            previous, current = current, next_vertex

            # Closed loop
            if current == start:
                break

        chains.append(chain)

    return chains


def delete_existing_object(name):
    existing = bpy.data.objects.get(name)

    if existing:
        bpy.data.objects.remove(existing, do_unlink=True)


def save_cross_section_svg(obj):
    """Save a Curve object as an SVG beside the current .blend file."""
    if not bpy.data.filepath:
        raise RuntimeError("Save the Blender file before exporting the SVG.")
    if obj.type != "CURVE":
        raise RuntimeError(f"'{obj.name}' is not a Curve object.")

    scale_length = bpy.context.scene.unit_settings.scale_length
    if scale_length <= 0:
        scale_length = 1.0
    blender_units_to_mm = scale_length * 1000.0

    paths = []
    all_points = []
    for spline in obj.data.splines:
        points = []
        if spline.type == "BEZIER":
            local_points = [point.co for point in spline.bezier_points]
        else:
            local_points = [point.co.xyz for point in spline.points]

        for local_point in local_points:
            world_point = obj.matrix_world @ local_point
            point = (
                world_point.x * blender_units_to_mm,
                world_point.y * blender_units_to_mm,
            )
            points.append(point)
            all_points.append(point)

        if len(points) >= 2:
            paths.append({"points": points, "closed": spline.use_cyclic_u})

    if not all_points:
        raise RuntimeError("The cross-section curve contains no exportable points.")

    min_x = min(point[0] for point in all_points)
    max_x = max(point[0] for point in all_points)
    min_y = min(point[1] for point in all_points)
    max_y = max(point[1] for point in all_points)
    drawing_width = max_x - min_x
    drawing_height = max_y - min_y
    svg_width = drawing_width + 2.0 * MARGIN_MM
    svg_height = drawing_height + 2.0 * MARGIN_MM

    elements = []
    for path in paths:
        converted = [
            (x - min_x + MARGIN_MM, max_y - y + MARGIN_MM)
            for x, y in path["points"]
        ]
        first_x, first_y = converted[0]
        commands = [f"M {first_x:.6f},{first_y:.6f}"]
        commands.extend(f"L {x:.6f},{y:.6f}" for x, y in converted[1:])
        if path["closed"]:
            commands.append("Z")
        elements.append(f'  <path d="{escape(" ".join(commands))}" />')

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
{os.linesep.join(elements)}
  </g>
</svg>
"""

    filepath = bpy.path.abspath("//" + SVG_FILENAME)
    with open(filepath, "w", encoding="utf-8") as svg_file:
        svg_file.write(svg_contents)

    print(f"SVG exported successfully: {filepath}")
    print(f"Geometry size: {drawing_width:.3f} mm x {drawing_height:.3f} mm")
    return filepath


# ------------------------------------------------------------
# Main operation
# ------------------------------------------------------------

obj = bpy.context.active_object

if obj is None:
    raise RuntimeError("Select the sign object first.")

if obj.type not in {"MESH", "CURVE", "FONT", "SURFACE", "META"}:
    raise RuntimeError(
        f"Selected object type '{obj.type}' cannot be evaluated as a mesh."
    )

# Convert millimetres to Blender units.
scale_length = bpy.context.scene.unit_settings.scale_length

if scale_length <= 0:
    scale_length = 1.0

slice_depth_bu = (SLICE_DEPTH_MM / 1000.0) / scale_length

# Get evaluated geometry so modifiers, booleans and text extrusion are included.
depsgraph = bpy.context.evaluated_depsgraph_get()
evaluated_obj = obj.evaluated_get(depsgraph)
evaluated_mesh = evaluated_obj.to_mesh()

try:
    bm = bmesh.new()
    bm.from_mesh(evaluated_mesh)

    # Move geometry into world coordinates.
    bm.transform(obj.matrix_world)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    if not bm.verts:
        raise RuntimeError("The selected object contains no mesh vertices.")

    top_z = max(vertex.co.z for vertex in bm.verts)
    slice_z = top_z - slice_depth_bu

    result = bmesh.ops.bisect_plane(
        bm,
        geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
        dist=1e-6,
        plane_co=Vector((0.0, 0.0, slice_z)),
        plane_no=Vector((0.0, 0.0, 1.0)),
        clear_inner=False,
        clear_outer=False,
    )

    cut_geometry = set(result["geom_cut"])

    cut_edges = [
        element
        for element in cut_geometry
        if isinstance(element, bmesh.types.BMEdge)
    ]

    if not cut_edges:
        raise RuntimeError(
            "The slice plane did not intersect the object. "
            "Check the object's orientation and thickness."
        )

    # Build indexed vertex and edge collections.
    cut_vertices = set()

    for edge in cut_edges:
        cut_vertices.update(edge.verts)

    cut_vertices = list(cut_vertices)
    vertex_index = {
        vertex: index
        for index, vertex in enumerate(cut_vertices)
    }

    coordinates = [
        vertex.co.copy()
        for vertex in cut_vertices
    ]

    indexed_edges = [
        (
            vertex_index[edge.verts[0]],
            vertex_index[edge.verts[1]],
        )
        for edge in cut_edges
    ]

    chains = trace_edge_chains(coordinates, indexed_edges)

    # Remove the previous generated cross section, if present.
    delete_existing_object(CROSS_SECTION_NAME)

    # Create a 2D curve.
    curve_data = bpy.data.curves.new(
        name=CROSS_SECTION_NAME,
        type="CURVE",
    )

    curve_data.dimensions = "2D"
    curve_data.resolution_u = 1
    curve_data.fill_mode = "NONE"

    for chain in chains:
        if len(chain) < 2:
            continue

        is_closed = chain[0] == chain[-1]

        if is_closed:
            chain = chain[:-1]

        spline = curve_data.splines.new("POLY")
        spline.points.add(len(chain) - 1)

        for point, vertex_id in zip(spline.points, chain):
            coordinate = coordinates[vertex_id]

            # Set Z to zero so the result is ready for 2D export.
            point.co = (
                coordinate.x,
                coordinate.y,
                0.0,
                1.0,
            )

        spline.use_cyclic_u = is_closed

    section_obj = bpy.data.objects.new(
        CROSS_SECTION_NAME,
        curve_data,
    )

    bpy.context.collection.objects.link(section_obj)

    # Select the resulting section.
    bpy.ops.object.select_all(action="DESELECT")
    section_obj.select_set(True)
    bpy.context.view_layer.objects.active = section_obj

    print(
        f"Created '{CROSS_SECTION_NAME}' at "
        f"Z = {slice_z:.6f} Blender units."
    )

finally:
    bm.free()
    evaluated_obj.to_mesh_clear()

save_cross_section_svg(section_obj)
