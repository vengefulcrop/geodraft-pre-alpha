"""Toolbar WorkSpaceTool entry for "Draw Circle"."""

from bpy.types import WorkSpaceTool

from ..core.axis_plane import keymap_entries as axis_keymap_entries
from ..core.cursor import STATE
from ..core.placement import PlacementOverlay
from ..core.scrubber import keymap_entries as scrubber_keymap_entries
from ..core.snap_holds import (
    keymap_entries as snap_hold_keymap_entries,
)
from ..core.subtract_hold import (
    keymap_entries as subtract_keymap_entries,
)
from ..core.surface_snap import keymap_entries as surface_keymap_entries
from ..core.widget_freeze import (
    keymap_entries as freeze_keymap_entries,
)
from ..core.toolkit import drop_stale_cursor, register_tool, unregister_tool
from .config import MARKER_HEIGHT, MIN_CIRCLE_SEGMENTS, SETTINGS_PATH
from .circle_ops import MESH_OT_geodraft_circle_draw
from .ops import VIEW3D_OT_geodraft_floor_grid_step

TOOL_IDNAME = "geodraft.draw_circle"

OVERLAY = PlacementOverlay(
    tool_idname=TOOL_IDNAME,
    settings_path=SETTINGS_PATH,
    marker_height=MARKER_HEIGHT,
    label=lambda settings: (
        "-" if STATE.get("subtract") else str(settings.circle_segments)
    ),
    marker_color=(0.55, 0.85, 1.0),
    # Flat geometry: the glow lies in the plane and falls toward the
    # inside of the outline, rather than standing up as a curtain.
    veil_inward=True,
    hint=(
        "click a centre, then a radius  |  type a number  |  F vertex "
        "count  |  Ctrl snap  |  Shift no grid  |  V freeze  |  "
        "X/Y/Z plane  |  N surface  |  Alt subtract"
    ),
)


class VIEW3D_T_geodraft_circle_draw(WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'

    bl_idname = TOOL_IDNAME
    bl_label = "Draw Circle"
    bl_description = (
        "Click for the centre, then again for the radius. Hold F to scrub "
        "the vertex count, Ctrl to snap to geometry, Shift to ignore the grid"
    )
    bl_icon = "ops.gpencil.primitive_circle"
    bl_widget = None
    bl_keymap = (
        # "any": True, so every modifier combination starts the tool.
        # An unspecified modifier in a keymap item means "must NOT be
        # held", so spelling out only the plain and Alt cases left
        # Ctrl+click and Shift+click matching nothing at all -- and
        # those are exactly the snapping holds.
        (
            MESH_OT_geodraft_circle_draw.bl_idname,
            {"type": 'LEFTMOUSE', "value": 'PRESS', "any": True},
            None,
        ),
        (
            VIEW3D_OT_geodraft_floor_grid_step.bl_idname,
            {"type": 'PAGE_UP', "value": 'PRESS'},
            {"properties": [("step", 1)]},
        ),
        (
            VIEW3D_OT_geodraft_floor_grid_step.bl_idname,
            {"type": 'PAGE_DOWN', "value": 'PRESS'},
            {"properties": [("step", -1)]},
        ),
    ) + axis_keymap_entries(SETTINGS_PATH) + freeze_keymap_entries(
        SETTINGS_PATH
    ) + snap_hold_keymap_entries(
        SETTINGS_PATH
    ) + surface_keymap_entries(
        SETTINGS_PATH
    ) + subtract_keymap_entries(SETTINGS_PATH) + scrubber_keymap_entries(
        SETTINGS_PATH, "circle_segments", key='F', label="Circle segments",
        # The track starts at 0 so its midpoint is a round 32; the stretch
        # below MIN_CIRCLE_SEGMENTS draws greyed out.
        ui_min=0, ui_max=64, coarse_step=8,
        hard_min=MIN_CIRCLE_SEGMENTS,
    )

    @staticmethod
    def draw_settings(context, layout, tool):
        settings = getattr(context.scene, SETTINGS_PATH)
        layout.prop(settings, "grid_multiplier")
        layout.prop(settings, "snap_to_grid", text="Grid")
        layout.prop(settings, "straight_to_mesh", text="Straight To Mesh")
        layout.prop(settings, "circle_segments")
        layout.prop(settings, "thickness")

    @staticmethod
    def draw_cursor(context, tool, xy):
        # One-line trampoline; see the note in wall/tool.py.
        OVERLAY.draw_cursor(context, tool, xy)


def register():
    OVERLAY.register()
    register_tool(VIEW3D_T_geodraft_circle_draw, separator=False)


def unregister():
    OVERLAY.unregister()
    drop_stale_cursor(TOOL_IDNAME)
    unregister_tool(VIEW3D_T_geodraft_circle_draw)
