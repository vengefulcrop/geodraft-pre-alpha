"""V parks every world-space widget so the view can be moved around them.

A drawing plane is a plane in a 3D scene, and one view of it is often not
enough to be sure of what is about to be built. Orbiting to check normally
destroys the thing being checked: the cursor keeps resolving against the
plane, so the marker and the rubber band walk away while the camera moves.

What is frozen is a *world* point, not a screen position. The scrubber's
pointer freeze pins a region coordinate, which is right for a scrubber --
the view does not move while a number is dragged. It is wrong here. The
same screen position resolves to a different world point after every orbit,
so a pinned cursor walked across the scene exactly when the freeze was
being used for the one thing it is for.

Everything that resolves a position asks for the frozen point first: the
paint cursor, and every modal, through snapped() and unsnapped(). What
stays available is what never asked in the first place -- a click and Enter
still confirm, Escape still cancels, and F still scrubs the vertex count.

A toggle rather than a hold: the point is to let go of the mouse and orbit,
which is not something a hand can do while holding a key down.
"""

import bpy

from .cursor import STATE, freeze_widgets, widgets_frozen
from .placement import refresh_cursor


class VIEW3D_OT_widget_freeze_toggle(bpy.types.Operator):
    """Hold every widget in place so the view can be moved around them."""

    bl_idname = "view3d.geodraft_widget_freeze_toggle"
    bl_label = "Freeze Widgets"
    bl_description = (
        "Hold the placement widgets at their current position so the view "
        "can be orbited around them. Press again to release"
    )
    bl_options = {'INTERNAL'}

    settings_path: bpy.props.StringProperty(default="")

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        if widgets_frozen():
            freeze_widgets(None)
            self.report({'INFO'}, "Widgets released")
        elif STATE.get("base") is None:
            # Nothing resolved yet, so there is no position to hold.
            self.report({'WARNING'}, "Nothing to freeze here")
            return {'CANCELLED'}
        else:
            freeze_widgets(STATE.get("base"))
            self.report({'INFO'}, "Widgets frozen -- V to release")

        refresh_cursor(context, self.settings_path)
        return {'FINISHED'}


def keymap_entries(settings_path):
    """Keymap tuple binding V for a tool's bl_keymap."""
    return (
        (
            VIEW3D_OT_widget_freeze_toggle.bl_idname,
            {"type": 'V', "value": 'PRESS'},
            {"properties": [("settings_path", settings_path)]},
        ),
    )


def register():
    bpy.utils.register_class(VIEW3D_OT_widget_freeze_toggle)


def unregister():
    bpy.utils.unregister_class(VIEW3D_OT_widget_freeze_toggle)
