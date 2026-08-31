"""Draggable, grid-snapped control points on a curve object.

Reusable by any curve-driven tool -- walls, fences, roads, paths. Subclass
the gizmo group and override `poll_object` (and the look) for a specific
marker property.

Modelled on nineslice_prototype.py's NINESLICE_GGT_scale: poll on a marker
property, and rebuild the handles unconditionally in refresh() rather than
caching by object name -- undo/redo can swap an object's underlying memory
while leaving its name unchanged, and a stale binding then points at freed
memory.

Deliberately NOT GIZMO_GT_move_3d with a target offset. That built-in maps
mouse motion to its target through its own screen projection, which for a
handle lying flat on the ground drifts far faster than the cursor, and it
knows nothing about a grid. These re-use the draw tool's own
ray-to-ground-plus-snap path, so a dragged point lands exactly where the
draw tool would have put it.
"""

import bpy
from mathutils import Matrix, Vector

from .polyline import POINT_RING_FACTOR
from .view import Plane, mouse_to_plane, resolve_view, viewport_cell


def poly_spline(obj):
    """The single POLY spline a curve object carries, or None."""
    if obj is None or obj.type != 'CURVE' or obj.data is None:
        return None
    splines = obj.data.splines
    if not splines:
        return None
    spline = splines[0]
    return spline if spline.type == 'POLY' else None


class CurvePointGizmo(bpy.types.Gizmo):
    """One draggable control point, snapped to the tool's ground grid."""

    bl_idname = "CURVE_GT_point_handle"

    __slots__ = ("point_index", "radius", "_start_co", "_grab_offset")

    # Subclasses override to supply their grid multiplier.
    grid_multiplier_path = None

    def _cell(self, context):
        multiplier = 1.0
        if self.grid_multiplier_path:
            settings = getattr(context.scene, self.grid_multiplier_path, None)
            if settings is not None:
                multiplier = getattr(settings, "grid_multiplier", 1.0)
        return viewport_cell(context, multiplier)

    @staticmethod
    def _object_plane(obj):
        """The drawing plane baked into the object's transform.

        create_plane_curve writes points in a frame whose X/Y are the plane's
        tangent/bitangent and whose Z is its normal, so the plane can be read
        straight back off the object matrix rather than stored separately.
        """
        basis = obj.matrix_world.to_3x3()
        tangent = (basis @ Vector((1.0, 0.0, 0.0))).normalized()
        bitangent = (basis @ Vector((0.0, 1.0, 0.0))).normalized()
        normal = (basis @ Vector((0.0, 0.0, 1.0))).normalized()
        return Plane(
            obj.matrix_world.translation.copy(), normal, tangent, bitangent,
        )

    def _spline(self, context):
        return poly_spline(context.object)

    def draw(self, context):
        """Draw the ring with the same shader the draw tool uses.

        Not draw_preset_circle: the gizmo presets are not antialiased the way
        the POLYLINE shader is, so a ring drawn by a preset visibly jumps in
        quality the moment drawing ends and the handles take over. Reusing
        draw_circle_3d makes the finished handles match the in-progress ones
        exactly -- same shader, same lineSmooth, same width.
        """
        from .draw import draw_circle_3d

        color = self.color_highlight if self.is_highlight else self.color
        alpha = self.alpha_highlight if self.is_highlight else self.alpha
        # The ring lies in the object's own drawing plane -- its local XY --
        # so handles on a wall drawn against a vertical plane stay in that
        # plane instead of lying flat on the floor.
        obj = context.object
        axis = None
        if obj is not None:
            axis = (obj.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0)))
            if axis.length <= 1e-9:
                axis = None
            else:
                axis.normalize()
        draw_circle_3d(
            self.matrix_basis.translation, self.radius,
            (color[0], color[1], color[2], alpha),
            width=2.0, axis=axis,
        )

    def draw_select(self, context, select_id):
        # Selection still goes through the preset: it only has to rasterise
        # an id, and test_select below is what actually decides hits.
        self.draw_preset_circle(
            self.matrix_basis, axis='POS_Z', select_id=select_id,
        )

    def test_select(self, context, location):
        from bpy_extras import view3d_utils

        region, rv3d = resolve_view(context)
        if region is None:
            return -1
        centre = self.matrix_basis.translation
        centre_2d = view3d_utils.location_3d_to_region_2d(
            region, rv3d, centre,
        )
        edge_2d = view3d_utils.location_3d_to_region_2d(
            region, rv3d, centre + Vector((self.radius, 0.0, 0.0)),
        )
        if centre_2d is None or edge_2d is None:
            return -1
        radius_px = max((edge_2d - centre_2d).length, 8.0)
        cursor = Vector((location[0], location[1]))
        return 0 if (centre_2d - cursor).length <= radius_px else -1

    def invoke(self, context, event):
        spline = self._spline(context)
        if spline is None or self.point_index >= len(spline.points):
            return {'CANCELLED'}

        point = spline.points[self.point_index]
        self._start_co = Vector(point.co[:3])

        # Remember where inside the handle the drag began, so the point does
        # not jump to the cursor on the first move.
        region, rv3d = resolve_view(context)
        ground = mouse_to_plane(
            region, rv3d, (event.mouse_region_x, event.mouse_region_y),
            self._object_plane(context.object),
        )
        world_start = context.object.matrix_world @ self._start_co
        self._grab_offset = (
            (world_start - ground) if ground is not None
            else Vector((0.0, 0.0, 0.0))
        )
        return {'RUNNING_MODAL'}

    def modal(self, context, event, tweak):
        spline = self._spline(context)
        obj = context.object
        if spline is None or obj is None:
            return {'CANCELLED'}
        if self.point_index >= len(spline.points):
            return {'CANCELLED'}

        region, rv3d = resolve_view(context)
        ground = mouse_to_plane(
            region, rv3d, (event.mouse_region_x, event.mouse_region_y),
            self._object_plane(obj),
        )
        if ground is None:
            return {'RUNNING_MODAL'}

        target = ground + self._grab_offset
        local = obj.matrix_world.inverted() @ target

        # Snap in the object's own plane: rounding world X/Y would drag the
        # point off a tilted drawing plane and quantise along the wrong axes.
        if 'PRECISE' not in tweak:
            cell = self._cell(context)
            if cell > 0.0:
                local = Vector((
                    round(local.x / cell) * cell,
                    round(local.y / cell) * cell,
                    0.0,
                ))
            else:
                local = Vector((local.x, local.y, 0.0))
        else:
            local = Vector((local.x, local.y, 0.0))
        point = spline.points[self.point_index]
        point.co = (local.x, local.y, local.z, point.co[3])
        obj.data.update_tag()
        obj.update_tag()
        return {'RUNNING_MODAL'}

    def exit(self, context, cancel):
        if not cancel:
            return
        spline = self._spline(context)
        obj = context.object
        if spline is None or obj is None:
            return
        if self.point_index >= len(spline.points):
            return
        point = spline.points[self.point_index]
        point.co = (
            self._start_co.x, self._start_co.y, self._start_co.z,
            point.co[3],
        )
        obj.data.update_tag()
        obj.update_tag()


class CurvePointHandlesBase(bpy.types.GizmoGroup):
    """One handle per control point of the active curve object."""

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT', 'SHOW_MODAL_ALL'}

    # Subclasses set these.
    gizmo_idname = CurvePointGizmo.bl_idname
    handle_color = (0.95, 0.70, 0.15)
    handle_color_highlight = (1.0, 0.9, 0.5)
    ring_factor = POINT_RING_FACTOR
    grid_multiplier_path = None

    @classmethod
    def poll_object(cls, obj):
        """Override: is this object one of ours?"""
        return poly_spline(obj) is not None

    @classmethod
    def poll(cls, context):
        obj = context.object
        if poly_spline(obj) is None or not cls.poll_object(obj):
            return False
        # A hidden object must not leave its handles floating in the
        # viewport. visible_get() accounts for the object, its collections
        # and local view, which hide_viewport alone does not.
        return obj.visible_get()

    def _cell(self, context):
        multiplier = 1.0
        if self.grid_multiplier_path:
            settings = getattr(context.scene, self.grid_multiplier_path, None)
            if settings is not None:
                multiplier = getattr(settings, "grid_multiplier", 1.0)
        return viewport_cell(context, multiplier)

    def setup(self, context):
        self.handles = []
        self._build(context)

    def _build(self, context):
        spline = poly_spline(context.object)
        if spline is None:
            return
        radius = self._cell(context) * self.ring_factor
        for index in range(len(spline.points)):
            gizmo = self.gizmos.new(self.gizmo_idname)
            gizmo.point_index = index
            gizmo.radius = radius
            gizmo.color = self.handle_color
            gizmo.alpha = 0.8
            gizmo.color_highlight = self.handle_color_highlight
            gizmo.alpha_highlight = 1.0
            gizmo.use_draw_modal = True
            self.handles.append(gizmo)

    def refresh(self, context):
        obj = context.object
        spline = poly_spline(obj)
        if spline is None:
            return

        if len(self.handles) != len(spline.points):
            self.gizmos.clear()
            self.handles = []
            self._build(context)
            if not self.handles:
                return

        radius = self._cell(context) * self.ring_factor
        matrix_world = obj.matrix_world
        for index, gizmo in enumerate(self.handles):
            point = spline.points[index]
            local = Vector((point.co[0], point.co[1], point.co[2]))
            gizmo.radius = radius
            gizmo.matrix_basis = (
                Matrix.Translation(matrix_world @ local)
                @ Matrix.Diagonal((radius, radius, radius, 1.0))
            )
