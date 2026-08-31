"""Snap the cursor to real geometry, obeying Blender's own snap settings.

There is deliberately no second set of snapping checkboxes in this addon.
Blender already has a magnet button and an element list in the header, every
user already knows what they mean, and a tool that ignored them in favour of
its own would be one more thing to keep in agreement. So: the magnet gates
this, and the element list says which candidates are eligible.

Holding Ctrl inverts the magnet for one point, the way Ctrl already does
during a Blender transform. See snap_holds.

Scope of the search is the polygon under the cursor, not the whole scene.
That is the cheap way to do it and the honest one: the ray already has to be
cast to know what is being pointed at, the candidates are then a handful of
verts and edges rather than every vertex in view, and the cost per mouse
move does not grow with the size of the scene. What it gives up is snapping
to a vertex the cursor is *near* but not pointing through -- an empty patch
of screen next to a corner will not find that corner. Worth revisiting with
a screen-space search over cached visible geometry if that starts to bite;
see doc/reference_cad_transform_engine.md for how CAD Transform does it.

Modifier results count. The ray is cast against the evaluated scene, and the
candidates are read off the evaluated geometry -- including the mesh a
Geometry Nodes modifier builds from a curve, which is what every shape this
addon draws is. Snapping lands on what the user can see, not on the cage
underneath it. See _snap_mesh, where both of those cost a correction.
"""

from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.geometry import intersect_point_line

from .cursor import STATE, set_snap_preview
from .view import RAYCAST_IGNORE_KEY

# Screen-space radius, in pixels at UI scale 1, within which a vertex or edge
# wins over the plain surface hit. Blender's own default snap radius is in
# the same range; small enough that pointing between two verts still means
# "the face", large enough to catch one without precision aiming.
SNAP_RADIUS_PIXELS = 14.0

# How far out an eligible target is still worth drawing, as a multiple of
# the snap radius. Targets outside the snap radius cannot win yet, and
# showing them is the point: the highlight has to appear *before* the snap
# happens, or it confirms rather than predicts.
PREVIEW_RADIUS_FACTOR = 3.0

# Element names, spelled as Blender's enum does.
VERTEX = 'VERTEX'
EDGE = 'EDGE'
FACE = 'FACE'
EDGE_MIDPOINT = 'EDGE_MIDPOINT'
FACE_NEAREST = 'FACE_NEAREST'

# Elements this module can snap to. Blender's list also holds GRID -- its
# default, and often the only one set -- which means the increment grid.
# That is our own grid step's job, not this module's.
GEOMETRY = frozenset((VERTEX, EDGE, FACE, EDGE_MIDPOINT, FACE_NEAREST))

# What the Ctrl hold assumes when Blender's list names no geometry element.
# Without this the hold does nothing at all on a default configuration,
# which reads as a broken key rather than as an empty element list.
FORCED_DEFAULT = frozenset((VERTEX, EDGE))


def snap_settings(context):
    """(enabled, elements) from the scene's snap settings.

    `snap_elements_base` is the current spelling and `snap_elements` the
    older one; both are read so the addon does not depend on which of them a
    given build exposes.
    """
    tool_settings = getattr(context.scene, "tool_settings", None)
    if tool_settings is None:
        return False, frozenset()

    elements = frozenset(
        getattr(tool_settings, "snap_elements_base", None)
        or getattr(tool_settings, "snap_elements", None)
        or ()
    ) & GEOMETRY

    # What the hold inverts is whether *geometry* snapping is happening, not
    # the magnet on its own. The two are not the same thing: Blender's
    # default is the magnet on with GRID as the only element, which is
    # snapping switched on and no geometry to snap to. Inverting the magnet
    # there turned off something that was doing nothing, and Ctrl looked
    # dead. Inverting the real state gives the key one meaning in every
    # configuration -- "geometry snapping, the other way".
    active = bool(getattr(tool_settings, "use_snap", False)) and bool(elements)
    forced = bool(STATE.get("snap_forced"))
    if active == forced:
        return False, frozenset()

    if not elements:
        elements = FORCED_DEFAULT
    return True, elements


def snap_radius(context):
    """The snap radius in real pixels, following the interface scale."""
    try:
        scale = context.preferences.system.ui_scale
    except AttributeError:
        scale = 1.0
    return SNAP_RADIUS_PIXELS * max(0.5, scale)


def _project(region, rv3d, point):
    return view3d_utils.location_3d_to_region_2d(region, rv3d, point)


# Pixel offsets retried when the direct ray misses. A vertex on the
# silhouette is the case that needs them: aiming exactly at a corner puts
# the ray along the edge of the mesh, where it hits nothing, so the
# highlight died at the last pixel before the target it was pointing at.
# Measured on a cube corner -- dead on missed, one pixel inside hit.
_GRAZE_OFFSETS = ((3.0, 0.0), (-3.0, 0.0), (0.0, 3.0), (0.0, -3.0))


def _ray_hit(context, region, rv3d, coord):
    """The object and polygon under the cursor, with the hit and depsgraph.

    Retries a few pixels around a miss, so a silhouette corner still
    resolves. Only a miss pays for this, which is the rare case.

    Deliberately not shared with view.raycast_surface: that one wants a
    location and a normal to stand a plane on and is happy to skip past
    ignored objects, while this one needs the object and polygon index to
    read candidates off, and a miss here is simply "no snap".
    """
    try:
        depsgraph = context.evaluated_depsgraph_get()
    except Exception:
        return None

    for offset in ((0.0, 0.0),) + _GRAZE_OFFSETS:
        at = (coord[0] + offset[0], coord[1] + offset[1])
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, at)
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, at)
        try:
            hit, location, normal, index, obj, matrix = (
                context.scene.ray_cast(depsgraph, origin, direction)
            )
        except Exception:
            return None

        if not hit or obj is None:
            continue
        original = getattr(obj, "original", obj)
        if original is not None and original.get(RAYCAST_IGNORE_KEY):
            # Scaffolding. Snapping to a cutter would be snapping to a tool.
            return None
        return location, normal, index, obj, matrix, depsgraph

    return None


def _snap_mesh(obj, depsgraph):
    """(mesh, temporary) holding the geometry the ray actually hit.

    Two corrections live here, both found by testing against a real scene.

    scene.ray_cast reports the *original* object, not the evaluated one
    (measured: is_evaluated was False on every hit). Reading its data meant
    reading the cage under the modifiers, so a snap could land on geometry
    nobody can see.

    An evaluated object is also not always a mesh. A curve with a Geometry
    Nodes modifier -- which is every shape this addon draws -- keeps Curve
    data, whose `polygons` do not exist, while the ray happily hits the mesh
    the modifier produced. That made the addon's own output unsnappable,
    which is precisely the geometry a decal workflow aims at.

    So: evaluate, take the evaluated mesh when there is one, and fall back to
    to_mesh() for everything else. The fallback builds a temporary mesh and
    the caller must free it.
    """
    evaluated = obj.evaluated_get(depsgraph) if depsgraph is not None else obj
    data = getattr(evaluated, "data", None)
    if getattr(data, "polygons", None) is not None:
        return evaluated, data, False

    try:
        mesh = evaluated.to_mesh()
    except Exception:
        return evaluated, None, False
    return evaluated, mesh, True


def _polygon_points(obj, matrix, index, depsgraph):
    """World-space vertices of polygon `index`, or None."""
    evaluated, mesh, temporary = _snap_mesh(obj, depsgraph)
    if mesh is None:
        return None
    try:
        polygons = mesh.polygons
        if index < 0 or index >= len(polygons):
            return None
        return [
            matrix @ mesh.vertices[vertex_index].co
            for vertex_index in polygons[index].vertices
        ]
    finally:
        if temporary:
            try:
                evaluated.to_mesh_clear()
            except Exception:
                pass


def element_snap(context, region, rv3d, coord):
    """(point, normal) snapped to nearby geometry, or (None, None).

    Also publishes what the overlay should highlight. The two are one
    question -- which targets are in range, and which of them wins -- so
    answering it twice would let the highlight and the snap disagree, which
    is the one thing a highlight must never do.
    """
    result = _resolve(context, region, rv3d, coord)
    if result is None:
        set_snap_preview(())
        return None, None
    point, normal, candidates, nearness = result
    set_snap_preview(candidates, point, nearness)
    return point, normal


def _resolve(context, region, rv3d, coord):
    """(point, normal, candidates, nearness), or None when nothing snaps."""
    enabled, elements = snap_settings(context)
    if not enabled or not elements or region is None or rv3d is None:
        return None

    hit = _ray_hit(context, region, rv3d, coord)
    if hit is None:
        return None
    location, normal, index, obj, matrix, depsgraph = hit

    surface = (
        location if elements & {FACE, FACE_NEAREST} else None
    )

    points = _polygon_points(obj, matrix, index, depsgraph)
    if not points:
        return (None, None, (), 0.0) if surface is None else (
            surface, normal, (), 0.0
        )

    cursor = Vector(coord)
    radius = snap_radius(context)
    preview_radius = radius * PREVIEW_RADIUS_FACTOR
    best = None
    best_distance = radius
    candidates = []

    def consider(point):
        nonlocal best, best_distance
        at = _project(region, rv3d, point)
        if at is None:
            return
        distance = (at - cursor).length
        if distance <= preview_radius:
            candidates.append(point)
        # Strictly closer, so the first element in the order below wins a
        # tie: a vertex beats the edge it sits on, which is the priority
        # Blender itself uses.
        if distance < best_distance:
            best, best_distance = point, distance

    if VERTEX in elements:
        for point in points:
            consider(point)

    if elements & {EDGE, EDGE_MIDPOINT}:
        for i, start in enumerate(points):
            end = points[(i + 1) % len(points)]
            if EDGE_MIDPOINT in elements:
                consider((start + end) * 0.5)
            if EDGE in elements:
                # The point on the edge nearest the surface hit, clamped to
                # the segment: projecting the *cursor* would need the edge in
                # screen space, and this lands on the edge in world space,
                # which is what a snap has to mean.
                closest, factor = intersect_point_line(location, start, end)
                consider(
                    start if factor <= 0.0
                    else end if factor >= 1.0
                    else closest
                )

    if best is not None:
        # 1 when the cursor sits exactly on the target, 0 at the edge of the
        # snap radius. The highlight reads as "closer" rather than as a
        # binary that flips at an invisible boundary.
        nearness = 1.0 - (best_distance / radius) if radius > 0.0 else 1.0
        return best, normal, candidates, max(0.0, min(1.0, nearness))
    if surface is None:
        # Nothing wins and there is no face to fall back on, but the targets
        # are still worth showing: they are what the cursor is approaching.
        return (None, None, candidates, 0.0) if candidates else None
    return surface, normal, candidates, 0.0
