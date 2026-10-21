"""
Look of the app: light gray, thick black borders, plain centred lowercase text.
"""

# ---------------------------------------------------------------------------
# THEME
#
#   All colors, fonts and sizes of the GUI live here.
#   Sizes are in "design pixels" at 100 % display scaling; Theme.px() scales
#   them for high-DPI Windows screens so the layout looks the same everywhere.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

import sys
import tkinter.font as tkfont


# ---------------------------------------------------------------------------
# 2. COLORS
# ---------------------------------------------------------------------------

BACKGROUND = "#d9d9d9"       # window and panels
BORDER = "#000000"

INK = "#111111"
INK_SECONDARY = "#4a4a48"
INK_MUTED = "#6e6d69"

FIELD = "#f4f4f2"            # entry boxes
FIELD_INVALID = "#f3c4bd"

HOVER = "#cbcbcb"
SELECTED = "#b3b3b3"         # selected road card
ACTIVE = "#111111"           # selected toggle (dark fill, light text)
ACTIVE_TEXT = "#f4f4f2"

PASS = "#006300"             # text color for a passed limit (with a check mark)
FAIL = "#b3261e"             # text color for a failed limit (with a cross)
PROGRESS = "#4a4a48"


# ---------------------------------------------------------------------------
# 3. SIZES (design pixels at 100 % scaling)
# ---------------------------------------------------------------------------

BORDER_WIDTH = 3             # thick black panel borders
THIN_BORDER = 2              # buttons and result cells
GAP = 10                     # space between panels
PAD = 10                     # space inside panels

LEFT_COLUMN_WIDTH = 440      # parameters panel
CARD_HEIGHT = 54             # road profile cards

WINDOW_SIZE = (1480, 940)
MIN_WINDOW_SIZE = (1180, 760)


# ---------------------------------------------------------------------------
# 4. FONTS AND SCALING
# ---------------------------------------------------------------------------

def _font_family(root):

    available = set(tkfont.families(root))

    for name in ("Segoe UI", "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"):
        if name in available:
            return name

    return "TkDefaultFont"


class Theme:
    """Fonts and pixel scaling for one Tk root window."""

    def __init__(self, root):

        # Tk on Windows reports 96 px per inch at 100 % scaling
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)

        family = _font_family(root)

        # macOS draws points smaller, so step every size up a little there
        bump = 2 if sys.platform == "darwin" else 0

        def font(size, weight="normal"):
            return tkfont.Font(root, family=family, size=size + bump, weight=weight)

        self.title = font(15)
        self.heading = font(9, "bold")
        self.body = font(10)
        self.small = font(9)
        self.button = font(10)
        self.card = font(12)
        self.value = font(13)

    def px(self, value):
        """Design pixels -> screen pixels."""

        return int(round(value * self.scale))


def enable_dpi_awareness():
    """Sharp text on high-DPI Windows screens (call before creating Tk)."""

    if sys.platform != "win32":
        return

    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass
