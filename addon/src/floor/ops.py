"""Floor creation, and the grid-step shortcut.

The free-hand polygon modal is not part of this edition; build_floor stays,
because the circle and the capsule are both polygons underneath.
"""

import bpy
from bpy.props import IntProperty

from ..core.curve_object import create_plane_curve, to_mesh_now
from ..core.destructive_cut import cut_meshes
from ..core.placement import refresh_cursor
from ..core.view import RAYCAST_IGNORE_KEY
from ..core.view import viewport_cell
from .config import (
    CIRCLE_KEY,
    CUTTER_COLLECTION,
    FLOOR_MARKER_KEY,
    SETTINGS_PATH,
)
from .geometry import (
    attach_cutter_modifier,
    attach_floor_modifier,
    ensure_cutter_collection,
)
from .props import push_floor_settings

# Objects this addon may cut destructively: the ones it made itself. The
# wall key is spelled out rather than imported, because the floor package
# must not depend on the wall package -- the decal edition ships without it.
MARKER_KEYS = (FLOOR_MARKER_KEY, "is_geodraft_wall")

MIN_MULTIPLIER = 1.0 / 64.0
MAX_MULTIPLIER = 64.0


def build_floor(context, points, plane, subtract, name=None,
                origin=None, circle=False):
    """Create a floor polygon (or a cutter) from world-space points.

    Shared by the circle and capsule tools: both are polygons whose points
    happen to lie on a generated outline, so there is no reason for two
    creation paths that could drift apart.
    """
    settings = getattr(context.scene, SETTINGS_PATH)

    if name is None:
        name = "GeoDraftFloor"
    if subtract:
        name += "Cut"

    # Built in plane-local space: Fill Curve only fills in XY, so a polygon
    # drawn on a vertical plane would otherwise collapse to nothing.
    obj = create_plane_curve(context, name, points, plane, True, origin)
    obj[FLOOR_MARKER_KEY] = True

    # Stamp the draw order before anything else reads it. Floors and cutters
    # share one counter, so "drawn after" is a single comparison rather than
    # two clocks that could disagree.
    obj.geodraft_floor.sequence = settings.next_sequence
    settings.next_sequence += 1
    if circle:
        # Its handles are centre + radius; the vertices are derived, so they
        # are not individually editable.
        obj[CIRCLE_KEY] = True

    if subtract:
        obj.geodraft_floor.role = 'SUBTRACT'
        # Cutters live only in the cutter collection, so they are not part of
        # the working scene tree and cannot be cut by each other.
        for collection in list(obj.users_collection):
            collection.objects.unlink(obj)
        ensure_cutter_collection().objects.link(obj)
        attach_cutter_modifier(obj)
        # Skipped by surface-normal orientation: a cutter is scaffolding, not
        # a surface to build against.
        obj[RAYCAST_IGNORE_KEY] = True
        # Wireframe and out of renders, but still selectable so its handles
        # keep working.
        obj.display_type = 'WIRE'
        obj.hide_render = True
    else:
        obj.geodraft_floor.thickness = settings.thickness
        attach_floor_modifier(obj)

    push_floor_settings(obj)

    for other in context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj

    if subtract:
        # A live cutter cuts curves. It cannot cut a mesh, because the
        # subtraction lives in the target's own modifier and a mesh has
        # none. So the meshes are cut here and now, whatever the
        # straight-to-mesh setting says: it is the only moment they can be
        # cut at all, and a cutter that silently skips half the scene is
        # worse than one that acts.
        cut = cut_meshes(context, obj, MARKER_KEYS)
        if cut and getattr(settings, "straight_to_mesh", False):
            # Nothing lingers in the destructive workflow. The cutter has
            # done everything it can do, so it goes.
            bpy.data.objects.remove(obj, do_unlink=True)
            return None
        return obj

    if getattr(settings, "straight_to_mesh", False):
        obj = to_mesh_now(context, obj)
    return obj


class VIEW3D_OT_geodraft_floor_grid_step(bpy.types.Operator):
    """Double or halve the drawing grid step."""

    bl_idname = "view3d.geodraft_floor_grid_step"
    bl_label = "Step Floor Grid Size"
    bl_description = "Double or halve the floor drawing grid step"
    bl_options = {'REGISTER', 'UNDO'}

    step: IntProperty(name="Step", default=1)

    def invoke(self, context, event):
        # The grid step changes the cursor's snapping and the dot spacing,
        # so re-resolve it against the current mouse rather than waiting.
        result = self.execute(context)
        refresh_cursor(context, SETTINGS_PATH, event)
        return result

    def execute(self, context):
        settings = getattr(context.scene, SETTINGS_PATH)
        factor = 2.0 if self.step > 0 else 0.5
        settings.grid_multiplier = min(
            MAX_MULTIPLIER,
            max(MIN_MULTIPLIER, settings.grid_multiplier * factor),
        )
        refresh_cursor(context, SETTINGS_PATH)
        self.report(
            {'INFO'},
            "Grid step: {:g} (x{:g} viewport grid)".format(
                viewport_cell(context, settings.grid_multiplier),
                settings.grid_multiplier,
            ),
        )
        return {'FINISHED'}


classes = (VIEW3D_OT_geodraft_floor_grid_step,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
