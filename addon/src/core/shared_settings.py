"""Settings that follow the user from one tool to the next.

Each tool owns its own settings group, which is right for what differs -- a
wall's alignment means nothing to a circle. But some settings are not really
about the tool at all: the grid step, whether to snap to surfaces, how the
overlay looks. Setting the grid to 4 and then switching tools should not
silently put you back on 1, because the user was not configuring the tool,
they were configuring how they are working.

So the properties named here mirror across every registered tool the moment
one of them changes. Mirroring rather than sharing one group keeps each
tool's own defaults intact and means a tool can simply not define a property
it does not use.

Which drawing plane is active does not appear here: it lives in cursor.STATE,
which is already global, so it carries across tools on its own.

Off by default is the wrong default -- carrying over is what people expect
and only surprises when it is absent -- so the option exists to turn it off,
not on.
"""

import bpy

# Same name, same meaning, in every tool that has them. Deliberately not
# `thickness` (a wall's is not a floor's) and not `veil_height` (each tool
# picks a height that suits its own geometry).
SHARED_PROPERTIES = (
    "grid_multiplier",
    "snap_to_grid",
    "straight_to_mesh",
    "surface_snap",
    "hollow_widget",
    "show_veil",
    "veil_alpha",
)

# Settings paths on the Scene, filled in as tool packages register.
_PATHS = []

# Mirroring assigns to other groups, and each assignment fires its own update
# callback. Without this the first change would recurse through every tool.
_MIRRORING = False


def register_settings_path(path):
    if path not in _PATHS:
        _PATHS.append(path)


def unregister_settings_path(path):
    if path in _PATHS:
        _PATHS.remove(path)


def sync_enabled(context):
    shared = getattr(context.scene, "geodraft_shared", None)
    return bool(getattr(shared, "sync_tools", True))


def mirror(name):
    """An `update=` callback that copies this property to the other tools.

    One callback per property, because a property update callback is not told
    which property fired it.
    """

    def _update(self, context):
        global _MIRRORING
        if _MIRRORING or context is None or not sync_enabled(context):
            return

        value = getattr(self, name)
        _MIRRORING = True
        try:
            for path in _PATHS:
                other = getattr(context.scene, path, None)
                # A tool that does not have this property simply opts out.
                if other is None or other == self or not hasattr(other, name):
                    continue
                if getattr(other, name) != value:
                    setattr(other, name, value)
        finally:
            _MIRRORING = False

    return _update


def push_all(context, source_path):
    """Force one tool's shared settings out to the rest.

    Used when sync is switched back on, so enabling it takes effect at once
    rather than on the next time something happens to change.
    """
    source = getattr(context.scene, source_path, None)
    if source is None:
        return
    for name in SHARED_PROPERTIES:
        if hasattr(source, name):
            mirror(name)(source, context)


class GeoDraftSharedSettings(bpy.types.PropertyGroup):
    """Cross-tool options."""

    sync_tools: bpy.props.BoolProperty(
        name="Share Between Tools",
        description=(
            "Keep the grid step, surface snapping and overlay settings the "
            "same across the circle and capsule tools"
        ),
        default=True,
    )


def draw_option(layout, context):
    shared = getattr(context.scene, "geodraft_shared", None)
    if shared is not None:
        layout.prop(shared, "sync_tools")


def register():
    bpy.utils.register_class(GeoDraftSharedSettings)
    bpy.types.Scene.geodraft_shared = bpy.props.PointerProperty(
        type=GeoDraftSharedSettings,
    )


def unregister():
    del bpy.types.Scene.geodraft_shared
    bpy.utils.unregister_class(GeoDraftSharedSettings)
