"""Shared rules for every tool that draws on the drawing plane.

Each drawing tool used to re-implement the same handful of behaviours --
resolve the region, recompute the grid cell, pass navigation through, park
while the view moves, snap to the plane, release the view slot on teardown.
Re-implementing them is how they drift: a tool that forgets one of these
behaves subtly differently from its neighbours, and the difference is
invisible in review because each modal reads fine on its own.

Mix this in and use `route()` as the first thing in modal(), and a new tool
inherits the whole ruleset rather than remembering it.
"""

from mathutils import Vector

from .cursor import (
    STATE, pointer_coord, release_pointer_on_move, reset_plane, set_plane,
)
from .element_snap import element_snap
from .view import (
    GROUND,
    axis_plane,
    forget_view,
    navigation_running,
    mouse_to_plane,
    mouse_to_plane_grid,
    resolve_view,
    view_changed,
    viewport_cell,
)


class GroundModalBase:
    """Common plumbing for a modal that draws on STATE's current plane."""

    # Scene property group this tool reads. Set by each operator; the base
    # only needs it for settings every drawing tool shares.
    settings_path = None

    # Events handed straight back to Blender so navigation keeps working.
    # Right-click is deliberately absent: it is passed through further down
    # by each tool so right-mouse navigation addons keep working mid-draw.
    NAVIGATION_EVENTS = {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}

    # Mid-draw drawing-plane switch: X, Y and Z re-orient the plane about
    # the point already placed, so a vertical run can be started from the
    # end of a horizontal one without leaving the tool.
    AXIS_KEYS = {'X', 'Y', 'Z'}

    # Slot for this modal's view-change history. Separate from the paint
    # cursor's, so the two do not consume each other's transitions.
    nav_slot = "modal"

    # --- setup / teardown -------------------------------------------------

    def setup_view(self, context):
        """Resolve region and rv3d. False when there is no 3D viewport."""
        self.region, self.rv3d = resolve_view(context)
        return self.region is not None

    def release_view(self):
        forget_view(self.nav_slot)

    # --- the drawing plane ------------------------------------------------

    def plane(self):
        return STATE.get("plane") or GROUND

    def grid_multiplier(self, context):
        """Override to point at the tool's own settings."""
        return 1.0

    def tool_settings(self, context):
        if not self.settings_path:
            return None
        return getattr(context.scene, self.settings_path, None)

    def grid_snapping(self, context):
        """False in gridless mode, where the pointer is taken as it lands.

        The Shift hold inverts the setting rather than clearing it, so the
        key means the same thing whichever way the setting is left.
        """
        setting = bool(getattr(
            self.tool_settings(context), "snap_to_grid", True,
        ))
        return setting != bool(STATE.get("grid_suppressed"))

    def update_cell(self, context):
        self.cell = viewport_cell(context, self.grid_multiplier(context))
        # Kept separate from the cell rather than folded into it as a zero.
        # The cell still sizes the dot field and the closing ring, which are
        # measures of scale rather than of snapping, and zeroing it would
        # shrink the ring to nothing and make a loop impossible to close.
        self.snap_grid = self.grid_snapping(context)
        return self.cell

    def pointer(self, event):
        """Where the tool should consider the pointer to be.

        Normally the mouse. While something has frozen the pointer -- the
        value scrubber borrows the mouse to drag a number -- it is wherever
        the marker was parked, so a click landing during the borrow places a
        point where the user can see the marker rather than where the mouse
        has since been dragged to.

        event.mouse_region_x/y is already region-relative -- unlike a
        paint-cursor xy, it must NOT go through region_coord().
        """
        return pointer_coord((event.mouse_region_x, event.mouse_region_y))

    def element_snapped(self, context, event):
        """A geometry snap under the pointer, brought onto the plane.

        Takes precedence over the grid: the magnet is an explicit request
        for *that* point, and a grid quantisation applied afterwards would
        move the cursor straight back off it.
        """
        if context is None:
            # Every call site is inside a modal, where bpy.context is the
            # same context the caller would have passed. Defaulting here
            # keeps the snap from having to be threaded through helpers that
            # only ever wanted an event.
            import bpy
            context = bpy.context
        point, _normal = element_snap(
            context, self.region, self.rv3d, self.pointer(event),
        )
        return self.plane().project(point)

    def frozen_point(self):
        """The world point the widgets are pinned to, or None."""
        return STATE.get("widget_freeze")

    def snapped(self, event, context=None):
        """Pointer position on the plane, snapped to the grid.

        In gridless mode the grid step is passed as zero, which Plane.snap
        already reads as "take the point as it is".
        """
        frozen = self.frozen_point()
        if frozen is not None:
            return frozen

        snapped = self.element_snapped(context, event)
        if snapped is not None:
            return snapped
        return mouse_to_plane_grid(
            self.region, self.rv3d, self.pointer(event), self.plane(),
            self.cell if getattr(self, "snap_grid", True) else 0.0,
        )

    def first_point(self, event, context=None):
        """The point a tool starts from, with a stuck plane as a failsafe.

        A modal that ends abnormally -- an exception, a window closing
        mid-draw -- can leave the drawing plane locked to a surface that is
        no longer under the cursor, or edge-on to the view. Nothing clears
        it, so every tool then refuses to start with "cannot place a point
        here" for the rest of the session, and the only cure is a restart.

        Since a locked plane with no modal running is meaningless anyway,
        the failure is worth one retry on the ground rather than a dead
        tool. Only invoke should use this: mid-draw the lock is real and a
        miss means the pointer is genuinely off the plane.
        """
        point = self.snapped(event, context)
        if point is None and STATE.get("plane_locked"):
            reset_plane()
            point = self.snapped(event, context)
        return point

    def unsnapped(self, event):
        """Pointer position on the plane, without grid quantisation."""
        frozen = self.frozen_point()
        if frozen is not None:
            return frozen
        return mouse_to_plane(
            self.region, self.rv3d, self.pointer(event), self.plane(),
        )

    # --- switching the plane mid-draw ------------------------------------

    def remember_plane(self):
        """Snapshot the plane the modal started on. Call from invoke().

        A mid-draw switch is scoped to the shape being drawn: it exists so a
        wall can turn a corner upward, not to change what the tool does next.
        Without a snapshot the axis it set outlives the modal, and the next
        idle press of that key reads as "already on this axis" and toggles
        the plane off instead of on.
        """
        self._entry_plane = (STATE.get("plane"), STATE.get("axis"))

    def restore_plane(self):
        """Undo a mid-draw switch. Call from teardown, before unlocking.

        Restores rather than resets, so an X toggle made *before* drawing
        began still stands afterwards.
        """
        plane, axis = getattr(self, "_entry_plane", (None, None))
        if plane is not None:
            set_plane(plane, locked=False, axis=axis)

    def plane_anchor(self):
        """The point a mid-draw plane switch pivots about.

        None means the tool has nothing placed yet and the key does nothing:
        without a committed point there is no "here" to rotate about, and
        the idle keymap already owns X/Y/Z for that case.
        """
        return None

    def on_plane_change(self, context, event):
        """Re-resolve whatever the tool tracks under the pointer. Override.

        The plane moved out from under the live point, so hover positions,
        radii and the like are stale until the tool recomputes them.
        """

    def switch_plane(self, context, event, axis):
        """Re-anchor the drawing plane on `axis` through the placed point.

        The anchor is what makes this usable rather than merely correct: the
        plane passes *through* the point already placed, so the next segment
        continues from where the last one ended instead of the outline
        jumping to wherever the world-axis plane happens to sit. It also puts
        the grid origin on that point, so it stays exactly clickable.

        Z is a real plane here, not the idle toggle's escape hatch -- mid-draw
        "back to horizontal" means horizontal *at this height*, and resetting
        to the world ground would strand the outline metres below itself.
        """
        anchor = self.plane_anchor()
        if anchor is None:
            return False

        # Face the plane toward the camera so the marker points back at the
        # viewer, matching the idle toggle.
        view_vector = self.rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
        set_plane(
            axis_plane(axis, anchor, view_vector), locked=True, axis=axis,
        )
        self.on_plane_change(context, event)
        self.push_state(context)
        self.redraw()
        return True

    def minimum_radius(self):
        """Below this, a radius counts as a click that never dragged.

        A quarter of a grid cell while the grid is on: with snapping, the
        smallest radius a user can actually express is one whole cell, so
        anything under a quarter of one is a click that went nowhere.

        Gridless, there is no such floor. Every size between zero and a cell
        is expressible and asking for one is the point of the mode, so the
        test drops to "did the cursor move at all". Keeping the cell-based
        figure there would silently refuse the small shapes the mode exists
        to draw.
        """
        if not getattr(self, "snap_grid", True):
            return 1e-6
        return getattr(self, "cell", 0.0) * 0.25

    def redraw(self):
        if getattr(self, "region", None) is not None:
            self.region.tag_redraw()

    # --- the shared rule --------------------------------------------------

    def navigating(self, context=None):
        """True while the view is moving under this modal.

        Two independent signals, because either alone misses cases: the view
        data changing between frames, and a navigation modal being live.
        Walk and fly report the second without the first.
        """
        if context is not None and navigation_running(context):
            # Still sample the view so its history stays current.
            view_changed(self.rv3d, self.nav_slot)
            return True
        return view_changed(self.rv3d, self.nav_slot)

    # --- state changes repaint immediately -------------------------------

    def state_signature(self, context):
        """Everything whose change should be visible at once.

        Override and extend. Anything included here repaints the moment it
        changes, rather than on the next mouse move.
        """
        plane = self.plane()
        return (
            round(getattr(self, "cell", 0.0), 6),
            bool(getattr(self, "snap_grid", True)),
            bool(STATE.get("snap_forced")),
            tuple(round(v, 6) for v in plane.normal),
            tuple(round(v, 6) for v in plane.origin),
        )

    def push_state(self, context):
        """Publish this modal's state to the overlay. Override."""

    def sync(self, context):
        """Repaint if any tracked state changed since the last event.

        Modifier keys are the reason this exists. Pressing Alt sends an
        event, but nothing in a mouse-driven flow reacts to it, so the
        subtract marker only appeared once the mouse happened to move --
        the state had already changed and the screen had not caught up.
        Comparing a signature every event catches modifier presses, keymap
        operators and anything else that changes state without motion.
        """
        signature = self.state_signature(context)
        if signature != getattr(self, "_state_signature", None):
            self._state_signature = signature
            self.push_state(context)
            self.redraw()
            return True
        return False

    def route(self, event, context=None):
        """Handle the behaviours every drawing tool shares.

        Returns a modal result to return immediately, or None to carry on.
        Call it first in modal(), before any tool-specific handling.

        Three rules live here:

        - Navigation events pass through, so orbit/pan/zoom keep working
          mid-draw.
        - While the view is moving, the tool freezes instead of tracking.
          The mouse is steering the camera, not placing geometry, so a live
          point would skate across the plane as the view swings.
        - X, Y and Z re-anchor the drawing plane about the point already
          placed, once the tool has one. See switch_plane.
        """
        if event.type in self.NAVIGATION_EVENTS:
            return {'PASS_THROUGH'}

        if event.type == 'MOUSEMOVE':
            # A real move is what ends a pointer freeze left pending by a
            # scrub; until then the marker -- and any click -- stays put.
            release_pointer_on_move()

        if event.type == 'MOUSEMOVE' and self.navigating(context):
            self.redraw()
            return {'RUNNING_MODAL'}

        # Ctrl and Shift are read straight off the event while a modal owns
        # the mouse. The keymap holds only cover the idle cursor, and their
        # PRESS never arrives once a modal is running.
        STATE["snap_forced"] = bool(event.ctrl)
        STATE["grid_suppressed"] = bool(event.shift)

        if event.type in self.AXIS_KEYS and event.value == 'PRESS':
            if self.switch_plane(context, event, event.type):
                return {'RUNNING_MODAL'}

        return None
