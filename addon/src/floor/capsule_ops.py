"""Four-click capsule: two circles, joined by their outer tangents.

Downstream this is a floor polygon like any other -- the hull of the two
circles is just a list of points -- so it shares the node group, the cutter
path and the subtract mode with the polygon and circle tools. Only the
gesture that produces the points is new.

The gesture reads as "circle, then circle":

  click   centre A
  click   radius A
  click   centre B
  click   radius B, and the capsule is built

Radius B starts out matching radius A rather than at zero, so the moment the
second centre is placed there is already a capsule on screen to judge --
starting from nothing would show a cone collapsing to a point, which is the
one shape the tool cannot make.
"""

import bpy

from ..core.cursor import (
    STATE,
    clear_sketch,
    set_capsule,
    set_cursor,
    set_guide,
    set_plane,
    set_sketch,
    set_subtract,
)
from ..core.cursor import set_hint
from ..core.modal_base import GroundModalBase
from ..core.numeric import NumberEntry
from bpy_extras import view3d_utils

from ..core.view import capsule_in_plane, plane_angle
from .config import CAPSULE_KEY, SETTINGS_PATH
from .ops import build_floor

# Stages, in the order they are stepped through.
RADIUS_A = 'RADIUS_A'
CENTRE_B = 'CENTRE_B'
RADIUS_B = 'RADIUS_B'


class MESH_OT_geodraft_capsule_draw(GroundModalBase, bpy.types.Operator):
    bl_idname = "mesh.geodraft_capsule_draw"
    bl_label = "Draw Capsule"
    bl_description = (
        "Click a centre and a radius, then a second centre and radius, to "
        "join two circles into a capsule. Hold F to scrub the vertex count, "
        "Alt to subtract"
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

    def _segments(self, context):
        return max(3, int(self._settings(context).circle_segments))

    HINTS = {
        RADIUS_A: (
            "click radius  |  type a number  |  F vertex count  |  "
            "Ctrl snap  |  Shift no grid  |  V freeze  |  Esc cancel"
        ),
        CENTRE_B: (
            "click the second centre  |  type a distance along the "
            "current direction  |  V freeze  |  Esc cancel"
        ),
        RADIUS_B: (
            "click the second radius  |  type a number  |  Enter to "
            "finish  |  V freeze  |  Esc cancel"
        ),
    }

    def _hint(self):
        set_hint(self.HINTS.get(self.stage), self.typed.text or None)

    def _apply_typed(self):
        """Put the typed number to work, in the way this stage means it."""
        value = self.typed.value
        if value is None:
            return
        if self.stage == RADIUS_A:
            self.radius_a = abs(value)
            self.centre_b = self.centre_a
            self.radius_b = self.radius_a
        elif self.stage == CENTRE_B:
            # Along the direction the widget was pointing when the first
            # digit landed, not the live one. Typing takes several
            # keystrokes, and a hand resting on the mouse would otherwise
            # swing the second circle around while the distance is entered.
            if self.typed_direction is not None:
                self.centre_b = (
                    self.centre_a + self.typed_direction * value
                )
        else:
            self.radius_b = abs(value)

    def _track(self, event):
        """Move whatever the current stage has attached to the pointer.

        Ignored once a number is being typed: the number owns the value
        then, and the next twitch of the mouse would erase it.
        """
        if self.typed.active:
            return
        point = self.snapped(event)
        if point is None:
            return
        if self.stage == RADIUS_A:
            self.radius_a = (point - self.centre_a).length
            if self.radius_a > 1e-6:
                # Where the drag points is where the first vertex goes, the
                # same as the circle tool. Only the preview circle can use
                # it -- once there are two circles the tangent points decide
                # where the arcs start -- but the preview *is* a circle, and
                # having it sit at a fixed rotation there while the circle
                # tool follows the drag is a difference with no reason.
                self.start_angle = plane_angle(
                    self.plane(), self.centre_a, point,
                )
            # Until the second circle is placed it shadows the first, so the
            # preview stays a plain circle rather than a lopsided capsule.
            self.centre_b = self.centre_a
            self.radius_b = self.radius_a
        elif self.stage == CENTRE_B:
            self.centre_b = point
        else:
            self.radius_b = (point - self.centre_b).length
        self.tracked = point

    def _warp_to_rim(self, context):
        """Put the mouse on the rim the preview is already showing.

        The second radius is the distance from its own centre to the cursor.
        That mapping needs no explaining, because the rim is under the
        pointer. It fails at exactly one moment: the pointer is standing on
        the centre it has just placed, the distance is zero, and a
        full-sized end collapses to nothing.

        Moving the mouse fixes that, rather than bending the mapping. The
        pointer goes to where the rim already is, so the size carries
        through the click unchanged, and a second click confirms it at once.
        Blender warps the cursor itself during a transform, so this is not a
        new thing for the user's hand.

        The rim is taken outward along the centre line. That is the
        direction the capsule grows in, and it keeps the pointer clear of
        the first circle. A plane tangent stands in when the two centres are
        at the same place.
        """
        axis = self.centre_b - self.centre_a
        plane = self.plane()
        if axis.length <= 1e-9:
            axis = plane.tangent.copy()
        rim = self.centre_b + axis.normalized() * self.radius_b

        at = view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, rim)
        if at is None or not (
            0.0 <= at.x <= self.region.width
            and 0.0 <= at.y <= self.region.height
        ):
            # The rim is behind the camera or outside this region. Warping
            # there would throw the mouse out of the viewport, which is far
            # worse than the collapse it is meant to prevent, so the radius
            # simply follows the cursor from wherever it lands.
            return
        context.window.cursor_warp(
            int(self.region.x + at.x), int(self.region.y + at.y),
        )
        self.tracked = rim

    def plane_anchor(self):
        """Centre A: the shape turns about the end that is already fixed."""
        return self.centre_a

    def on_plane_change(self, context, event):
        # Every distance was measured in the old plane's grid; re-take the
        # live one so the shape follows the pointer onto the new one.
        self._track(event)

    def state_signature(self, context):
        return super().state_signature(context) + (
            bool(self.subtract),
            round(self.radius_a, 6),
            round(self.radius_b, 6),
            round(self.start_angle, 6),
            self.typed.text,
            self.stage,
            self._segments(context),
        )

    def push_state(self, context):
        set_capsule(
            self.centre_a, self.radius_a, self.centre_b, self.radius_b,
            self.start_angle,
        )
        # Rings mark the two centres, not every generated vertex.
        set_sketch([], None, True, False, rings=[self.centre_a, self.centre_b])
        # The construction line reads as "this radius", and while the second
        # centre is being placed, as "this far apart".
        set_guide(
            self.centre_a if self.stage != RADIUS_B else self.centre_b,
            self.tracked,
        )
        set_subtract(self.subtract)

        # The marker rides the point being dragged, which is also the point
        # the pointer resolved to, so it and the tool's paint cursor agree.
        set_cursor(self.tracked, self.cell)
        self._hint()
        self.redraw()

    # --- modal ------------------------------------------------------------

    def invoke(self, context, event):
        if not self.setup_view(context):
            return {'CANCELLED'}

        self.update_cell(context)
        self.stage = RADIUS_A
        self.radius_a = 0.0
        self.radius_b = 0.0
        self.start_angle = 0.0
        self.typed = NumberEntry()
        self.typed_direction = None
        self.subtract = bool(event.alt)

        self.centre_a = self.first_point(event, context)
        if self.centre_a is None:
            self.report({'WARNING'}, "Cannot place a centre here")
            return {'CANCELLED'}
        self.centre_b = self.centre_a
        self.tracked = self.centre_a

        # Lock the plane for the rest of the interaction, exactly as the
        # circle does: a surface-snapped capsule must not re-orient halfway
        # through, or the two circles end up on different planes.
        self.remember_plane()
        set_plane(self.plane(), locked=True, axis=STATE.get("axis"))

        self.push_state(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        routed = self.route(event, context)
        if routed is not None:
            return routed

        self.update_cell(context)
        self.subtract = bool(event.alt)
        self.sync(context)

        if event.type == 'ESC' and event.value == 'PRESS' and self.typed.active:
            # Escape drops the number first. A second press cancels the
            # capsule, so backing out of a typo does not lose the shape.
            self.typed.clear()
            self.typed_direction = None
            self.push_state(context)
            return {'RUNNING_MODAL'}

        if not self.typed.active and self.stage == CENTRE_B:
            # Lock the direction before the first digit is consumed, while
            # the widget is still where the user was looking when they
            # decided to type.
            offset = self.tracked - self.centre_a
            self.typed_direction = (
                offset.normalized() if offset.length > 1e-9 else None
            )

        if self.typed.handle(event):
            self._apply_typed()
            self.push_state(context)
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            self._track(event)
            self.push_state(context)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value in {
            'PRESS', 'DOUBLE_CLICK',
        }:
            self._track(event)
            # A typed value is committed by the click that follows it, so
            # the buffer starts empty for the next stage.
            self.typed.clear()
            self.typed_direction = None
            if self.stage == RADIUS_A:
                if self.radius_a <= self.minimum_radius():
                    # A click that never dragged. Keep waiting for a radius
                    # rather than advancing to a stage the build would then
                    # reject. Gridless, almost nothing is too small.
                    return {'RUNNING_MODAL'}
                self.stage = CENTRE_B
            elif self.stage == CENTRE_B:
                self.stage = RADIUS_B
                # The pointer stands on the centre it just placed, so move
                # it out to the rim the preview is showing.
                self._warp_to_rim(context)
            else:
                return self._finish(context)
            self.push_state(context)
            return {'RUNNING_MODAL'}

        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            # Enter takes the shape as it stands, so a capsule with two equal
            # ends does not need the fourth click.
            if self.stage == RADIUS_A:
                return self._cancel()
            return self._finish(context)

        if event.type == 'ESC' and event.value == 'PRESS':
            return self._cancel()

        # Right-click stays with whatever owns it (navigation addons).
        return {'PASS_THROUGH'}

    def _teardown(self):
        self.restore_plane()
        STATE["plane_locked"] = False
        clear_sketch()
        set_guide(None, None)
        set_hint(None)
        self.release_view()
        self.redraw()

    def _cancel(self):
        self._teardown()
        return {'CANCELLED'}

    def _finish(self, context):
        plane = self.plane()
        points = capsule_in_plane(
            plane, self.centre_a, self.radius_a,
            self.centre_b, self.radius_b, self._segments(context),
            self.start_angle,
        )
        radius = max(self.radius_a, self.radius_b)
        centre = self.centre_a
        subtract = self.subtract

        if radius <= self.minimum_radius():
            return self._cancel()

        # Built before teardown: build_floor reads the drawing plane off the
        # shared state, which teardown puts back.
        obj = build_floor(
            context, points, plane, subtract,
            name="GeoDraftCapsule", origin=centre,
        )
        if obj is not None:
            # None when a destructive cut consumed the cutter; there is no
            # object left to mark.
            obj[CAPSULE_KEY] = True
        self._teardown()
        return {'FINISHED'}


classes = (MESH_OT_geodraft_capsule_draw,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
