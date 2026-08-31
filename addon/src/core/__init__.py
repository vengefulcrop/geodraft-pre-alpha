"""Generic, tool-agnostic building blocks.

Nothing in here knows what a wall is. Each module is meant to be reused by
the next procedural tool (fences, roads, paths, floor plates) without edits:

    units     scene-scale conversion between authored and Blender units
    view      viewport resolution, ground projection, grid snap, navigation
    draw      GPU overlay primitives, 2D and world-space
    lathe     revolved widget geometry with an analytic silhouette
    cursor    shared cursor/sketch state between producers and the drawer
    polyline  modal ground-grid polyline drawing
    handles   draggable, grid-snapped control points on a curve
    nodes     node-group build and modifier-input helpers
    toolkit   WorkSpaceTool registration, draw handlers, reload cleanup

The tool-specific half lives in ../wall/ and ../floor/.

Some of these modules register classes of their own -- the axis-plane and
surface-snap operators, the value scrubber, the subtract hold, and the
cross-tool settings group. They belong to no single tool and must register
exactly once, so this package registers them and the tool packages do not.

That used to be the wall package's job, with a comment explaining that it
owned them because somebody had to. It cost an edition: a build that shipped
the floor tools without the wall package registered no axis-plane operator,
so every X/Y/Z keymap entry pointed at an operator that did not exist and
the keys silently did nothing.
"""

from . import axis_plane
from . import scrubber
from . import shared_settings
from . import snap_holds
from . import subtract_hold
from . import surface_snap
from . import widget_freeze

# shared_settings first: the tool property groups call into it while they
# register, to announce their settings path.
_MODULES = (
    shared_settings, axis_plane, surface_snap, scrubber, subtract_hold,
    snap_holds, widget_freeze,
)


def register():
    for module in _MODULES:
        module.register()


def unregister():
    for module in reversed(_MODULES):
        module.unregister()
