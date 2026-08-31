"""X and Y toggle the drawing plane to that world axis; Z restores default.

The plane is pinned at the grid point the cursor was already on, so the
override rotates the drawing surface *about the point you were pointing at*
rather than jumping somewhere else.

These were holds. Holding is the wrong shape for the gesture: drawing a
vertical outline means clicking several points on that plane, and holding a
key throughout while also clicking is a hand position, not an interaction.
As a toggle, X sets the plane and X again clears it, and pressing the other
axis switches rather than stacking.

Z exists because a toggle can be forgotten in a way a hold cannot: it always
restores the ground plane, whatever the current state, so there is one key
that means "back to normal" and it never has to be reasoned about. It does
not toggle a Z-facing plane of its own -- that would give the failsafe a
second state and defeat the point.

A toggle also removes the modal. The hold needed one because the paint
cursor receives no events, only a mouse position, so a key-held state could
be observed nowhere else. A press is just an operator.
"""

import bpy
from mathutils import Vector

from .cursor import STATE, reset_plane, set_plane
from .placement import refresh_cursor
from .view import axis_plane, resolve_view


class VIEW3D_OT_axis_plane_toggle(bpy.types.Operator):
    """Toggle the drawing plane onto a world axis, or back to the ground."""

    bl_idname = "view3d.geodraft_axis_plane_toggle"
    bl_label = "Axis Drawing Plane"
    bl_description = (
        "Draw on a plane facing this world axis, pinned at the current grid "
        "point. Press again to return to the ground plane"
    )
    bl_options = {'INTERNAL'}

    axis: bpy.props.EnumProperty(
        name="Axis",
        items=(('X', "X", ""), ('Y', "Y", ""), ('Z', "Z", "")),
        default='X',
    )
    settings_path: bpy.props.StringProperty(default="")

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        region, rv3d = resolve_view(context)
        if region is None:
            return {'CANCELLED'}

        # Z is the failsafe and always clears; X and Y clear only when they
        # are the axis already in force, so pressing the other one switches.
        if self.axis == 'Z' or STATE.get("axis") == self.axis:
            reset_plane()
            label = "ground"
        else:
            # Pin the new plane where the cursor already was. Falling back to
            # the world origin only matters when the tool has never had a
            # valid hit.
            anchor = STATE.get("base") or Vector((0.0, 0.0, 0.0))
            view_vector = rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))
            set_plane(
                axis_plane(self.axis, anchor, view_vector),
                locked=True, axis=self.axis,
            )
            label = self.axis

        # Re-project onto the new plane straight away. The paint cursor only
        # recomputes when the pointer actually moves, so without this the
        # marker hangs at its old height until the mouse is nudged.
        refresh_cursor(context, self.settings_path, event)
        self.report({'INFO'}, "Drawing plane: {}".format(label))
        return {'FINISHED'}


# Modifier states Z is bound under. "any" would be shorter and would take
# Ctrl+Z with it, and undo is not ours to shadow. A keymap item cannot say
# "any modifier except Ctrl", so the combinations are spelled out: Z alone
# and with Shift or Alt stay the plane toggle, Ctrl+Z and Ctrl+Shift+Z stay
# undo and redo.
_Z_MODIFIERS = (
    {},
    {"shift": True},
    {"alt": True},
    {"shift": True, "alt": True},
)


def keymap_entries(settings_path):
    """Keymap tuples binding X, Y and Z for a tool's bl_keymap.

    Z shadows Blender's shading pie while the tool is active, the same trade
    the N binding makes against the sidebar.

    X and Y take "any", so the plane can still be turned while a snapping
    hold is down -- without it, Ctrl+X matches nothing and the key reads as
    dead exactly when a user is mid-gesture. Z cannot afford "any"; see
    _Z_MODIFIERS.
    """
    def entry(axis, event):
        return (
            VIEW3D_OT_axis_plane_toggle.bl_idname,
            dict({"type": axis, "value": 'PRESS'}, **event),
            {"properties": [
                ("axis", axis), ("settings_path", settings_path),
            ]},
        )

    return tuple(
        entry(axis, {"any": True}) for axis in ('X', 'Y')
    ) + tuple(
        entry('Z', modifiers) for modifiers in _Z_MODIFIERS
    )


def register():
    bpy.utils.register_class(VIEW3D_OT_axis_plane_toggle)


def unregister():
    bpy.utils.unregister_class(VIEW3D_OT_axis_plane_toggle)
