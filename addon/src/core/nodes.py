"""Geometry Nodes group and modifier-input helpers.

Thin, version-sensitive plumbing that every GN-backed tool needs. The
awkward parts are documented here so each new tool does not rediscover them.
"""

import bpy


def new_socket(tree, name, in_out, socket_type, **kwargs):
    socket = tree.interface.new_socket(
        name=name, in_out=in_out, socket_type=socket_type,
    )
    for key, value in kwargs.items():
        setattr(socket, key, value)
    return socket


def ensure_group(name, builder, rebuild=False):
    """Fetch a node group by name, building it on first use.

    `builder(tree)` populates interface and nodes.
    """
    tree = bpy.data.node_groups.get(name)
    if tree is not None and not rebuild:
        return tree

    if tree is not None:
        tree.nodes.clear()
        tree.interface.clear()
    else:
        tree = bpy.data.node_groups.new(name, "GeometryNodeTree")

    # Survive a save/load: the group exists before any modifier holds it.
    tree.use_fake_user = True
    builder(tree)
    return tree


def attach_modifier(obj, modifier_name, tree):
    """Add (or reuse) a Nodes modifier carrying `tree`."""
    modifier = obj.modifiers.get(modifier_name)
    if modifier is None:
        modifier = obj.modifiers.new(name=modifier_name, type='NODES')
    modifier.node_group = tree
    return modifier


def set_modifier_input(modifier, socket_name, value):
    """Write a value to a node-group input by its interface name.

    Three things make this less obvious than it looks:

    - Modifier inputs are addressed by opaque identifier ("Socket_2"), not by
      label, so the name is resolved through the tree interface rather than
      hardcoding identifiers that shift whenever the group is rebuilt.
    - Blender 5.x exposes them through `modifier.properties.inputs`. The old
      `modifier[identifier] = value` subscript raises "id properties not
      supported for this type".
    - A field-capable socket is stored as an IDProperty *group* whose "value"
      key carries the scalar. The group form is tried FIRST, and that order
      matters: when the group is still empty, a bare assignment does not
      raise -- it succeeds and writes a legacy scalar that the modifier then
      silently ignores. Measured: the socket read back as 0.5 while the node
      tree still evaluated it as 0, so an extrude gated on "thickness > 0"
      never fired. Only when the group already held a value did the bare
      assignment raise and expose the problem.

    Also note: any input never written explicitly reads back as zero after
    the group is rebuilt with fresh socket identifiers. Push every input a
    tool depends on, including ones that "have a default".
    """
    tree = modifier.node_group
    if tree is None:
        return False

    for item in tree.interface.items_tree:
        if getattr(item, "in_out", None) != 'INPUT':
            continue
        if item.name != socket_name:
            continue

        inputs = modifier.properties.inputs
        try:
            inputs[item.identifier]["value"] = value
        except (TypeError, KeyError):
            # Not a group (a plain scalar socket, or not materialised yet).
            inputs[item.identifier] = value
        return True
    return False
