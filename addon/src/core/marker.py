"""Default placement marker: a lathed cone/stem/cap.

The silhouette is the profile authored as `arrow_widget` in the project
scene (edges revolved by a Screw modifier, axis Z, 16 steps), baked in here
as (radius, z) pairs so the addon does not depend on that object existing.

Shared by every placement tool. Only the profile lives here; the revolving,
shading and silhouette all come from .lathe, so a tool wanting a different
marker just builds another Lathe.
"""

from .lathe import Lathe

PROFILE_HEIGHT = 3.0229

# Cone tip at the ground -> cone -> stem, stopping at the text cut-out.
LOWER = (
    (0.0000, 0.0000),
    (0.1201, 0.4529),
    (0.1201, 0.5186),
    (0.0305, 0.5608),
    (0.0305, 1.4602),
    (0.0000, 1.4602),
)

# Stem resumes above the cut-out -> rounded cap.
UPPER = (
    (0.0000, 1.8586),
    (0.0305, 1.8586),
    (0.0305, 2.8517),
    (0.0926, 2.8985),
    (0.0926, 3.0000),
    (0.0000, 3.0229),
)

# Midpoint of the cut-out, where the height label sits.
TEXT_ANCHOR_Z = (1.4602 + 1.8586) * 0.5

ARROW = Lathe((LOWER, UPPER), PROFILE_HEIGHT)


def text_anchor(base, height):
    """World point at the centre of the stem's text cut-out."""
    return ARROW.anchor(base, height, TEXT_ANCHOR_Z)
