"""Modal polyline drawing on the ground grid.

Generic over what gets built: subclass, implement `grid_multiplier` and
`build`, and you get the whole interaction -- press/drag/release placement,
grid snapping, loop closing, navigation parking, and the shared overlay
state the tool's draw handler consumes.

State machine modelled on relay's sketch pipeline (click commits a point,
mouse-move previews a rubber band) plus QOL PolyPal's press/drag/release
placement. See ../../../doc/research_addon_patterns.md.

Semantics:
  invoke   the tool keymap fires the operator ON a LEFTMOUSE PRESS, so that
           press IS the first point and must be committed here. Waiting for
           the next event swallows the first click and nothing ever starts.
  PRESS    commits another point, or closes the loop on the first point
  RELEASE  commits only past a drag threshold, so press-drag-release places
           a segment and plain click-click also works
  MOVE     updates the snapped hover point
  DBLCLICK finish
  RET      finish
  ESC      always cancels

Right-click is deliberately NOT bound. It is passed straight through so a
right-mouse navigation addon keeps working while drawing, which is a common
setup and impossible to use if the modal swallows the button. Tools that
want the old behaviour can set `finish_on_right_click = True`.
"""

from mathutils import Vector

from . import draw
from .modal_base import GroundModalBase
from .cursor import (
    STATE,
    set_hint,
    clear_sketch,
    set_cursor,
    set_plane,
    set_sketch,
    set_subtract,
)
from .view import (
    GROUND,
    forget_view,
    mouse_to_plane,
    mouse_to_plane_grid,
    resolve_view,
    view_changed,
    viewport_cell,
)

DRAG_THRESHOLD_PIXELS = 4.0

# Fraction of a grid cell within which the first point accepts a closing
# click. Shared with whatever draws the ring, so the hit test and the visible
# disk cannot disagree.
POINT_RING_FACTOR = 0.5 * 0.75


class PolylineDrawBase(GroundModalBase):
    """Mix into a bpy.types.Operator alongside the usual bl_ idents."""

    ring_factor = POINT_RING_FACTOR
    drag_threshold = DRAG_THRESHOLD_PIXELS

    # Off by default so right-mouse navigation addons keep working mid-draw.
    finish_on_right_click = False

    # When True, holding Alt marks the polyline as subtractive and build()
    # receives subtract=True. Tools that have no subtractive form ignore it.
    supports_subtract = False

    # --- subclass hooks ---------------------------------------------------

    def grid_multiplier(self, context):
        """Multiplier applied to the viewport's grid scale."""
        return 1.0

    def build(self, context, points, closed, subtract=False):
        """Create whatever the polyline represents. Return the object."""
        raise NotImplementedError

    # --- helpers ----------------------------------------------------------

    def _hover(self, context, event):
        return self.snapped(event)

    def _near_first_point(self, event):
        """True when the cursor is inside the first point's ring.

        Tested in world space against the *unsnapped* ground position, so
        eligibility matches the disk drawn on screen. Testing the snapped
        hover would be useless: it and the point both lie on grid
        intersections, so the distance is either zero or a whole cell --
        no disk, only an exact hit.
        """
        if len(self.points) < 3:
            return False
        ground = self.unsnapped(event)
        if ground is None:
            return False
        return (ground - self.points[0]).length <= self.cell * self.ring_factor

    def _commit(self, point):
        """Append a point, ignoring an exact repeat of the last one."""
        if point is None:
            return
        if self.points and (self.points[-1] - point).length < 1e-6:
            return
        self.points.append(point.copy())

    def _redraw(self):
        self.redraw()

    # --- switching the plane mid-draw -------------------------------------

    def plane_anchor(self):
        """The last committed point, so the plane turns about the free end.

        The *last* rather than the first: pressing X after a run of points
        should stand a wall up from where the outline currently is, and
        pivoting about the start would leave the new plane nowhere near it.
        With a single point placed the two are the same thing anyway.
        """
        return self.points[-1] if self.points else None

    def on_plane_change(self, context, event):
        self.hover = self._hover(context, event)
        # The first point's disk is measured in the old plane; re-test it
        # rather than leaving a stale green ring saying a click would close.
        self.closing = self._near_first_point(event)

    def state_signature(self, context):
        return super().state_signature(context) + (
            bool(self.subtract), bool(self.closing), len(self.points),
        )

    def push_state(self, context):
        self._push_state(context)

    def _push_state(self, context):
        """Feed the shared cursor state; the tool's handler does the drawing.

        This operator deliberately owns no draw handler. It used to, and the
        result was two widgets at once: the tool's paint cursor kept drawing
        the 3D marker while this drew a second 2D one.
        """
        if self.hover is not None:
            cell_px = draw.cell_pixels(
                self.region, self.rv3d, self.hover, self.cell,
            )
            if cell_px:
                self.point_size = max(2.0, min(64.0, cell_px / 8.0))

        set_cursor(self.hover, self.cell, self.point_size)
        set_sketch(self.points, self.hover, self.closed, self.closing)
        set_subtract(self.subtract)
        set_hint(
            "click the first point to close  |  Enter finishes  |  "
            "Ctrl snap  |  Shift no grid  |  V freeze  |  X/Y/Z plane  |  "
            "Esc cancel"
            if len(self.points) > 2 else
            "click to place the next point  |  Enter finishes  |  "
            "Ctrl snap  |  Shift no grid  |  V freeze  |  X/Y/Z plane  |  "
            "Esc cancel"
        )

    # --- modal ------------------------------------------------------------

    def invoke(self, context, event):
        self.points = []
        self.closed = False
        self.closing = False
        self.point_size = 8.0
        self.press_pos = None
        # Whatever Alt state is held when the polyline ends decides the mode,
        # so it can be reconsidered mid-draw rather than fixed at the first
        # click.
        self.subtract = self.supports_subtract and event.alt

        if not self.setup_view(context):
            return {'CANCELLED'}
        self.update_cell(context)

        # Lock whatever plane the cursor had resolved when drawing started.
        # Without this a surface-snapped polyline would re-orient every time
        # the ray crossed onto a differently-angled face, and the points
        # already placed would no longer lie in the plane being drawn on.
        # Carry the axis through: this re-lock would otherwise clear it, and
        # pressing X mid-draw would then toggle the plane it is already on
        # back *on* instead of off.
        self.remember_plane()
        set_plane(
            STATE.get("plane") or GROUND, locked=True, axis=STATE.get("axis"),
        )

        self.hover = self.first_point(event, context)
        if self.hover is None:
            self.report({'WARNING'}, "Cannot place a point on the ground here")
            return {'CANCELLED'}

        # The press that launched this operator is the first point.
        self._commit(self.hover)
        self.press_pos = Vector((event.mouse_region_x, event.mouse_region_y))

        self._push_state(context)
        context.window_manager.modal_handler_add(self)
        self._redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        # Navigation pass-through and view-parking are the shared rule; see
        # GroundModalBase.route.
        routed = self.route(event, context)
        if routed is not None:
            return routed

        self.update_cell(context)
        if self.supports_subtract:
            self.subtract = event.alt

        # Any tracked change -- Alt going down, the grid step changing --
        # repaints here, without waiting for motion.
        self.sync(context)

        if event.type == 'MOUSEMOVE':
            self.hover = self._hover(context, event)
            self.closing = self._near_first_point(event)
            self._push_state(context)
            self._redraw()
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if self._near_first_point(event):
                self.closed = True
                return self._finish(context)
            self.hover = self._hover(context, event)
            self._commit(self.hover)
            self.press_pos = Vector(
                (event.mouse_region_x, event.mouse_region_y)
            )
            self._push_state(context)
            self._redraw()
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            # Only a genuine drag places a point here; a plain click already
            # placed its point on PRESS.
            if self.press_pos is not None:
                cursor = Vector(
                    (event.mouse_region_x, event.mouse_region_y)
                )
                if (cursor - self.press_pos).length > self.drag_threshold:
                    self.hover = self._hover(context, event)
                    self._commit(self.hover)
            self.press_pos = None
            self._push_state(context)
            self._redraw()
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'DOUBLE_CLICK':
            # The first click of the pair already committed its point on
            # PRESS; this only ends the polyline.
            return self._finish(context)

        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            return self._finish(context)

        if event.type == 'RIGHTMOUSE':
            if not self.finish_on_right_click:
                # Hand it to whatever owns right-click (navigation addons)
                # rather than ending the polyline.
                return {'PASS_THROUGH'}
            if event.value == 'PRESS':
                if len(self.points) >= 2:
                    return self._finish(context)
                return self._cancel()
            return {'RUNNING_MODAL'}

        if event.type == 'ESC' and event.value == 'PRESS':
            return self._cancel()

        return {'RUNNING_MODAL'}

    def _teardown(self):
        self.restore_plane()
        STATE["plane_locked"] = False
        clear_sketch()
        self.release_view()
        self._redraw()

    def _finish(self, context):
        # Build first, tear down after: build() reads the drawing plane off
        # the shared state, and teardown puts back whatever plane was in
        # force before the modal started.
        if len(self.points) < 2:
            self._teardown()
            return {'CANCELLED'}
        self.build(context, self.points, self.closed, self.subtract)
        self._teardown()
        return {'FINISHED'}

    def _cancel(self):
        self._teardown()
        return {'CANCELLED'}

    def cancel(self, context):
        # Called when Blender aborts the modal for us (window close, etc).
        self._teardown()
