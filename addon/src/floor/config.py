"""Floor-specific identifiers and authored dimensions."""

from ..core.units import to_bu

FLOOR_MARKER_KEY = "is_geodraft_floor"

NODE_GROUP_NAME = "GeoDraftFloor"
MODIFIER_NAME = "GeoDraftFloor"
SETTINGS_PATH = "geodraft_floor_tool"

# Authored in game units, used in Blender units.
THICKNESS_UNITS = 0.0        # flat by default
MARKER_HEIGHT_UNITS = 96.0   # the placement marker is just a cursor here,
                             # so its height is chosen to read well, not to
                             # mean anything about the geometry.
VEIL_HEIGHT_UNITS = 32.0

# Subtractive polygons are swept into a slab this deep, centred on their
# plane, so the cutter is a solid that spans whatever it cuts. A flat cutter
# does nothing: a coplanar flat-on-flat difference splits faces but removes
# none (measured -- a 4x4 minus a 2x2 came back with area 16, not 12).
#
# Only deep enough to clear the plates it cuts, not a full-height prism: a
# cutter is a tool the user has to see past, so it should barely protrude.
# Exposed per cutter, since a thicker slab occasionally needs a deeper cut.
CUTTER_DEPTH_UNITS = 48.0

# A cutter cuts what was already there when it was drawn, and nothing drawn
# afterwards -- so both floors and cutters carry a draw order, and each floor
# subtracts only the cutters whose order is greater than its own. The cutter
# stores its number as this attribute so the floor can filter the realized
# collection; a plain object property would not survive into Geometry Nodes.
CUT_SEQUENCE_ATTRIBUTE = "geodraft_cut_sequence"

# Stands in for "newer than anything" when an object predates draw ordering,
# which keeps cutters in existing scenes cutting rather than silently
# switching off. Far above any real count, and exactly representable as a
# float, since the attribute is a float.
LEGACY_SEQUENCE = 1 << 24

CUTTER_COLLECTION = "GeoDraftFloorCutters"
CUTTER_NODE_GROUP_NAME = "GeoDraftFloorCutter"
CUTTER_MODIFIER_NAME = "GeoDraftFloorCutter"

# Objects carrying this property are skipped by surface-normal orientation.
# Cutters are construction tools, not surfaces to build against.
RAYCAST_IGNORE_KEY = "geodraft_ignore_raycast"

# Marks a polygon whose points are generated, not hand-placed. Its handles
# are the centre and one radius point, not one per vertex.
CIRCLE_KEY = "geodraft_circle"

# Marks a capsule: the hull of two circles. Generated like a circle, so its
# vertices are not hand-placed either. It has no handle group of its own yet,
# which is why it only needs to be recognisable enough to be *excluded* from
# the per-point one -- four handles (two centres, two radii) is a bigger
# piece of work than the tool needs to be useful.
CAPSULE_KEY = "geodraft_capsule"

DEFAULT_CIRCLE_SEGMENTS = 24
MIN_CIRCLE_SEGMENTS = 3
MAX_CIRCLE_SEGMENTS = 256

ROLE_ITEMS = (
    ('ADD', "Add", "This polygon is solid"),
    ('SUBTRACT', "Subtract", "This polygon cuts the polygons it overlaps"),
)

DEFAULT_THICKNESS = to_bu(THICKNESS_UNITS)
CUTTER_DEPTH = to_bu(CUTTER_DEPTH_UNITS)
MARKER_HEIGHT = to_bu(MARKER_HEIGHT_UNITS)
VEIL_HEIGHT = to_bu(VEIL_HEIGHT_UNITS)
