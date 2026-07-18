import bpy
import bmesh
import os
from mathutils import Vector
from xml.sax.saxutils import escape


# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------

SLICE_DEPTH_MM = 1.0

# The SVG is saved beside the current .blend file as
# "<Blender filename>-cross-section.svg".
MARGIN_MM = 2.0

# Operation classification. These match make-sign.py's generated layout.
MOUNTING_HOLE_DIAMETER_IN = 0.25
MOUNTING_HOLE_EDGE_OFFSET_IN = 0.5
MOUNTING_HOLE_MATCH_TOLERANCE = 0.20
LOGO_REGION_WIDTH_IN = 4.25
LOGO_REGION_HEIGHT_IN = 1.75


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


def polygon_area(points):
    """Return the signed area of a closed two-dimensional polygon."""
    return sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
    ) / 2.0


def point_in_polygon(point, polygon):
    """Return whether a point lies inside a polygon using ray casting."""
    px, py = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = current
        x2, y2 = previous
        if (y1 > py) != (y2 > py):
            crossing_x = (x2 - x1) * (py - y1) / (y2 - y1) + x1
            if px < crossing_x:
                inside = not inside
        previous = current
    return inside


def compound_carved_shapes(paths):
    """Group nested closed loops into filled carved regions and their islands."""
    closed = [path for path in paths if path["closed"] and len(path["points"]) >= 3]
    areas = [abs(polygon_area(path["points"])) for path in closed]
    parents = [None] * len(closed)

    for index, path in enumerate(closed):
        containing = [
            candidate
            for candidate, other in enumerate(closed)
            if areas[candidate] > areas[index]
            and point_in_polygon(path["points"][0], other["points"])
        ]
        if containing:
            parents[index] = min(containing, key=lambda candidate: areas[candidate])

    depths = []
    for index in range(len(closed)):
        depth = 0
        parent = parents[index]
        while parent is not None:
            depth += 1
            parent = parents[parent]
        depths.append(depth)

    # Depth zero is the sign's outside perimeter. Odd depths are voids cut
    # from the material; their direct even-depth children are uncut islands,
    # such as the inside of a border or a letter counter.
    shapes = []
    for index, depth in enumerate(depths):
        if depth % 2 == 1:
            children = [
                child
                for child, parent in enumerate(parents)
                if parent == index
            ]
            shapes.append([closed[index]] + [closed[child] for child in children])
    return shapes


def shape_bounds(shape):
    """Return XY bounds for every contour in a compound carved shape."""
    points = [point for contour in shape for point in contour["points"]]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), max(xs), min(ys), max(ys)


def classify_carved_shape(shape, sign_bounds):
    """Return logo, holes, or main for a carved compound shape."""
    min_x, max_x, min_y, max_y = shape_bounds(shape)
    sign_min_x, sign_max_x, sign_min_y, sign_max_y = sign_bounds
    width = max_x - min_x
    height = max_y - min_y
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    diameter_mm = MOUNTING_HOLE_DIAMETER_IN * 25.4
    edge_offset_mm = MOUNTING_HOLE_EDGE_OFFSET_IN * 25.4
    diameter_tolerance = diameter_mm * MOUNTING_HOLE_MATCH_TOLERANCE
    position_tolerance = max(diameter_tolerance, 0.5)
    sign_center_x = (sign_min_x + sign_max_x) / 2
    expected_hole_ys = (
        sign_min_y + edge_offset_mm,
        sign_max_y - edge_offset_mm,
    )
    is_mounting_hole = (
        abs(width - diameter_mm) <= diameter_tolerance
        and abs(height - diameter_mm) <= diameter_tolerance
        and abs(center_x - sign_center_x) <= position_tolerance
        and any(
            abs(center_y - expected_y) <= position_tolerance
            for expected_y in expected_hole_ys
        )
    )
    if is_mounting_hole:
        return "holes"

    logo_left = sign_max_x - LOGO_REGION_WIDTH_IN * 25.4
    logo_top = sign_min_y + LOGO_REGION_HEIGHT_IN * 25.4
    if min_x >= logo_left and max_y <= logo_top:
        return "logo"
    return "main"


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

    def svg_path_commands(path):
        converted = [
            (x - min_x + MARGIN_MM, max_y - y + MARGIN_MM)
            for x, y in path["points"]
        ]
        first_x, first_y = converted[0]
        commands = [f"M {first_x:.6f},{first_y:.6f}"]
        commands.extend(f"L {x:.6f},{y:.6f}" for x, y in converted[1:])
        if path["closed"]:
            commands.append("Z")
        return " ".join(commands)

    carved_shapes = compound_carved_shapes(paths)
    if not carved_shapes:
        raise RuntimeError(
            "No enclosed carved regions were found in the cross section. "
            "Verify that the slice depth passes through the carved pockets."
        )

    classified_elements = {"logo": [], "holes": [], "main": []}
    sign_bounds = (min_x, max_x, min_y, max_y)
    for index, shape in enumerate(carved_shapes, start=1):
        oriented_shape = []
        for contour_index, path in enumerate(shape):
            # Easel's SVG conversion is more reliable when holes use opposite
            # winding rather than depending on even-odd fill support. The SVG
            # Y-axis inversion below reverses both windings but preserves their
            # required opposition.
            want_counter_clockwise = contour_index == 0
            points = path["points"]
            is_counter_clockwise = polygon_area(points) > 0
            if is_counter_clockwise != want_counter_clockwise:
                points = list(reversed(points))
            oriented_shape.append({"points": points, "closed": True})

        compound_path = " ".join(
            svg_path_commands(path) for path in oriented_shape
        )
        operation = classify_carved_shape(shape, sign_bounds)
        element = (
            f'  <path id="carved-region-{index}" '
            f'data-operation="{operation}" '
            f'd="{escape(compound_path)}" fill="#000000" stroke="none" '
            f'fill-rule="nonzero" />'
        )
        classified_elements[operation].append(element)

    def svg_document(body, source):
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg
    xmlns="http://www.w3.org/2000/svg"
    width="{svg_width:.6f}mm"
    height="{svg_height:.6f}mm"
    viewBox="0 0 {svg_width:.6f} {svg_height:.6f}"
    data-source="{escape(source)}">
{body}
</svg>
"""

    blend_name = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
    for operation, elements in classified_elements.items():
        if not elements:
            raise RuntimeError(
                f"No {operation} pockets were detected. Check the operation "
                "classification settings at the top of this script."
            )

    # Keep every pocket as a direct child of the SVG. Easel then exposes each
    # path independently while preserving compound contours within a pocket.
    ordered_elements = (
        classified_elements["main"]
        + classified_elements["logo"]
        + classified_elements["holes"]
    )
    filename = f"{blend_name}-carving-pockets.svg"
    filepath = bpy.path.abspath("//" + filename)
    contents = svg_document(os.linesep.join(ordered_elements), obj.name)
    with open(filepath, "w", encoding="utf-8") as svg_file:
        svg_file.write(contents)

    print(f"Combined carving SVG: {filepath}")
    for operation in ("main", "logo", "holes"):
        print(f"  {operation.title()}: {len(classified_elements[operation])} pocket(s)")

    print(f"Geometry size: {drawing_width:.3f} mm x {drawing_height:.3f} mm")
    print(f"Carved regions: {len(carved_shapes)} filled compound shape(s)")
    return filepath


# ------------------------------------------------------------
# Main operation
# ------------------------------------------------------------

obj = bpy.context.active_object

if obj is None:
    raise RuntimeError("Select the sign object first.")

blend_name = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
cross_section_name = f"{blend_name or 'untitled'}-cross-section"

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
    delete_existing_object(cross_section_name)

    # Create a 2D curve.
    curve_data = bpy.data.curves.new(
        name=cross_section_name,
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
        cross_section_name,
        curve_data,
    )

    bpy.context.collection.objects.link(section_obj)

    # Select the resulting section.
    bpy.ops.object.select_all(action="DESELECT")
    section_obj.select_set(True)
    bpy.context.view_layer.objects.active = section_obj

    print(
        f"Created '{cross_section_name}' at "
        f"Z = {slice_z:.6f} Blender units."
    )

finally:
    bm.free()
    evaluated_obj.to_mesh_clear()

save_cross_section_svg(section_obj)
