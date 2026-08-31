"""Undo/redo resync for floors.

Undo restores RNA values without running their update= callbacks, so a
floor's PropertyGroup can end up disagreeing with its GN modifier inputs.
"""

import bpy

from .config import FLOOR_MARKER_KEY
from .props import push_floor_settings


def iter_floor_objects():
    for obj in bpy.data.objects:
        if obj.type == 'CURVE' and FLOOR_MARKER_KEY in obj:
            yield obj


@bpy.app.handlers.persistent
def _resync_after_undo_redo(scene=None, depsgraph=None):
    for obj in iter_floor_objects():
        try:
            push_floor_settings(obj)
        except ReferenceError:
            continue


def register():
    bpy.app.handlers.undo_post.append(_resync_after_undo_redo)
    bpy.app.handlers.redo_post.append(_resync_after_undo_redo)


def unregister():
    for handlers in (bpy.app.handlers.redo_post, bpy.app.handlers.undo_post):
        if _resync_after_undo_redo in handlers:
            handlers.remove(_resync_after_undo_redo)
