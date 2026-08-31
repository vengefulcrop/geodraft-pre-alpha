"""The circle and capsule tools, and the floor geometry they build."""

from . import props
from . import ops
from . import circle_ops
from . import capsule_ops
from . import gizmos
from . import ui
from . import tool_circle
from . import tool_capsule
from . import handlers

# The scrubber and the subtract hold are registered by ..core, along with
# every other class that belongs to no single tool.
_MODULES = (
    props, ops, circle_ops, capsule_ops, gizmos, ui, tool_circle,
    tool_capsule, handlers,
)


def register():
    for module in _MODULES:
        module.register()


def unregister():
    for module in reversed(_MODULES):
        module.unregister()
