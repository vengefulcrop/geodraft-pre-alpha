"""Post-creation drag handles for floors.

A circle gets exactly two -- its centre and one radius point -- because its
vertices are generated. Ringing all 24 would advertise 24 handles where
there are two, and dragging one would only break the circle.

Nothing in this edition draws a hand-placed point, so the per-point handle
group is not here. A capsule has no handle group yet either: it is redrawn
rather than edited.
"""

import bpy
from mathutils import Matrix, Vector

from ..core.handles import (
    CurvePointGizmo, CurvePointHandlesBase, poly_spline,
)
from ..core.polyline import POINT_RING_FACTOR
from ..core.view import mouse_to_plane, resolve_view, viewport_cell
from .config import (
    CAPSULE_KEY, CIRCLE_KEY, FLOOR_MARKER_KEY, SETTINGS_PATH,
)


def is_floor(obj):
    return (
        obj is not None
        and obj.type == 'CURVE'
        and FLOOR_MARKER_KEY in obj
    )


def is_circle(obj):
    return is_floor(obj) and bool(obj.get(CIRCLE_KEY))


def is_capsule(obj):
    return is_floor(obj) and bool(obj.get(CAPSULE_KEY))


def floor_spline(obj):
    return poly_spline(obj) if is_floor(obj) else None


def circle_rim(spline):
    """The circle's first vertex, in local space.

    The first vertex is where the radius was dragged to when the circle was
    drawn, so it is both the radius and the rotation, and the natural place
    to hang the radius handle -- unlike a fixed local +X, which would sit at
    an arbitrary point on the rim.
    """
    if spline is None or not len(spline.points):
        return Vector((0.0, 0.0, 0.0))
    point = spline.points[0]
    return Vector((point.co[0], point.co[1], point.co[2]))


def circle_radius(spline):
    """Radius of a generated circle: its first point's distance from zero."""
    return circle_rim(spline).length


# --- circles ---------------------------------------------------------------

class GEODRAFT_GT_circle_handle(CurvePointGizmo):
    """Centre or radius handle of a generated circle."""

    bl_idname = "GEODRAFT_GT_circle_handle"
    grid_multiplier_path = SETTINGS_PATH

    __slots__ = ("mode", "_start_location", "_start_points")

    def invoke(self, context, event):
        obj = context.object
        spline = floor_spline(obj)
        if spline is None:
            return {'CANCELLED'}

        self._start_location = obj.location.copy()
        self._start_points = [
            Vector((p.co[0], p.co[1], p.co[2])) for p in spline.points
        ]

        region, rv3d = resolve_view(context)
        ground = mouse_to_plane(
            region, rv3d, (event.mouse_region_x, event.mouse_region_y),
            self._object_plane(obj),
        )
        # Grab offset keeps the handle from jumping to the cursor on the
        # first move, exactly as for a point handle.
        anchor = obj.matrix_world @ (
            Vector((0.0, 0.0, 0.0)) if self.mode == 'CENTER'
            else circle_rim(spline)
        )
        self._grab_offset = (
            (anchor - ground) if ground is not None
            else Vector((0.0, 0.0, 0.0))
        )
        return {'RUNNING_MODAL'}

    def modal(self, context, event, tweak):
        obj = context.object
        spline = floor_spline(obj)
        if spline is None:
            return {'CANCELLED'}

        region, rv3d = resolve_view(context)
        ground = mouse_to_plane(
            region, rv3d, (event.mouse_region_x, event.mouse_region_y),
            self._object_plane(obj),
        )
        if ground is None:
            return {'RUNNING_MODAL'}

        target = ground + self._grab_offset
        cell = self._cell(context)
        snap = cell > 0.0 and 'PRECISE' not in tweak

        if self.mode == 'CENTER':
            # Moving the whole circle is moving the object; the generated
            # points stay exactly as they are.
            local = obj.matrix_world.inverted() @ target
            if snap:
                local = Vector((
                    round(local.x / cell) * cell,
                    round(local.y / cell) * cell,
                    0.0,
                ))
            obj.location = obj.matrix_world @ local
        else:
            import math

            local = obj.matrix_world.inverted() @ target
            flat = Vector((local.x, local.y, 0.0))
            radius = flat.length
            if snap:
                radius = round(radius / cell) * cell
            if radius < 1e-6:
                return {'RUNNING_MODAL'}

            # Rotate as well as scale: the handle sits on the first vertex,
            # which *is* the circle's rotation, so dragging it around the
            # centre spins the circle rather than sliding the handle off it.
            start = self._start_points[0]
            delta = math.atan2(flat.y, flat.x) - math.atan2(start.y, start.x)
            cos_d, sin_d = math.cos(delta), math.sin(delta)
            factor = radius / (start.length or 1.0)

            # Uniform scale plus a common rotation preserves the vertex count
            # and the spacing, so this cannot deform the circle.
            for point, origin_point in zip(spline.points, self._start_points):
                x = origin_point.x * cos_d - origin_point.y * sin_d
                y = origin_point.x * sin_d + origin_point.y * cos_d
                point.co = (x * factor, y * factor, 0.0, point.co[3])

        obj.data.update_tag()
        obj.update_tag()
        return {'RUNNING_MODAL'}

    def exit(self, context, cancel):
        if not cancel:
            return
        obj = context.object
        spline = floor_spline(obj)
        if obj is None or spline is None:
            return
        obj.location = self._start_location
        for point, start in zip(spline.points, self._start_points):
            point.co = (start.x, start.y, start.z, point.co[3])
        obj.data.update_tag()
        obj.update_tag()


class VIEW3D_GGT_geodraft_circle_edit(CurvePointHandlesBase):
    bl_idname = "VIEW3D_GGT_geodraft_circle_edit"
    bl_label = "GeoDraft Circle Edit Widgets"

    gizmo_idname = GEODRAFT_GT_circle_handle.bl_idname
    grid_multiplier_path = SETTINGS_PATH
    handle_color = (0.35, 0.75, 0.95)
    handle_color_highlight = (0.6, 0.9, 1.0)

    @classmethod
    def poll_object(cls, obj):
        return is_circle(obj)

    def _build(self, context):
        radius = self._cell(context) * POINT_RING_FACTOR
        for mode in ('CENTER', 'RADIUS'):
            gizmo = self.gizmos.new(self.gizmo_idname)
            gizmo.mode = mode
            gizmo.point_index = 0
            gizmo.radius = radius
            gizmo.color = self.handle_color
            gizmo.alpha = 0.8
            gizmo.color_highlight = self.handle_color_highlight
            gizmo.alpha_highlight = 1.0
            gizmo.use_draw_modal = True
            self.handles.append(gizmo)

    def refresh(self, context):
        obj = context.object
        spline = floor_spline(obj)
        if spline is None:
            return

        if len(self.handles) != 2:
            self.gizmos.clear()
            self.handles = []
            self._build(context)

        ring = self._cell(context) * POINT_RING_FACTOR
        matrix_world = obj.matrix_world
        rim = circle_rim(spline)
        for gizmo in self.handles:
            local = (
                Vector((0.0, 0.0, 0.0)) if gizmo.mode == 'CENTER' else rim
            )
            gizmo.radius = ring
            gizmo.matrix_basis = (
                Matrix.Translation(matrix_world @ local)
                @ Matrix.Diagonal((ring, ring, ring, 1.0))
            )


classes = (
    GEODRAFT_GT_circle_handle,
    VIEW3D_GGT_geodraft_circle_edit,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
