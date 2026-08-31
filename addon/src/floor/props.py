"""Scene tool settings and per-floor settings."""

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
)

from ..core.nodes import set_modifier_input
from ..core.shared_settings import (
    mirror,
    register_settings_path,
    unregister_settings_path,
)
from .config import (
    CUTTER_DEPTH,
    CUTTER_MODIFIER_NAME,
    DEFAULT_CIRCLE_SEGMENTS,
    DEFAULT_THICKNESS,
    MAX_CIRCLE_SEGMENTS,
    MIN_CIRCLE_SEGMENTS,
    ROLE_ITEMS,
    FLOOR_MARKER_KEY,
    LEGACY_SEQUENCE,
    MARKER_HEIGHT,
    MODIFIER_NAME,
    SETTINGS_PATH,
    VEIL_HEIGHT,
)


def push_floor_settings(obj):
    """Mirror an object's properties into its GN modifier inputs."""
    if obj is None or FLOOR_MARKER_KEY not in obj:
        return

    if obj.geodraft_floor.role == 'SUBTRACT':
        cutter = obj.modifiers.get(CUTTER_MODIFIER_NAME)
        if cutter is not None and cutter.type == 'NODES':
            set_modifier_input(cutter, "Depth", obj.geodraft_floor.cutter_depth)
            # A cutter with no draw order predates ordering, so it counts as
            # newer than everything and keeps cutting what it always cut.
            set_modifier_input(
                cutter, "Sequence",
                float(obj.geodraft_floor.sequence or LEGACY_SEQUENCE),
            )
            obj.update_tag()
        return

    modifier = obj.modifiers.get(MODIFIER_NAME)
    if modifier is None or modifier.type != 'NODES':
        return

    # Pushed explicitly rather than left to socket defaults: rebuilding the
    # node group assigns fresh socket identifiers, and any input not given
    # explicitly reads back as zero.
    set_modifier_input(modifier, "Thickness", obj.geodraft_floor.thickness)
    # A floor with no draw order predates ordering, so it counts as older
    # than every cutter and keeps being cut by all of them.
    set_modifier_input(modifier, "Sequence", float(obj.geodraft_floor.sequence))
    obj.update_tag()


def _update_floor(self, context):
    # self.id_data can be a stale reference to a freed object if this fires
    # during an undo step.
    try:
        push_floor_settings(self.id_data)
    except ReferenceError:
        pass


class GeoDraftFloorObjectSettings(bpy.types.PropertyGroup):
    """Per-floor settings, stored on the floor object itself."""

    role: EnumProperty(
        name="Role",
        items=ROLE_ITEMS,
        default='ADD',
    )

    sequence: IntProperty(
        name="Draw Order",
        description=(
            "When this polygon was drawn. A cutter subtracts only from "
            "polygons drawn before it"
        ),
        default=0,
        min=0,
        update=_update_floor,
    )

    thickness: FloatProperty(
        name="Thickness",
        description="Extrusion height; 0 leaves a flat polygon",
        default=DEFAULT_THICKNESS,
        min=0.0,
        soft_max=MARKER_HEIGHT,
        update=_update_floor,
    )
    cutter_depth: FloatProperty(
        name="Cut Depth",
        description=(
            "How far a subtractive polygon protrudes either side of its "
            "plane. Only needs to clear what it cuts"
        ),
        default=CUTTER_DEPTH,
        min=0.0,
        soft_max=MARKER_HEIGHT * 4.0,
        update=_update_floor,
    )


class GeoDraftFloorToolSettings(bpy.types.PropertyGroup):
    """Draw-tool settings, shared per scene."""

    next_sequence: IntProperty(
        name="Next Draw Order",
        description=(
            "Counter handed to each polygon as it is drawn, so cutters know "
            "what already existed"
        ),
        default=1,
        min=1,
        options={'HIDDEN'},
    )

    grid_multiplier: FloatProperty(
        name="Grid Step",
        description="Snapping step as a multiple of the viewport's grid scale",
        default=1.0,
        min=0.001,
        soft_min=0.125,
        soft_max=64.0,
        update=mirror("grid_multiplier"),
    )
    thickness: FloatProperty(
        name="Thickness",
        description="Thickness applied to newly drawn floors; 0 is flat",
        default=DEFAULT_THICKNESS,
        min=0.0,
        soft_max=MARKER_HEIGHT,
    )
    snap_to_grid: BoolProperty(
        name="Snap To Grid",
        description=(
            "Quantise placed points to the drawing grid. Off draws freely, "
            "wherever the cursor lands"
        ),
        default=True,
        update=mirror("snap_to_grid"),
    )
    straight_to_mesh: BoolProperty(
        name="Straight To Mesh",
        description=(
            "Convert each new shape to a mesh as soon as it is drawn. This "
            "throws away the curve, so the shape can no longer be re-solved "
            "from its handles. Cutters are left alone: they have to stay "
            "live for the shapes they cut"
        ),
        default=False,
        update=mirror("straight_to_mesh"),
    )
    surface_snap: BoolProperty(
        name="Snap To Surface",
        description=(
            "Orient the drawing plane to the surface under the cursor "
            "instead of the ground plane"
        ),
        default=False,
        update=mirror("surface_snap"),
    )
    circle_segments: IntProperty(
        name="Circle Segments",
        description="Vertex count for new circles; hold F to scrub",
        default=DEFAULT_CIRCLE_SEGMENTS,
        min=MIN_CIRCLE_SEGMENTS,
    )
    hollow_widget: BoolProperty(
        name="Hollow Widget",
        description=(
            "Draw the placement widget as a transparent body with only its "
            "silhouette visible"
        ),
        default=True,
        update=mirror("hollow_widget"),
    )
    show_veil: BoolProperty(
        name="Outline Preview",
        description=(
            "Show a translucent curtain rising from the drawn outline"
        ),
        default=True,
        update=mirror("show_veil"),
    )
    veil_height: FloatProperty(
        name="Preview Height",
        default=VEIL_HEIGHT,
        min=0.0,
        soft_max=MARKER_HEIGHT,
    )
    veil_alpha: FloatProperty(
        name="Preview Opacity",
        default=0.35,
        min=0.0,
        max=1.0,
        update=mirror("veil_alpha"),
    )


classes = (GeoDraftFloorObjectSettings, GeoDraftFloorToolSettings)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    register_settings_path(SETTINGS_PATH)
    bpy.types.Object.geodraft_floor = PointerProperty(type=GeoDraftFloorObjectSettings)
    setattr(
        bpy.types.Scene, SETTINGS_PATH,
        PointerProperty(type=GeoDraftFloorToolSettings),
    )


def unregister():
    unregister_settings_path(SETTINGS_PATH)
    delattr(bpy.types.Scene, SETTINGS_PATH)
    del bpy.types.Object.geodraft_floor
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
