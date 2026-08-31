"""Hold Alt to see, before drawing anything, that the next shape will cut.

The draw modal already reads `event.alt` on every event, so Alt has always
worked *while* drawing. What it could not do is show anything beforehand:
until the first click there is no modal, and the paint cursor receives no
events at all -- only a mouse position -- so a held key is invisible to it.

Binding Alt down and up in the tool keymap gives the idle cursor the same
state the modal would have had, so the marker turns red and reads "-" before
the first point goes down rather than after it. The modal keeps reading
`event.alt` for itself; this only covers the gap before one exists.

Both Alt keys are bound: Blender reports them as distinct events, and a user
who holds the right one means the same thing.
"""

import bpy

from .cursor import STATE, set_subtract
from .placement import refresh_cursor


class VIEW3D_OT_subtract_hold(bpy.types.Operator):
    """Show that the next shape drawn will subtract."""

    bl_idname = "view3d.geodraft_subtract_hold"
    bl_label = "Subtract Preview"
    bl_options = {'INTERNAL'}

    pressed: bpy.props.BoolProperty(default=True)
    settings_path: bpy.props.StringProperty(default="")

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        if STATE.get("subtract") != self.pressed:
            set_subtract(self.pressed)
            # Repaint now: nothing else will, because the mouse has not moved
            # and a held key generates no further events.
            refresh_cursor(context, self.settings_path, event)
        # PASS_THROUGH, not FINISHED: Alt is a modifier, and swallowing it
        # would break every Alt-combination the user has bound underneath --
        # the alt-middle-mouse overlays, alt-click, and so on.
        return {'PASS_THROUGH'}


def keymap_entries(settings_path):
    """Keymap tuples binding both Alt keys, down and up, for a tool."""
    return tuple(
        (
            VIEW3D_OT_subtract_hold.bl_idname,
            # "any": True, so a release while another modifier is down still
            # registers. An unspecified modifier means "must NOT be held".
            {"type": key, "value": value, "any": True},
            {"properties": [
                ("pressed", value == 'PRESS'),
                ("settings_path", settings_path),
            ]},
        )
        for key in ('LEFT_ALT', 'RIGHT_ALT')
        for value in ('PRESS', 'RELEASE')
    )


def register():
    bpy.utils.register_class(VIEW3D_OT_subtract_hold)


def unregister():
    bpy.utils.unregister_class(VIEW3D_OT_subtract_hold)
