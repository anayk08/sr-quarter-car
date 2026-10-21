"""
Road editor: shape the road in the road view, like the bands of an EQ.
"""

# ---------------------------------------------------------------------------
# ROAD EDITOR
#
#   Every road feature has a point at its top (at its bottom for a dip).
#
#     drag a point             move the feature along the road, set its height
#     scroll on a point        make it longer or shorter
#     double-click the road    add a bump there (below the line: a dip)
#     right-click              add, delete, or change a feature's shape
#     Delete key               delete the selected feature
#
#   The bar above the plot shows the selected feature's numbers; type in it
#   for exact values.
#
#   A preset card stays a preset while it is moved or resized (that edits
#   its size values in the setup tab). Adding, deleting or reshaping a
#   feature makes a custom road, so the presets themselves never change.
#   The "custom road" button brings the custom road back after picking a card.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

import math
import tkinter as tk
from dataclasses import replace
from tkinter import ttk

import numpy as np

from ..plotting import refresh_road
from ..road import SHAPES, Feature, make_road, road_features
from .theme import BACKGROUND, INK, INK_SECONDARY
from .widgets import FlatButton


HINT = "drag a point  |  scroll = length  |  double-click = add  |  right-click = more"

MIN_HEIGHT = 0.0005     # m, smallest feature height or depth
MIN_LENGTH = 0.02       # m

# Features added from the right-click menu: shape, length (m), height (m)
NEW_FEATURES = {
    "bump": ("bump", 0.30, 0.010),
    "dip": ("bump", 0.30, -0.010),
    "hole": ("hole", 0.25, -0.020),
}


def _legal_height(shape, height, radius, can_flip):
    """Keep a height usable: holes go down and stay shallower than the tire."""

    if shape == "hole":
        return -min(max(-height, MIN_HEIGHT), 0.95 * radius)

    if not can_flip:
        return max(height, MIN_HEIGHT)

    return math.copysign(max(abs(height), MIN_HEIGHT), height or 1.0)


# ---------------------------------------------------------------------------
# 2. EDITOR
# ---------------------------------------------------------------------------

class RoadEditor:
    """Mouse editing of the road in the road view, plus the number bar above it."""

    def __init__(self, app, parent):

        self.app = app
        self.form = app.form

        self.plot = None            # RoadPlot of the road view on screen
        self.selected = 0           # index of the selected feature
        self.dragging = None        # index of the feature being dragged

        self.bar = self._build_bar(parent)

    # -------------------------------------------------------------------
    # Number bar
    # -------------------------------------------------------------------

    def _build_bar(self, parent):

        theme = self.app.theme
        px = theme.px

        bar = tk.Frame(parent, bg=BACKGROUND)

        self.custom_button = FlatButton(bar, theme, "custom road", self.use_custom,
                                        font=theme.small, padx=10, pady=2)
        self.custom_button.pack(side="left", padx=(0, px(14)))

        self.feature_name = tk.Label(bar, text="", font=theme.small, bg=BACKGROUND,
                                     fg=INK_SECONDARY, width=16, anchor="w")
        self.feature_name.pack(side="left")

        self.shape_box = ttk.Combobox(bar, values=SHAPES, state="readonly", width=8,
                                      style="Flat.TCombobox", font=theme.small)
        self.shape_box.pack(side="left", padx=(0, px(10)))
        self.shape_box.bind("<<ComboboxSelected>>",
                            lambda _event: self.reshape(self.selected, self.shape_box.get()))

        self.texts = {}

        for key, name, unit in (("start", "start", "m"), ("length", "length", "m"),
                                ("height", "height", "mm")):

            tk.Label(bar, text=name, font=theme.small, bg=BACKGROUND,
                     fg=INK_SECONDARY).pack(side="left", padx=(0, px(3)))

            text = tk.StringVar()
            entry = tk.Entry(bar, textvariable=text, width=7, justify="right", font=theme.small,
                             bg="#f4f4f2", fg=INK, relief="solid", bd=1, highlightthickness=0)
            entry.pack(side="left")
            entry.bind("<Return>", self._apply_numbers)
            entry.bind("<FocusOut>", self._apply_numbers)

            tk.Label(bar, text=unit, font=theme.small, bg=BACKGROUND,
                     fg=INK_SECONDARY).pack(side="left", padx=(px(2), px(10)))

            self.texts[key] = text

        FlatButton(bar, theme, "delete", lambda: self.delete(self.selected),
                   font=theme.small, padx=8, pady=1).pack(side="left")

        return bar

    def refresh_bar(self):
        """Show the selected feature's numbers."""

        features = self._features()
        custom = self.form.profile == "custom"

        self.custom_button.set_active(custom)

        if not features:
            self.feature_name.configure(text="no features")
            for text in self.texts.values():
                text.set("")
            self.shape_box.set("")
            return

        self.selected = min(self.selected, len(features) - 1)
        feature = features[self.selected]

        owner = "feature" if custom else self.form.profile
        self.feature_name.configure(text=f"{owner} {self.selected + 1} of {len(features)}"
                                    if len(features) > 1 else owner)

        self.shape_box.set(feature.shape)
        self.texts["start"].set(f"{feature.start:.3f}")
        self.texts["length"].set(f"{feature.length:.3f}")
        self.texts["height"].set(f"{feature.height * 1000:.1f}")

    def _apply_numbers(self, _event=None):

        features = self._features()

        if not features:
            return

        feature = features[self.selected]

        try:
            start, length, height = (float(self.texts[key].get())
                                     for key in ("start", "length", "height"))
        except ValueError:
            self.app.set_status("road feature: start, length and height must be numbers",
                                error=True)
            return

        unchanged = (f"{start:.3f}", f"{length:.3f}", f"{height:.1f}") == (
            f"{feature.start:.3f}", f"{feature.length:.3f}", f"{feature.height * 1000:.1f}")

        if not unchanged:
            self.edit(self.selected, centre=start + length / 2, height=height / 1000,
                      length=length)
            self.app.draw_view()

    # -------------------------------------------------------------------
    # The road being edited
    # -------------------------------------------------------------------

    def _features(self):
        """Features of the road in the setup tab ([] if its size values are bad)."""

        try:
            return road_features(self.form.preview_case().road)
        except ValueError:
            return []

    def edit(self, index, centre=None, height=None, length=None):
        """Move or resize one feature. A preset keeps being a preset."""

        case = self.form.preview_case()
        features = road_features(case.road)
        feature = features[index]
        custom = case.road.profile == "custom"

        length = max(feature.length if length is None else length, MIN_LENGTH)
        centre = feature.centre if centre is None else centre
        height = _legal_height(feature.shape, feature.height if height is None else height,
                               case.corner.tire_radius, can_flip=custom)

        if custom:
            # Round to what the bar shows: 1 mm along the road, 0.1 mm in height
            features[index] = replace(
                feature,
                start=round(max(0.0, centre - length / 2), 3),
                length=round(length, 3),
                height=round(height, 4),
            )
            self.form.set_custom_features(features)
            return

        # Preset: the drag sets its size values (all strips of a rumble strip move together)
        road = case.road

        if road.profile == "rumble strip":
            length = min(length, road.pitch)

        first_start = centre - length / 2 - (index * road.pitch if road.profile == "rumble strip" else 0)

        self.form.set_values(dict(
            height=abs(height),
            length=length,
            start_time=max(0.0, first_start) / road.speed,
        ))

    def _set_features(self, features, selected):
        """Replace every feature: the road becomes custom."""

        self.selected = max(0, selected)
        self.form.set_custom_features(features)
        self.app.road_became_custom()

    def add(self, x, kind, height=None):

        shape, length, default_height = NEW_FEATURES[kind]
        radius = self.form.preview_case().corner.tire_radius

        height = _legal_height(shape, default_height if height is None else height, radius, True)
        feature = Feature(shape, round(max(0.0, x - length / 2), 3), length, round(height, 4))

        features = self._features() + [feature]
        self._set_features(features, len(features) - 1)

    def delete(self, index):

        features = self._features()

        if index < len(features):
            del features[index]
            self._set_features(features, min(index, len(features) - 1))

    def reshape(self, index, shape):

        features = self._features()

        if index >= len(features) or features[index].shape == shape:
            return

        radius = self.form.preview_case().corner.tire_radius
        feature = features[index]

        # A hole always goes down; a bump made from a hole stays a dip
        height = _legal_height(shape, -abs(feature.height) if shape == "hole" else feature.height,
                               radius, can_flip=True)

        features[index] = replace(feature, shape=shape, height=height)
        self._set_features(features, index)

    def use_custom(self):
        """Switch to the custom road (a copy of the current preset the first time)."""

        if self.form.profile == "custom":
            return

        features = self.form.custom_features or self._features()
        self._set_features(features, 0)

    # -------------------------------------------------------------------
    # Mouse and keyboard (called by the app while the road view is shown)
    # -------------------------------------------------------------------

    def _node_at(self, event):
        """Index of the feature point under the mouse, or None."""

        plot = self.plot

        if plot is None or plot.nodes is None or not len(plot.nodes):
            return None

        screen = plot.profile_ax.transData.transform(plot.nodes)
        distance = np.hypot(screen[:, 0] - event.x, screen[:, 1] - event.y)
        nearest = int(np.argmin(distance))

        return nearest if distance[nearest] < self.app.theme.px(12) else None

    def press(self, event):

        if self.plot is None or event.inaxes is not self.plot.profile_ax:
            return

        self.app.canvas_widget.focus_set()

        index = self._node_at(event)

        if event.button == 3:
            self._menu(index, event.xdata, event.ydata / 1000)
            return

        if event.dblclick and index is None:
            height = event.ydata / 1000
            self.add(event.xdata, "bump", height if abs(height) >= 0.002 else None)
            return

        if index is not None:
            self.selected = index
            self.dragging = index
            self.refresh_bar()

            # Freeze the layout so the axes do not move under the mouse
            self.app.figure.set_layout_engine("none")
            self._redraw_curves()

    def motion(self, event):

        if self.dragging is None:
            return

        # Follow the mouse even outside the plot (the view refits on release),
        # within one view-size beyond each edge
        ax = self.plot.profile_ax
        x, height = ax.transData.inverted().transform((event.x, event.y))

        (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
        x = min(max(x, x0 - (x1 - x0)), x1 + (x1 - x0))
        height = min(max(height, y0 - (y1 - y0)), y1 + (y1 - y0))

        self.edit(self.dragging, centre=x, height=height / 1000)
        self._redraw_curves()
        self.refresh_bar()

    def release(self, _event):

        if self.dragging is not None:
            self.dragging = None
            self.app.draw_view()

    def scroll(self, event):

        if self.plot is None or event.inaxes is not self.plot.profile_ax:
            return

        index = self._node_at(event)

        if index is None:
            return

        self.selected = index
        feature = self._features()[index]

        self.edit(index, length=feature.length * 1.1 ** event.step)
        self.app.draw_view()

    def key(self, event):

        if event.key in ("delete", "backspace") and self._features():
            self.delete(self.selected)

    def _menu(self, index, x, height):

        menu = tk.Menu(self.app.root, tearoff=0)

        if index is not None:

            self.selected = index
            self.refresh_bar()

            current = self._features()[index].shape
            for shape in SHAPES:
                if shape != current:
                    menu.add_command(label=f"make it a {shape}",
                                     command=lambda s=shape: self.reshape(index, s))

            menu.add_command(label="delete", command=lambda: self.delete(index))
            menu.add_separator()

        for kind in NEW_FEATURES:
            menu.add_command(label=f"add a {kind} here", command=lambda k=kind: self.add(x, k))

        menu.tk_popup(*self.app.root.winfo_pointerxy())

    def _redraw_curves(self):
        """Fast redraw while dragging: just the road curves and points."""

        case = self.form.preview_case()

        try:
            road = make_road(case.road, case.corner.tire_radius)
        except ValueError:
            return

        refresh_road(self.plot, road, self.selected)
        self.app.canvas.draw_idle()
