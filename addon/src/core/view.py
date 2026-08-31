"""Ground-plane projection and world-aligned grid snapping.

Spike 1. Simpler than relay's lib/grids.py: that one carries a full
tangent/bitangent frame so the grid can be calibrated to an arbitrary picked
plane. We only ever target the world ground plane for now, so the tangent
frame is the world X/Y axes and snapping collapses to a per-axis round.
Keep the function boundary the same shape as relay's so swapping in an
arbitrary-plane grid later is a local change.

Everything here is world space: the plane is world Z=0 and snapping is on
world X/Y, so the result never depends on camera orientation.
"""

from mathutils import Vector
from mathutils.geometry import intersect_line_plane
from bpy_extras import view3d_utils

GROUND_ORIGIN = Vector((0.0, 0.0, 0.0))
GROUND_NORMAL = Vector((0.0, 0.0, 1.0))


class Plane:
    """The surface a tool draws on: an origin plus an orthonormal frame.

    `tangent` and `bitangent` are the grid's two axes *within* the plane, so
    snapping is a per-axis round in that frame rather than in world X/Y. The
    ground plane is just the special case where they are world X and Y.
    """

    __slots__ = ("origin", "normal", "tangent", "bitangent")

    def __init__(self, origin, normal, tangent, bitangent):
        self.origin = origin
        self.normal = normal
        self.tangent = tangent
        self.bitangent = bitangent

    def snap(self, point, cell):
        """Quantise a point on this plane to the nearest grid intersection."""
        if point is None:
            return None
        if cell <= 0.0:
            return point.copy()
        local = point - self.origin
        u = round(local.dot(self.tangent) / cell) * cell
        v = round(local.dot(self.bitangent) / cell) * cell
        return self.origin + self.tangent * u + self.bitangent * v

    def project(self, point):
        """Drop a point onto this plane along its normal.

        Element snapping can land on geometry that is off the drawing plane
        entirely. The plane still owns where the shape is built -- a curve is
        written in plane-local XY -- so an off-plane snap has to be brought
        back to it here, visibly, rather than being silently flattened later
        when the curve is created.
        """
        if point is None:
            return None
        return point - self.normal * (point - self.origin).dot(self.normal)

    def cell_corner(self, u_steps, v_steps, cell, anchor):
        """A point `u_steps`/`v_steps` cells away from `anchor` in-plane."""
        return anchor + self.tangent * (u_steps * cell) \
            + self.bitangent * (v_steps * cell)

    def offsets_from(self, point, anchor):
        """In-plane (u, v) of `point` relative to `anchor`."""
        local = point - anchor
        return local.dot(self.tangent), local.dot(self.bitangent)


GROUND = Plane(
    GROUND_ORIGIN,
    GROUND_NORMAL,
    Vector((1.0, 0.0, 0.0)),
    Vector((0.0, 1.0, 0.0)),
)


def axis_plane(axis, origin, view_vector=None):
    """A plane whose normal is a canonical world axis, through `origin`.

    `axis` is 'X', 'Y' or 'Z'. When `view_vector` is given the normal is
    flipped to face the viewer, so the marker standing on the plane always
    points back toward the camera rather than away through the geometry.

    The in-plane axes are chosen so one of them stays world Z wherever that
    is meaningful -- on a vertical plane the grid should read as
    "along the wall" and "up", not as an arbitrary rotation.

    Every frame here is right-handed (tangent x bitangent == normal), which
    matters well beyond the grid: curve objects bake this frame into their
    object matrix, and a left-handed frame is a mirror. A mirrored matrix
    inverts the geometry it evaluates, and Mesh Boolean then reads the solid
    as inside-out and quietly removes nothing. Y is the case that needs care
    -- X x Z is -Y, not +Y -- so its tangent is -X.
    """
    if axis == 'X':
        normal = Vector((1.0, 0.0, 0.0))
        tangent = Vector((0.0, 1.0, 0.0))
        bitangent = Vector((0.0, 0.0, 1.0))
    elif axis == 'Y':
        normal = Vector((0.0, 1.0, 0.0))
        tangent = Vector((-1.0, 0.0, 0.0))
        bitangent = Vector((0.0, 0.0, 1.0))
    else:
        normal = Vector((0.0, 0.0, 1.0))
        tangent = Vector((1.0, 0.0, 0.0))
        bitangent = Vector((0.0, 1.0, 0.0))

    if view_vector is not None and normal.dot(view_vector) > 0.0:
        # view_vector points away from the camera, so a positive dot means
        # the plane's normal points away too; flip it toward the viewer.
        normal = -normal
        tangent = -tangent

    return Plane(origin.copy(), normal, tangent, bitangent)


def circle_in_plane(plane, centre, radius, segments, start_angle=0.0):
    """`segments` points on a circle lying in `plane`.

    Built from the plane's own axes, so the circle lies in the drawing plane
    rather than always flat on the ground. `start_angle` puts the first
    vertex where the radius was dragged to, so the drag sets the rotation.
    """
    import math

    points = []
    for i in range(segments):
        angle = start_angle + (i / segments) * math.tau
        points.append(
            centre
            + plane.tangent * (math.cos(angle) * radius)
            + plane.bitangent * (math.sin(angle) * radius)
        )
    return points


def capsule_in_plane(plane, centre_a, radius_a, centre_b, radius_b,
                     segments, start_angle=0.0):
    """The outline of two circles joined by their outer tangents.

    The convex hull of the pair: an arc of each circle plus the two straight
    tangent spans between them, which fall out for free as the segment
    joining the end of one arc to the start of the next.

    `segments` is the count a *whole* circle would get, and each arc takes
    the share its sweep is worth, so a capsule's curvature is as dense as a
    circle drawn with the same setting rather than coarser for being split.

    When one circle swallows the other the hull is simply the bigger circle;
    returning that rather than refusing keeps the preview alive while the
    user drags a radius through the degenerate range. `start_angle` places
    that circle's first vertex, exactly as the circle tool does, so the
    shape follows the drag instead of sitting at a fixed rotation until the
    second centre lands. A real capsule ignores it: the tangent points fix
    where its arcs start, and there is no freedom left to spend.
    """
    import math

    segments = max(3, int(segments))

    offset = centre_b - centre_a
    # Measured in the plane's own axes, so the maths is a plain 2D problem
    # regardless of how the plane is oriented in the world.
    dx = offset.dot(plane.tangent)
    dy = offset.dot(plane.bitangent)
    distance = math.hypot(dx, dy)

    if distance <= abs(radius_a - radius_b) + 1e-9:
        if radius_a >= radius_b:
            return circle_in_plane(
                plane, centre_a, radius_a, segments, start_angle,
            )
        return circle_in_plane(
            plane, centre_b, radius_b, segments, start_angle,
        )

    base = math.atan2(dy, dx)
    # The half-angle from the centre line to the tangent point. Equal radii
    # give a right angle -- the tangents run parallel to the centre line --
    # and it opens or closes from there as one circle outgrows the other.
    alpha = math.acos(
        max(-1.0, min(1.0, (radius_a - radius_b) / distance))
    )

    sweep_a = math.tau - 2.0 * alpha
    sweep_b = 2.0 * alpha

    def arc(centre, radius, start, sweep):
        count = max(2, int(round(segments * sweep / math.tau)))
        return [
            centre
            + plane.tangent * (math.cos(start + sweep * i / count) * radius)
            + plane.bitangent * (math.sin(start + sweep * i / count) * radius)
            for i in range(count + 1)
        ]

    # Both arcs run counter-clockwise so the outline keeps one winding: a
    # mixed winding would fold the polygon over itself at the tangents.
    return (
        arc(centre_a, radius_a, base + alpha, sweep_a)
        + arc(centre_b, radius_b, base - alpha, sweep_b)
    )


def plane_angle(plane, centre, point):
    """Angle of `point` about `centre`, measured in the plane's own axes."""
    import math

    offset = point - centre
    return math.atan2(offset.dot(plane.bitangent), offset.dot(plane.tangent))


def plane_from_normal(normal, point):
    """A drawing plane through `point` with the given surface normal.

    The in-plane axes follow the same convention as axis_plane: one stays
    horizontal and the other points up-ish, so the grid on a wall reads as
    "along the wall" and "up" rather than as an arbitrary spin. A
    floor-facing normal falls back to plain world X/Y.

    The plane's *origin* is the world origin projected onto the plane, not
    the hit point. Anchoring at the hit would make snapping meaningless --
    the cursor would always land exactly on itself -- whereas a fixed anchor
    gives a grid that stays put as the cursor slides across the surface.

    The frame is right-handed for every normal, including a downward-facing
    one. That is a correctness requirement, not tidiness: the frame is baked
    into the curve object's matrix, and a left-handed one is a mirror, which
    inverts the geometry and leaves Mesh Boolean reading the solid as
    inside-out. Deriving the bitangent from the other two guarantees it,
    where hardcoding world Y for the near-vertical case did not -- against a
    ceiling, X x Y points opposite the normal.
    """
    n = normal.normalized()
    if abs(n.z) > 0.999:
        tangent = Vector((1.0, 0.0, 0.0))
    else:
        tangent = Vector((0.0, 0.0, 1.0)).cross(n).normalized()
    bitangent = n.cross(tangent).normalized()

    origin = n * point.dot(n)
    return Plane(origin, n, tangent, bitangent)


RAYCAST_IGNORE_KEY = "geodraft_ignore_raycast"

# How many times the ray may restart past an ignored hit before giving up.
_RAYCAST_RETRIES = 8


def raycast_surface(context, region, rv3d, coord):
    """(location, normal) of the scene surface under `coord`, or (None, None).

    Plain screen-to-world: the view ray is cast into the evaluated scene, so
    it hits whatever the user is actually pointing at, modifier results
    included.

    Objects flagged with RAYCAST_IGNORE_KEY are skipped. scene.ray_cast takes
    no exclusion list, so the ray is restarted just past each ignored hit
    rather than filtered afterwards -- otherwise a cutter in front of a wall
    would simply block it. Cutters are construction tools; orienting the
    drawing plane to one would be orienting to scaffolding.
    """
    if region is None or rv3d is None:
        return None, None

    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

    try:
        depsgraph = context.evaluated_depsgraph_get()
    except Exception:
        return None, None

    start = origin.copy()
    for _ in range(_RAYCAST_RETRIES):
        try:
            hit, location, normal, _index, obj, _matrix = (
                context.scene.ray_cast(depsgraph, start, direction)
            )
        except Exception:
            return None, None

        if not hit:
            return None, None

        original = getattr(obj, "original", obj)
        if original is not None and original.get(RAYCAST_IGNORE_KEY):
            # Nudge past the surface we just hit and try again.
            start = location + direction * 1e-4
            continue

        if normal.length <= 1e-9:
            return None, None
        return location, normal

    return None, None


def mouse_to_plane(region, rv3d, coord, plane):
    """Intersect the view ray under `coord` with an arbitrary plane.

    Same in-front-of-the-viewer rejection as mouse_to_ground; see its note.
    """
    if region is None or rv3d is None:
        return None

    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)

    hit = intersect_line_plane(
        origin, origin + direction, plane.origin, plane.normal,
    )
    if hit is None:
        return None
    if (hit - origin).dot(direction) <= 0.0:
        return None
    return hit


def mouse_to_plane_grid(region, rv3d, coord, plane, cell):
    return plane.snap(mouse_to_plane(region, rv3d, coord, plane), cell)


def resolve_view(context):
    """(region, rv3d) for the 3D viewport, or (None, None).

    Resolved explicitly off the area rather than trusting context.region /
    context.region_data, which depend on which region the callback happens
    to be dispatched from. A mismatched region/rv3d pair silently produces
    rays that behave as though the camera were somewhere else.
    """
    area = getattr(context, "area", None)
    if area is None or area.type != 'VIEW_3D':
        return None, None

    region = None
    for candidate in area.regions:
        if candidate.type == 'WINDOW':
            region = candidate
            break

    space = area.spaces.active
    rv3d = getattr(space, "region_3d", None)
    if region is None or rv3d is None:
        return None, None
    return region, rv3d


_LAST_VIEW = {}


def view_changed(rv3d, slot="cursor"):
    """True when the view moved since this slot last asked.

    Used to suspend cursor tracking during navigation. There is no "is the
    user orbiting" flag to query: modal navigation operators run inside
    Blender and a draw handler sees no events. But orbit, pan and zoom all
    change the view matrix every frame, while an idle viewport does not, so
    comparing the matrix between draws is a reliable proxy.

    `slot` keeps a separate history per consumer. The paint cursor and the
    draw modal can both run in the same frame, and a shared history would let
    whichever asked first consume the transition, leaving the other seeing a
    stationary view.
    """
    key = (slot, rv3d.as_pointer())
    # Properties AND the view matrix, because neither alone is enough and
    # they go stale in opposite situations:
    #
    # - The matrices are recomputed only when the region draws. Sampling
    #   them from a modal (which is not a draw callback) reports a stale
    #   value, so a matrix-only signature misses ordinary navigation.
    # - Walk/fly navigation drives the view without the properties tracking
    #   its rotation live. A property-only signature therefore parks for
    #   WASD translation but not for mouse-look, which is exactly the
    #   asymmetry that showed up: the marker froze while walking forward and
    #   skated while turning.
    #
    # Measured: assigning view_rotation changes the properties while
    # view_matrix stays put until a redraw. Combining them only ever adds
    # detections, so the union is strictly safer than either.
    current = (
        tuple(round(v, 6) for v in rv3d.view_location),
        tuple(round(v, 6) for v in rv3d.view_rotation),
        round(rv3d.view_distance, 6),
        rv3d.view_perspective,
        tuple(round(v, 5) for row in rv3d.view_matrix for v in row),
    )
    previous = _LAST_VIEW.get(key)
    _LAST_VIEW[key] = current
    return previous is not None and previous != current


def forget_view(slot="cursor"):
    for key in [k for k in _LAST_VIEW if k[0] == slot]:
        del _LAST_VIEW[key]


# Viewport navigation modals. While one of these is running the view is
# being driven, whatever the view data happens to say.
NAVIGATION_OPERATORS = frozenset((
    "VIEW3D_OT_walk",
    "VIEW3D_OT_fly",
    "VIEW3D_OT_rotate",
    "VIEW3D_OT_move",
    "VIEW3D_OT_zoom",
    "VIEW3D_OT_dolly",
    "VIEW3D_OT_view_orbit",
    "VIEW3D_OT_view_pan",
    "VIEW3D_OT_ndof_orbit",
    "VIEW3D_OT_ndof_orbit_zoom",
    "VIEW3D_OT_ndof_pan",
    "VIEW3D_OT_ndof_all",
))


def navigation_running(context):
    """True while a viewport navigation modal owns the view.

    Comparing view data between frames is not enough on its own. Walk and
    fly keep feeding paint cursors a *changing* mouse position while the
    view data we can read stays put, so a mouse-look reads as "the user
    moved the mouse, the camera is still" and the marker slides across the
    ground following the cursor instead of staying where it was left.
    Measured: 156 consecutive cursor updates during a mouse-look, every one
    with moved=True and navigating=False.

    Asking which modals are running sidesteps the question entirely -- it
    does not care whether the view data has caught up yet.
    """
    window = getattr(context, "window", None)
    if window is None:
        return False
    try:
        return any(
            op.bl_idname in NAVIGATION_OPERATORS
            for op in window.modal_operators
        )
    except (AttributeError, TypeError):
        # Older builds have no modal_operators; fall back to view compare.
        return False


_LAST_POINTER = {}


def pointer_moved(xy, slot="cursor"):
    """True when the mouse actually moved since this slot last asked.

    The paint cursor is called for view changes too, not only mouse motion,
    so `view_changed` alone is not enough to park the widget: a wheel zoom
    leaves the mouse still, the view settles by the next call, and the widget
    silently re-projects to a different ground point and jumps.

    Requiring real pointer movement also makes the widget agree with the
    draw modal, which only ever recomputes on MOUSEMOVE -- previously the
    widget snapped to the new projection while the rubber-band line waited
    for a mouse move, and the two disagreed.
    """
    current = (int(xy[0]), int(xy[1]))
    previous = _LAST_POINTER.get(slot)
    _LAST_POINTER[slot] = current
    return previous is None or previous != current


def forget_pointer(slot="cursor"):
    _LAST_POINTER.pop(slot, None)


def region_coord(region, xy):
    """Convert a paint-cursor xy (window space) to region space.

    The paint-cursor callback behind the tool's always-on cursor reports the
    mouse in WINDOW coordinates, while region_2d_to_* expect coordinates
    relative to the region. The docs for draw_cursor_add do not say which
    space it uses; the deciding evidence is that the cursor tracks correctly
    only when the viewport is fullscreen -- exactly when the region origin is
    (0, 0) and the two spaces coincide.

    This is not a harmless offset. Sampling the view ray hundreds of pixels
    above the real cursor lands above the horizon in a tilted view, so the
    ground hit is flung forward along the view direction (and the error
    grows non-linearly toward the horizon). That is the "projected onto a
    plane at the camera's feet, receding into perspective" behaviour.

    Modal operators must NOT use this: event.mouse_region_x/y is already
    region-relative.
    """
    return (xy[0] - region.x, xy[1] - region.y)


def viewport_cell(context, multiplier=1.0):
    """Grid cell size in Blender units, following the viewport's own grid.

    Blender's floor grid spacing is the 3D view overlay's grid_scale, so
    snapping to our own independent number would visibly disagree with the
    grid the user is looking at. Read theirs and scale it.
    """
    area = getattr(context, "area", None)
    scale = 1.0
    if area is not None and area.type == 'VIEW_3D':
        overlay = getattr(area.spaces.active, "overlay", None)
        if overlay is not None:
            scale = getattr(overlay, "grid_scale", 1.0) or 1.0
    return scale * multiplier


def mouse_to_ground(region, rv3d, coord):
    """Intersect the view ray under `coord` with the world Z=0 plane.

    Returns None when there is no usable hit *in front of the viewer*:

    - the ray is parallel to the ground (grazing/edge-on view), which
      intersect_line_plane signals by returning None;
    - the hit lies behind the ray origin. This is the important one: in any
      tilted perspective view, screen points above the horizon only meet the
      ground plane behind the camera, and intersect_line_plane returns that
      mirrored point quite happily. Using it makes the cursor appear to fly
      off into the distance along the view direction. A top-down view has no
      horizon on screen, which is why the bug hides there.
    """
    if region is None or rv3d is None:
        return None

    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)

    hit = intersect_line_plane(
        origin, origin + direction, GROUND_ORIGIN, GROUND_NORMAL,
    )
    if hit is None:
        return None

    if (hit - origin).dot(direction) <= 0.0:
        return None
    return hit


def snap_to_grid(point, cell):
    """Quantise a world point to the nearest grid intersection.

    Z is forced to exactly 0 rather than rounded: the point came off the
    ground plane already, and rounding a float that is nominally 0.0 can
    yield -0.0 and other noise that shows up as jitter in the overlay.
    """
    if point is None:
        return None
    if cell <= 0.0:
        return Vector((point.x, point.y, 0.0))

    return Vector((
        round(point.x / cell) * cell,
        round(point.y / cell) * cell,
        0.0,
    ))


def mouse_to_grid(region, rv3d, coord, cell):
    return snap_to_grid(mouse_to_ground(region, rv3d, coord), cell)
