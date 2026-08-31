"""WorkSpaceTool registration, draw handlers, and reload hygiene.

The tool system holds references that outlive a module reload, and several
of its internals are NamedTuples or private maps. Everything needed to
register a tool cleanly -- and to clean up after a previous load -- lives
here so each tool does not re-solve it.
"""

import bpy


def active_tool_is(context, idname):
    import bl_ui.space_toolsystem_common as tsc

    try:
        active = tsc.ToolSelectPanelHelper.tool_active_from_context(context)
    except Exception:
        return False
    return active is not None and active.idname == idname


_HANDLER_REGISTRY_KEY = "_geodraft_draw_handlers"


def _handler_registry():
    """Draw-handler handles, stored where a module reload cannot lose them.

    Blender offers no way to enumerate registered draw handlers, so a handle
    dropped on the floor leaks forever: the callback keeps running, bound to
    the *old* module's state, which shows up as a second frozen copy of the
    overlay next to the live one. Module-level storage is not enough because
    a reload builds fresh module globals; driver_namespace survives, so the
    new instance can find and remove what the old one left behind.
    """
    registry = bpy.app.driver_namespace.get(_HANDLER_REGISTRY_KEY)
    if registry is None:
        registry = {}
        bpy.app.driver_namespace[_HANDLER_REGISTRY_KEY] = registry
    return registry


class DrawHandlers:
    """Owns a set of SpaceView3D draw handlers and an optional timer.

    `name` must be stable across reloads (a tool idname is ideal): it is the
    key under which handles are recorded so a later load can clean them up.
    """

    def __init__(self, name):
        self.name = name
        self._timer = None

    @property
    def _handles(self):
        return _handler_registry().setdefault(self.name, {})

    def add(self, key, callback, kind):
        self.remove(key)
        self._handles[key] = bpy.types.SpaceView3D.draw_handler_add(
            callback, (), 'WINDOW', kind,
        )

    def remove(self, key):
        handle = self._handles.pop(key, None)
        if handle is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
            except Exception:
                pass

    def add_timer(self, callback):
        if not bpy.app.timers.is_registered(callback):
            bpy.app.timers.register(callback, persistent=True)
        self._timer = callback

    def clear(self):
        if self._timer is not None and bpy.app.timers.is_registered(
            self._timer
        ):
            try:
                bpy.app.timers.unregister(self._timer)
            except Exception:
                pass
        self._timer = None
        for key in list(self._handles):
            self.remove(key)


def drop_stale_cursor(idname, space_type='VIEW_3D'):
    """Remove the paint cursor left behind by a previous load.

    _activate_by_item registers the cursor with the ToolDef captured in its
    args and stashes the handle in a module-level map keyed by
    (space_type, view_type). Re-registering a tool does not touch that
    handle, so without this a reload leaves the old callback live -- and a
    full unregister leaves it pointing at code that no longer exists.

    Skips the clear when some *other* tool is demonstrably active, so we do
    not rip the cursor out from under it. When the active tool cannot be
    determined -- tool_active_from_context needs a space_data that a script
    or headless context may not have -- it clears anyway: another tool's
    cursor returns the moment it is re-activated, whereas a handler pointing
    at unloaded code raises on every mouse move.
    """
    import bl_ui.space_toolsystem_common as tsc

    try:
        active = tsc.ToolSelectPanelHelper.tool_active_from_context(
            bpy.context,
        )
        if active is not None and active.idname != idname:
            return
    except Exception:
        pass

    handle_map = getattr(tsc._activate_by_item, "_cursor_draw_handle", None)
    if not handle_map:
        return

    for key in [k for k in handle_map if k[0] == space_type]:
        handle = handle_map.pop(key, None)
        if handle is not None:
            try:
                bpy.types.WindowManager.draw_cursor_remove(handle)
            except Exception:
                pass


def drop_stale_tool(tool_cls):
    """Unregister a tool left behind by a previous load of its module.

    register_tool() raises if the bl_idname is taken, and reload-on-save
    hands a *new* class object each time, so the stale registration can only
    be found by scanning the registry for the matching idname.
    """
    from bl_ui.space_toolsystem_common import ToolSelectPanelHelper, ToolDef

    cls = ToolSelectPanelHelper._tool_class_from_space_type(
        tool_cls.bl_space_type,
    )
    if cls is None:
        return

    idname = tool_cls.bl_idname
    tools = cls._tools[tool_cls.bl_context_mode]

    # ToolDef is itself a NamedTuple, so isinstance(entry, tuple) is True for
    # a plain tool as well as for a *group* of tools. Test for ToolDef FIRST;
    # treating a ToolDef as a group and recursing into it explodes it into
    # its fields and silently corrupts the whole toolbar registry.
    def _strip(seq):
        out = []
        for entry in seq:
            if isinstance(entry, ToolDef):
                if entry.idname == idname:
                    continue
                out.append(entry)
            elif isinstance(entry, tuple):
                inner = tuple(
                    item for item in entry
                    if not (
                        isinstance(item, ToolDef) and item.idname == idname
                    )
                )
                if inner:
                    out.append(inner)
            else:
                out.append(entry)
        return out

    tools[:] = _strip(tools)


def register_tool(tool_cls, **kwargs):
    """Register, clearing a stale registration of the same idname first.

    Note on placement: passing `after=` an idname that sits inside a group
    inserts the tool *into that group*, where it is only reachable from that
    group's dropdown. Appending with `separator=True` and no `after` gives a
    top-level toolbar entry, which is how Construction Lines places itself.
    """
    try:
        bpy.utils.register_tool(tool_cls, **kwargs)
    except Exception:
        drop_stale_tool(tool_cls)
        bpy.utils.register_tool(tool_cls, **kwargs)


def unregister_tool(tool_cls):
    try:
        bpy.utils.unregister_tool(tool_cls)
    except Exception:
        drop_stale_tool(tool_cls)
