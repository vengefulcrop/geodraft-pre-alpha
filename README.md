# GeoDraft Decals

Blender 5.3 add-on: draw flat, curve-based circles and capsules on a plane, for decal work.

## Install

Download the latest version from the Releases section.

Enable this edition or the full GeoDraft, never both at the same time. The
two have different extension ids, so Blender installs them side by side, but
they register the same operator classes and the same toolbar idnames, and
the second one to register wins.

## The tools

`3D viewport > Object Mode > leftside toolbar` 

**Draw Circle** — click the centre, click again for the radius. The drag
angle sets where the first vertex lands, so it sets the rotation too. Clicking centre then typing a number will set the radius to that value in scene units. Click LMB or press Enter to finalize operation. 

**Draw Capsule** — click a centre and a radius, then a second centre and a
radius. The result is the outline of both circles joined by their outer
tangents. Enter takes the shape as it stands, so two equal ends need only
three clicks. Typing a number after clicking a centre sets the radius of the first circle. Confirming and typing a number again will put the centre of the next circle the specified amount of units away, in the direction of the mouse cursor. Confirming and typing a number after this operation will set the radius of the second circle. 

## Top Bar options:

**Grid Step** — scale scene grid by this much, same option can be found natively in the overlay menu of Blender. 

**Grid** — whether to use the snapping grid that matches the scene grid or not. 

**Straight To Mesh** — immediately converts the drawing result to a polygon mesh upon drawing completion. 

**Circle Segments** — set the amount of circle vertices, same as the F scrubber menu. 

**Thickness** — Solidify the final geometry by this amount in scene units, upward from the drawing plane. 

##  Keymap:

| | |
|---|---|
| `Alt` hold | makes the shape cut instead of add. It subtracts from the GeoDraft shapes it overlaps, whether they are still curves or have been converted to meshes. Everything else in the scene is left alone |
| `F` hold + drag left-right | change the vertex count; type digits to set it to any value; hold Ctrl and drag to snap to multiples of 8. |
| `Shift` hold | inverts the state of the Grid toggle while held |
| `X` `Y` `Z` | align the drawing plane to one of the three axes with its positive normal facing the camera. If a point is already placed, the plane will be re-oriented around that point |
| `N` | orient the drawing plane dynamically to the surface normal under the cursor |
| `Ctrl` hold | inverts geometry snapping while held. Blender's default has the magnet on with Grid as its only element, and nothing is snapping to geometry then, so Ctrl turns vertex and edge snapping on. If geometry snapping is already running, Ctrl suppresses it instead. Which elements count comes from Blender's own snap menu, and this works with or without `N` |
| `V` toggle | Freeze all in-world widgets, such as the grid and the arrow pointer, in place, so that you can navigate freely, while they remain static. |
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
