"""Two-point circle: click the centre, click again for the radius.

Shares everything downstream with the polygon tool -- the same node group,
the same handles, the same subtract mode -- because a circle is just a
polygon whose points happen to lie on one.
"""

import math

import bpy
from mathutils import Vector

from ..core.cursor import (
    STATE,
    clear_sketch,
    set_circle,
    set_cursor,
    set_guide,
    set_plane,
    set_sketch,
    set_subtract,
)
from ..core import draw
from ..core.cursor import set_hint
from ..core.modal_base import GroundModalBase
from ..core.numeric import NumberEntry
from ..core.view import (
    GROUND,
    circle_in_plane,
    plane_angle,
    forget_view,
    mouse_to_plane,
    mouse_to_plane_grid,
    resolve_view,
    view_changed,
    viewport_cell,
)
from .config import SETTINGS_PATH
from .ops import build_floor


# The circle maths lives in core.view alongside the plane it is built in;
# re-exported here because the tool and its gizmos both reach for it.
circle_points = circle_in_plane


class MESH_OT_geodraft_circle_draw(GroundModalBase, bpy.types.Operator):
    bl_idname = "mesh.geodraft_circle_draw"
    bl_label = "Draw Circle"
    bl_description = (
        "Click for the centre, then again for the radius. Hold F to scrub "
        "the vertex count, Alt to subtract"
    )
    bl_options = {'REGISTER', 'UNDO'}

    settings_path = SETTINGS_PATH

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    # --- helpers ----------------------------------------------------------

    def _settings(self, context):
        return getattr(context.scene, SETTINGS_PATH)

    def grid_multiplier(self, context):
        return self._settings(context).grid_multiplier

    def _plane(self):
        return self.plane()

    def _snapped(self, event):
        return self.snapped(event)

    HINT_IDLE = (
        "click radius  |  type a number  |  F vertex count  |  "
        "Ctrl snap  |  Shift no grid  |  V freeze  |  X/Y/Z plane  |  "
        "Alt subtract  |  Esc cancel"
    )

    def _hint(self):
        set_hint(self.HINT_IDLE, self.typed.text or None)

    def _track_rim(self, edge):
        """Take radius and start angle from a point on the rim.

        Ignored while a number is being typed: the number is the radius
        then, and the next twitch of the mouse would otherwise erase it.
        """
        if edge is None or self.typed.active:
            return
        self.radius = (edge - self.centre).length
        if self.radius > 1e-6:
            self.start_angle = plane_angle(self._plane(), self.centre, edge)

    def _rim(self, context):
        """The point the radius currently reaches, or the centre before any."""
        if self.radius <= 1e-6:
            return self.centre
        segments = max(3, self._settings(context).circle_segments)
        return circle_in_plane(
            self._plane(), self.centre, self.radius, segments,
            self.start_angle,
        )[0]

    def plane_anchor(self):
        """The centre: the circle turns in place when the plane changes."""
        return self.centre

    def on_plane_change(self, context, event):
        # The rim was resolved in the old plane; re-derive both radius and
        # start angle in the new one, or the circle keeps a rotation that no
        # longer means anything.
        self._track_rim(self._snapped(event))

    def state_signature(self, context):
        return super().state_signature(context) + (
            self.typed.text,
            bool(self.subtract),
            round(self.radius, 6),
            round(self.start_angle, 6),
            int(self._settings(context).circle_segments),
        )

    def push_state(self, context):
        self._push(context)

    def _push(self, context):
        rim = self._rim(context)

        # Pushed as parameters, not baked points: the overlay regenerates the
        # ring every redraw, so an F+scroll segment change shows at once
        # rather than waiting for the next mouse move.
        set_circle(self.centre, self.radius, self.start_angle)
        set_sketch([], None, True, False, rings=[self.centre, rim])
        # The radius line, drawn like the wall tool's rubber band.
        set_guide(self.centre, rim if self.radius > 1e-6 else None)
        set_subtract(self.subtract)

        # The marker rides the radius point, not the centre. Both this and
        # the tool's paint cursor write the cursor position, and the rim IS
        # the snapped mouse point, so they agree instead of fighting -- which
        # is what made the marker flick between the centre and the rim.
        set_cursor(rim, self.cell)

        self._hint()
        self.redraw()

    # --- modal ------------------------------------------------------------

    def invoke(self, context, event):
        if not self.setup_view(context):
            return {'CANCELLED'}

        self.update_cell(context)
        self.radius = 0.0
        self.start_angle = 0.0
        self.typed = NumberEntry()
        self.subtract = bool(event.alt)

        self.centre = self.first_point(event, context)
        if self.centre is None:
            self.report({'WARNING'}, "Cannot place a centre here")
            return {'CANCELLED'}

        # Lock the plane for the rest of the interaction, so a surface-snapped
        # circle does not re-orient as the ray crosses onto another face.
        # Carrying the axis through keeps an X/Y toggle togglable mid-draw.
        self.remember_plane()
        set_plane(self._plane(), locked=True, axis=STATE.get("axis"))

        self._push(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        # Navigation pass-through and view-parking are the shared rule; see
        # GroundModalBase.route.
        routed = self.route(event, context)
        if routed is not None:
            return routed

        self.update_cell(context)
        self.subtract = bool(event.alt)
        self.sync(context)

        if event.type == 'ESC' and event.value == 'PRESS' and self.typed.active:
            # Escape backs out of the number first, and only cancels the
            # circle if it is pressed again with nothing typed.
            self.typed.clear()
            self._push(context)
            return {'RUNNING_MODAL'}

        if self.typed.handle(event):
            value = self.typed.value
            if value is not None:
                self.radius = abs(value)
            self._push(context)
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            self._track_rim(self._snapped(event))
            self._push(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value in {
            'PRESS', 'DOUBLE_CLICK',
        }:
            self._track_rim(self._snapped(event))
            return self._finish(context)

        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            return self._finish(context)

        if event.type == 'ESC' and event.value == 'PRESS':
            self._teardown()
            return {'CANCELLED'}

        # Right-click stays with whatever owns it (navigation addons).
        return {'PASS_THROUGH'}

    def _teardown(self):
        self.restore_plane()
        STATE["plane_locked"] = False
        clear_sketch()
        set_hint(None)
        self.release_view()
        self.redraw()

    def _finish(self, context):
        plane = self._plane()
        segments = self._settings(context).circle_segments
        radius = self.radius
        centre = self.centre
        start_angle = self.start_angle
        subtract = self.subtract
        self._teardown()

        if radius <= self.minimum_radius():
            return {'CANCELLED'}

        build_floor(
            context,
            circle_points(plane, centre, radius, segments, start_angle),
            plane,
            subtract,
            name="GeoDraftCircle",
            origin=centre,
            circle=True,
        )
        return {'FINISHED'}


classes = (MESH_OT_geodraft_circle_draw,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
