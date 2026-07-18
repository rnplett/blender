"""Cut an SVG-shaped pocket into the selected Blender mesh.

Run from Blender's Scripting workspace after selecting one mesh object. Blender
units are treated as inches, matching make-sign.py. Coordinates are in the
selected object's local coordinate system.
"""

import os

import bpy
from mathutils import Vector


# SVG and pocket placement (inches).
SVG_FILE = r"C:\path\to\shape.svg"
MAX_WIDTH = 4.0
MAX_HEIGHT = 3.0
BOTTOM_LEFT_X = 1.0
BOTTOM_LEFT_Y = 1.0
POCKET_DEPTH = 0.125
Z_OVERSHOOT = 0.02

# True enlarges a small SVG until one dimension reaches the configured limit.
# False only shrinks SVGs that are too large.
ALLOW_UPSCALE = True


def selected_mesh():
    """Return the one selected mesh that will receive the pocket."""
    selected = [obj for obj in bpy.context.selected_objects if obj.type == "MESH"]
    if len(selected) != 1:
        raise RuntimeError("Select exactly one mesh object before running this script")
    if not selected[0].data.vertices:
        raise RuntimeError("The selected mesh has no vertices")
    return selected[0]


def imported_svg_objects(filepath):
    """Import an SVG and return only the curve objects created by the import."""
    before = set(bpy.data.objects)
    filepath = bpy.path.abspath(filepath)
    try:
        bpy.ops.import_curve.svg(filepath=filepath)
    except AttributeError:
        # Blender 4.3+ exposes the built-in SVG importer under wm.
        bpy.ops.wm.svg_import(filepath=filepath)
    imported = [obj for obj in bpy.data.objects if obj not in before]
    curves = [obj for obj in imported if obj.type == "CURVE"]

    if not curves:
        for obj in imported:
            bpy.data.objects.remove(obj, do_unlink=True)
        raise RuntimeError("The SVG did not contain any importable filled paths")

    # Non-curve helper objects are not part of the cutter.
    for obj in imported:
        if obj.type != "CURVE":
            bpy.data.objects.remove(obj, do_unlink=True)
    return curves


def join_curves(curves):
    """Join all imported paths so their shared fill and holes stay together."""
    bpy.ops.object.select_all(action="DESELECT")
    for curve in curves:
        curve.select_set(True)
    bpy.context.view_layer.objects.active = curves[0]
    bpy.ops.object.join()
    result = bpy.context.active_object
    result.name = "SVG_Pocket_Cutter"
    result.data.dimensions = "2D"
    result.data.fill_mode = "BOTH"
    return result


def mesh_bounds_xy(obj):
    """Return the object's mesh-space XY bounds."""
    xs = [vertex.co.x for vertex in obj.data.vertices]
    ys = [vertex.co.y for vertex in obj.data.vertices]
    return min(xs), max(xs), min(ys), max(ys)


def make_cutter(target):
    """Import, fit, and place the SVG as a solid Boolean cutter."""
    curves = imported_svg_objects(SVG_FILE)
    cutter = join_curves(curves)

    # SVG importers may assign transforms to individual paths. Apply the joined
    # transform before measuring so all paths use one predictable coordinate set.
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    cutter.data.extrude = POCKET_DEPTH + Z_OVERSHOOT
    bpy.ops.object.convert(target="MESH")

    min_x, max_x, min_y, max_y = mesh_bounds_xy(cutter)
    source_width = max_x - min_x
    source_height = max_y - min_y
    if source_width <= 0 or source_height <= 0:
        raise RuntimeError("The imported SVG has zero width or height")

    scale = min(MAX_WIDTH / source_width, MAX_HEIGHT / source_height)
    if not ALLOW_UPSCALE:
        scale = min(1.0, scale)

    # Curves extrude along Z. Rebuild every vertex directly in the selected
    # object's local coordinates, including the desired top-to-depth interval.
    source_zs = [vertex.co.z for vertex in cutter.data.vertices]
    min_z = min(source_zs)
    max_z = max(source_zs)
    source_depth = max_z - min_z
    if source_depth <= 0:
        raise RuntimeError("Could not create a solid cutter from the SVG paths")

    top_z = max(vertex.co.z for vertex in target.data.vertices)
    cutter_height = POCKET_DEPTH + Z_OVERSHOOT
    for vertex in cutter.data.vertices:
        normalized_z = (vertex.co.z - min_z) / source_depth
        vertex.co = Vector(
            (
                BOTTOM_LEFT_X + (vertex.co.x - min_x) * scale,
                BOTTOM_LEFT_Y + (vertex.co.y - min_y) * scale,
                top_z - POCKET_DEPTH + normalized_z * cutter_height,
            )
        )

    cutter.matrix_world = target.matrix_world.copy()
    fitted_width = source_width * scale
    fitted_height = source_height * scale
    print(
        f'SVG fitted to {fitted_width:.4f}" x {fitted_height:.4f}"; '
        f'bottom-left at ({BOTTOM_LEFT_X:.4f}", {BOTTOM_LEFT_Y:.4f}")'
    )
    return cutter


def subtract_cutter(target, cutter):
    """Subtract the SVG cutter and remove its temporary object and mesh."""
    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    modifier = target.modifiers.new(name="SVG_Pocket", type="BOOLEAN")
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


def validate_settings():
    if not SVG_FILE or not os.path.isfile(bpy.path.abspath(SVG_FILE)):
        raise FileNotFoundError(f"SVG_FILE does not exist: {SVG_FILE}")
    if MAX_WIDTH <= 0 or MAX_HEIGHT <= 0:
        raise ValueError("MAX_WIDTH and MAX_HEIGHT must be greater than zero")
    if POCKET_DEPTH <= 0:
        raise ValueError("POCKET_DEPTH must be greater than zero")
    if Z_OVERSHOOT <= 0:
        raise ValueError("Z_OVERSHOOT must be greater than zero")


def main():
    validate_settings()
    target = selected_mesh()
    cutter = make_cutter(target)
    subtract_cutter(target, cutter)

    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    print(
        f'Cut SVG pocket {POCKET_DEPTH}" deep into {target.name} from {SVG_FILE}'
    )


if __name__ == "__main__":
    main()
