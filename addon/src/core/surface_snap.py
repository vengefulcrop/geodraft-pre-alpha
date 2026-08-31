"""Toggle: orient the drawing plane to the surface under the cursor.

With it on, the view ray is cast into the scene and the marker stands on
whatever it hits, along that surface's normal -- so pointing at a wall makes
the marker lie against the wall, pointing at a ramp tilts it to the ramp.
With it off, drawing stays on the world ground plane.

The toggle is a per-tool setting rather than a modal, because unlike the
X/Y axis override this is a mode you leave on, not something you hold.
"""

import bpy

from .placement import refresh_cursor


class VIEW3D_OT_surface_snap_toggle(bpy.types.Operator):
    """Toggle orienting the drawing plane to the surface under the cursor."""

    bl_idname = "view3d.geodraft_surface_snap_toggle"
    bl_label = "Snap To Surface"
    bl_description = (
        "Orient the drawing plane to the surface under the cursor instead of "
        "the ground plane"
    )
    bl_options = {'INTERNAL'}

    settings_path: bpy.props.StringProperty(default="")

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        # Toggling changes which plane the cursor resolves against, so the
        # marker has to be re-resolved now. Waiting for a mouse move would
        # make the toggle look like it had not taken effect.
        result = self.execute(context)
        refresh_cursor(context, self.settings_path, event)
        return result

    def execute(self, context):
        settings = getattr(context.scene, self.settings_path, None)
        if settings is None:
            return {'CANCELLED'}

        settings.surface_snap = not settings.surface_snap
        refresh_cursor(context, self.settings_path)
        self.report(
            {'INFO'},
            "Surface snapping: {}".format(
                "on" if settings.surface_snap else "off"
            ),
        )
        return {'FINISHED'}


def keymap_entries(settings_path):
    """Keymap tuple binding N for a tool's bl_keymap.

    Note this shadows Blender's own N (sidebar toggle) while the tool is
    active, which is the trade the binding asks for.
    """
    return (
        (
            VIEW3D_OT_surface_snap_toggle.bl_idname,
            {"type": 'N', "value": 'PRESS'},
            {"properties": [("settings_path", settings_path)]},
        ),
    )


def register():
    bpy.utils.register_class(VIEW3D_OT_surface_snap_toggle)


def unregister():
    bpy.utils.unregister_class(VIEW3D_OT_surface_snap_toggle)
