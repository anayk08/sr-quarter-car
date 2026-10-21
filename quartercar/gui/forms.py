"""
The two tabs of the parameters panel: the setup form and the sweep form.
"""

# ---------------------------------------------------------------------------
# FORMS
#
#   ParameterForm   "setup" tab. One row per ParamSpec (parameters.py), with
#                   the derived values (wheel rate, frequencies, ...) in gray.
#                   Every box is checked while typing; bad ones turn red.
#                   It also holds the road: a preset card's size values, or
#                   the features of the custom road drawn in the road view.
#
#   SweepForm       "sweep" tab. Up to four swept variables, each with
#                   start / stop / step, plus what to rank and map them by.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

from ..config import DesignCase, with_value
from ..metrics import DEFAULT_RANK_METRIC, RANK_METRICS
from ..parameters import DERIVED, PARAMETERS, SECTIONS, SWEEP_VARIABLES, DEFAULT_SWEEP_ROWS
from ..road import PRESET_DEFAULTS, PRESET_LABELS, make_road
from ..sweep import SweepAxis
from .theme import BACKGROUND, BORDER, FIELD, FIELD_INVALID, INK, INK_MUTED, INK_SECONDARY
from .widgets import CheckBox, Tooltip


# Road values that belong to one preset (each preset remembers its own)
ROAD_SIZE_KEYS = ("height", "length", "pitch", "count")


def _entry(parent, theme, variable, width):
    return tk.Entry(
        parent, textvariable=variable, width=width, justify="right", font=theme.body,
        bg=FIELD, fg=INK, insertbackground=INK, relief="solid", bd=1, highlightthickness=0,
    )


# ---------------------------------------------------------------------------
# 2. SETUP FORM
# ---------------------------------------------------------------------------

@dataclass
class InputRow:
    spec: object
    label: tk.Label
    entry: tk.Entry
    unit: tk.Label
    text: tk.StringVar


class ParameterForm:
    """'setup' tab: one row per input parameter, derived values in gray."""

    def __init__(self, parent, theme, on_change):

        self.parent = parent
        self.theme = theme
        self.on_change = on_change          # on_change(case or None, errors)

        self.rows = {}                      # key -> InputRow
        self.derived = {}                   # key -> (spec, value label)
        self.section_titles = {}

        self.profile = "bump"               # a preset card, or "custom"
        self.custom_features = []           # road.Feature list of the custom road
        self.road_memory = {}               # preset -> {key: text}

        self._pending = None
        self._loading = False

        parent.columnconfigure(0, weight=1)

        self._build()

    # -------------------------------------------------------------------
    # Layout
    # -------------------------------------------------------------------

    def _build(self):

        px = self.theme.px
        row = 0

        for section in SECTIONS:

            title = tk.Label(self.parent, text=section, font=self.theme.heading,
                             bg=BACKGROUND, fg=INK, anchor="w")
            title.grid(row=row, column=0, columnspan=3, sticky="ew",
                       pady=(px(14) if row else px(2), px(2)))

            tk.Frame(self.parent, bg=BORDER, height=1).grid(
                row=row + 1, column=0, columnspan=3, sticky="ew", pady=(0, px(5)))

            self.section_titles[section] = title
            row += 2

            if section == "road":
                self.custom_note = tk.Label(
                    self.parent, font=self.theme.small, bg=BACKGROUND, fg=INK_SECONDARY,
                    anchor="w", justify="left",
                    text="Custom road: drag its points in the road view.\n"
                         "Pick a card below the road view for a preset.",
                )
                self.custom_note.grid(row=row, column=0, columnspan=3, sticky="ew",
                                      pady=(0, px(4)))
                row += 1

            for spec in PARAMETERS:

                if spec.section != section:
                    continue

                text = tk.StringVar()
                label = tk.Label(self.parent, text=spec.label, font=self.theme.body,
                                 bg=BACKGROUND, fg=INK, anchor="w")
                entry = _entry(self.parent, self.theme, text, width=9)
                unit = tk.Label(self.parent, text="" if spec.unit == "-" else spec.unit,
                                font=self.theme.small, bg=BACKGROUND, fg=INK_SECONDARY,
                                anchor="w", width=6)

                label.grid(row=row, column=0, sticky="w", pady=px(2))
                entry.grid(row=row, column=1, sticky="e", padx=(px(6), px(5)), pady=px(2))
                unit.grid(row=row, column=2, sticky="w", pady=px(2))

                text.trace_add("write", self._changed)

                if spec.help:
                    Tooltip(label, self.theme, spec.help)

                self.rows[spec.key] = InputRow(spec, label, entry, unit, text)
                row += 1

            for spec in DERIVED:

                if spec.section != section:
                    continue

                line = tk.Frame(self.parent, bg=BACKGROUND)
                name = tk.Label(line, text=spec.label, font=self.theme.small,
                                bg=BACKGROUND, fg=INK_MUTED, anchor="w")
                value = tk.Label(line, text="-", font=self.theme.small,
                                 bg=BACKGROUND, fg=INK_SECONDARY, anchor="e")

                name.pack(side="left")
                value.pack(side="right")
                line.grid(row=row, column=0, columnspan=3, sticky="ew", pady=px(1))

                if spec.help:
                    Tooltip(name, self.theme, spec.help)

                self.derived[spec.key] = (spec, value)
                row += 1

    # -------------------------------------------------------------------
    # Reading and checking
    # -------------------------------------------------------------------

    def _changed(self, *_):

        if self._loading:
            return

        if self._pending is not None:
            self.parent.after_cancel(self._pending)

        self._pending = self.parent.after(150, self.refresh)

    def _parse(self):
        """SI values and error messages, both by key."""

        values, errors = {}, {}

        for key, row in self.rows.items():

            if not row.spec.applies_to(self.profile):
                continue

            try:
                shown = float(row.text.get().strip())
            except ValueError:
                errors[key] = "must be a number"
                continue

            message = row.spec.check(shown)

            if message:
                errors[key] = message
            else:
                values[key] = row.spec.from_display(shown)

        return values, errors

    def _case_from(self, values):
        """DesignCase from the defaults plus every value that parsed."""

        case = with_value(DesignCase(), ("road", "profile"), self.profile)
        case = with_value(case, ("road", "features"), tuple(self.custom_features))

        for key, value in values.items():
            case = self.rows[key].spec.set(case, value)

        return case

    def _cross_check(self, case):
        """Checks that need more than one value: can the road be built?"""

        try:
            make_road(case.road, case.corner.tire_radius)
        except ValueError as error:

            if self.profile == "custom":
                return {"road": str(error)}

            keys = [key for key in ROAD_SIZE_KEYS if self.rows[key].spec.applies_to(self.profile)]
            if "tire radius" in str(error):
                keys.append("tire_radius")

            return {key: str(error) for key in keys}

        return {}

    def refresh(self):
        """Re-check every box, color the bad ones, update the derived values."""

        self._pending = None

        values, errors = self._parse()
        case = self._case_from(values)
        errors.update(self._cross_check(case))

        for key, row in self.rows.items():
            row.entry.configure(bg=FIELD_INVALID if key in errors else FIELD)

        for spec, value in self.derived.values():
            value.configure(text=spec.text(case))

        self.on_change(None if errors else case, errors)

    def read_case(self):
        """(DesignCase, {}) when every box is valid, else (None, errors by key)."""

        values, errors = self._parse()

        if errors:
            return None, errors

        case = self._case_from(values)
        errors = self._cross_check(case)

        return (None, errors) if errors else (case, {})

    def preview_case(self):
        """Best-effort case for previews: bad boxes fall back to defaults."""

        values, _ = self._parse()
        return self._case_from(values)

    def label_for(self, key):
        return self.rows[key].label.cget("text") if key in self.rows else key

    # -------------------------------------------------------------------
    # Writing
    # -------------------------------------------------------------------

    def set_case(self, case):
        """Fill every box from a case (also switches the road profile)."""

        self._loading = True

        try:
            self.custom_features = list(case.road.features)
            self._show_profile(case.road.profile)

            for row in self.rows.values():
                row.text.set(row.spec.format(row.spec.get(case)))
        finally:
            self._loading = False

        self.refresh()

    def set_values(self, values):
        """Set some boxes from SI values (used when a preset is dragged)."""

        for key, value in values.items():
            row = self.rows[key]
            row.text.set(row.spec.format(value))

    def set_custom_features(self, features):
        """Make the road custom, with these features."""

        self.custom_features = list(features)
        self.set_profile("custom")
        self._changed()

    def set_profile(self, profile):
        """Switch road; each preset keeps its own height, length, ..."""

        if profile == self.profile:
            return

        self._loading = True

        try:
            if self.profile != "custom":
                self.road_memory[self.profile] = {
                    key: self.rows[key].text.get() for key in ROAD_SIZE_KEYS
                }

            self._show_profile(profile)

            if profile != "custom":
                saved = self.road_memory.get(profile)
                defaults = {key: self.rows[key].spec.format(value)
                            for key, value in PRESET_DEFAULTS[profile].items()}

                for key, text in (saved or defaults).items():
                    self.rows[key].text.set(text)
        finally:
            self._loading = False

        self.refresh()

    def _show_profile(self, profile):

        self.profile = profile
        self.section_titles["road"].configure(text=f"road  |  {profile}")

        if profile == "custom":
            self.custom_note.grid()
        else:
            self.custom_note.grid_remove()

        labels = PRESET_LABELS.get(profile, {})

        for key, row in self.rows.items():

            row.label.configure(text=labels.get(key, row.spec.label))

            for widget in (row.label, row.entry, row.unit):
                if row.spec.applies_to(profile):
                    widget.grid()
                else:
                    widget.grid_remove()

    def clear_memory(self):
        self.road_memory.clear()
        self.custom_features = []

    def entry_for(self, key):
        return self.rows[key].entry if key in self.rows else None


# ---------------------------------------------------------------------------
# 3. SWEEP FORM
# ---------------------------------------------------------------------------

class SweepRow:
    """One swept variable: on/off, which variable, start / stop / step, count."""

    def __init__(self, form, parent, grid_row, key, enabled):

        theme = form.theme
        px = theme.px

        self.form = form

        self.enabled = tk.BooleanVar(value=enabled)
        self.check = CheckBox(parent, theme, self.enabled, command=form.update_summary)

        self.variable = ttk.Combobox(parent, values=list(form.labels.values()), state="readonly",
                                     width=22, style="Flat.TCombobox", font=theme.small)
        self.variable.set(form.labels[key])
        self.variable.bind("<<ComboboxSelected>>", self._variable_changed)

        self.texts = [tk.StringVar() for _ in range(3)]
        self.entries = [_entry(parent, theme, text, width=6) for text in self.texts]

        self.count = tk.Label(parent, text="", font=theme.small, bg=BACKGROUND,
                              fg=INK_SECONDARY, width=4, anchor="e")

        self.check.grid(row=grid_row, column=0, sticky="w", padx=(0, px(6)), pady=px(3))
        self.variable.grid(row=grid_row, column=1, sticky="ew", padx=(0, px(6)), pady=px(3))

        for column, entry in enumerate(self.entries, start=2):
            entry.grid(row=grid_row, column=column, padx=px(2), pady=px(3))

        self.count.grid(row=grid_row, column=5, sticky="e", pady=px(3))

        self.fill_defaults(key)

        for text in self.texts:
            text.trace_add("write", lambda *_: form.update_summary())

    @property
    def key(self):
        return self.form.keys[self.variable.get()]

    def fill_defaults(self, key):

        start, stop, step = SWEEP_VARIABLES[key].sweep_range

        for text, value in zip(self.texts, (start, stop, step)):
            text.set(f"{value:g}")

    def _variable_changed(self, _event):
        self.fill_defaults(self.key)
        self.form.update_summary()

    def read_axis(self):
        """(SweepAxis, None) or (None, error message)."""

        spec = SWEEP_VARIABLES[self.key]

        try:
            start, stop, step = (float(text.get()) for text in self.texts)
        except ValueError:
            return None, f"{spec.label}: start, stop and step must be numbers"

        for value in (start, stop):
            message = spec.check(value)
            if message:
                return None, f"{spec.label}: {message}"

        axis = SweepAxis(self.key, spec.from_display(start), spec.from_display(stop),
                         spec.from_display(step))

        try:
            axis.values()
        except ValueError as error:
            return None, str(error)

        return axis, None


class SweepForm:
    """'sweep' tab: up to four swept variables, and what to rank them by."""

    def __init__(self, parent, theme, on_view_change, workers):

        px = theme.px

        self.theme = theme
        self.on_view_change = on_view_change

        self.labels = {
            spec.key: f"{spec.label} ({spec.unit})" if spec.unit not in ("", "-") else spec.label
            for spec in SWEEP_VARIABLES.values()
        }
        self.keys = {label: key for key, label in self.labels.items()}

        parent.columnconfigure(1, weight=1)

        tk.Label(
            parent, font=theme.small, bg=BACKGROUND, fg=INK_SECONDARY, justify="left",
            anchor="w", wraplength=px(390),
            text="Every combination of the ticked variables is run. "
                 "Anything not swept keeps its value from the setup tab.",
        ).grid(row=0, column=0, columnspan=6, sticky="ew", pady=(px(4), px(10)))

        for column, text in enumerate(("", "variable", "start", "stop", "step", "n")):
            tk.Label(parent, text=text, font=theme.heading, bg=BACKGROUND, fg=INK,
                     anchor="w" if column < 2 else "center").grid(
                row=1, column=column, sticky="ew", pady=(0, px(2)))

        tk.Frame(parent, bg=BORDER, height=1).grid(
            row=2, column=0, columnspan=6, sticky="ew", pady=(0, px(4)))

        self.rows = [
            SweepRow(self, parent, 3 + i, key, enabled)
            for i, (key, enabled) in enumerate(DEFAULT_SWEEP_ROWS)
        ]

        self.summary = tk.Label(parent, text="", font=theme.body, bg=BACKGROUND, fg=INK,
                                anchor="w", justify="left")
        self.summary.grid(row=8, column=0, columnspan=6, sticky="ew", pady=(px(10), px(2)))

        tk.Label(
            parent, font=theme.small, bg=BACKGROUND, fg=INK_SECONDARY, justify="left",
            anchor="w", wraplength=px(390),
            text="damping scale multiplies all four damping ratios from the setup tab "
                 "(keeps their balance). Road height, length and pitch only apply to "
                 f"the preset cards. Big sweeps use {workers} processes.",
        ).grid(row=9, column=0, columnspan=6, sticky="ew", pady=(px(2), px(14)))

        # Ranking and the map of the sweep view
        tk.Label(parent, text="rank and map", font=theme.heading, bg=BACKGROUND, fg=INK,
                 anchor="w").grid(row=10, column=0, columnspan=6, sticky="ew")
        tk.Frame(parent, bg=BORDER, height=1).grid(
            row=11, column=0, columnspan=6, sticky="ew", pady=(px(2), px(6)))

        self.metric_labels = {key: metric.label for key, metric in RANK_METRICS.items()}

        self.rank_box = ttk.Combobox(parent, state="readonly", style="Flat.TCombobox",
                                     font=theme.small, values=list(self.metric_labels.values()))
        self.rank_box.set(self.metric_labels[DEFAULT_RANK_METRIC])

        self.map_x = ttk.Combobox(parent, state="disabled", style="Flat.TCombobox", font=theme.small)
        self.map_y = ttk.Combobox(parent, state="disabled", style="Flat.TCombobox", font=theme.small)

        for grid_row, (name, box) in enumerate(
            (("rank by", self.rank_box), ("x axis", self.map_x), ("y axis", self.map_y)), start=12,
        ):
            tk.Label(parent, text=name, font=theme.small, bg=BACKGROUND, fg=INK_SECONDARY,
                     anchor="w").grid(row=grid_row, column=0, sticky="w")
            box.grid(row=grid_row, column=1, sticky="ew", padx=(0, px(6)), pady=px(2))
            box.bind("<<ComboboxSelected>>", lambda _event: self.on_view_change())

        tk.Label(
            parent, font=theme.small, bg=BACKGROUND, fg=INK_MUTED, justify="left", anchor="w",
            wraplength=px(390),
            text="Setups that pass every design limit are ranked by this value, the "
                 "rest come last. Changing these redraws the latest sweep, no re-run needed.",
        ).grid(row=15, column=0, columnspan=6, sticky="ew", pady=(px(2), 0))

        self.map_labels = []
        self.update_summary()

    # -------------------------------------------------------------------

    def read_axes(self):
        """(list of SweepAxis, list of error messages)."""

        axes, errors = [], []

        for row in self.rows:

            if not row.enabled.get():
                continue

            axis, error = row.read_axis()

            if error:
                errors.append(error)
            else:
                axes.append(axis)

        keys = [axis.key for axis in axes]
        if len(set(keys)) != len(keys):
            errors.append("each variable can only be swept once")

        return axes, errors

    def update_summary(self):

        counts = []

        for row in self.rows:

            axis, error = row.read_axis()

            if row.enabled.get():
                count = len(axis.values()) if axis is not None else None
                row.count.configure(text="?" if count is None else str(count))
                if count is not None:
                    counts.append(count)
            else:
                row.count.configure(text="-")

            for entry in row.entries:
                entry.configure(bg=FIELD_INVALID if (error and row.enabled.get()) else FIELD)

        if not counts:
            self.summary.configure(text="tick at least one variable to sweep")
            return

        total = 1
        for count in counts:
            total *= count

        self.summary.configure(text=f"{' x '.join(map(str, counts))} = {total} runs")

    def reset(self):

        for row, (key, enabled) in zip(self.rows, DEFAULT_SWEEP_ROWS):
            row.enabled.set(enabled)
            row.variable.set(self.labels[key])
            row.fill_defaults(key)

        self.rank_box.set(self.metric_labels[DEFAULT_RANK_METRIC])
        self.set_map_choices([])
        self.update_summary()

    # -------------------------------------------------------------------
    # Ranking metric and map axes
    # -------------------------------------------------------------------

    def rank_metric(self):
        chosen = self.rank_box.get()
        return next(key for key, label in self.metric_labels.items() if label == chosen)

    def set_rank_metric(self, key):
        self.rank_box.set(self.metric_labels[key])
        self.on_view_change()

    def set_map_choices(self, axes):
        """Offer the swept variables of the latest sweep as map axes."""

        self.map_labels = [axis.spec.name for axis in axes]

        if not axes:
            for box in (self.map_x, self.map_y):
                box.configure(values=[], state="disabled")
                box.set("")
            return

        self.map_x.configure(values=self.map_labels, state="readonly")
        self.map_x.set(self.map_labels[0])

        if len(axes) > 1:
            self.map_y.configure(values=self.map_labels, state="readonly")
            self.map_y.set(self.map_labels[1])
        else:
            self.map_y.configure(values=[], state="disabled")
            self.map_y.set("")

    def map_axes(self):
        """Indices of the chosen map axes: (x, y) with y None for a line plot."""

        if not self.map_labels:
            return 0, None

        x = self.map_labels.index(self.map_x.get()) if self.map_x.get() in self.map_labels else 0

        if len(self.map_labels) < 2:
            return x, None

        y = self.map_labels.index(self.map_y.get()) if self.map_y.get() in self.map_labels else 1

        if y == x:
            y = next(i for i in range(len(self.map_labels)) if i != x)

        return x, y
