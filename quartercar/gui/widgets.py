"""
Small reusable widgets in the mockup style (flat, gray, thick black borders).
"""

# ---------------------------------------------------------------------------
# WIDGETS
#
#   Panel        bordered box with a centred title
#   FlatButton   flat bordered button (looks the same on Windows and macOS)
#   CheckBox     flat tick box
#   RoadCard     one road profile card: sketch of the profile + its name
#   ScrollFrame  vertical scrolling area with mouse-wheel support
#   ProgressBar  thin bar for sweep progress
#   ResultCell   one key number in the results bar
#   Tooltip      help text shown when hovering a label
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

import sys
import tkinter as tk
from tkinter import ttk

from ..road import profile_icon
from .theme import (
    ACTIVE, ACTIVE_TEXT, BACKGROUND, BORDER, BORDER_WIDTH, CARD_HEIGHT, FAIL, FIELD,
    HOVER, INK, INK_MUTED, INK_SECONDARY, PAD, PASS, PROGRESS, SELECTED, THIN_BORDER,
)


# ---------------------------------------------------------------------------
# 2. PANEL
# ---------------------------------------------------------------------------

class Panel(tk.Frame):
    """Box with a thick black border and a centred lowercase title."""

    def __init__(self, parent, theme, title):

        px = theme.px

        super().__init__(
            parent, bg=BACKGROUND, bd=0,
            highlightthickness=px(BORDER_WIDTH),
            highlightbackground=BORDER, highlightcolor=BORDER,
        )

        # Header: [left extras]  title  [right extras], title always centred
        self.header = tk.Frame(self, bg=BACKGROUND)
        self.header.pack(fill="x", padx=px(PAD), pady=(px(6), 0))
        self.header.columnconfigure(0, weight=1, uniform="side")
        self.header.columnconfigure(2, weight=1, uniform="side")

        self.header_left = tk.Frame(self.header, bg=BACKGROUND)
        self.header_left.grid(row=0, column=0, sticky="w")

        self.title = tk.Label(self.header, text=title, font=theme.title, bg=BACKGROUND, fg=INK)
        self.title.grid(row=0, column=1)

        self.header_right = tk.Frame(self.header, bg=BACKGROUND)
        self.header_right.grid(row=0, column=2, sticky="e")

        self.body = tk.Frame(self, bg=BACKGROUND)
        self.body.pack(fill="both", expand=True, padx=px(PAD), pady=(px(4), px(PAD)))


# ---------------------------------------------------------------------------
# 3. FLAT BUTTON
# ---------------------------------------------------------------------------

class FlatButton(tk.Label):
    """
    Flat button with a black border. Built from a Label because native
    buttons ignore colors on macOS.
    """

    def __init__(self, parent, theme, text, command, font=None, padx=12, pady=5,
                 border=THIN_BORDER):

        px = theme.px

        super().__init__(
            parent, text=text, font=font or theme.button, bg=BACKGROUND, fg=INK,
            padx=px(padx), pady=px(pady), bd=0, cursor="hand2",
            highlightthickness=px(border), highlightbackground=BORDER, highlightcolor=BORDER,
        )

        self.command = command
        self.enabled = True
        self.active = False
        self.hovered = False

        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<ButtonRelease-1>", self._click)

    def set_enabled(self, enabled):
        self.enabled = enabled
        self._paint()

    def set_active(self, active):
        self.active = active
        self._paint()

    def set_text(self, text):
        self.configure(text=text)

    def _paint(self):

        if self.active:
            background, foreground = ACTIVE, ACTIVE_TEXT
        elif not self.enabled:
            background, foreground = BACKGROUND, INK_MUTED
        elif self.hovered:
            background, foreground = HOVER, INK
        else:
            background, foreground = BACKGROUND, INK

        self.configure(bg=background, fg=foreground, cursor="hand2" if self.enabled else "arrow")

    def _enter(self, _event):
        self.hovered = True
        self._paint()

    def _leave(self, _event):
        self.hovered = False
        self._paint()

    def _click(self, event):

        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()

        if self.enabled and inside and self.command is not None:
            self.command()


class CheckBox(tk.Label):
    """Square tick box in the same flat style (scales with the font on any screen)."""

    def __init__(self, parent, theme, variable, command=None):

        super().__init__(
            parent, text="", font=theme.small, width=2, bg=FIELD, fg=INK, bd=0,
            cursor="hand2", highlightthickness=1, highlightbackground=BORDER,
        )

        self.variable = variable
        self.command = command

        variable.trace_add("write", lambda *_: self._paint())
        self.bind("<ButtonRelease-1>", self._toggle)

        self._paint()

    def _paint(self):
        self.configure(text="✓" if self.variable.get() else "")

    def _toggle(self, _event):

        self.variable.set(not self.variable.get())

        if self.command is not None:
            self.command()


# ---------------------------------------------------------------------------
# 4. ROAD PROFILE CARD
# ---------------------------------------------------------------------------

class RoadCard(tk.Canvas):
    """One road profile card: a small sketch of the profile above its name."""

    def __init__(self, parent, theme, profile, on_select):

        px = theme.px

        super().__init__(
            parent, bg=BACKGROUND, height=px(CARD_HEIGHT), bd=0, cursor="hand2",
            highlightthickness=px(BORDER_WIDTH),
            highlightbackground=BORDER, highlightcolor=BORDER,
        )

        self.theme = theme
        self.profile = profile
        self.on_select = on_select

        self.selected = False
        self.hovered = False

        self.icon_x, self.icon_z = profile_icon(profile)

        self.bind("<Configure>", self.redraw)
        self.bind("<Enter>", lambda _event: self._hover(True))
        self.bind("<Leave>", lambda _event: self._hover(False))
        self.bind("<ButtonRelease-1>", lambda _event: self.on_select(self.profile))

    def set_selected(self, selected):
        self.selected = selected
        self.redraw()

    def _hover(self, hovered):
        self.hovered = hovered
        self.redraw()

    def redraw(self, _event=None):

        self.delete("all")

        width = self.winfo_width()
        height = self.winfo_height()

        if self.selected:
            self.configure(bg=SELECTED)
        else:
            self.configure(bg=HOVER if self.hovered else BACKGROUND)

        # Profile sketch, centred in the upper half
        icon_width = min(width * 0.30, self.theme.px(110))
        icon_height = height * 0.22
        left = (width - icon_width) / 2
        base = height * 0.40

        points = []
        for x, z in zip(self.icon_x, self.icon_z):
            points += [left + x * icon_width, base - z * icon_height]

        self.create_line(*points, fill=INK, width=max(1, self.theme.px(2)))

        # Name
        self.create_text(width / 2, height * 0.70, text=self.profile,
                         font=self.theme.card, fill=INK)


# ---------------------------------------------------------------------------
# 5. SCROLLING AREA
# ---------------------------------------------------------------------------

class ScrollFrame(tk.Frame):
    """Vertical scrolling area. Put widgets in .inner"""

    def __init__(self, parent, theme):

        super().__init__(parent, bg=BACKGROUND)

        self.canvas = tk.Canvas(self, bg=BACKGROUND, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                       style="Flat.Vertical.TScrollbar")

        self.inner = tk.Frame(self.canvas, bg=BACKGROUND)
        self.window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y", padx=(theme.px(4), 0))

        self.inner.bind("<Configure>", self._update_region)
        self.canvas.bind("<Configure>", self._fit_width)

        # One wheel handler for the whole app; it only scrolls when the
        # pointer is over this area
        root = self.winfo_toplevel()
        root.bind_all("<MouseWheel>", self._on_wheel, add="+")
        root.bind_all("<Button-4>", self._on_wheel, add="+")
        root.bind_all("<Button-5>", self._on_wheel, add="+")

    def _update_region(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _fit_width(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)

    def _contains(self, widget):

        while widget is not None and not isinstance(widget, str):
            if widget is self:
                return True
            widget = getattr(widget, "master", None)

        return False

    def _on_wheel(self, event):

        # The widget under the pointer (Tk on Windows sends the wheel to the focused one)
        under_pointer = self.winfo_containing(event.x_root, event.y_root)

        if not self._contains(under_pointer) or self.canvas.yview() == (0.0, 1.0):
            return

        if event.num == 4:
            steps = -1
        elif event.num == 5:
            steps = 1
        elif sys.platform == "darwin":
            steps = -event.delta
        else:
            steps = -int(event.delta / 120) or (-1 if event.delta > 0 else 1)

        self.canvas.yview_scroll(steps, "units")

    def scroll_to(self, widget):
        """Scroll so that a widget inside .inner is visible."""

        self.update_idletasks()

        total = max(1, self.inner.winfo_height())
        top = widget.winfo_rooty() - self.inner.winfo_rooty()

        self.canvas.yview_moveto(max(0.0, (top - 40) / total))


# ---------------------------------------------------------------------------
# 6. PROGRESS BAR
# ---------------------------------------------------------------------------

class ProgressBar(tk.Canvas):
    """Thin flat progress bar."""

    def __init__(self, parent, theme):

        super().__init__(
            parent, bg=BACKGROUND, height=theme.px(8), bd=0,
            highlightthickness=1, highlightbackground=INK_MUTED,
        )

        self.fraction = 0.0
        self.bind("<Configure>", lambda _event: self._draw())

    def set(self, fraction):
        self.fraction = min(max(fraction, 0.0), 1.0)
        self._draw()

    def _draw(self):

        self.delete("all")

        if self.fraction > 0:
            self.create_rectangle(0, 0, self.winfo_width() * self.fraction, self.winfo_height(),
                                  fill=PROGRESS, width=0)


# ---------------------------------------------------------------------------
# 7. RESULT CELL
# ---------------------------------------------------------------------------

class ResultCell(tk.Frame):
    """One key number: name on top, big value, then the limit and pass / fail."""

    def __init__(self, parent, theme, label):

        px = theme.px

        super().__init__(
            parent, bg=BACKGROUND,
            highlightthickness=px(THIN_BORDER), highlightbackground=BORDER,
        )

        self.name = tk.Label(self, text=label, font=theme.small, bg=BACKGROUND, fg=INK_SECONDARY)
        self.value = tk.Label(self, text="-", font=theme.value, bg=BACKGROUND, fg=INK)
        self.detail = tk.Label(self, text=" ", font=theme.small, bg=BACKGROUND, fg=INK_SECONDARY)

        self.name.pack(pady=(px(3), 0))
        self.value.pack()
        self.detail.pack(pady=(0, px(3)))

    def show(self, value, detail="", passed=None):
        """passed: True / False for a limit check, None for plain information."""

        if passed is None:
            mark, color = "", INK_SECONDARY
        elif passed:
            mark, color = "✓ ", PASS
        else:
            mark, color = "✗ ", FAIL

        self.value.configure(text=value, fg=FAIL if passed is False else INK)
        self.detail.configure(text=f"{mark}{detail}" or " ", fg=color)

    def clear(self):
        self.value.configure(text="-", fg=INK)
        self.detail.configure(text=" ", fg=INK_SECONDARY)


# ---------------------------------------------------------------------------
# 8. TOOLTIP
# ---------------------------------------------------------------------------

class Tooltip:
    """Help text that appears after hovering a widget for a moment."""

    def __init__(self, widget, theme, text, delay=450):

        self.widget = widget
        self.theme = theme
        self.text = text
        self.delay = delay

        self.window = None
        self.pending = None

        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event):
        self._cancel()
        self.pending = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self.pending is not None:
            self.widget.after_cancel(self.pending)
            self.pending = None

    def _show(self):

        self.pending = None

        if self.window is not None or not self.text:
            return

        x = self.widget.winfo_rootx() + self.theme.px(12)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + self.theme.px(4)

        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{x}+{y}")

        tk.Label(
            self.window, text=self.text, font=self.theme.small, bg=FIELD, fg=INK,
            justify="left", wraplength=self.theme.px(300),
            padx=self.theme.px(8), pady=self.theme.px(5),
            highlightthickness=1, highlightbackground=BORDER,
        ).pack()

    def _hide(self, _event=None):

        self._cancel()

        if self.window is not None:
            self.window.destroy()
            self.window = None
