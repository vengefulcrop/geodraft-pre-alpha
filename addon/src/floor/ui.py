"""N-panel for the circle and capsule tools."""

import bpy

from .config import SETTINGS_PATH
from .gizmos import is_floor
from ..core.shared_settings import draw_option as draw_shared_option


class VIEW3D_PT_geodraft_floor(bpy.types.Panel):
    bl_label = "Decal Tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "GeoDraft"

    def draw(self, context):
        layout = self.layout
        settings = getattr(context.scene, SETTINGS_PATH)

        col = layout.column(align=True)
        col.label(text="New Shapes")
        col.prop(settings, "grid_multiplier")
        col.prop(settings, "snap_to_grid")
        col.prop(settings, "straight_to_mesh")
        col.prop(settings, "thickness")
        col.label(text="Hold Alt while drawing to subtract", icon='INFO')

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Overlay")
        col.prop(settings, "surface_snap", text="Snap To Surface (N)")
        col.label(
            text="Ctrl: snap to geometry   Shift: ignore the grid",
            icon='SNAP_ON',
        )
        col.label(
            text="Which elements: Blender's own snap menu",
            icon='BLANK1',
        )
        col.prop(settings, "hollow_widget")
        col.prop(settings, "show_veil")
        sub = col.column(align=True)
        sub.active = settings.show_veil
        sub.prop(settings, "veil_height")
        sub.prop(settings, "veil_alpha")
        col.separator()
        draw_shared_option(col, context)

        obj = context.object
        if is_floor(obj):
            layout.separator()
            col = layout.column(align=True)
            col.label(text="Selected Shape")
            col.prop(obj.geodraft_floor, "role")
            sub = col.column(align=True)
            sub.active = obj.geodraft_floor.role == 'ADD'
            sub.prop(obj.geodraft_floor, "thickness")


classes = (VIEW3D_PT_geodraft_floor,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
