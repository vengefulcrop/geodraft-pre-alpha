"""GPU overlay primitives, 2D and world-space.

Used by both the tool's always-on cursor (WorkSpaceTool.draw_cursor, which
fires on every mouse move while the tool is active) and the draw operator's
in-progress polyline. Everything is projected to 2D here rather than drawn
with a 3D shader, so a single POST_PIXEL/cursor callback can render it.

UNIFORM_COLOR is deprecated for wide lines and for points; the POLYLINE_*
and POINT_* shaders carry width/size as uniforms instead.
"""

import gpu
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from mathutils import Vector

_LINE_SHADER = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
_POINT_SHADER = gpu.shader.from_builtin('POINT_UNIFORM_COLOR')

COLOR_COMMITTED = (0.95, 0.70, 0.15, 1.0)
COLOR_PREVIEW = (0.95, 0.70, 0.15, 0.55)
COLOR_POINT = (1.0, 1.0, 1.0, 1.0)
COLOR_CURSOR = (0.20, 0.85, 1.0, 0.9)
COLOR_CURSOR_DIM = (0.20, 0.85, 1.0, 0.35)


def to_2d(region, rv3d, point, origin=None):
    """Project a world point to the drawing surface's pixel space.

    location_3d_to_region_2d returns REGION-relative pixels. A
    SpaceView3D.draw_handler (POST_PIXEL) draws in that same region space, so
    it passes origin=None.

    The paint cursor behind the tool's always-on widget does not: it reports
    its xy and draws in WINDOW space (Blender's own circle-select cursor
    draws at the raw xy and is correct in every layout, so its coordinate
    input and its drawing surface must agree). Those callers pass
    origin=(region.x, region.y) to shift region pixels into window pixels.

    Getting this wrong does not merely offset the overlay: the widget is
    drawn at a point that maps to a different world position than the one
    under the mouse, so it appears to sit off the ground plane and to slide
    further than the cursor as the view moves. It only looks right fullscreen,
    where the region origin is (0, 0) and the two spaces coincide.
    """
    projected = view3d_utils.location_3d_to_region_2d(region, rv3d, point)
    if projected is None or origin is None:
        return projected
    return Vector((projected.x + origin[0], projected.y + origin[1]))


def draw_lines(coords, color, width=2.0, kind='LINE_STRIP'):
    coords = [c for c in coords if c is not None]
    if len(coords) < 2:
        return
    gpu.state.blend_set('ALPHA')
    batch = batch_for_shader(_LINE_SHADER, kind, {"pos": coords})
    _LINE_SHADER.bind()
    # The polyline shader works in pixels and needs the viewport size to
    # convert; without it lines render at an arbitrary width.
    _LINE_SHADER.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    _LINE_SHADER.uniform_float("lineWidth", width)
    _LINE_SHADER.uniform_float("color", color)
    batch.draw(_LINE_SHADER)
    gpu.state.blend_set('NONE')


def draw_points(coords, color, size=7.0):
    coords = [c for c in coords if c is not None]
    if not coords:
        return
    gpu.state.blend_set('ALPHA')
    batch = batch_for_shader(_POINT_SHADER, 'POINTS', {"pos": coords})
    _POINT_SHADER.bind()
    _POINT_SHADER.uniform_float("size", size)
    _POINT_SHADER.uniform_float("color", color)
    batch.draw(_POINT_SHADER)
    gpu.state.blend_set('NONE')


_POINT_FLAT_SHADER = gpu.shader.from_builtin('POINT_FLAT_COLOR')

GRID_RGB = (0.62, 0.74, 0.86)
GRID_POINT_SIZE = 7.0


_SMOOTH_SHADER = gpu.shader.from_builtin('SMOOTH_COLOR')

COLOR_VEIL = (0.95, 0.55, 0.12)


def draw_lines_3d(coords, color, width=2.0, kind='LINE_STRIP'):
    """Polyline in world space, for a POST_VIEW handler."""
    if len(coords) < 2:
        return
    gpu.state.blend_set('ALPHA')
    batch = batch_for_shader(_LINE_SHADER, kind, {"pos": coords})
    _LINE_SHADER.bind()
    _LINE_SHADER.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    _LINE_SHADER.uniform_float("lineWidth", width)
    # The polyline shader can feather its own edges; there is no MSAA to fall
    # back on for overlay draws, so this is the only antialiasing lines get.
    _LINE_SHADER.uniform_bool("lineSmooth", True)
    _LINE_SHADER.uniform_float("color", color)
    batch.draw(_LINE_SHADER)
    gpu.state.blend_set('NONE')


def _perpendicular_frame(axis):
    """Two unit vectors spanning the plane perpendicular to `axis`."""
    w = axis.normalized()
    seed = (
        Vector((0.0, 0.0, 1.0)) if abs(w.z) < 0.9 else Vector((1.0, 0.0, 0.0))
    )
    u = seed.cross(w)
    if u.length <= 1e-9:
        u = Vector((1.0, 0.0, 0.0))
    u.normalize()
    return u, w.cross(u)


def draw_circle_3d(center, radius, color, segments=48, width=2.0, axis=None):
    """Circle outline lying in the plane perpendicular to `axis`.

    Defaults to Z-facing (the ground plane). Passing the drawing plane's
    normal keeps the point rings lying *in* that plane rather than staying
    stubbornly flat on the floor when drawing on a vertical plane.
    """
    import math

    if axis is None:
        u = Vector((1.0, 0.0, 0.0))
        v = Vector((0.0, 1.0, 0.0))
    else:
        u, v = _perpendicular_frame(axis)

    coords = []
    for i in range(segments + 1):
        angle = (i / segments) * math.tau
        offset = (u * math.cos(angle) + v * math.sin(angle)) * radius
        coords.append((
            center.x + offset.x, center.y + offset.y, center.z + offset.z,
        ))
    draw_lines_3d(coords, color, width=width)


# Sharper than this and a mitred corner's offset runs away toward infinity,
# so it is capped and the corner opens slightly instead. Same trade as the
# wall node group's Miter Scale Limit.
_VEIL_MITER_MIN = 0.35


def _veil_strip(pairs, closed, rgb, alpha):
    """Draw a faded strip between a base outline and its offset outline.

    `pairs` is [(base, offset), ...] along the outline. Both veils are this
    shape and differ only in where the offset points are: straight up for a
    wall, sideways into the polygon for a floor.
    """
    if len(pairs) < 2:
        return

    spans = list(zip(pairs, pairs[1:]))
    if closed and len(pairs) > 2:
        spans.append((pairs[-1], pairs[0]))

    coords = []
    colors = []
    near = (*rgb, alpha)
    far = (*rgb, 0.0)
    for (a_b, a_f), (b_b, b_f) in spans:
        a_base = (a_b.x, a_b.y, a_b.z)
        b_base = (b_b.x, b_b.y, b_b.z)
        a_off = (a_f.x, a_f.y, a_f.z)
        b_off = (b_f.x, b_f.y, b_f.z)
        for tri, cols in (
            ((a_base, b_base, b_off), (near, near, far)),
            ((a_base, b_off, a_off), (near, far, far)),
        ):
            coords.extend(tri)
            colors.extend(cols)

    if not coords:
        return

    gpu.state.blend_set('ALPHA')
    # No depth write: the curtain is an overlay hint, and writing depth would
    # let it occlude the widget and dots drawn after it.
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.face_culling_set('NONE')
    batch = batch_for_shader(
        _SMOOTH_SHADER, 'TRIS', {"pos": coords, "color": colors},
    )
    _SMOOTH_SHADER.bind()
    batch.draw(_SMOOTH_SHADER)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


def draw_veil(points, height, rgb=COLOR_VEIL, alpha=0.5, closed=False,
              axis=None):
    """Vertical curtain rising from the drawn line, fading out with height.

    Opaque-ish at the base and alpha 0 at `height`, so the wall's footprint
    reads as a volume before any geometry exists.
    """
    if len(points) < 2 or height <= 0.0:
        return

    # The curtain rises along the drawing plane's normal, not world Z, so it
    # stays perpendicular to the outline on a vertical plane.
    up = Vector((0.0, 0.0, 1.0)) if axis is None else axis.normalized()
    rise = up * height
    _veil_strip([(p, p + rise) for p in points], closed, rgb, alpha)


def interior_side(points, normal, closed, view_vector=None):
    """Which side of the outline the glow should lie on: +1 left, -1 right.

    Once an actual corner exists the shape has an inside, and the signed area
    about the plane normal says which way the outline winds -- left of travel
    for a counter-clockwise loop. The area is taken as a vector and dotted
    with the normal rather than read off the plane's 2D frame, because that
    frame is not consistently right-handed (axis_plane negates the tangent to
    keep the normal facing the viewer).

    With fewer than three points there is no angle yet and no inside to face,
    so it falls back to whichever side faces the camera. Nothing about the
    first segment says which side will become the inside, so the tie breaks
    on legibility: the glow is where the user is looking.
    """
    if len(points) >= 3:
        # The loop is closed virtually even for an outline still being drawn:
        # an unfinished L already has a side that reads as its inside, and
        # waiting for the user to close it would flip the glow at the end.
        origin = points[0]
        area = Vector((0.0, 0.0, 0.0))
        for a, b in zip(points, list(points[1:]) + [points[0]]):
            area += (a - origin).cross(b - origin)
        winding = area.dot(normal)
        if abs(winding) > 1e-9:
            return 1.0 if winding > 0.0 else -1.0

    if view_vector is not None:
        direction = points[1] - points[0]
        if direction.length > 1e-9:
            left = normal.cross(direction.normalized())
            # view_vector points away from the camera, so the side with a
            # negative dot is the one facing back toward it.
            return 1.0 if left.dot(view_vector) < 0.0 else -1.0
    return 1.0


def dedupe(points, closed=False, epsilon=1e-9):
    """Drop consecutive coincident points.

    The outline being drawn routinely contains a duplicate: committing a
    point does not move the mouse, so the live hover sits exactly on the
    point just placed until the next motion. A duplicate is a zero-length
    segment, which has no direction and therefore no offset direction
    either -- it pinches the band shut at that vertex. The curtain never
    noticed, because it offsets every vertex the same way regardless of the
    segments around it.
    """
    kept = []
    for point in points:
        if not kept or (point - kept[-1]).length > epsilon:
            kept.append(point)
    if closed and len(kept) > 1 and (kept[-1] - kept[0]).length <= epsilon:
        kept.pop()
    return kept


def inward_offsets(points, height, normal, closed=False, view_vector=None):
    """Each point pushed `height` toward the outline's inside.

    Corners are mitred along the bisector so the band keeps a constant width
    across a turn rather than notching on the outside of every angle.
    """
    normal = normal.normalized()
    side = interior_side(points, normal, closed, view_vector)

    count = len(points)
    wrap = closed and count > 2

    def segment_normal(index):
        """Inward normal of the segment leaving vertex `index`, or None."""
        nxt = index + 1
        if nxt >= count:
            if not wrap:
                return None
            nxt = 0
        direction = points[nxt] - points[index]
        if direction.length <= 1e-9:
            return None
        return normal.cross(direction.normalized()) * side

    offsets = []
    for index in range(count):
        outgoing = segment_normal(index)
        if index > 0:
            incoming = segment_normal(index - 1)
        elif wrap:
            incoming = segment_normal(count - 1)
        else:
            incoming = None

        candidates = [n for n in (incoming, outgoing) if n is not None]
        if not candidates:
            offsets.append(points[index])
            continue

        bisector = candidates[0] if len(candidates) == 1 else (
            candidates[0] + candidates[1]
        )
        if bisector.length <= 1e-9:
            # The outline doubles back on itself; no bisector exists, so use
            # one of the two segment normals rather than a zero vector.
            bisector = candidates[-1]
        bisector = bisector.normalized()

        # Lengthen the offset at a corner so the band keeps a constant width
        # across the turn, capped so a sharp corner cannot spike.
        reach = max(bisector.dot(candidates[-1]), _VEIL_MITER_MIN)
        offsets.append(points[index] + bisector * (height / reach))

    return offsets


def draw_veil_inward(points, height, normal, rgb=COLOR_VEIL, alpha=0.5,
                     closed=False, view_vector=None):
    """Glow lying *in* the drawing plane, spreading toward the inner angle.

    A wall's curtain stands up because a wall does; flat geometry has no
    height to stand in, so the same hint reads better as a band lying in the
    plane and falling inward across the face being outlined.
    """
    points = dedupe(points, closed)
    if len(points) < 2 or height <= 0.0:
        return

    offsets = inward_offsets(points, height, normal, closed, view_vector)
    _veil_strip(list(zip(points, offsets)), closed, rgb, alpha)


# Snap targets: a target in range but not winning, and one that would be
# taken if the click happened now. Two channels carry the difference --
# colour and size -- because either alone is easy to miss against busy
# geometry, and the pair reads at a glance without needing a legend.
COLOR_SNAP_IDLE = (0.78, 0.82, 0.88, 0.45)
COLOR_SNAP_ACTIVE = (0.20, 0.85, 1.0, 1.0)
SNAP_IDLE_SIZE = 6.0
SNAP_ACTIVE_SIZE = 11.0
SNAP_ACTIVE_SIZE_NEAR = 19.0


def draw_snap_targets(candidates, winner, nearness):
    """Dots on every eligible snap target, with the winning one lit.

    The winner grows and warms as the cursor closes on it, rather than
    switching state at a threshold: a highlight that pops on at an invisible
    boundary tells the user where the boundary was, not where the point will
    land.
    """
    idle = [
        (p.x, p.y, p.z) for p in candidates
        if winner is None or (p - winner).length > 1e-9
    ]
    if idle:
        draw_points(idle, COLOR_SNAP_IDLE, size=SNAP_IDLE_SIZE)

    if winner is None:
        return

    nearness = max(0.0, min(1.0, nearness))
    size = SNAP_ACTIVE_SIZE + (
        SNAP_ACTIVE_SIZE_NEAR - SNAP_ACTIVE_SIZE
    ) * nearness
    color = tuple(
        idle_c + (active_c - idle_c) * nearness
        for idle_c, active_c in zip(COLOR_SNAP_IDLE, COLOR_SNAP_ACTIVE)
    )
    # A dimmer, larger dot behind the core, so the target stays visible on
    # top of light geometry as well as dark.
    draw_points(
        [(winner.x, winner.y, winner.z)],
        (color[0], color[1], color[2], color[3] * 0.35),
        size=size * 1.8,
    )
    draw_points([(winner.x, winner.y, winner.z)], color, size=size)


def cell_pixels(region, rv3d, center, cell):
    """Screen size, in pixels, of one grid cell at `center`.

    Lets world-referenced sizes (the dot diameter is a fraction of a cell) be
    expressed in the pixel units the POINT shaders actually take.
    """
    a = view3d_utils.location_3d_to_region_2d(region, rv3d, center)
    b = view3d_utils.location_3d_to_region_2d(
        region, rv3d, center + Vector((cell, 0.0, 0.0)),
    )
    if a is None or b is None:
        return None
    return (b - a).length


def draw_plane_grid_3d(plane, center, cell, radius_cells=18, point_size=8.0):
    """Grid dot field lying in an arbitrary drawing plane.

    Same radial mask as the ground version, but stepped along the plane's
    own tangent/bitangent so the field tilts with the drawing plane instead
    of always lying flat on the floor.
    """
    if cell <= 0.0:
        return

    # Anchor to the grid itself so the field does not shimmer as the cursor
    # snaps from cell to cell.
    anchor = plane.snap(center, cell)
    if anchor is None:
        return
    radius = cell * radius_cells

    coords = []
    colors = []
    for iu in range(-radius_cells, radius_cells + 1):
        for iv in range(-radius_cells, radius_cells + 1):
            dist = ((iu * cell) ** 2 + (iv * cell) ** 2) ** 0.5
            if dist > radius:
                continue
            t = 1.0 - (dist / radius)
            alpha = t ** 1.5
            if alpha <= 0.01:
                continue
            point = plane.cell_corner(iu, iv, cell, anchor)
            coords.append((point.x, point.y, point.z))
            colors.append((*GRID_RGB, alpha))

    if not coords:
        return

    gpu.state.blend_set('ALPHA')
    batch = batch_for_shader(
        _POINT_FLAT_SHADER, 'POINTS', {"pos": coords, "color": colors},
    )
    _POINT_FLAT_SHADER.bind()
    _POINT_FLAT_SHADER.uniform_float("size", point_size)
    batch.draw(_POINT_FLAT_SHADER)
    gpu.state.blend_set('NONE')


def draw_ground_grid_3d(center, cell, radius_cells=18, point_size=8.0):
    """Grid dot field in world space, for a POST_VIEW draw handler.

    Same radial mask as the 2D version, but positions are handed over as
    world coordinates and Blender's view matrix does the projection, so no
    region/window conversion is involved.
    """
    if cell <= 0.0:
        return

    ox = round(center.x / cell) * cell
    oy = round(center.y / cell) * cell
    radius = cell * radius_cells

    coords = []
    colors = []
    for ix in range(-radius_cells, radius_cells + 1):
        for iy in range(-radius_cells, radius_cells + 1):
            x = ox + ix * cell
            y = oy + iy * cell
            dist = ((x - center.x) ** 2 + (y - center.y) ** 2) ** 0.5
            if dist > radius:
                continue
            t = 1.0 - (dist / radius)
            alpha = t ** 1.5
            if alpha <= 0.01:
                continue
            coords.append((x, y, 0.0))
            colors.append((*GRID_RGB, alpha))

    if not coords:
        return

    gpu.state.blend_set('ALPHA')
    batch = batch_for_shader(
        _POINT_FLAT_SHADER, 'POINTS', {"pos": coords, "color": colors},
    )
    _POINT_FLAT_SHADER.bind()
    _POINT_FLAT_SHADER.uniform_float("size", point_size)
    batch.draw(_POINT_FLAT_SHADER)
    gpu.state.blend_set('NONE')


