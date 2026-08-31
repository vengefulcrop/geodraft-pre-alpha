"""Scene-scale conversion.

The project's imported kit is authored in game units but sits in Blender at
1:100 -- measured: Floor384 is 3.84 BU across, S_LDKIT_Block_3072 is 30.72.
Every authored dimension must be converted or geometry (and the viewport
overlay drawn from it) comes out 100x too large.

Keep authored numbers in game units in config, and convert here at the
boundary, rather than sprinkling 0.01 through the code.
"""

UNIT_SCALE = 0.01


def to_bu(units):
    """Game units -> Blender units."""
    return units * UNIT_SCALE


def to_units(blender_units):
    """Blender units -> game units, for display."""
    return blender_units / UNIT_SCALE
