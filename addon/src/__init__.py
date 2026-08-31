"""Addon entry point (decal edition).

    core/   generic, tool-agnostic building blocks
    floor/  flat polygons filled from a drawn outline

This build ships the circle and capsule tools only. The wall tool and the
free-hand polygon tool are stripped rather than hidden: a tool that is
registered but unreachable is still code that can fail at registration, and
the point of this edition is that everything in it is finished.
"""

from . import core
from . import floor

# core first: it registers the shared operators and the settings group that
# every tool's keymap and property group expects to already exist. Getting
# that wrong is what made this edition's X, Y and Z keys do nothing.
_TOOLS = (core, floor)


def register():
    for module in _TOOLS:
        module.register()


def unregister():
    for module in reversed(_TOOLS):
        module.unregister()
