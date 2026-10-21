"""
Main window of the FSAE quarter-car design tool.
"""

# ---------------------------------------------------------------------------
# APP
#
#   +----------------+--------------------------------------------+
#   |                |                 the road                   |
#   |   parameters   |    views: road | response | sweep | ranking |
#   |  [setup|sweep] |    (the road view is also the road editor) |
#   |                +---------------------+----------------------+
#   |                |        bump         |        ditch         |
#   |                +---------------------+----------------------+
#   |                |      triangle       |     rumble strip     |
#   | [run] [sweep]  +---------------------+----------------------+
#   | [reset]        |                 results                    |
#   +----------------+--------------------------------------------+
#
#   Simulations and sweeps run in a background thread so the window stays
#   responsive. Results come back through a queue that the Tk loop polls.
#
#   Shortcuts: F5 run simulation, F6 run sweep, Esc cancel a sweep.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

import csv
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from ..config import GRAVITY, LBF_IN_TO_N_M, DesignCase
from ..metrics import RANK_METRICS
from ..plotting import plot_message, plot_response, plot_road, plot_sweep
from ..road import PRESETS
from ..sweep import default_workers, evaluate_design, run_sweep, sweep_size
from .forms import ParameterForm, SweepForm
from .road_editor import HINT, RoadEditor
from .theme import (
    BACKGROUND, BORDER, FAIL, FIELD, GAP, INK, INK_MUTED, INK_SECONDARY, LEFT_COLUMN_WIDTH,
    MIN_WINDOW_SIZE, PASS, SELECTED, WINDOW_SIZE, Theme, enable_dpi_awareness,
)
from .widgets import FlatButton, Panel, ProgressBar, ResultCell, RoadCard, ScrollFrame


# Ask before starting a sweep bigger than this
CONFIRM_RUNS = 3000

VIEWS = ("road", "response", "sweep", "ranking")

VIEW_HINTS = {
    "road": HINT,
    "response": "",
    "sweep": "hover a setup, double-click to load it",
    "ranking": "double-click a row to load it, click a heading to rank by it",
}

RESULT_CELLS = (
    ("motion_ratio", "motion ratio"),
    ("spring_rate", "spring rate"),
    ("ride_height", "min ride height"),
    ("travel", "max travel  comp / reb"),
    ("acceleration", "max body accel"),
)


# ---------------------------------------------------------------------------
# 2. MAIN WINDOW
# ---------------------------------------------------------------------------

class QuarterCarApp:

    def __init__(self, root):

        self.root = root
        self.theme = Theme(root)
        self.workers = default_workers()

        # Results currently shown
        self.evaluation = None          # latest single run
        self.sweep = None               # latest sweep
        self.ranked = []                # sweep points in table order
        self.sweep_plot = None          # hover / click info of the sweep charts

        # Background work
        self.busy = None                # "simulation" or "sweep" while running
        self.messages = queue.Queue()
        self.cancel = threading.Event()

        self.view = "road"
        self._status_is_error = False
        self._input_note = ""
        self._road_redraw = None
        self._hover_point = None
        self._hover_note = None

        self._setup_window()
        self._setup_styles()
        self._build_layout()

        self.form.set_case(DesignCase())
        self._mark_profile(DesignCase().road.profile)
        self.show_tab("setup")
        self.show_view("road")

        root.bind("<F5>", lambda _event: self.run_simulation())
        root.bind("<F6>", lambda _event: self.run_sweep())
        root.bind("<Escape>", lambda _event: self.cancel_sweep())
        root.protocol("WM_DELETE_WINDOW", self._close)

        root.after(40, self._poll_messages)

    # -------------------------------------------------------------------
    # Window and styles
    # -------------------------------------------------------------------

    def _setup_window(self):

        px = self.theme.px
        root = self.root

        root.title("FSAE quarter-car suspension design tool")
        root.configure(bg=BACKGROUND)

        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()

        width = min(px(WINDOW_SIZE[0]), int(screen_width * 0.94))
        height = min(px(WINDOW_SIZE[1]), int(screen_height * 0.88))

        left = max(0, (screen_width - width) // 2)
        top = max(0, (screen_height - height) // 3)

        root.geometry(f"{width}x{height}+{left}+{top}")
        root.minsize(min(px(MIN_WINDOW_SIZE[0]), width), min(px(MIN_WINDOW_SIZE[1]), height))

        # Small screen (e.g. a laptop at 150-200 % scaling): use all of it
        if height < px(WINDOW_SIZE[1]) and sys.platform == "win32":
            root.state("zoomed")

    def _setup_styles(self):
        """ttk widgets (drop-down, table, scrollbar) in the same flat gray look."""

        px = self.theme.px
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure("Flat.TCombobox", fieldbackground=FIELD, background=BACKGROUND,
                        foreground=INK, arrowcolor=INK, bordercolor=INK_MUTED,
                        lightcolor=FIELD, darkcolor=FIELD, padding=px(2), arrowsize=px(12))
        style.map("Flat.TCombobox",
                  fieldbackground=[("readonly", FIELD), ("disabled", BACKGROUND)],
                  foreground=[("disabled", INK_MUTED)],
                  selectbackground=[("readonly", FIELD)],
                  selectforeground=[("readonly", INK)])

        for orientation in ("Vertical", "Horizontal"):
            style.configure(f"Flat.{orientation}.TScrollbar", background=BACKGROUND,
                            troughcolor=BACKGROUND, bordercolor=INK_MUTED, arrowcolor=INK,
                            lightcolor=BACKGROUND, darkcolor=BACKGROUND, gripcount=0,
                            arrowsize=px(12))

        style.configure("Ranking.Treeview", background=FIELD, fieldbackground=FIELD,
                        foreground=INK, rowheight=px(22), font=self.theme.small, borderwidth=0)
        style.configure("Ranking.Treeview.Heading", background=BACKGROUND, foreground=INK,
                        font=self.theme.heading, relief="flat", borderwidth=1)
        style.map("Ranking.Treeview", background=[("selected", SELECTED)],
                  foreground=[("selected", INK)])

        self.root.option_add("*TCombobox*Listbox.font", self.theme.small)

    # -------------------------------------------------------------------
    # Layout
    # -------------------------------------------------------------------

    def _build_layout(self):

        px = self.theme.px

        outer = tk.Frame(self.root, bg=BACKGROUND)
        outer.pack(fill="both", expand=True, padx=px(GAP), pady=px(GAP))
        outer.columnconfigure(0, minsize=px(LEFT_COLUMN_WIDTH))
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        # Left: parameters, full height (as in the mockup)
        self.parameters_panel = Panel(outer, self.theme, "parameters")
        self.parameters_panel.grid(row=0, column=0, sticky="nsew", padx=(0, px(GAP)))

        # Right: the road, the road cards, the results
        right = tk.Frame(outer, bg=BACKGROUND)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self.road_panel = Panel(right, self.theme, "the road")
        self.road_panel.grid(row=0, column=0, sticky="nsew")

        cards = tk.Frame(right, bg=BACKGROUND)
        cards.grid(row=1, column=0, sticky="ew", pady=(px(GAP), 0))

        self.results_panel = Panel(right, self.theme, "results")
        self.results_panel.grid(row=2, column=0, sticky="ew", pady=(px(GAP), 0))

        self._build_parameters()
        self._build_road_panel()
        self._build_cards(cards)
        self._build_results()

    def _build_parameters(self):

        px = self.theme.px
        theme = self.theme
        body = self.parameters_panel.body

        # Tabs: setup | sweep
        tabs = tk.Frame(body, bg=BACKGROUND)
        tabs.pack(side="top", fill="x", pady=(0, px(8)))

        holder = tk.Frame(tabs, bg=BACKGROUND)
        holder.pack()

        self.tab_buttons = {}
        for name in ("setup", "sweep"):
            button = FlatButton(holder, theme, name, lambda n=name: self.show_tab(n),
                                font=theme.small, padx=18, pady=3)
            button.pack(side="left", padx=px(3))
            self.tab_buttons[name] = button

        # Actions at the bottom
        actions = tk.Frame(body, bg=BACKGROUND)
        actions.pack(side="bottom", fill="x", pady=(px(10), 0))

        buttons = tk.Frame(actions, bg=BACKGROUND)
        buttons.pack(fill="x")

        self.run_button = FlatButton(buttons, theme, "run simulation", self.run_simulation, pady=7)
        self.sweep_button = FlatButton(buttons, theme, "run sweep", self.run_sweep, pady=7)
        self.reset_button = FlatButton(buttons, theme, "reset", self.reset, pady=7)

        for column, button in enumerate((self.run_button, self.sweep_button, self.reset_button)):
            buttons.columnconfigure(column, weight=1, uniform="button")
            button.grid(row=0, column=column, sticky="ew",
                        padx=(0 if column == 0 else px(6), 0))

        self.progress = ProgressBar(actions, theme)
        self.progress.pack(fill="x", pady=(px(8), px(4)))

        self.status = tk.Label(actions, text="ready", font=theme.small, bg=BACKGROUND,
                               fg=INK_SECONDARY, anchor="w", justify="left")
        self.status.pack(fill="x")
        self.status.bind("<Configure>",
                         lambda event: self.status.configure(wraplength=max(50, event.width)))

        # Tab contents
        content = tk.Frame(body, bg=BACKGROUND)
        content.pack(side="top", fill="both", expand=True)

        self.setup_area = ScrollFrame(content, theme)
        self.form = ParameterForm(self.setup_area.inner, theme, self._inputs_changed)

        self.sweep_area = tk.Frame(content, bg=BACKGROUND)
        self.sweep_form = SweepForm(self.sweep_area, theme, self._sweep_view_changed, self.workers)

    def _build_road_panel(self):

        px = self.theme.px
        panel = self.road_panel

        self.view_hint = tk.Label(panel.header_left, text="", font=self.theme.small,
                                  bg=BACKGROUND, fg=INK_MUTED)
        self.view_hint.pack(side="left")

        self.view_buttons = {}
        for name in VIEWS:
            button = FlatButton(panel.header_right, self.theme, name,
                                lambda n=name: self.show_view(n),
                                font=self.theme.small, padx=8, pady=2)
            button.pack(side="left", padx=(px(4), 0))
            self.view_buttons[name] = button

        self.editor = RoadEditor(self, panel.body)

        self.figure = Figure(figsize=(9, 5), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.figure, master=panel.body)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.configure(bg=BACKGROUND, highlightthickness=0, bd=0)

        # Mouse and keys go to the road editor or to the sweep charts
        for event, handler in (
            ("button_press_event", self._on_press),
            ("motion_notify_event", self._on_motion),
            ("button_release_event", self._on_release),
            ("scroll_event", self._on_scroll),
            ("key_press_event", self._on_key),
        ):
            self.canvas.mpl_connect(event, handler)

        self.ranking_frame = self._build_ranking(panel.body)

    def _build_ranking(self, parent):

        px = self.theme.px
        theme = self.theme

        frame = tk.Frame(parent, bg=BACKGROUND)

        bar = tk.Frame(frame, bg=BACKGROUND)
        bar.pack(fill="x", pady=(0, px(6)))

        FlatButton(bar, theme, "load selected setup", self._load_selected,
                   font=theme.small, padx=10, pady=3).pack(side="left")
        FlatButton(bar, theme, "export csv", self._export_csv,
                   font=theme.small, padx=10, pady=3).pack(side="left", padx=(px(6), 0))

        self.ranking_note = tk.Label(bar, text="", font=theme.small, bg=BACKGROUND,
                                     fg=INK_SECONDARY)
        self.ranking_note.pack(side="right")

        holder = tk.Frame(frame, bg=BACKGROUND, highlightthickness=1, highlightbackground=BORDER)
        holder.pack(fill="both", expand=True)

        self.table = ttk.Treeview(holder, show="headings", style="Ranking.Treeview",
                                  selectmode="browse")
        vertical = ttk.Scrollbar(holder, orient="vertical", command=self.table.yview,
                                 style="Flat.Vertical.TScrollbar")
        horizontal = ttk.Scrollbar(holder, orient="horizontal", command=self.table.xview,
                                   style="Flat.Horizontal.TScrollbar")
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)

        horizontal.pack(side="bottom", fill="x")
        vertical.pack(side="right", fill="y")
        self.table.pack(side="left", fill="both", expand=True)

        self.table.tag_configure("fails", foreground=INK_MUTED)
        self.table.bind("<Double-1>", self._table_double_click)

        return frame

    def _build_cards(self, parent):

        px = self.theme.px

        parent.columnconfigure(0, weight=1, uniform="card")
        parent.columnconfigure(1, weight=1, uniform="card")

        self.cards = {}

        for i, profile in enumerate(PRESETS):

            card = RoadCard(parent, self.theme, profile, self.select_profile)
            card.grid(
                row=i // 2, column=i % 2, sticky="ew",
                padx=(0, px(GAP)) if i % 2 == 0 else 0,
                pady=(0, px(GAP)) if i < 2 else 0,
            )

            self.cards[profile] = card

    def _build_results(self):

        px = self.theme.px
        theme = self.theme
        body = self.results_panel.body

        self.stale_note = tk.Label(self.results_panel.header_right, text="", font=theme.small,
                                   bg=BACKGROUND, fg=FAIL)
        self.stale_note.pack(side="right")

        self.results_source = tk.Label(self.results_panel.header_left, text="", font=theme.small,
                                       bg=BACKGROUND, fg=INK_MUTED)
        self.results_source.pack(side="left")

        cells = tk.Frame(body, bg=BACKGROUND)
        cells.pack(fill="x")

        self.cells = {}

        for column, (key, label) in enumerate(RESULT_CELLS):
            cells.columnconfigure(column, weight=1, uniform="cell")
            cell = ResultCell(cells, theme, label)
            cell.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else px(8), 0))
            self.cells[key] = cell

        line = tk.Frame(body, bg=BACKGROUND)
        line.pack(fill="x", pady=(px(6), 0))

        self.verdict = tk.Label(line, text="", font=theme.body, bg=BACKGROUND, fg=INK, anchor="w")
        self.verdict.pack(side="left")

        self.summary = tk.Label(line, text="run a simulation or a sweep to see results here",
                                font=theme.small, bg=BACKGROUND, fg=INK_SECONDARY, anchor="w")
        self.summary.pack(side="left", fill="x", expand=True, padx=(px(10), 0))

        # Extra line for sweep results only
        self.sweep_line = tk.Label(body, text="", font=theme.small, bg=BACKGROUND,
                                   fg=INK_SECONDARY, anchor="w", justify="left")
        self.sweep_line.bind("<Configure>",
                             lambda event: self.sweep_line.configure(wraplength=max(50, event.width)))

    # -------------------------------------------------------------------
    # Tabs, views, road
    # -------------------------------------------------------------------

    def show_tab(self, name):

        for tab, button in self.tab_buttons.items():
            button.set_active(tab == name)

        if name == "setup":
            self.sweep_area.pack_forget()
            self.setup_area.pack(fill="both", expand=True)
        else:
            self.setup_area.pack_forget()
            self.sweep_area.pack(fill="both", expand=True)

    def show_view(self, name):

        self.view = name

        for view, button in self.view_buttons.items():
            button.set_active(view == name)

        self.view_hint.configure(text=VIEW_HINTS[name])

        for widget in (self.editor.bar, self.canvas_widget, self.ranking_frame):
            widget.pack_forget()

        if name == "ranking":
            self.ranking_frame.pack(fill="both", expand=True)
            return

        if name == "road":
            self.editor.bar.pack(fill="x", pady=(0, self.theme.px(6)))

        self.canvas_widget.pack(fill="both", expand=True)
        self.draw_view()

    def draw_view(self):
        """Redraw the figure for the current view."""

        self.sweep_plot = None
        self.editor.plot = None
        self._hover_point = None
        self._hover_note = None

        if self.view == "road":
            self.editor.plot = plot_road(self.figure, self.form.preview_case(),
                                         self.editor.selected)
            self.editor.refresh_bar()

        elif self.view == "response":
            if self.evaluation is None:
                plot_message(self.figure, "press  run simulation  to see the time response")
            else:
                plot_response(self.figure, self.evaluation)

        elif self.view == "sweep":
            if self.sweep is None or not self.sweep.points:
                plot_message(self.figure, "set the ranges on the sweep tab, then press  run sweep")
            else:
                self.sweep_plot = plot_sweep(self.figure, self.sweep,
                                             self.sweep_form.rank_metric(),
                                             *self.sweep_form.map_axes())

        self.canvas.draw_idle()

    def select_profile(self, profile):
        """A road card was clicked."""

        if self.busy:
            return

        self._mark_profile(profile)
        self.editor.selected = 0
        self.form.set_profile(profile)
        self.show_view("road")

    def road_became_custom(self):
        """The road editor turned the road into a custom one."""

        self._mark_profile(None)
        self.show_view("road")

    def _mark_profile(self, profile):
        for name, card in self.cards.items():
            card.set_selected(name == profile)

    def _inputs_changed(self, case, errors):
        """Called by the setup form after every (debounced) edit."""

        if errors:
            key, message = next(iter(errors.items()))
            self.set_status(f"{self.form.label_for(key)}: {message}", error=True)
        elif self._status_is_error:
            self.set_status("ready")

        # While a point is dragged the editor redraws the road itself
        if self.view == "road" and self.editor.dragging is None:
            if self._road_redraw is not None:
                self.root.after_cancel(self._road_redraw)
            self._road_redraw = self.root.after(150, self._redraw_road)

        if self.evaluation is not None or self.sweep is not None:
            self.stale_note.configure(text="inputs changed since these results")

    def _redraw_road(self):
        self._road_redraw = None
        if self.view == "road" and self.editor.dragging is None:
            self.draw_view()

    def _sweep_view_changed(self):
        """Rank metric or map axes changed: re-rank and redraw, no re-run."""

        if self.sweep is not None:
            self._show_sweep()

        if self.view == "sweep":
            self.draw_view()

    def set_status(self, text, error=False):
        self._status_is_error = error
        self.status.configure(text=text, fg=FAIL if error else INK_SECONDARY)

    # -------------------------------------------------------------------
    # Mouse and keys on the figure
    # -------------------------------------------------------------------

    def _on_press(self, event):

        if self.view == "road":
            self.editor.press(event)
        elif self.view == "sweep" and event.dblclick:
            point = self._point_at(event)
            if point is not None:
                self.load_point(point)

    def _on_motion(self, event):

        if self.view == "road":
            self.editor.motion(event)
        elif self.view == "sweep":
            self._hover(event)

    def _on_release(self, event):
        if self.view == "road":
            self.editor.release(event)

    def _on_scroll(self, event):
        if self.view == "road":
            self.editor.scroll(event)

    def _on_key(self, event):
        if self.view == "road":
            self.editor.key(event)

    # -------------------------------------------------------------------
    # Run, sweep, reset
    # -------------------------------------------------------------------

    def _read_inputs(self):
        """Validated case from the setup tab, or None (and a message)."""

        case, errors = self.form.read_case()

        if errors:
            key, message = next(iter(errors.items()))
            self.show_tab("setup")
            self.set_status(f"check the red boxes - {self.form.label_for(key)}: {message}",
                            error=True)
            entry = self.form.entry_for(key)
            if entry is not None:
                self.setup_area.scroll_to(entry)
                entry.focus_set()
            return None

        # A whole-car mass typed in by mistake is the most likely input error
        self._input_note = (
            "  -  note: sprung mass is this corner's share, not the whole car"
            if case.corner.sprung_mass > 150 else ""
        )

        return case

    def run_simulation(self):

        if self.busy:
            return

        case = self._read_inputs()

        if case is None:
            return

        self.set_status("running simulation ..." + self._input_note)
        self._start("simulation", lambda: evaluate_design(case))

    def run_sweep(self):

        if self.busy == "sweep":
            self.cancel_sweep()
            return

        if self.busy:
            return

        case = self._read_inputs()

        if case is None:
            return

        axes, errors = self.sweep_form.read_axes()

        errors += [f"{axis.spec.label} does not apply to the {case.road.profile} road"
                   for axis in axes if not axis.spec.applies_to(case.road.profile)]

        if errors or not axes:
            self.show_tab("sweep")
            self.set_status(errors[0] if errors else "tick at least one variable on the sweep tab",
                            error=True)
            return

        total = sweep_size(axes)

        if total > CONFIRM_RUNS and not messagebox.askyesno(
            "large sweep", f"This sweep has {total} setups and may take a while. Run it?",
            parent=self.root,
        ):
            return

        self.cancel.clear()

        def progress(done, count):
            self.messages.put(("progress", done, count))

        def job():
            return run_sweep(case, axes, on_progress=progress,
                             should_stop=self.cancel.is_set, workers=self.workers)

        self.set_status(f"sweeping {total} setups ..." + self._input_note)
        self._start("sweep", job)

    def cancel_sweep(self):
        if self.busy == "sweep":
            self.cancel.set()
            self.set_status("cancelling ... (finished setups are kept)")

    def reset(self):

        if self.busy:
            return

        self.form.clear_memory()
        self.form.set_case(DesignCase())
        self._mark_profile(DesignCase().road.profile)
        self.editor.selected = 0
        self.sweep_form.reset()

        self.evaluation = None
        self.sweep = None
        self.ranked = []
        self.table.delete(*self.table.get_children())
        self.ranking_note.configure(text="")

        for cell in self.cells.values():
            cell.clear()

        self.verdict.configure(text="")
        self.summary.configure(text="run a simulation or a sweep to see results here")
        self.sweep_line.configure(text="")
        self.sweep_line.pack_forget()
        self.results_source.configure(text="")
        self.stale_note.configure(text="")
        self.progress.set(0)

        self.show_tab("setup")
        self.show_view("road")
        self.set_status("all inputs back to their defaults")

    # -------------------------------------------------------------------
    # Background worker
    # -------------------------------------------------------------------

    def _start(self, kind, job):

        self.busy = kind
        self._update_buttons()
        self.progress.set(0)

        def work():
            try:
                self.messages.put(("done", kind, job()))
            except Exception as error:      # report any failure in the window
                self.messages.put(("error", kind, f"{type(error).__name__}: {error}"))

        threading.Thread(target=work, daemon=True).start()

    def _update_buttons(self):

        self.run_button.set_enabled(self.busy is None)
        self.reset_button.set_enabled(self.busy is None)
        self.sweep_button.set_enabled(self.busy in (None, "sweep"))
        self.sweep_button.set_text("cancel sweep" if self.busy == "sweep" else "run sweep")

    def _poll_messages(self):

        try:
            while True:
                self._handle(self.messages.get_nowait())
        except queue.Empty:
            pass

        self.root.after(40, self._poll_messages)

    def _handle(self, message):

        if message[0] == "progress":
            _, done, total = message
            self.progress.set(done / total)
            self.set_status(f"sweep  {done} / {total}")
            return

        kind, job, payload = message

        self.busy = None
        self._update_buttons()

        if kind == "error":
            self.progress.set(0)
            self.set_status(f"{job} failed - {payload}", error=True)
        elif job == "simulation":
            self._simulation_done(payload)
        else:
            self._sweep_done(payload)

    def _simulation_done(self, evaluation):

        self.evaluation = evaluation
        self.progress.set(1)

        self._show_results(evaluation)
        self.results_source.configure(text="single run")
        self.stale_note.configure(text="")

        self.show_view("response")
        self.set_status("simulation done" + self._input_note)

    def _sweep_done(self, sweep):

        self.sweep = sweep
        self.progress.set(1 if not sweep.cancelled else self.progress.fraction)

        self.sweep_form.set_map_choices(sweep.axes)
        self._show_sweep()
        self.stale_note.configure(text="")

        self.show_view("sweep")

        state = "cancelled after" if sweep.cancelled else "done:"
        self.set_status(f"sweep {state} {len(sweep.points)} setups in {sweep.elapsed:.1f} s"
                        + self._input_note)

    # -------------------------------------------------------------------
    # Results bar
    # -------------------------------------------------------------------

    def _show_results(self, evaluation, header=""):

        case = evaluation.case
        corner = case.corner
        limits = case.limits
        metrics = evaluation.metrics
        checks = {check.key: check for check in evaluation.checks}

        self.cells["motion_ratio"].show(f"{corner.motion_ratio:.3f}", "spring / wheel travel")

        self.cells["spring_rate"].show(
            f"{corner.spring_rate / LBF_IN_TO_N_M:.0f} lbf/in",
            f"wheel rate {corner.wheel_rate / LBF_IN_TO_N_M:.0f} lbf/in",
        )

        self.cells["ride_height"].show(
            f"{metrics.min_ride_height * 1000:.1f} mm",
            f"limit {limits.min_ride_height * 1000:.1f} mm",
            checks["ride_height"].passed,
        )

        self.cells["travel"].show(
            f"{metrics.max_compression * 1000:.1f} / {metrics.max_rebound * 1000:.1f} mm",
            f"limits {limits.max_compression * 1000:.1f} / {limits.max_rebound * 1000:.1f} mm",
            checks["compression"].passed and checks["rebound"].passed,
        )

        self.cells["acceleration"].show(
            f"{metrics.max_body_acceleration / GRAVITY:.2f} g",
            f"limit {limits.max_body_acceleration / GRAVITY:.2f} g",
            checks["body_acceleration"].passed,
        )

        failed = [check.label for check in evaluation.checks if not check.passed]

        if failed:
            self.verdict.configure(text="✗ fails: " + ", ".join(failed), fg=FAIL)
        else:
            self.verdict.configure(text="✓ passes every limit", fg=PASS)

        if metrics.air_time > 0:
            contact = (f"tire in the air {metrics.air_time * 1000:.1f} ms "
                       f"(limit {limits.max_air_time * 1000:.1f} ms)")
        else:
            contact = (f"tire stays on the ground, lowest load {metrics.min_contact_force:.0f} N "
                       f"({metrics.max_tire_load_loss * 100:.0f} % lost)")

        self.summary.configure(text=contact)

        if header:
            self.sweep_line.configure(text=header)
            self.sweep_line.pack(fill="x", pady=(self.theme.px(2), 0))
        else:
            self.sweep_line.configure(text="")
            self.sweep_line.pack_forget()

    def _describe_point(self, sweep, point, separator="  |  ", skip=()):
        return separator.join(
            f"{axis.spec.name} {axis.spec.format(value)}"
            f"{'' if axis.spec.unit in ('', '-') else ' ' + axis.spec.unit}"
            for axis, value in zip(sweep.axes, point.values)
            if axis.key not in skip
        )

    def _show_sweep(self):
        """Ranking table and results bar for the latest sweep and rank metric."""

        self._fill_ranking()

        if not self.ranked:
            return

        self._show_results(self.ranked[0].evaluation, header=self._sweep_header())
        self.results_source.configure(text="best setup of the sweep")

    def _sweep_header(self):
        """One line about the sweep: size, swept values not shown in the cells, warnings."""

        sweep, best = self.sweep, self.ranked[0]
        rank = RANK_METRICS[self.sweep_form.rank_metric()]

        if best.feasible:
            parts = [f"best {rank.label} of {len(self.ranked)} setups "
                     f"({sweep.feasible_count} pass)"]
        else:
            parts = [f"none of {len(self.ranked)} setups passes every limit: "
                     f"this one misses by the least"]

        others = self._describe_point(sweep, best, ", ", skip=("motion_ratio", "spring_rate"))
        if others:
            parts.append(others)

        # Best at the end of a range: the optimum may lie outside it
        edges = []
        for i, axis in enumerate(sweep.axes):
            count = len(sweep.grids[i])
            if count >= 3 and best.index[i] in (0, count - 1):
                edges.append(f"{axis.spec.name} ({'low' if best.index[i] == 0 else 'high'})")

        if edges:
            parts.append(f"best is at the edge of the range for {', '.join(edges)}: widen it")

        return "   |   ".join(parts)

    # -------------------------------------------------------------------
    # Ranking table
    # -------------------------------------------------------------------

    def _fill_ranking(self):

        px = self.theme.px
        sweep = self.sweep
        table = self.table
        rank_key = self.sweep_form.rank_metric()

        table.delete(*table.get_children())

        # The ranked value first, then "over limit": how far a failing setup
        # misses the limits (failing rows sort by it), then the swept values
        metric_order = [rank_key] + [key for key in RANK_METRICS if key != rank_key]

        def metric_column(key):
            metric = RANK_METRICS[key]
            heading = f"{metric.short} {metric.unit}" + ("  ▾" if key == rank_key else "")
            return key, heading, 92, key

        columns = [("rank", "#", 44, None), ("result", "result", 58, None),
                   metric_column(rank_key), ("over", "over limit %", 92, None)]

        for i, axis in enumerate(sweep.axes):
            unit = "" if axis.spec.unit in ("", "-") else f" ({axis.spec.unit})"
            columns.append((f"axis{i}", f"{axis.spec.name}{unit}", 130, None))

        columns += [metric_column(key) for key in metric_order[1:]]

        table.configure(columns=[column for column, _, _, _ in columns])

        for column, heading, width, metric in columns:
            table.heading(column, text=heading,
                          command=(lambda k=metric: self.sweep_form.set_rank_metric(k))
                          if metric else "")
            table.column(column, width=px(width), minwidth=px(40), stretch=False,
                         anchor="w" if column == "result" else "e")

        self.ranked = sweep.ranked(rank_key)

        for rank, point in enumerate(self.ranked, start=1):

            evaluation = point.evaluation

            metrics = [RANK_METRICS[key].format(evaluation.metrics) for key in metric_order]

            values = [rank, "pass" if evaluation.feasible else "fail", metrics[0],
                      f"{evaluation.violation * 100:.0f}"]
            values += [axis.spec.format(value) for axis, value in zip(sweep.axes, point.values)]
            values += metrics[1:]

            table.insert("", "end", iid=str(rank - 1), values=values,
                         tags=() if evaluation.feasible else ("fails",))

        skipped = len(sweep.points) - len(self.ranked)
        note = f"{len(self.ranked)} setups, {sweep.feasible_count} pass"
        if skipped:
            note += f", {skipped} could not run (invalid road size)"

        self.ranking_note.configure(text=note)

    def _table_double_click(self, event):
        if self.table.identify_region(event.x, event.y) == "cell":
            self._load_selected()

    def _load_selected(self):

        selection = self.table.selection()

        if not selection:
            self.set_status("select a row in the ranking first")
            return

        self.load_point(self.ranked[int(selection[0])])

    def load_point(self, point):
        """Put a sweep setup into the setup tab and simulate it."""

        if self.busy or point.evaluation is None:
            return

        case = point.evaluation.case

        self.form.set_case(case)
        self._mark_profile(case.road.profile)
        self.editor.selected = 0
        self.show_tab("setup")

        self.run_simulation()
        self.set_status(f"loaded {self._describe_point(self.sweep, point, ', ')}  -  running ...")

    def _export_csv(self):

        if self.sweep is None:
            self.set_status("run a sweep first")
            return

        path = filedialog.asksaveasfilename(
            parent=self.root, title="export sweep results", defaultextension=".csv",
            initialfile="sweep_results.csv", filetypes=[("CSV files", "*.csv")],
        )

        if not path:
            return

        sweep = self.sweep

        header = ["rank", "passes", "failed limits"]
        header += [f"{axis.spec.label} ({axis.spec.unit})" for axis in sweep.axes]
        header += [f"{metric.label} ({metric.unit})" for metric in RANK_METRICS.values()]

        with open(path, "w", newline="", encoding="utf-8") as file:

            writer = csv.writer(file)
            writer.writerow(header)

            for rank, point in enumerate(self.ranked, start=1):

                evaluation = point.evaluation

                row = [rank, evaluation.feasible,
                       "; ".join(check.label for check in evaluation.checks if not check.passed)]
                row += [axis.spec.format(value) for axis, value in zip(sweep.axes, point.values)]
                row += [round(metric.display(evaluation.metrics), 4)
                        for metric in RANK_METRICS.values()]

                writer.writerow(row)

        self.set_status(f"saved {path}")

    # -------------------------------------------------------------------
    # Sweep chart interaction (hover = details, double-click = load)
    # -------------------------------------------------------------------

    def _point_at(self, event):

        info = self.sweep_plot

        if info is None or event.inaxes is None:
            return None

        if event.inaxes is info.trade_ax and info.trade_xy is not None and len(info.trade_xy):

            screen = info.trade_ax.transData.transform(info.trade_xy)
            distance = np.hypot(screen[:, 0] - event.x, screen[:, 1] - event.y)
            nearest = int(np.argmin(distance))

            if distance[nearest] < self.theme.px(14):
                return info.trade_points[nearest]

        if event.inaxes is info.map_ax and event.xdata is not None:

            column = int(round(event.xdata))
            row = int(round(event.ydata)) if len(info.map_axes) == 2 else 0

            return info.cell_points.get((column, row))

        return None

    def _hover(self, event):

        if self.sweep_plot is None:
            return

        point = self._point_at(event)

        if point is self._hover_point:
            return

        self._hover_point = point

        if self._hover_note is not None:
            self._hover_note.remove()
            self._hover_note = None

        if point is not None:

            metrics = point.evaluation.metrics
            rank = RANK_METRICS[self.sweep_form.rank_metric()]
            verdict = "passes" if point.feasible else "fails a limit"

            text = (
                f"{self._describe_point(self.sweep, point, chr(10))}\n"
                f"{rank.label} {rank.format(metrics)} {rank.unit}  ({verdict})\n"
                f"accel {metrics.max_body_acceleration / GRAVITY:.2f} g  |  "
                f"load lost {metrics.max_tire_load_loss * 100:.0f} %  |  "
                f"comp {metrics.max_compression * 1000:.1f} mm"
            )

            ax = event.inaxes
            right_half = event.x > (ax.bbox.x0 + ax.bbox.x1) / 2
            top_half = event.y > (ax.bbox.y0 + ax.bbox.y1) / 2

            self._hover_note = ax.annotate(
                text, xy=(event.xdata, event.ydata),
                xytext=(-12 if right_half else 12, -12 if top_half else 12),
                textcoords="offset points",
                ha="right" if right_half else "left", va="top" if top_half else "bottom",
                fontsize=8, color=INK, zorder=10, annotation_clip=False,
                bbox=dict(boxstyle="square,pad=0.45", facecolor="#fcfcfb",
                          edgecolor=BORDER, linewidth=0.8),
            )

            # Keep the note out of the automatic layout, or the charts would shift
            self._hover_note.set_in_layout(False)

        self.canvas.draw_idle()

    # -------------------------------------------------------------------

    def _close(self):
        self.cancel.set()
        self.root.destroy()


# ---------------------------------------------------------------------------
# 3. START
# ---------------------------------------------------------------------------

def main():
    enable_dpi_awareness()
    root = tk.Tk()
    QuarterCarApp(root)
    root.mainloop()
