"""Hold a key to summon a value scrubber: drag, or type, to set a number.

Layout follows doc/design/scrubbermockup.excalidraw: a half-width track
centred in the region, tall labelled ticks at each end and the midpoint,
shorter ticks subdividing each half into quarters, and a handle at the
current value.

Interaction, while the key is held:

  drag left/right   change the value
  Ctrl              snap to coarse increments
  type digits       set the value directly
  release / Enter   commit
  Escape            revert to the value held when the scrub began

The value is written live so the viewport previews every intermediate
state; release confirms, and Escape puts back what was there. The scrubber
only ends the *scrub* -- whatever modal was running underneath, such as an
in-progress circle, carries on.

The track's range is presentation only. Typing is not bound by it: any
non-negative number is accepted, and the handle simply parks at the end of
the track when the value runs past it.
"""

import math

import blf
import bpy

from . import draw
from .cursor import freeze_pointer, thaw_pointer
from .numeric import digit_for
from .placement import refresh_cursor

# Track geometry, in fractions of the region.
TRACK_WIDTH = 0.5
TRACK_Y = 0.18
MAJOR_TICK = 28.0
MINOR_TICK = 20.0
MINOR_DIVISIONS = 8

COLOR_TRACK = (0.85, 0.87, 0.90, 0.95)
# The stretch of track below the hard minimum. Drawn rather than omitted so
# the range keeps its familiar shape -- a circle scrubber that started at 3
# put its midpoint at an unreadable 34 -- while showing that the low end
# cannot be reached.
COLOR_DISABLED = (0.45, 0.47, 0.50, 0.55)
COLOR_HANDLE = (0.95, 0.70, 0.15, 1.0)
COLOR_TEXT = (1.0, 1.0, 1.0, 0.95)
COLOR_TYPED = (0.35, 0.95, 0.45, 1.0)


class VIEW3D_OT_value_scrubber(bpy.types.Operator):
    """While held, drag or type to set an integer tool setting."""

    bl_idname = "view3d.geodraft_value_scrubber"
    bl_label = "Scrub Value"
    bl_options = {'INTERNAL'}

    settings_path: bpy.props.StringProperty(default="")
    prop_name: bpy.props.StringProperty(default="")
    key: bpy.props.StringProperty(default="F")
    label: bpy.props.StringProperty(default="Value")
    # Presentation range for the track. Typing may exceed it.
    ui_min: bpy.props.IntProperty(default=3)
    ui_max: bpy.props.IntProperty(default=64)
    coarse_step: bpy.props.IntProperty(default=8)
    hard_min: bpy.props.IntProperty(default=3)

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'

    # --- value plumbing ---------------------------------------------------

    def _settings(self, context):
        return getattr(context.scene, self.settings_path, None)

    def _read(self, context):
        return int(getattr(self._settings(context), self.prop_name))

    def _write(self, context, value):
        value = max(self.hard_min, int(round(value)))
        settings = self._settings(context)
        if int(getattr(settings, self.prop_name)) != value:
            setattr(settings, self.prop_name, value)
            # Live preview: everything downstream reads the property, so
            # pushing it now is what makes the change visible mid-drag.
            refresh_cursor(context, self.settings_path)
        self.value = value

    # --- modal ------------------------------------------------------------

    def invoke(self, context, event):
        if self._settings(context) is None:
            return {'CANCELLED'}

        self.start_value = self._read(context)
        self.value = self.start_value
        self.start_x = event.mouse_region_x
        self.typed = ""

        # For the duration of the hold the mouse is a slider, not a pointer.
        # Pinning it keeps the placement marker where the user left it, and
        # -- because every tool reads the pointer through the same freeze --
        # a click during the scrub still lands on the marker rather than on
        # wherever the drag has since carried the mouse.
        freeze_pointer((event.mouse_region_x, event.mouse_region_y))

        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_callback, (self, context), 'WINDOW', 'POST_PIXEL',
        )
        context.area.tag_redraw()
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        area = context.area

        if event.type == self.key and event.value == 'RELEASE':
            return self._finish(context)

        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            return self._finish(context)

        if event.type == 'ESC' and event.value == 'PRESS':
            self._write(context, self.start_value)
            return self._finish(context, cancelled=True)

        if event.value == 'PRESS':
            digit = digit_for(event.type)
            if digit is not None:
                # Typing takes over from the drag until the mouse moves.
                self.typed += digit
                self._write(context, int(self.typed))
                if area:
                    area.tag_redraw()
                return {'RUNNING_MODAL'}
            if event.type == 'BACK_SPACE':
                self.typed = self.typed[:-1]
                if self.typed:
                    self._write(context, int(self.typed))
                if area:
                    area.tag_redraw()
                return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            self.typed = ""
            width = max(1.0, context.region.width * TRACK_WIDTH)
            span = max(1, self.ui_max - self.ui_min)
            delta = (event.mouse_region_x - self.start_x) / width * span
            value = self.start_value + delta
            if event.ctrl:
                # floor(x + 0.5), not round(): round() is banker's rounding,
                # which sends exact halves to the *even* multiple -- 20 would
                # snap down to 16 rather than up to 24.
                step = max(1, self.coarse_step)
                value = math.floor(value / step + 0.5) * step
            self._write(context, value)
            if area:
                area.tag_redraw()
            return {'RUNNING_MODAL'}

        # Navigation and everything else carries on underneath.
        return {'PASS_THROUGH'}

    def _finish(self, context, cancelled=False):
        thaw_pointer()
        if getattr(self, "_handle", None) is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(
                    self._handle, 'WINDOW',
                )
            except Exception:
                pass
            self._handle = None
        if context.area:
            context.area.tag_redraw()
        if not cancelled:
            self.report(
                {'INFO'}, "{}: {}".format(self.label, self.value),
            )
        return {'FINISHED'}


def _draw_callback(op, context):
    region = context.region
    if region is None:
        return

    width = region.width * TRACK_WIDTH
    x0 = (region.width - width) * 0.5
    x1 = x0 + width
    y = region.height * TRACK_Y

    span = max(1, op.ui_max - op.ui_min)

    def value_at(fraction):
        return op.ui_min + span * fraction

    def color_for(fraction):
        return (
            COLOR_DISABLED if value_at(fraction) < op.hard_min
            else COLOR_TRACK
        )

    # The track in two stretches, so the unreachable low end reads as
    # unreachable rather than as part of the range.
    disabled = min(1.0, max(0.0, (op.hard_min - op.ui_min) / span))
    xd = x0 + width * disabled
    if disabled > 0.0:
        draw.draw_lines([(x0, y), (xd, y)], COLOR_DISABLED, width=1.6)
    draw.draw_lines([(xd, y), (x1, y)], COLOR_TRACK, width=1.6)

    def tick(fraction, height):
        x = x0 + width * fraction
        draw.draw_lines(
            [(x, y - height * 0.5), (x, y + height * 0.5)],
            color_for(fraction), width=1.6,
        )
        return x

    for i in range(1, MINOR_DIVISIONS):
        if i * 2 == MINOR_DIVISIONS:
            continue
        tick(i / MINOR_DIVISIONS, MINOR_TICK)

    blf.size(0, 13)
    for fraction in (0.0, 0.5, 1.0):
        x = tick(fraction, MAJOR_TICK)
        text = str(int(round(value_at(fraction))))
        text_w, text_h = blf.dimensions(0, text)
        blf.color(0, *(
            COLOR_DISABLED if value_at(fraction) < op.hard_min else COLOR_TEXT
        ))
        blf.position(0, x - text_w * 0.5, y - MAJOR_TICK - text_h, 0.0)
        blf.draw(0, text)

    # The handle parks at the end of the track once the value runs past the
    # presentation range; the readout still shows the real number.
    fraction = min(1.0, max(0.0, (op.value - op.ui_min) / span))
    hx = x0 + width * fraction
    draw.draw_lines(
        [(hx, y - MAJOR_TICK * 0.75), (hx, y + MAJOR_TICK * 0.75)],
        COLOR_HANDLE, width=3.0,
    )

    readout = op.typed if op.typed else str(op.value)
    blf.size(0, 26)
    blf.color(0, *(COLOR_TYPED if op.typed else COLOR_HANDLE))
    text_w, _ = blf.dimensions(0, readout)
    blf.position(0, hx - text_w * 0.5, y + MAJOR_TICK * 0.75 + 10.0, 0.0)
    blf.draw(0, readout)

    blf.size(0, 12)
    blf.color(0, *COLOR_TEXT)
    hint = "{}   drag  ·  Ctrl snap  ·  type  ·  release to apply".format(
        op.label,
    )
    hint_w, _ = blf.dimensions(0, hint)
    blf.position(0, (region.width - hint_w) * 0.5, y + 64.0, 0.0)
    blf.draw(0, hint)


def keymap_entries(settings_path, prop_name, key='F', label="Value",
                   ui_min=3, ui_max=64, coarse_step=8, hard_min=3):
    return (
        (
            VIEW3D_OT_value_scrubber.bl_idname,
            {"type": key, "value": 'PRESS'},
            {"properties": [
                ("settings_path", settings_path),
                ("prop_name", prop_name),
                ("key", key),
                ("label", label),
                ("ui_min", ui_min),
                ("ui_max", ui_max),
                ("coarse_step", coarse_step),
                ("hard_min", hard_min),
            ]},
        ),
    )


def register():
    bpy.utils.register_class(VIEW3D_OT_value_scrubber)


def unregister():
    bpy.utils.unregister_class(VIEW3D_OT_value_scrubber)
