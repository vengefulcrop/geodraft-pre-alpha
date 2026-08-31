# GeoDraft Decals

Blender 5.3 add-on: draw circles and capsules on a plane, for decal work.
A cut-down edition of GeoDraft — it ships the two generated-shape tools
and nothing else.

## Install

Drop the `addon/` folder in as an extension (it carries its own
`blender_manifest.toml`), or zip `addon/` and install the zip.

Enable this edition **or** the full GeoDraft, never both at once. The
two have different extension ids, so Blender will install them side by side,
but the tools inside them do not: both editions register the same operator
classes and the same toolbar idnames, and the second one to register wins.
Disable one before you enable the other.

## The two tools

Both live in the 3D viewport toolbar, and both build the same thing: a curve
object with a Geometry Nodes modifier that fills it. Nothing is baked — what
you drew is still the shape's definition afterwards.

**Draw Circle** — click the centre, click again for the radius. The drag
angle sets where the first vertex lands, so it sets the rotation too.

**Draw Capsule** — click a centre and a radius, then a second centre and a
radius. The result is the outline of both circles joined by their outer
tangents. Enter takes the shape as it stands, so two equal ends need only
three clicks.

While drawing either one:

| | |
|---|---|
| `Alt` | the shape cuts instead of adding |
| `F` + drag | scrub the vertex count; type digits to set it outright |
| `X` `Y` `Z` | turn the drawing plane, pivoting about the point already placed |
| `N` | orient the drawing plane to the surface under the cursor |
| `PageUp` / `PageDown` | double or halve the grid step |
| `Esc` | cancel |

## Snapping

Vertex, edge and edge-midpoint snapping follow **Blender's own magnet** in
the header — this add-on has no second set of snap checkboxes. Turn the
magnet on and pick elements there, and the cursor snaps to the polygon under
it. Turn `Snap To Grid` off in the tool header for gridless drawing.

For snapping decals onto a wall, turn on both the magnet and `Snap To
Surface` (`N`): the surface sets which plane the shape is built on, the
magnet places the point on it.

## What is not here

The research notes and design documents are not in this edition. The source
still cites them by path in a few comments, because those citations say
where a decision came from and are worth keeping. The documents themselves
live in the full add-on.

The wall tool and the free-hand polygon tool are stripped from this edition,
not hidden. A capsule has no post-creation drag handles yet, so a capsule is
redrawn rather than edited; a circle has its two (centre and radius).
