"""Cut plain meshes with a cutter, once, for good.

A live cutter cuts nothing here. Subtraction lives inside each shape's
Geometry Nodes modifier, which reads the cutter collection every time it
evaluates, and "Straight To Mesh" removes that modifier. The result is a
mesh with no way to hear about a cutter drawn later, so subtract quietly did
nothing to exactly the objects that option produces.

There is no live answer for a mesh. A modifier put back on it would undo the
conversion the user asked for. So the cut is applied the same way the mesh
was made: once, destructively, with a Boolean modifier that is applied and
gone.

Scope is deliberately narrow. Only objects this addon marked as its own are
cut, and only those whose bounds actually overlap the cutter. Booleaning
whatever else happens to sit in the scene would be a much worse surprise
than a cutter that appears to do nothing.
"""

import bpy
from mathutils import Vector

# Applied and removed immediately, so the name only has to survive one call.
MODIFIER_NAME = "GeoDraftDestructiveCut"


def world_bounds(obj):
    """(minimum, maximum) corner of an object's world-space bounding box."""
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    return (
        Vector((min(c.x for c in corners),
                min(c.y for c in corners),
                min(c.z for c in corners))),
        Vector((max(c.x for c in corners),
                max(c.y for c in corners),
                max(c.z for c in corners))),
    )


def bounds_overlap(a, b, margin=1e-6):
    """True when two world-space boxes share any volume."""
    a_min, a_max = a
    b_min, b_max = b
    for axis in range(3):
        if a_max[axis] < b_min[axis] - margin:
            return False
        if b_max[axis] < a_min[axis] - margin:
            return False
    return True


def _knife(context, cutter):
    """A temporary mesh object holding the cutter's evaluated geometry.

    The cutter is a curve, and Boolean needs a mesh. Its own modifier is
    what turns the outline into a solid slab, so the evaluated result is
    what has to be handed over -- the curve alone is an outline with no
    volume, and Boolean against it removes nothing.
    """
    try:
        depsgraph = context.evaluated_depsgraph_get()
        mesh = bpy.data.meshes.new_from_object(cutter.evaluated_get(depsgraph))
    except Exception:
        return None
    if mesh is None or not len(mesh.polygons):
        if mesh is not None:
            bpy.data.meshes.remove(mesh)
        return None

    knife = bpy.data.objects.new("GeoDraftCutKnife", mesh)
    knife.matrix_world = cutter.matrix_world.copy()
    context.collection.objects.link(knife)
    return knife


def _discard(knife):
    mesh = knife.data
    bpy.data.objects.remove(knife, do_unlink=True)
    if mesh is not None and not mesh.users:
        bpy.data.meshes.remove(mesh)


def targets(context, cutter, marker_keys):
    """Mesh objects this addon owns that the cutter overlaps."""
    box = world_bounds(cutter)
    found = []
    for obj in context.view_layer.objects:
        if obj is cutter or obj.type != 'MESH':
            continue
        if not any(key in obj for key in marker_keys):
            continue
        if obj.hide_get() or not obj.visible_get():
            # A hidden object cannot be checked by the person doing the
            # cutting, so it is not cut.
            continue
        if bounds_overlap(box, world_bounds(obj)):
            found.append(obj)
    return found


def cut_meshes(context, cutter, marker_keys):
    """Subtract `cutter` from every mesh it overlaps. Returns the count.

    Each cut is applied and the modifier removed, so the target stays a
    plain mesh. Undo puts it all back in one step, which is the only safety
    net a destructive operation gets, and the reason this reports what it
    did rather than doing it silently.
    """
    found = targets(context, cutter, marker_keys)
    if not found:
        return 0

    knife = _knife(context, cutter)
    if knife is None:
        return 0

    cut = 0
    try:
        for target in found:
            modifier = target.modifiers.new(MODIFIER_NAME, 'BOOLEAN')
            modifier.operation = 'DIFFERENCE'
            modifier.object = knife
            # EXACT rather than FAST: the shapes drawn here are flat-sided
            # and often coplanar with what they cut, which is where the fast
            # solver leaves holes.
            modifier.solver = 'EXACT'
            try:
                with context.temp_override(
                    object=target,
                    active_object=target,
                    selected_objects=[target],
                    selected_editable_objects=[target],
                ):
                    bpy.ops.object.modifier_apply(modifier=modifier.name)
                cut += 1
            except Exception:
                # Leave the target as it was rather than half-cut.
                target.modifiers.remove(modifier)
    finally:
        _discard(knife)
    return cut
