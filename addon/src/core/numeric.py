"""Type a number while drawing, instead of dragging for it.

A drag says "about this big". Often the answer is not about anything -- it
is 2.5 metres, because the thing being modelled is 2.5 metres. Every CAD
tool answers this the same way, by letting digits arrive mid-gesture and
taking over from the mouse, and there is no reason to make a user drag for a
number they already know.

Taking over is the important half. Once a digit has been typed, the mouse
must stop moving the value, or the number is overwritten by the next twitch
of the hand before it can be confirmed. The buffer therefore reports whether
it is `active`, and a tool that is holding one asks that before it tracks
the pointer. Clearing it hands control back.

The keys are the scrubber's, because they are the same gesture in a
different place: digits, a decimal point, Backspace to correct, Escape to
abandon the number and go back to the mouse.
"""

# The number row and the numpad spell their keys differently: ZERO..NINE
# against NUMPAD_0..NUMPAD_9, so the numpad needs its own branch rather than
# a prefix on the words.
_DIGIT_NAMES = {
    "ZERO": "0", "ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4",
    "FIVE": "5", "SIX": "6", "SEVEN": "7", "EIGHT": "8", "NINE": "9",
}

_POINT_KEYS = {"PERIOD", "NUMPAD_PERIOD", "COMMA"}


def digit_for(event_type):
    """The digit an event types, or None."""
    if event_type in _DIGIT_NAMES:
        return _DIGIT_NAMES[event_type]
    if event_type.startswith("NUMPAD_") and event_type[7:].isdigit():
        return event_type[7:]
    return None


class NumberEntry:
    """A typed number in progress."""

    __slots__ = ("text",)

    def __init__(self):
        self.text = ""

    @property
    def active(self):
        return bool(self.text)

    @property
    def value(self):
        """The number typed so far, or None when there is not one yet.

        None covers the states that are real to be in halfway through
        typing but are not numbers: nothing typed, a lone minus, a lone
        point. Python reads "2." as 2.0, which is the right answer anyway.
        A tool that gets None keeps the value it had rather than flickering
        to zero between keystrokes.
        """
        try:
            return float(self.text)
        except ValueError:
            return None

    def clear(self):
        self.text = ""

    def handle(self, event):
        """Consume a key if it belongs to the number. True when it did.

        Only PRESS is consumed. The matching RELEASE has to fall through, or
        a tool that acts on release -- placing a point, say -- would see the
        release of a digit key it never saw pressed.
        """
        if event.value != 'PRESS':
            return False

        digit = digit_for(event.type)
        if digit is not None:
            self.text += digit
            return True

        if event.type in _POINT_KEYS:
            # One point only, and a leading one means "0.".
            if "." not in self.text:
                self.text = (self.text or "0") + "."
            return True

        if event.type == 'BACK_SPACE':
            # Consumed even when empty: Backspace during a draw has no other
            # meaning, and letting it through once the buffer runs out makes
            # the key do two different things one keystroke apart.
            self.text = self.text[:-1]
            return True

        if event.type == 'MINUS' and not self.text:
            self.text = "-"
            return True

        return False
