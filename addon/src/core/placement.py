"""The viewport overlay shared by every ground-plane placement tool.

One `PlacementOverlay` instance per tool owns: the paint cursor that resolves
the snapped ground point, a POST_VIEW handler that draws the grid dot field,
the in-progress sketch and the 3D marker, a POST_PIXEL handler for the label,
and the timer driving the close-the-loop animation.

Splitting the work across those three handlers is deliberate and load-bearing:

- The paint cursor runs in WINDOW space, the wrong space for projecting world
  geometry (see draw.to_2d), so it only does the part that genuinely needs
  the mouse -- ray-cast to the snapped ground point -- and stashes the result.
- POST_VIEW gets Blender's own view matrix, so world coordinates go straight
  in and the window/region coordinate problem cannot recur.
- POST_PIXEL is region space and is used only for screen-aligned text.

Settings are read with getattr defaults, so a tool only has to define the
properties it actually wants to expose.
"""

import math
import time

import blf
import bpy
from bpy_extras import view3d_utils
from mathutils import Vector

from . import draw
from .element_snap import element_snap
from .cursor import (
    STATE,
    clear_holds,
    release_pointer_on_move,
    set_cursor,
    set_plane,
)
from .marker import ARROW
from .polyline import POINT_RING_FACTOR
from .toolkit import DrawHandlers, active_tool_is
from .view import (
    GROUND,
    resolve_view,
    capsule_in_plane,
    circle_in_plane,
    mouse_to_plane_grid,
    navigation_running,
    plane_from_normal,
    raycast_surface,
    pointer_moved,
    region_coord,
    resolve_view,
    view_changed,
    viewport_cell,
)

# Close-the-loop bob: seconds per cycle, travel as a fraction of the marker's
# height, and the redraw rate while it runs.
BOB_PERIOD = 2.4
BOB_AMPLITUDE = 0.12
BOB_FPS = 30.0

COLOR_MARKER = (1.0, 1.0, 1.0)

# The hint line along the bottom of the region, and the number being typed
# above it. Same position, size and colours as the scrubber's own hint, so
# the two read as one voice rather than as two overlays that met by accident.
HINT_Y = 24.0
COLOR_HINT = (1.0, 1.0, 1.0, 0.65)
COLOR_TYPED = (0.35, 0.95, 0.45, 1.0)
# Ring colour while hovering the point that would close the loop.
COLOR_CLOSE = (0.25, 0.95, 0.35, 1.0)

# Marker tint per drawing-plane orientation, matching Blender's own axis
# colours so the held direction is readable at a glance.
COLOR_SUBTRACT = (1.0, 0.30, 0.30)

AXIS_COLORS = {
    'X': (1.0, 0.35, 0.38),
    'Y': (0.52, 0.85, 0.25),
}


def axis_color(normal, default):
    """Red on an X-facing plane, green on Y, the tool's own colour on Z."""
    ax, ay, az = abs(normal.x), abs(normal.y), abs(normal.z)
    if ax > ay and ax > az:
        return AXIS_COLORS['X']
    if ay > ax and ay > az:
        return AXIS_COLORS['Y']
    return default


def current_lift(marker_height):
    """World-Z offset of the bob, shared by everything that follows it.

    The marker (POST_VIEW) and the label (POST_PIXEL) are drawn by separate
    handlers, so both derive the offset from this one clock -- otherwise the
    label drifts out of the marker mid-animation.

    Measured from entry rather than a free-running global clock, and shaped
    so the cycle *starts* at zero. Both are needed, or the marker jumps the
    instant the cursor enters the disk.
    """
    since = STATE.get("closing_since")
    if not STATE.get("closing") or since is None:
        return 0.0

    phase = ((time.time() - since) % BOB_PERIOD) / BOB_PERIOD
    return (
        (1.0 - math.cos(phase * math.tau)) * 0.5
    ) * marker_height * BOB_AMPLITUDE


def resolve_cursor(context, settings, region, rv3d, coord):
    """Re-resolve the cursor from a region-relative mouse position.

    Extracted from the paint cursor so that *anything* changing the drawing
    state can repaint immediately rather than waiting for the next mouse
    move: toggling surface snap, stepping the grid, switching the axis plane.
    A setting that only takes visible effect on the next mouse move reads as
    a broken toggle.
    """
    frozen = STATE.get("widget_freeze")
    if frozen is not None:
        # Held in world space, so orbiting moves the camera around the
        # widget instead of dragging the widget across the screen. Nothing
        # below this line may run: re-resolving is precisely what the freeze
        # forbids.
        set_cursor(frozen, viewport_cell(context, settings.grid_multiplier))
        region.tag_redraw()
        return frozen

    snap_to_surface = (
        getattr(settings, "surface_snap", False)
        and not STATE.get("plane_locked")
    )
    if snap_to_surface:
        location, normal = raycast_surface(context, region, rv3d, coord)
        if location is not None:
            set_plane(plane_from_normal(normal, location))
        else:
            # Nothing under the cursor; fall back to the ground rather than
            # keeping the last surface's orientation.
            set_plane(GROUND)
    elif not STATE.get("plane_locked"):
        # Snapping is off, and nothing explicit owns the plane, so the
        # drawing plane is the ground. Without this the plane simply kept
        # whatever surface it last aligned to, and switching the mode off
        # left the cursor stuck on that face's orientation -- the setting
        # looked like it had not applied.
        #
        # Guarded on plane_locked so it cannot stamp on an X/Y toggle or on a
        # polyline that locked its plane when drawing began.
        set_plane(GROUND)

    cell = viewport_cell(context, settings.grid_multiplier)
    plane = STATE.get("plane") or GROUND
    # Gridless: the cell still sizes the dots and rings, it just stops
    # quantising. Plane.snap reads a zero step as "leave the point alone".
    snapping = (
        getattr(settings, "snap_to_grid", True)
        != bool(STATE.get("grid_suppressed"))
    )
    snapped, _normal = element_snap(context, region, rv3d, coord)
    if snapped is not None:
        # The magnet asked for that exact point; the plane still owns which
        # surface the shape is built on, so it is projected rather than
        # taken as-is, and the grid step is not applied on top of it.
        base = plane.project(snapped)
    else:
        base = mouse_to_plane_grid(
            region, rv3d, coord, plane, cell if snapping else 0.0,
        )

    point_size = None
    if base is not None:
        # Dots are sized as a fraction of a grid cell, so they read as
        # world-scale spheres rather than fixed-size screen dots.
        cell_px = draw.cell_pixels(region, rv3d, base, cell)
        if cell_px:
            point_size = max(2.0, min(64.0, cell_px / 8.0))

    set_cursor(base, cell, point_size)
    region.tag_redraw()
    return base


def refresh_cursor(context, settings_path, event=None):
    """Repaint the cursor now, from the current mouse position.

    Call from any operator that alters drawing state. `event` supplies a
    region-relative mouse position; without one the cursor keeps its place
    and only the redraw happens.
    """
    settings = getattr(context.scene, settings_path, None)
    region, rv3d = resolve_view(context)
    if settings is None or region is None:
        return None
    if event is None:
        region.tag_redraw()
        return STATE.get("base")
    return resolve_cursor(
        context, settings, region, rv3d,
        (event.mouse_region_x, event.mouse_region_y),
    )


class PlacementOverlay:
    """Draws the cursor, grid and in-progress sketch for one tool."""

    def __init__(self, tool_idname, settings_path, marker_height,
                 marker=ARROW, label=None, marker_color=COLOR_MARKER,
                 veil_inward=False, hint=None):
        # veil_inward: lay the glow in the drawing plane, spreading toward
        # the outline's inner angle, instead of standing it up along the
        # plane normal. Flat geometry has no height for a curtain to occupy.
        self.veil_inward = veil_inward
        self.tool_idname = tool_idname
        self.settings_path = settings_path
        self.marker = marker
        self.marker_height = marker_height
        self.marker_color = marker_color
        # Callable(settings) -> str, or None for no label.
        self.label = label
        # The key list shown when nothing is being drawn. A running modal
        # publishes its own through STATE, because the useful keys change
        # from one stage of a gesture to the next.
        self.hint = hint
        self._handlers = DrawHandlers(tool_idname)

    # --- helpers ----------------------------------------------------------

    def settings(self, context):
        return getattr(context.scene, self.settings_path, None)

    def _is_active(self, context):
        return active_tool_is(context, self.tool_idname)

    # --- the paint cursor -------------------------------------------------

    def draw_cursor(self, context, tool, xy):
        """Resolve the cursor position; the marker is drawn in POST_VIEW."""
        region, rv3d = resolve_view(context)
        if region is None:
            return

        settings = self.settings(context)
        if settings is None:
            # Properties are gone (mid-unregister); nothing sensible to draw.
            return

        cell = viewport_cell(context, settings.grid_multiplier)

        # Both must be sampled every call to keep their histories current,
        # so evaluate them before the branch rather than short-circuiting.
        moved = pointer_moved(xy, "cursor")
        navigating = view_changed(rv3d, "cursor") or navigation_running(
            context
        )

        if moved:
            # Ends a freeze the scrubber left pending; the marker holds its
            # place until the mouse genuinely moves off it.
            release_pointer_on_move()

        if navigating:
            # A modifier held through an orbit or a pan belongs to the
            # navigation, not to us, and its release never reaches our
            # keymap. Forget the holds rather than leaving them stuck on.
            clear_holds()

        if navigating or not moved or STATE.get("pointer_freeze"):
            # Either the mouse is steering the camera (orbit/pan), the view
            # moved without it (wheel zoom, numpad views), or the mouse has
            # been borrowed to scrub a value. Park the marker; it resumes on
            # the next real mouse move.
            set_cursor(STATE.get("base"), cell)
            return

        # The paint cursor reports WINDOW-space xy; region_coord converts.
        resolve_cursor(
            context, settings, region, rv3d, region_coord(region, xy),
        )

    # --- handlers ---------------------------------------------------------

    def _draw_view(self):
        """POST_VIEW: everything world-space -- veil, sketch, dots, marker.

        Single consumer of cursor state, so the idle cursor and an
        in-progress polyline can never draw competing markers.
        """
        context = bpy.context
        region, rv3d = resolve_view(context)
        if region is None or not self._is_active(context):
            return

        settings = self.settings(context)
        if settings is None:
            return

        base = STATE.get("base")
        hover = STATE.get("hover")
        plane = STATE.get("plane") or GROUND

        # A circle is regenerated here rather than stored as baked points, so
        # changing the segment count redraws immediately instead of waiting
        # for the next mouse move to rebuild it.
        circle = STATE.get("circle")
        capsule = STATE.get("capsule")
        segments = max(3, int(getattr(settings, "circle_segments", 24)))
        if capsule is not None:
            # Unpacked by name. A "*capsule, segments" call silently fed the
            # start angle to the segment count and the count to the angle
            # the moment the tuple grew a fifth member: the capsule became a
            # triangle, and scrubbing the vertex count rotated it.
            centre_a, radius_a, centre_b, radius_b, angle = capsule
            points = capsule_in_plane(
                plane, centre_a, radius_a, centre_b, radius_b,
                segments, angle,
            )
        elif circle is not None:
            centre, radius, start_angle = circle
            points = circle_in_plane(
                plane, centre, radius, segments, start_angle,
            )
        else:
            points = list(STATE.get("points") or [])
        view_vector = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))

        # Preview curtain first: it is translucent and must not occlude the
        # markers drawn over it.
        if getattr(settings, "show_veil", False) and points:
            veil_points = points + ([hover] if hover is not None else [])
            height = getattr(settings, "veil_height", 0.64)
            alpha = getattr(settings, "veil_alpha", 0.5)
            closed = STATE.get("closed", False)
            if self.veil_inward:
                draw.draw_veil_inward(
                    veil_points, height, plane.normal, alpha=alpha,
                    closed=closed,
                    # Only consulted before the outline has a corner, to put
                    # the glow on the far side of the line being drawn.
                    view_vector=view_vector,
                )
            else:
                draw.draw_veil(
                    veil_points, height, alpha=alpha, closed=closed,
                    axis=plane.normal,
                )

        # Snap targets first, so a highlight never hides the outline it is
        # helping to place.
        preview = STATE.get("snap_preview")
        if preview is not None:
            # Unpacked by name, like the capsule below. A star-unpack here
            # would silently shift every argument the day the tuple grows.
            candidates, winner, nearness = preview
            draw.draw_snap_targets(candidates, winner, nearness)

        grid_on = (
            getattr(settings, "snap_to_grid", True)
            != bool(STATE.get("grid_suppressed"))
        )
        if base is not None and grid_on:
            # No dot field in gridless mode: dots the cursor does not land on
            # are a lie about where the point will go.
            draw.draw_plane_grid_3d(
                plane, base, STATE["cell"],
                point_size=STATE["point_size"],
            )

        guide = STATE.get("guide")
        if guide is not None:
            a, b = guide
            draw.draw_lines_3d(
                [(a.x, a.y, a.z), (b.x, b.y, b.z)],
                draw.COLOR_PREVIEW, width=2.5,
            )

        if points:
            # Close the strip when the outline is closed. Without this the
            # span from the last point back to the first is simply never
            # drawn, which on a circle -- always closed -- leaves a
            # permanent gap at the start angle. The veil already closed
            # itself, so the outline was the only thing missing a segment.
            outline = list(points)
            if STATE.get("closed") and len(outline) > 2:
                outline.append(outline[0])
            draw.draw_lines_3d(
                [(p.x, p.y, p.z) for p in outline],
                draw.COLOR_COMMITTED, width=2.5,
            )
            if hover is not None:
                draw.draw_lines_3d(
                    [
                        (points[-1].x, points[-1].y, points[-1].z),
                        (hover.x, hover.y, hover.z),
                    ],
                    draw.COLOR_PREVIEW, width=2.5,
                )

            # Z-facing ring on each placed point. The first turns green while
            # hovering it, matching the bobbing marker: both say "clicking
            # here closes the loop".
            ring = STATE["cell"] * POINT_RING_FACTOR
            closing = STATE.get("closing")
            # A generated shape rings only its real handles; ringing every
            # vertex would advertise grips that do not exist.
            explicit = STATE.get("ring_points")
            ringed = points if explicit is None else explicit
            for index, point in enumerate(ringed):
                color = (
                    COLOR_CLOSE if (closing and index == 0 and explicit is None)
                    else draw.COLOR_COMMITTED
                )
                draw.draw_circle_3d(
                    point, ring, color, width=2.0, axis=plane.normal,
                )

        if base is not None:
            # The marker stands along the drawing plane's normal, so on a
            # vertical plane it points back out at the viewer rather than
            # staying stubbornly world-up.
            axis = plane.normal
            lift = current_lift(self.marker_height)
            self.marker.draw(
                base + axis * lift,
                self.marker_height, view_vector,
                color=(
                    COLOR_SUBTRACT if STATE.get("subtract")
                    else axis_color(axis, self.marker_color)
                ),
                hollow=getattr(settings, "hollow_widget", True),
                axis=axis,
            )

    def _draw_hints(self, region):
        """The key list along the bottom, and the number being typed.

        Drawn in the same place and the same voice as the scrubber's hint
        line, because it answers the same question. A tool with this many
        holds and stages is unusable from memory alone, and a key that is
        only documented in a tooltip may as well not exist.
        """
        hint = STATE.get("hint") or self.hint
        typed = STATE.get("typed")
        if not hint and not typed:
            return

        y = HINT_Y

        if typed:
            # Above the hints and much larger: while a number is being typed
            # it is the only thing that matters on screen.
            blf.size(0, 26)
            blf.color(0, *COLOR_TYPED)
            width, _ = blf.dimensions(0, typed)
            blf.position(0, (region.width - width) * 0.5, y + 26.0, 0.0)
            blf.draw(0, typed)

        if hint:
            blf.size(0, 12)
            blf.color(0, *COLOR_HINT)
            width, _ = blf.dimensions(0, hint)
            blf.position(0, (region.width - width) * 0.5, y, 0.0)
            blf.draw(0, hint)

    def _draw_pixel(self):
        """POST_PIXEL: the label in the marker's cut-out, and the hints."""
        context = bpy.context
        region, rv3d = resolve_view(context)
        if region is None or not self._is_active(context):
            return

        settings = self.settings(context)
        if settings is None:
            return

        self._draw_hints(region)

        if self.label is None:
            return

        base = STATE.get("base")
        if base is None:
            return

        text = self.label(settings)
        if not text:
            return

        # Follow the bob, so the label stays inside the cut-out.
        plane = STATE.get("plane") or GROUND
        axis = plane.normal
        anchor = self.marker.anchor(
            base, self.marker_height, self.marker.profile_height * 0.5489,
            axis=axis,
        ) + axis * current_lift(self.marker_height)
        at = view3d_utils.location_3d_to_region_2d(region, rv3d, anchor)
        if at is None:
            return

        blf.size(0, 13)
        width, height = blf.dimensions(0, text)
        blf.position(0, at.x - width * 0.5, at.y - height * 0.5, 0.0)
        blf.color(0, 1.0, 1.0, 1.0, 0.95)
        blf.draw(0, text)

    def _animation_timer(self):
        """Drive redraws only while the close-loop bob is running.

        A draw handler cannot animate on its own -- nothing invalidates the
        region between mouse events, so the marker would freeze mid-bob. This
        ticks only while `closing` is set, leaving an idle viewport untouched.
        """
        if STATE.get("closing"):
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
        return 1.0 / BOB_FPS

    # --- lifecycle --------------------------------------------------------

    def register(self):
        self._handlers.clear()
        self._handlers.add_timer(self._animation_timer)
        self._handlers.add("view", self._draw_view, 'POST_VIEW')
        self._handlers.add("pixel", self._draw_pixel, 'POST_PIXEL')

    def unregister(self):
        self._handlers.clear()
        STATE["base"] = None
