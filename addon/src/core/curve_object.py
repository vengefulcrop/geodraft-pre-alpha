"""Create a curve object whose local XY *is* the drawing plane.

Rather than storing the drawing plane as data and teaching every node group
about it, the plane is baked into the object's transform: the curve's points
are written in a local frame where the plane's tangent/bitangent are X/Y and
its normal is Z, and the object matrix rotates that frame into place.

Two things fall out of this for free:

- `Fill Curve` only fills in XY -- a vertical curve collapses to nothing
  (measured: a 4-point square on an X-facing plane produced 2 verts and 0
  faces). Working in local space means it always sees a flat XY curve.
- Geometry Nodes evaluates in object local space, so a wall's 'Z Up' sweep
  frame becomes "up relative to the drawing plane" with no extra inputs.

The gizmo handles already convert through `matrix_world`, so dragging keeps
working unchanged.
"""

from mathutils import Matrix



def to_mesh_now(context, obj):
    """Apply the modifier stack and leave a plain mesh behind.

    Destructive on purpose: the shape stops being a curve, and its handles
    and its settings go with it. That is the whole request -- some work
    wants geometry, not a thing that re-solves.

    Cutters never come here. A cutter has to stay live, because the shapes
    it cuts read it through Geometry Nodes every time they evaluate.

    A failure is swallowed rather than raised. The shape is already built
    and selected by this point, so the worst case is a curve where a mesh
    was wanted, and the user can convert it by hand.
    """
    import bpy

    try:
        bpy.ops.object.convert(target='MESH')
    except Exception:
        return obj
    return context.view_layer.objects.active or obj


def plane_matrix(plane, origin):
    """World matrix whose X/Y/Z are the plane's tangent/bitangent/normal."""
    basis = Matrix((
        (plane.tangent.x, plane.bitangent.x, plane.normal.x, origin.x),
        (plane.tangent.y, plane.bitangent.y, plane.normal.y, origin.y),
        (plane.tangent.z, plane.bitangent.z, plane.normal.z, origin.z),
        (0.0, 0.0, 0.0, 1.0),
    ))
    return basis


def create_plane_curve(context, name, points, plane, closed, origin=None):
    """A POLY curve object holding `points` (world space) in plane-local XY.

    `origin` sets the object's own origin; it defaults to the first point.
    A circle passes its centre instead, so its centre handle is simply the
    object origin and a radius edit is a scale about local zero.
    """
    import bpy

    if origin is None:
        origin = points[0]
    matrix = plane_matrix(plane, origin)
    to_local = matrix.inverted()

    curve = bpy.data.curves.new(name, type='CURVE')
    curve.dimensions = '3D'
    spline = curve.splines.new('POLY')
    # A new POLY spline starts with one point already present.
    spline.points.add(len(points) - 1)
    for spline_point, point in zip(spline.points, points):
        local = to_local @ point
        # Snap the plane axis to exactly zero: the points came off the plane
        # already, and float residue there makes Fill Curve's planarity test
        # unnecessarily marginal.
        spline_point.co = (local.x, local.y, 0.0, 1.0)
    spline.use_cyclic_u = closed

    obj = bpy.data.objects.new(name, curve)
    obj.matrix_world = matrix
    context.collection.objects.link(obj)
    return obj
