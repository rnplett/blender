"""Cut an inset border groove along the selected object's outside top edge.

The top is the highest local-Z plane in the mesh. All faces on that plane are
combined and shared edges are ignored, so the groove follows only the object's
outside boundary. The object itself may be moved or rotated in the scene.
"""

import bpy
from mathutils import Vector


# Dimensions are inches when using the unit convention from make-sign.py.
BORDER_INSET = 0.5
BORDER_WIDTH = 0.125
BORDER_DEPTH = 0.125
NORMAL_OVERSHOOT = 0.02
GEOMETRY_TOLERANCE = 1e-7
TOP_PLANE_TOLERANCE = 1e-5


def selected_mesh():
    selected = [obj for obj in bpy.context.selected_objects if obj.type == "MESH"]
    if len(selected) != 1:
        raise RuntimeError("Select exactly one mesh object before running this script")
    if len(selected[0].data.polygons) == 0:
        raise RuntimeError("The selected mesh has no faces")
    return selected[0]


def polygon_area_xy(vertex_indices, mesh):
    points = [mesh.vertices[index].co for index in vertex_indices]
    return sum(
        point.x * points[(index + 1) % len(points)].y
        - points[(index + 1) % len(points)].x * point.y
        for index, point in enumerate(points)
    ) / 2


def boundary_loops(boundary_edges):
    """Chain unordered boundary edges into closed vertex-index loops."""
    neighbors = {}
    for first, second in boundary_edges:
        neighbors.setdefault(first, []).append(second)
        neighbors.setdefault(second, []).append(first)

    invalid = [index for index, linked in neighbors.items() if len(linked) != 2]
    if invalid:
        raise RuntimeError(
            "The top outline branches or is open; expected closed boundary loops"
        )

    unused = {tuple(sorted(edge)) for edge in boundary_edges}
    loops = []
    while unused:
        first, second = next(iter(unused))
        loop = [first]
        previous, current = first, second
        unused.remove(tuple(sorted((previous, current))))

        while current != first:
            loop.append(current)
            choices = [index for index in neighbors[current] if index != previous]
            if len(choices) != 1:
                raise RuntimeError("Could not follow the top boundary")
            following = choices[0]
            edge = tuple(sorted((current, following)))
            if following != first and edge not in unused:
                raise RuntimeError("The top boundary does not form a simple loop")
            unused.discard(edge)
            previous, current = current, following

        loops.append(loop)
    return loops


def find_top_outline(obj):
    """Return the outer boundary of all faces lying on the maximum-Z plane."""
    mesh = obj.data
    highest_z = max(vertex.co.z for vertex in mesh.vertices)
    tolerance = max(1.0, abs(highest_z)) * TOP_PLANE_TOLERANCE

    top_faces = [
        polygon
        for polygon in mesh.polygons
        if all(
            abs(mesh.vertices[index].co.z - highest_z) <= tolerance
            for index in polygon.vertices
        )
    ]
    if not top_faces:
        raise RuntimeError("No face was found on the mesh's highest Z plane")

    edge_counts = {}
    for polygon in top_faces:
        indices = list(polygon.vertices)
        for index, first in enumerate(indices):
            second = indices[(index + 1) % len(indices)]
            edge = tuple(sorted((first, second)))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1

    outside_edges = [edge for edge, count in edge_counts.items() if count == 1]
    if not outside_edges:
        raise RuntimeError("The highest faces have no outside boundary")

    loops = boundary_loops(outside_edges)
    # The largest projected loop is the outside edge. Smaller loops are holes
    # and intentionally do not receive a border.
    outside_loop = max(loops, key=lambda loop: abs(polygon_area_xy(loop, mesh)))
    if polygon_area_xy(outside_loop, mesh) < 0:
        outside_loop.reverse()

    world_vertices = [obj.matrix_world @ mesh.vertices[index].co for index in outside_loop]
    local_up = Vector((0, 0, 1))
    normal_matrix = obj.matrix_world.to_3x3().inverted().transposed()
    world_normal = (normal_matrix @ local_up).normalized()
    print(
        f"Top plane: local Z={highest_z:.5f}, {len(top_faces)} face(s), "
        f"{len(outside_loop)} outside edges"
    )
    return world_vertices, world_normal


def face_coordinates(vertices, normal):
    """Project a world-space face into its own two-dimensional coordinate system."""
    origin = vertices[0]
    axis_x = (vertices[1] - origin).normalized()
    axis_y = normal.cross(axis_x).normalized()
    points = [
        Vector(((vertex - origin).dot(axis_x), (vertex - origin).dot(axis_y)))
        for vertex in vertices
    ]

    area = sum(
        point.cross(points[(index + 1) % len(points)])
        for index, point in enumerate(points)
    ) / 2
    if abs(area) <= GEOMETRY_TOLERANCE:
        raise RuntimeError("The detected top face has no usable area")
    if area < 0:
        points.reverse()

    return origin, axis_x, axis_y, points


def line_intersection(point_a, direction_a, point_b, direction_b):
    denominator = direction_a.cross(direction_b)
    if abs(denominator) <= GEOMETRY_TOLERANCE:
        raise RuntimeError(
            "The top face has adjacent parallel edges that cannot be inset cleanly"
        )
    distance = (point_b - point_a).cross(direction_b) / denominator
    return point_a + distance * direction_a


def inset_polygon(points, distance):
    """Inset a counter-clockwise convex polygon by an even distance."""
    if distance < 0:
        raise ValueError("Border inset distances cannot be negative")

    offset_lines = []
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        direction = next_point - point
        if direction.length <= GEOMETRY_TOLERANCE:
            raise RuntimeError("The top face contains a zero-length edge")
        direction.normalize()
        inward = Vector((-direction.y, direction.x))
        offset_lines.append((point + inward * distance, direction))

    inset = []
    for index in range(len(offset_lines)):
        previous = offset_lines[index - 1]
        current = offset_lines[index]
        inset.append(line_intersection(*previous, *current))

    # A valid inset retains the original counter-clockwise winding.
    area = sum(
        point.cross(inset[(index + 1) % len(inset)])
        for index, point in enumerate(inset)
    ) / 2
    if area <= GEOMETRY_TOLERANCE:
        raise ValueError("The top face is too small for the configured border inset")
    return inset


def make_ring_cutter(obj, face_vertices, normal):
    origin, axis_x, axis_y, face_points = face_coordinates(face_vertices, normal)
    outer = inset_polygon(face_points, BORDER_INSET)
    inner = inset_polygon(face_points, BORDER_INSET + BORDER_WIDTH)
    count = len(outer)

    def world_point(point, normal_offset):
        return origin + axis_x * point.x + axis_y * point.y + normal * normal_offset

    # Outer bottom, inner bottom, outer top, inner top.
    bottom = -BORDER_DEPTH
    top = NORMAL_OVERSHOOT
    vertices = [world_point(point, bottom) for point in outer]
    vertices += [world_point(point, bottom) for point in inner]
    vertices += [world_point(point, top) for point in outer]
    vertices += [world_point(point, top) for point in inner]

    faces = []
    for index in range(count):
        next_index = (index + 1) % count
        outer_bottom = index
        inner_bottom = count + index
        outer_top = 2 * count + index
        inner_top = 3 * count + index
        next_outer_bottom = next_index
        next_inner_bottom = count + next_index
        next_outer_top = 2 * count + next_index
        next_inner_top = 3 * count + next_index

        faces.extend(
            (
                (outer_bottom, next_outer_bottom, next_inner_bottom, inner_bottom),
                (outer_top, inner_top, next_inner_top, next_outer_top),
                (outer_bottom, outer_top, next_outer_top, next_outer_bottom),
                (inner_bottom, next_inner_bottom, next_inner_top, inner_top),
            )
        )

    mesh = bpy.data.meshes.new("Border_Cutter_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    cutter = bpy.data.objects.new("Border_Cutter", mesh)
    bpy.context.collection.objects.link(cutter)
    return cutter


def apply_border(obj, cutter):
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    modifier = obj.modifiers.new(name="Inset_Border", type="BOOLEAN")
    modifier.operation = "DIFFERENCE"
    modifier.object = cutter
    try:
        modifier.solver = "EXACT"
    except AttributeError:
        pass
    bpy.ops.object.modifier_apply(modifier=modifier.name)

    cutter_mesh = cutter.data
    bpy.data.objects.remove(cutter, do_unlink=True)
    bpy.data.meshes.remove(cutter_mesh)


def main():
    if BORDER_WIDTH <= 0 or BORDER_DEPTH <= 0:
        raise ValueError("BORDER_WIDTH and BORDER_DEPTH must be greater than zero")

    obj = selected_mesh()
    face_vertices, normal = find_top_outline(obj)
    cutter = make_ring_cutter(obj, face_vertices, normal)
    apply_border(obj, cutter)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    print(
        f'Added {BORDER_WIDTH}" border, inset {BORDER_INSET}" and '
        f'cut {BORDER_DEPTH}" into the top face of {obj.name}'
    )


if __name__ == "__main__":
    main()
