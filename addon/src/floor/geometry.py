"""The floor's Geometry Nodes group: closed curve -> filled polygon.

    Group Input (cyclic curve)
      -> Fill Curve       N-gons                  [the flat polygon]
      -> Extrude Mesh     faces, +Z * Thickness   [only when Thickness > 0]
      -> Set Shade Smooth off
      -> Group Output

Thickness 0 leaves a single flat n-gon, which is the default: these are
floor plates and footprints, not slabs. The extrude is always present in the
graph and simply does nothing at 0, so there is no branch to maintain.
"""

import bpy

from ..core.nodes import attach_modifier, ensure_group, new_socket
from .config import (
    CUT_SEQUENCE_ATTRIBUTE,
    CUTTER_COLLECTION,
    CUTTER_DEPTH,
    CUTTER_MODIFIER_NAME,
    CUTTER_NODE_GROUP_NAME,
    DEFAULT_THICKNESS,
    MODIFIER_NAME,
    NODE_GROUP_NAME,
)


def ensure_cutter_collection():
    """The collection every subtractive polygon lives in.

    Kept out of the scene's own collections so cutters do not clutter the
    outliner's working tree, but still linked to the scene so they evaluate.
    """
    collection = bpy.data.collections.get(CUTTER_COLLECTION)
    if collection is None:
        collection = bpy.data.collections.new(CUTTER_COLLECTION)
    scene = bpy.context.scene
    if collection.name not in scene.collection.children:
        scene.collection.children.link(collection)
    return collection


def _set_fill_mode(node, mode='NGONS'):
    """Fill Curve's mode moved from a node enum to a menu socket.

    Set Curve Normal made the same move and takes the *display* name there
    ('Z Up', not 'Z_UP'), so try the node property first and fall back to the
    socket with both spellings rather than assuming either shape.
    """
    try:
        node.mode = mode
        return "node.mode"
    except (AttributeError, TypeError):
        pass
    for value in ('N-gons', 'NGONS', 'Ngons'):
        try:
            node.inputs["Mode"].default_value = value
            return "socket:%s" % value
        except (KeyError, TypeError):
            continue
    return "default"


def _build(tree):
    new_socket(tree, "Geometry", 'INPUT', 'NodeSocketGeometry')
    new_socket(
        tree, "Thickness", 'INPUT', 'NodeSocketFloat',
        default_value=DEFAULT_THICKNESS, min_value=0.0,
    )
    new_socket(
        tree, "Sequence", 'INPUT', 'NodeSocketFloat', default_value=0.0,
    )
    new_socket(tree, "Geometry", 'OUTPUT', 'NodeSocketGeometry')

    nodes = tree.nodes
    links = tree.links

    group_in = nodes.new("NodeGroupInput")
    group_in.location = (-600, 0)
    group_out = nodes.new("NodeGroupOutput")
    group_out.location = (980, 0)

    fill = nodes.new("GeometryNodeFillCurve")
    fill.location = (-360, 0)
    _set_fill_mode(fill)
    links.new(group_in.outputs["Geometry"], fill.inputs["Curve"])

    up = nodes.new("FunctionNodeInputVector")
    up.location = (-360, -220)
    up.vector = (0.0, 0.0, 1.0)

    # Extrude Mesh at scale 0 does NOT do nothing: it still duplicates the
    # geometry and leaves degenerate side faces (measured: a filled square
    # came out 8 verts / 5 faces instead of 4 / 1). Gate it on the selection
    # instead, so thickness 0 leaves a clean single n-gon.
    solid = nodes.new("FunctionNodeCompare")
    solid.location = (-360, -380)
    solid.data_type = 'FLOAT'
    solid.operation = 'GREATER_THAN'
    solid.inputs[1].default_value = 0.0
    links.new(group_in.outputs["Thickness"], solid.inputs[0])

    extrude = nodes.new("GeometryNodeExtrudeMesh")
    extrude.location = (-120, 0)
    extrude.mode = 'FACES'
    links.new(fill.outputs["Mesh"], extrude.inputs["Mesh"])
    links.new(solid.outputs["Result"], extrude.inputs["Selection"])
    links.new(up.outputs["Vector"], extrude.inputs["Offset"])
    links.new(group_in.outputs["Thickness"], extrude.inputs["Offset Scale"])

    # Extrude consumes the face it extrudes, so a thickened plate comes out
    # as an open shell (measured: 8 verts / 5 faces -- top plus four sides,
    # no bottom). Join a flipped second fill as the bottom.
    #
    # The cap MUST be gated on thickness, not merely coincident-and-welded.
    # At thickness 0 the two fills sit exactly on top of each other and the
    # weld keeps the *flipped* one, so a flat plate came out facing away from
    # the viewer -- the face you were looking at was its backface. Fill Curve
    # normalises winding, so this happened for every draw direction rather
    # than only for one, which is what made it look like a plane-orientation
    # bug rather than a capping bug.
    cap = nodes.new("GeometryNodeFillCurve")
    cap.location = (-360, 220)
    _set_fill_mode(cap)
    links.new(group_in.outputs["Geometry"], cap.inputs["Curve"])

    flip = nodes.new("GeometryNodeFlipFaces")
    flip.location = (-160, 220)
    links.new(cap.outputs["Mesh"], flip.inputs["Mesh"])

    cap_switch = nodes.new("GeometryNodeSwitch")
    cap_switch.location = (-20, 220)
    cap_switch.input_type = 'GEOMETRY'
    links.new(solid.outputs["Result"], cap_switch.inputs[0])
    links.new(flip.outputs["Mesh"], cap_switch.inputs[2])

    join = nodes.new("GeometryNodeJoinGeometry")
    join.location = (140, 0)
    links.new(extrude.outputs["Mesh"], join.inputs["Geometry"])
    links.new(cap_switch.outputs[0], join.inputs["Geometry"])

    weld = nodes.new("GeometryNodeMergeByDistance")
    weld.location = (300, 0)
    weld.inputs["Distance"].default_value = 1e-5
    links.new(join.outputs["Geometry"], weld.inputs["Geometry"])

    # Subtract every cutter in the shared collection. Cutters that do not
    # overlap simply remove nothing, so membership is global rather than
    # resolved per polygon -- which keeps it live: moving a cutter later
    # affects whatever it moves over, with no re-linking.
    #
    # Read RELATIVE so cutters arrive in this object's local space; ORIGINAL
    # would ignore both transforms and cut in the wrong place, since every
    # polygon carries its drawing plane in its own matrix.
    cutters = nodes.new("GeometryNodeCollectionInfo")
    cutters.location = (300, -420)
    cutters.transform_space = 'RELATIVE'
    cutters.inputs["Collection"].default_value = ensure_cutter_collection()
    cutters.inputs["Separate Children"].default_value = False

    # Collection Info emits *instances*, and Mesh Boolean silently ignores
    # them -- it returned the uncut plate with no error at all. They have to
    # be realized into actual mesh first.
    realize = nodes.new("GeometryNodeRealizeInstances")
    realize.location = (460, -420)
    links.new(cutters.outputs["Instances"], realize.inputs["Geometry"])

    # Keep only the cutters drawn after this polygon. A cut is meant to apply
    # to what was already there when it was made, so a floor drawn later sits
    # on top of an older hole rather than acquiring it -- otherwise a cutter
    # keeps punching through everything added near it forever, and there is no
    # way to build over a cut.
    #
    # Compared on the geometry rather than resolved in Python because the
    # cutter collection is read whole and live: adding, deleting or reordering
    # cutters must not require re-linking anything.
    cut_sequence = nodes.new("GeometryNodeInputNamedAttribute")
    cut_sequence.location = (460, -640)
    cut_sequence.data_type = 'FLOAT'
    cut_sequence.inputs["Name"].default_value = CUT_SEQUENCE_ATTRIBUTE

    newer = nodes.new("FunctionNodeCompare")
    newer.location = (620, -640)
    newer.data_type = 'FLOAT'
    newer.operation = 'GREATER_THAN'
    links.new(cut_sequence.outputs["Attribute"], newer.inputs[0])
    links.new(group_in.outputs["Sequence"], newer.inputs[1])

    applicable = nodes.new("GeometryNodeSeparateGeometry")
    applicable.location = (780, -420)
    # FACE, not POINT: separating by point would drop faces whose corners
    # straddle the test, and every point of one cutter carries the same
    # number anyway.
    applicable.domain = 'FACE'
    links.new(realize.outputs["Geometry"], applicable.inputs["Geometry"])
    links.new(newer.outputs["Result"], applicable.inputs["Selection"])

    difference = nodes.new("GeometryNodeMeshBoolean")
    difference.location = (620, 0)
    difference.operation = 'DIFFERENCE'
    # EXACT is the solver that actually removes material here; a flat cutter
    # under any solver only splits faces.
    difference.solver = 'EXACT'
    links.new(weld.outputs["Geometry"], difference.inputs[0])
    links.new(applicable.outputs["Selection"], difference.inputs[1])

    # A zero-thickness plate is not a solid, and DIFFERENCE is only defined
    # for solids. Blender does not refuse: it cuts the hole correctly in the
    # plane and then wraps the opening in the cutter's own back surface, so
    # the hole comes out as a filled recess. Measured on a 24-gon plate,
    # faces by local Z: 99.387 at 0 (the correct plate-with-hole), 3.0 at
    # -0.12 (recess walls), 12.42 at -0.24 (its floor).
    #
    # Coincidentally it comes out clean when the cutter's rim falls on the
    # plate's own vertex ring -- a concentric circle, a square on a square --
    # which is why this survived the first round of testing.
    #
    # For a flat plate the meaningful result is the 2D one: difference the
    # region by the cutter's cross-section in the plane. Every face the
    # boolean puts off the plane is an artefact of pretending the plate had
    # volume, so keeping the in-plane faces *is* that 2D answer rather than a
    # tidy-up. Geometry is authored in plane-local space, so "in the plane"
    # is simply local Z ~ 0.
    #
    # With real thickness the plate is a genuine solid, the boolean is
    # well-defined and its side walls are wanted, so the filter is switched
    # out entirely.
    position = nodes.new("GeometryNodeInputPosition")
    position.location = (620, -620)

    separate_z = nodes.new("ShaderNodeSeparateXYZ")
    separate_z.location = (780, -620)
    links.new(position.outputs["Position"], separate_z.inputs["Vector"])

    depth = nodes.new("ShaderNodeMath")
    depth.location = (920, -620)
    depth.operation = 'ABSOLUTE'
    links.new(separate_z.outputs["Z"], depth.inputs[0])

    in_plane = nodes.new("FunctionNodeCompare")
    in_plane.location = (1060, -620)
    in_plane.data_type = 'FLOAT'
    in_plane.operation = 'LESS_THAN'
    # Loose enough to survive the solver's own rounding, far tighter than the
    # nearest artefact: recess walls land at half the cutter depth.
    in_plane.inputs[1].default_value = 1e-4
    links.new(depth.outputs["Value"], in_plane.inputs[0])

    flat_only = nodes.new("GeometryNodeSeparateGeometry")
    flat_only.location = (1220, -300)
    flat_only.domain = 'FACE'
    links.new(difference.outputs["Mesh"], flat_only.inputs["Geometry"])
    links.new(in_plane.outputs["Result"], flat_only.inputs["Selection"])

    flat_switch = nodes.new("GeometryNodeSwitch")
    flat_switch.location = (1380, 0)
    flat_switch.input_type = 'GEOMETRY'
    links.new(solid.outputs["Result"], flat_switch.inputs[0])
    links.new(flat_only.outputs["Selection"], flat_switch.inputs[1])
    links.new(difference.outputs["Mesh"], flat_switch.inputs[2])

    shade = nodes.new("GeometryNodeSetShadeSmooth")
    shade.location = (1540, 0)
    shade.inputs["Shade Smooth"].default_value = False
    links.new(flat_switch.outputs[0], shade.inputs["Geometry"])

    links.new(shade.outputs["Geometry"], group_out.inputs["Geometry"])


def _build_cutter(tree):
    """A subtractive polygon: its outline swept into a slab.

    Deliberately has no boolean of its own. Cutters live in the collection
    that the main floor group reads, so giving them the main group would make
    the collection depend on itself and Blender would refuse the cycle.
    """
    new_socket(tree, "Geometry", 'INPUT', 'NodeSocketGeometry')
    new_socket(
        tree, "Depth", 'INPUT', 'NodeSocketFloat',
        default_value=CUTTER_DEPTH, min_value=0.0,
    )
    new_socket(
        tree, "Sequence", 'INPUT', 'NodeSocketFloat', default_value=0.0,
    )
    new_socket(tree, "Geometry", 'OUTPUT', 'NodeSocketGeometry')

    nodes = tree.nodes
    links = tree.links

    group_in = nodes.new("NodeGroupInput")
    group_in.location = (-600, 0)
    group_out = nodes.new("NodeGroupOutput")
    group_out.location = (400, 0)

    half = nodes.new("ShaderNodeMath")
    half.location = (-600, -400)
    half.operation = 'MULTIPLY'
    half.inputs[1].default_value = -0.5
    links.new(group_in.outputs["Depth"], half.inputs[0])

    drop = nodes.new("ShaderNodeCombineXYZ")
    drop.location = (-420, -400)
    links.new(half.outputs["Value"], drop.inputs["Z"])

    fill = nodes.new("GeometryNodeFillCurve")
    fill.location = (-400, 0)
    _set_fill_mode(fill)
    links.new(group_in.outputs["Geometry"], fill.inputs["Curve"])

    # Drop the slab half its depth so it straddles the plane it was drawn
    # on, and cuts geometry on both sides of it.
    lower = nodes.new("GeometryNodeTransform")
    lower.location = (-200, 0)
    links.new(drop.outputs["Vector"], lower.inputs["Translation"])
    links.new(fill.outputs["Mesh"], lower.inputs["Geometry"])

    up = nodes.new("FunctionNodeInputVector")
    up.location = (-200, -220)
    up.vector = (0.0, 0.0, 1.0)

    extrude = nodes.new("GeometryNodeExtrudeMesh")
    extrude.location = (0, 0)
    extrude.mode = 'FACES'
    links.new(group_in.outputs["Depth"], extrude.inputs["Offset Scale"])
    links.new(lower.outputs["Geometry"], extrude.inputs["Mesh"])
    links.new(up.outputs["Vector"], extrude.inputs["Offset"])

    cap = nodes.new("GeometryNodeFillCurve")
    cap.location = (-400, 220)
    _set_fill_mode(cap)
    links.new(group_in.outputs["Geometry"], cap.inputs["Curve"])

    cap_low = nodes.new("GeometryNodeTransform")
    cap_low.location = (-200, 220)
    links.new(drop.outputs["Vector"], cap_low.inputs["Translation"])
    links.new(cap.outputs["Mesh"], cap_low.inputs["Geometry"])

    flip = nodes.new("GeometryNodeFlipFaces")
    flip.location = (0, 220)
    links.new(cap_low.outputs["Geometry"], flip.inputs["Mesh"])

    join = nodes.new("GeometryNodeJoinGeometry")
    join.location = (200, 0)
    links.new(extrude.outputs["Mesh"], join.inputs["Geometry"])
    links.new(flip.outputs["Mesh"], join.inputs["Geometry"])

    # Stamp the draw order onto the slab itself. Every floor reads the whole
    # cutter collection, so the only place the two can meet is on the
    # geometry: an object property does not cross into Geometry Nodes.
    stamp = nodes.new("GeometryNodeStoreNamedAttribute")
    stamp.location = (300, 0)
    stamp.data_type = 'FLOAT'
    stamp.domain = 'POINT'
    stamp.inputs["Name"].default_value = CUT_SEQUENCE_ATTRIBUTE
    links.new(join.outputs["Geometry"], stamp.inputs["Geometry"])
    links.new(group_in.outputs["Sequence"], stamp.inputs["Value"])

    links.new(stamp.outputs["Geometry"], group_out.inputs["Geometry"])


def ensure_cutter_group(rebuild=False):
    return ensure_group(CUTTER_NODE_GROUP_NAME, _build_cutter, rebuild=rebuild)


def attach_cutter_modifier(obj):
    return attach_modifier(obj, CUTTER_MODIFIER_NAME, ensure_cutter_group())


def ensure_floor_group(rebuild=False):
    return ensure_group(NODE_GROUP_NAME, _build, rebuild=rebuild)


def attach_floor_modifier(obj):
    return attach_modifier(obj, MODIFIER_NAME, ensure_floor_group())
