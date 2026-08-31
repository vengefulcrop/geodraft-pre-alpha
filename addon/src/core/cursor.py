"""Shared cursor/sketch state for the viewport overlay.

Two producers write here -- the tool's paint cursor (when idle) and the draw
modal (while a polyline is in progress) -- and the tool's POST_VIEW /
POST_PIXEL handlers are the single consumer.

Centralising it is what stops the two from drawing competing widgets: the
modal used to render its own 2D cursor while the paint cursor kept drawing
the 3D one, so both appeared once the first point went down. Now the modal
only updates state and the same handler draws everything.
"""

import time

from .view import GROUND

STATE = {
    # The surface being drawn on. Defaults to the world ground plane; the
    # axis-plane override swaps it while X or Y is toggled on.
    "plane": GROUND,
    # While set, the plane is owned by something explicit -- the X/Y toggle,
    # or an in-progress polyline -- and automatic surface orientation must
    # not overwrite it.
    "plane_locked": False,
    # Which world axis the plane was toggled to ('X'/'Y'), or None. Kept so
    # pressing the same key again knows to toggle back off, rather than
    # re-applying the plane it is already on.
    "axis": None,
    # True while the polyline being drawn will subtract rather than add.
    "subtract": False,
    # What geometry snapping can see from here: (candidates, winner,
    # nearness). `nearness` runs 0..1 and is 1 when the cursor is exactly on
    # the winner, which is what grows and colours its highlight.
    "snap_preview": None,
    # One line of key hints for the bottom of the viewport, and the number
    # being typed, if any. Both are published by whatever is running: the
    # hints change per drawing stage, and only the stage knows.
    "hint": None,
    "typed": None,
    # Ctrl held: invert whether geometry snapping is active.
    "snap_forced": False,
    # Shift held: invert whether the grid quantises the point.
    "grid_suppressed": False,
    # Snapped ground point under the cursor, or None when there is no hit.
    "base": None,
    "cell": 0.0,
    "point_size": 8.0,
    # Polyline in progress (empty when idle).
    "points": [],
    "hover": None,
    "closed": False,
    # Which points get a ring drawn on them. None means "every sketch
    # point"; an explicit list lets a generated shape ring only its real
    # handles.
    "ring_points": None,
    # A circle in progress, stored as parameters rather than baked points so
    # the overlay can regenerate it at draw time -- changing the segment
    # count then shows immediately instead of waiting for a mouse move.
    "circle": None,
    # A capsule in progress: (centre_a, radius_a, centre_b, radius_b),
    # stored as parameters for the same reason a circle is.
    "capsule": None,
    # An extra construction line, e.g. a circle's centre-to-rim radius.
    "guide": None,
    # True while the cursor is inside the polyline's first point's disk, i.e.
    # clicking would close the loop. Drives the widget's bob animation.
    "closing": False,
    # Clock the bob is measured from, reset on every entry into `closing`.
    "closing_since": None,
    # World point every widget is pinned to while the freeze is on, or None.
    # Deliberately a world point and not a screen one: the freeze exists so
    # the *view* can be moved, and a pinned screen position resolves to a
    # different world point on every orbit -- which is the widget walking
    # away, the exact thing the freeze is for.
    "widget_freeze": None,
    # Region-space (x, y) the pointer is pinned to, or None when it follows
    # the mouse. Set while a modal borrows the mouse for something other than
    # pointing -- scrubbing a value, say -- so the marker holds its place and
    # a click during that borrowed time still means where the marker is.
    "pointer_freeze": None,
    # True once something has asked to thaw but the mouse has not yet moved.
    # The freeze survives until it does; see thaw_pointer.
    "pointer_thawing": False,
}


def set_cursor(base, cell, point_size=None):
    STATE["base"] = base
    STATE["cell"] = cell
    if point_size is not None:
        STATE["point_size"] = point_size


def set_sketch(points, hover, closed=False, closing=False, rings=None):
    STATE["points"] = points
    STATE["hover"] = hover
    STATE["closed"] = closed
    STATE["ring_points"] = rings

    # Restart the bob's clock on every entry, rather than letting a free
    # running global phase decide where the animation picks up -- otherwise
    # re-entering the disk snaps the widget to whatever height the cycle
    # happened to be at.
    was_closing = STATE["closing"]
    STATE["closing"] = closing
    if closing and not was_closing:
        STATE["closing_since"] = time.time()
    elif not closing:
        STATE["closing_since"] = None


def set_subtract(value):
    STATE["subtract"] = bool(value)


def set_snap_preview(candidates, winner=None, nearness=0.0):
    """Publish what the snap highlight should draw, or clear it."""
    if not candidates and winner is None:
        STATE["snap_preview"] = None
    else:
        STATE["snap_preview"] = (
            list(candidates), winner, float(nearness),
        )


def set_hint(text, typed=None):
    """Publish the key hints, and any number being typed."""
    STATE["hint"] = text or None
    STATE["typed"] = typed or None


def clear_holds():
    """Forget every held-key state.

    Called when navigation takes the view, because a modifier that was part
    of a navigation gesture -- Shift to pan, Alt to orbit -- is not a hold
    on this tool, and its release goes to the navigation modal rather than
    to our keymap. Without this the state stayed on for the rest of the
    session, and the grid looked switched off for no visible reason.
    """
    STATE["snap_forced"] = False
    STATE["grid_suppressed"] = False
    STATE["subtract"] = False


def set_snap_forced(value):
    STATE["snap_forced"] = bool(value)


def set_grid_suppressed(value):
    STATE["grid_suppressed"] = bool(value)


def set_circle(centre, radius, start_angle):
    STATE["circle"] = (
        None if centre is None else (centre, radius, start_angle)
    )


def set_capsule(centre_a, radius_a, centre_b, radius_b, start_angle=0.0):
    STATE["capsule"] = (
        None if centre_a is None
        else (centre_a, radius_a, centre_b, radius_b, start_angle)
    )


def set_guide(start, end):
    STATE["guide"] = None if (start is None or end is None) else (start, end)


def clear_sketch():
    # `subtract` deliberately survives: it tracks whether Alt is *currently*
    # held, not whether a shape is in progress. Clearing it here left the
    # cursor claiming the next shape would add while the user was still
    # holding Alt to draw another cutter. The draw modal reassigns it from
    # event.alt on every event, and the keymap covers the idle gap, so it is
    # always somebody's business but never this function's.
    STATE["circle"] = None
    STATE["capsule"] = None
    STATE["ring_points"] = None
    STATE["guide"] = None
    STATE["points"] = []
    STATE["hover"] = None
    STATE["closed"] = False
    STATE["closing"] = False
    STATE["closing_since"] = None


def freeze_widgets(point):
    """Pin every widget to a world point until released."""
    STATE["widget_freeze"] = None if point is None else point.copy()


def widgets_frozen():
    return STATE.get("widget_freeze") is not None


def freeze_pointer(coord):
    """Pin the pointer to a region-space (x, y) until thawed."""
    STATE["pointer_freeze"] = (float(coord[0]), float(coord[1]))
    STATE["pointer_thawing"] = False


def thaw_pointer():
    """Release the pointer on the next real mouse move, not now.

    Releasing immediately teleports the marker: the scrub carried the mouse
    across the region, so the moment the freeze lifts the pointer is metres
    from where the marker is standing, and the *next event* -- typically the
    click meant to confirm what is on screen -- resolves at the mouse
    instead. The user sees the shape jump and commit in the same frame.

    Holding the freeze until a MOUSEMOVE arrives makes the release visible
    and the click honest: what you clicked is what was drawn, and the marker
    only leaves the marker's place when the mouse actually moves it there.
    """
    if STATE["pointer_freeze"] is not None:
        STATE["pointer_thawing"] = True


def release_pointer_on_move():
    """Finish a pending thaw. Call only from a genuine mouse move."""
    if STATE["pointer_thawing"]:
        STATE["pointer_freeze"] = None
        STATE["pointer_thawing"] = False


def pointer_coord(coord):
    """`coord`, or the frozen position when the pointer is pinned."""
    return STATE.get("pointer_freeze") or coord


def set_plane(plane, locked=False, axis=None):
    STATE["plane"] = plane
    STATE["plane_locked"] = locked
    STATE["axis"] = axis


def reset_plane():
    STATE["plane"] = GROUND
    STATE["plane_locked"] = False
    STATE["axis"] = None


def clear():
    STATE["base"] = None
    STATE["pointer_freeze"] = None
    STATE["pointer_thawing"] = False
    STATE["subtract"] = False
    STATE["snap_forced"] = False
    STATE["grid_suppressed"] = False
    STATE["snap_preview"] = None
    STATE["widget_freeze"] = None
    STATE["hint"] = None
    STATE["typed"] = None
    reset_plane()
    clear_sketch()
