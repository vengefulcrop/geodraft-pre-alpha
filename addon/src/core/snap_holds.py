"""Hold Ctrl for geometry snapping, hold Shift to ignore the grid.

Both are *inversions*, not switches: the hold does the opposite of whatever
the persistent setting says, so Ctrl turns geometry snapping on when it is
off and off when it is on. That is how Ctrl already behaves during a Blender
transform, and a key that means "the other one, briefly" needs no mode to be
remembered.

Why holds at all, when both already have a setting? Because the setting is
in a panel and the decision is at the cursor. Wanting one point on a vertex
and the next back on the grid is an ordinary thing to want, and it should
not cost two trips to a checkbox.

The same gap the subtract hold covers applies here, for the same reason: the
paint cursor receives no events, only a mouse position, so before the first
click a held key is invisible to it. Binding both keys down and up gives the
idle cursor the state the modal would have had, and the modal keeps reading
event.ctrl and event.shift for itself.

Ctrl forcing snapping ON has one extra job. Blender's element list can be
set to GRID alone -- it is the default -- and then there is no geometry
element to snap to and the hold would do nothing at all. In that case only,
the hold assumes vertex and edge. A hold that silently does nothing is worse
than one that guesses the two elements everybody means.
"""

import bpy

from .cursor import STATE, set_grid_suppressed, set_snap_forced
from .placement import refresh_cursor


class VIEW3D_OT_snap_hold(bpy.types.Operator):
    """Invert a snapping setting while the key is held."""

    bl_idname = "view3d.geodraft_snap_hold"
    bl_label = "Snap Hold"
    bl_options = {'INTERNAL'}

    mode: bpy.props.EnumProperty(
        name="Mode",
        items=(
            ('SNAP', "Geometry Snap", "Invert snapping to vertices and edges"),
            ('GRID', "Grid", "Invert grid snapping"),
        ),
        default='SNAP',
    )
    pressed: bpy.props.BoolProperty(default=True)
    settings_path: bpy.props.StringProperty(default="")

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        key = "snap_forced" if self.mode == 'SNAP' else "grid_suppressed"
        if STATE.get(key) != self.pressed:
            if self.mode == 'SNAP':
                set_snap_forced(self.pressed)
            else:
                set_grid_suppressed(self.pressed)
            # Repaint now. The mouse has not moved and a held key sends no
            # further events, so nothing else will.
            refresh_cursor(context, self.settings_path, event)
        # PASS_THROUGH, because both keys are modifiers: swallowing them
        # would break every combination bound underneath.
        return {'PASS_THROUGH'}


def keymap_entries(settings_path):
    """Keymap tuples binding both Ctrl keys and both Shift keys."""
    return tuple(
        (
            VIEW3D_OT_snap_hold.bl_idname,
            # "any": True on both edges. Without it a release while another
            # modifier is down matches nothing -- an unspecified modifier
            # means "must NOT be held" -- so releasing Shift while Ctrl was
            # also held left grid snapping switched off with no key down.
            {"type": key, "value": value, "any": True},
            {"properties": [
                ("mode", mode),
                ("pressed", value == 'PRESS'),
                ("settings_path", settings_path),
            ]},
        )
        for mode, keys in (
            ('SNAP', ('LEFT_CTRL', 'RIGHT_CTRL')),
            ('GRID', ('LEFT_SHIFT', 'RIGHT_SHIFT')),
        )
        for key in keys
        for value in ('PRESS', 'RELEASE')
    )


def register():
    bpy.utils.register_class(VIEW3D_OT_snap_hold)


def unregister():
    bpy.utils.unregister_class(VIEW3D_OT_snap_hold)
