"""
Matplotlib figures for the design tool.

No Tk code in here: every function draws into a matplotlib Figure that it is
given, so the same plots work in the app, in a script, or in a web app later.
"""

# ---------------------------------------------------------------------------
# PLOTTING
#
#   plot_road(fig, case)                quarter-car sketch + editable road
#   refresh_road(plot, road)            redraw just the road curves (dragging)
#   plot_response(fig, evaluation)      time histories of one run, with the limits
#   plot_sweep(fig, sweep, metric, x, y)  metric map + trade-off chart of a sweep
#   plot_message(fig, text)             empty view with a hint
#
#   Colors follow the part they show, in every plot:
#     blue   = body (sprung mass)      orange = wheel (unsprung mass)
#     gray   = road                    red dashed = a design limit
#     light -> dark blue = size of the mapped metric
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field

import matplotlib
import numpy as np
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap, ListedColormap
from matplotlib.patches import Rectangle

from .config import GRAVITY, LBF_IN_TO_N_M
from .damper import build_damper
from .metrics import RANK_METRICS
from .road import describe, make_road, surface_outline


# ---------------------------------------------------------------------------
# 2. STYLE
# ---------------------------------------------------------------------------

FIGURE = "#d9d9d9"          # same gray as the app panels
SURFACE = "#fcfcfb"         # plot area

INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#b9b8b0"

BODY = "#2a78d6"            # sprung mass
WHEEL = "#eb6834"           # unsprung mass
ROAD = "#52514e"
ROAD_FILL = "#d6d5ce"
LIMIT = "#d03b3b"           # design limits and violations
FAILED = "#a8a7a0"          # setups that fail a limit

MAP_COLORS = ListedColormap(
    LinearSegmentedColormap.from_list(
        "metric", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
    )(np.linspace(0, 1, 256))
)


def _font_family():
    """First font from the list that matplotlib can find on this machine."""

    available = {font.name for font in font_manager.fontManager.ttflist}

    for name in ("Segoe UI", "Helvetica Neue", "Helvetica", "Arial"):
        if name in available:
            return [name, "DejaVu Sans"]

    return ["DejaVu Sans"]


STYLE = {
    "font.family": _font_family(),
    "font.size": 8.5,
    "text.color": INK,
    "figure.facecolor": FIGURE,
    "axes.facecolor": SURFACE,
    "axes.edgecolor": AXIS,
    "axes.linewidth": 0.8,
    "axes.titlesize": 9.5,
    "axes.titlecolor": INK,
    "axes.titlelocation": "left",
    "axes.titlepad": 5,
    "axes.labelsize": 8.5,
    "axes.labelcolor": INK_SECONDARY,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "grid.linestyle": "-",
    "xtick.color": AXIS,
    "ytick.color": AXIS,
    "xtick.labelcolor": INK_SECONDARY,
    "ytick.labelcolor": INK_SECONDARY,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "legend.frameon": False,
    "lines.linewidth": 1.6,
    "lines.solid_capstyle": "round",
}


def _new_page(fig):
    """Clear the figure and switch on constrained layout."""

    fig.clear()
    fig.set_facecolor(FIGURE)
    fig.set_layout_engine("constrained")
    fig.get_layout_engine().set(w_pad=0.06, h_pad=0.06, wspace=0.06, hspace=0.08)


def _limit_line(ax, value, text, label_below=False, horizontal=True):
    """
    Dashed red line marking a design limit. The label sits on the allowed
    side of the line (below an upper limit, above a lower limit), so it
    never runs into the plot title.
    """

    if horizontal:
        ax.axhline(value, color=LIMIT, linewidth=1.0, linestyle=(0, (4, 3)))
        ax.annotate(
            text, xy=(1.0, value), xycoords=("axes fraction", "data"),
            xytext=(-3, -2 if label_below else 2), textcoords="offset points",
            ha="right", va="top" if label_below else "bottom", fontsize=7.5, color=LIMIT,
        )
    else:
        ax.axvline(value, color=LIMIT, linewidth=1.0, linestyle=(0, (4, 3)))
        ax.annotate(
            text, xy=(value, 1.0), xycoords=("data", "axes fraction"),
            xytext=(-3, -3), textcoords="offset points",
            ha="right", va="top", fontsize=7.5, color=LIMIT,
        )


def _mark_extreme(ax, x, y, text, violated):
    """Dot + value label on the extreme of a curve (direct label)."""

    color = LIMIT if violated else INK

    ax.plot([x], [y], "o", markersize=4.5, color=color,
            markeredgecolor=SURFACE, markeredgewidth=1.2, zorder=5)

    ax.annotate(text, xy=(x, y), xytext=(5, 0), textcoords="offset points",
                ha="left", va="center", fontsize=7.5, color=color)


def plot_message(fig, text):
    """Empty view with a short hint in the middle."""

    with matplotlib.rc_context(STYLE):

        _new_page(fig)

        ax = fig.add_subplot()
        ax.set_axis_off()
        ax.text(0.5, 0.5, text, ha="center", va="center", fontsize=11, color=INK_SECONDARY)


# ---------------------------------------------------------------------------
# 3. ROAD VIEW (QUARTER-CAR SKETCH + EDITABLE ROAD)
# ---------------------------------------------------------------------------

def _spring(ax, x, y0, y1, width=0.9, turns=5, color=INK):

    lead = 0.18 * (y1 - y0)
    count = 2 * turns

    ys = np.linspace(y0 + lead, y1 - lead, count + 1)
    xs = [x] + [x + (width / 2 if i % 2 else -width / 2) for i in range(1, count)] + [x]

    ax.plot([x, x], [y0, y0 + lead], color=color, linewidth=1.3)
    ax.plot(xs, ys, color=color, linewidth=1.3)
    ax.plot([x, x], [y1 - lead, y1], color=color, linewidth=1.3)


def _damper(ax, x, y0, y1, width=0.9, color=INK):

    height = y1 - y0
    cylinder_bottom = y0 + 0.2 * height
    cylinder_top = y0 + 0.68 * height
    piston = y0 + 0.5 * height

    ax.plot([x, x], [y0, cylinder_bottom], color=color, linewidth=1.3)
    ax.plot(
        [x - width / 2, x - width / 2, x + width / 2, x + width / 2],
        [cylinder_top, cylinder_bottom, cylinder_bottom, cylinder_top],
        color=color, linewidth=1.3,
    )
    ax.plot([x - 0.38 * width, x + 0.38 * width], [piston, piston], color=color, linewidth=2.2)
    ax.plot([x, x], [piston, y1], color=color, linewidth=1.3)


def _mass(ax, x0, x1, y0, y1, edge, title, value):
    """Mass block with a name and a value, spaced in points so they never overlap."""

    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=SURFACE,
                           edgecolor=edge, linewidth=1.8, zorder=3))

    middle = ((x0 + x1) / 2, (y0 + y1) / 2)

    ax.annotate(title, xy=middle, xytext=(0, 5), textcoords="offset points",
                ha="center", va="bottom", fontsize=7.5, color=INK_SECONDARY, zorder=4)
    ax.annotate(value, xy=middle, xytext=(0, 3), textcoords="offset points",
                ha="center", va="top", fontsize=9, color=INK, zorder=4)


def _side_label(ax, y, text):
    ax.text(6.15, y, text, fontsize=7.5, color=INK_SECONDARY, va="center", ha="left")


def draw_quarter_car(ax, case, road):
    """Sketch of the one-corner model with its main values, over the road."""

    corner = case.corner
    damper = corner.damper
    lbf_in = 1 / LBF_IN_TO_N_M

    ax.set_xlim(0, 10)
    ax.set_ylim(0, 14.2)
    ax.set_axis_off()

    # Road surface (flat if the road cannot be built)
    outline_x, outline_z = surface_outline(road) if road else (np.array([0.0, 1.0]), np.zeros(2))
    road_x = 0.4 + 9.2 * outline_x
    road_y = 1.0 + 0.9 * outline_z
    ax.fill_between(road_x, road_y, 0.35, color=ROAD_FILL, linewidth=0)
    ax.plot(road_x, road_y, color=ROAD, linewidth=1.6)

    # Tire spring + tire damping
    _spring(ax, 2.9, 1.9, 4.1, width=0.8)
    _damper(ax, 4.1, 1.9, 4.1, width=0.8)
    ax.plot([2.5, 4.5], [1.9, 1.9], color=INK, linewidth=1.3)

    # Unsprung mass
    _mass(ax, 1.9, 5.1, 4.1, 5.9, WHEEL, "unsprung", f"{corner.unsprung_mass:.2f} kg")

    # Suspension spring + nonlinear damper
    _spring(ax, 2.9, 5.9, 9.3, width=0.8)
    _damper(ax, 4.1, 5.9, 9.3, width=0.8)

    # Sprung mass: this corner's share only
    _mass(ax, 1.4, 5.6, 9.3, 11.6, BODY, "sprung (corner)", f"{corner.sprung_mass:.2f} kg")

    # Values next to the parts
    _side_label(ax, 10.45, f"MR {corner.motion_ratio:.3f}")
    _side_label(ax, 8.4, f"wheel {corner.wheel_rate * lbf_in:.0f} lbf/in")
    _side_label(ax, 6.8, f"LS {damper.LSC_ratio:.2f} / {damper.LSR_ratio:.2f}")
    _side_label(ax, 3.0, f"tire {corner.tire_spring_rate * lbf_in:.0f} lbf/in")

    # Coordinates
    for y, name in ((10.45, "zs"), (5.0, "zu"), (1.45, "zr")):
        ax.annotate("", xy=(0.75, y + 0.75), xytext=(0.75, y - 0.25),
                    arrowprops=dict(arrowstyle="->", color=INK_SECONDARY, linewidth=1.0))
        ax.annotate(name, xy=(0.75, y + 0.25), xytext=(-4, 0), textcoords="offset points",
                    fontsize=7.5, color=INK_SECONDARY, ha="right", va="center")

    ax.text(5.0, 13.3, "one wheel corner", ha="center", va="center", fontsize=9, color=INK)


@dataclass
class RoadPlot:
    """The road axes and the parts the road editor redraws while dragging."""

    profile_ax: object
    velocity_ax: object
    window: tuple = (0.0, 3.0)                      # x range shown (m)
    nodes: np.ndarray = None                        # feature points: (x m, height mm)
    artists: dict = field(default_factory=dict)


def road_window(road):
    """x range to show: every feature plus room around it to add more."""

    if road is None:
        return 0.0, 3.0

    pad = max(0.25 * (road.end - road.start), 0.3)

    return max(0.0, road.start - pad), road.end + pad


def refresh_road(plot, road, selected=None, rescale=False):
    """Redraw the road curves and the feature points in place."""

    artists = plot.artists

    if rescale:
        plot.window = road_window(road)

    positions = np.linspace(*plot.window, 900)

    if road is None:
        z = slope = np.zeros_like(positions)
        features, speed = [], 0.0
    else:
        z, slope = road.profile(positions)
        features, speed = road.features, road.speed

    # Hole walls, drawn dashed: the solid line is the wheel path over them
    walls = []
    for feature in features:
        if feature.shape == "hole":
            depth = feature.height * 1000
            walls += [(feature.start, 0), (feature.start, depth), (feature.end, depth),
                      (feature.end, 0), (np.nan, np.nan)]

    walls = np.array(walls).reshape(-1, 2)
    artists["walls"].set_data(walls[:, 0], walls[:, 1])

    artists["profile"].set_data(positions, z * 1000)

    if artists.get("fill") is not None:
        artists["fill"].remove()
    artists["fill"] = plot.profile_ax.fill_between(positions, z * 1000, 0, color=ROAD_FILL,
                                                   linewidth=0, zorder=1)

    artists["velocity"].set_data(positions, slope * speed)

    plot.nodes = np.array([(f.centre, f.height * 1000) for f in features]).reshape(-1, 2)
    artists["nodes"].set_data(plot.nodes[:, 0], plot.nodes[:, 1])

    chosen = plot.nodes[[selected]] if selected is not None and selected < len(plot.nodes) else []
    chosen = np.reshape(chosen, (-1, 2))
    artists["selected"].set_data(chosen[:, 0], chosen[:, 1])

    if rescale:

        # Leave room above and below the road, to drag points and add bumps or dips
        heights = np.concatenate([z * 1000, plot.nodes[:, 1], [0.0]])
        room = max(5.0, 0.6 * np.abs(heights).max())
        low, high = min(heights.min(), -room), max(heights.max(), room)
        margin = 0.15 * (high - low)

        plot.profile_ax.set_xlim(*plot.window)
        plot.profile_ax.set_ylim(low - margin, high + margin)

        plot.velocity_ax.relim()
        plot.velocity_ax.autoscale_view(scalex=False)


def plot_road(fig, case, selected=None):
    """Road view: model sketch, the road (with a point per feature) and its velocity."""

    try:
        road = make_road(case.road, case.corner.tire_radius)
        problem = ""
    except ValueError as error:
        road, problem = None, str(error)

    with matplotlib.rc_context(STYLE):

        _new_page(fig)

        grid = fig.add_gridspec(2, 2, width_ratios=[1.0, 2.3], height_ratios=[1.25, 1.0])

        sketch = fig.add_subplot(grid[:, 0])
        profile_ax = fig.add_subplot(grid[0, 1])
        velocity_ax = fig.add_subplot(grid[1, 1], sharex=profile_ax)

        draw_quarter_car(sketch, case, road)

        plot = RoadPlot(profile_ax, velocity_ax)

        plot.artists = dict(
            walls=profile_ax.plot([], [], color=ROAD, linewidth=1.0, linestyle=(0, (3, 2)),
                                  zorder=2)[0],
            profile=profile_ax.plot([], [], color=ROAD, zorder=3)[0],
            nodes=profile_ax.plot([], [], "o", markersize=7, markerfacecolor=SURFACE,
                                  markeredgecolor=INK, markeredgewidth=1.5, zorder=5)[0],
            selected=profile_ax.plot([], [], "o", markersize=9, markerfacecolor=INK,
                                     markeredgecolor=SURFACE, markeredgewidth=1.5, zorder=6)[0],
            velocity=velocity_ax.plot([], [], color=ROAD)[0],
        )

        profile_ax.axhline(0, color=AXIS, linewidth=0.8, zorder=0)
        profile_ax.set_title(f"road  |  {describe(case.road, road)}" if road else "road")
        profile_ax.set_ylabel("height (mm)")
        profile_ax.tick_params(labelbottom=False)

        velocity_ax.axhline(0, color=AXIS, linewidth=0.8)
        velocity_ax.set_ylabel("m/s")
        velocity_ax.set_xlabel("distance from the car's start (m)")
        velocity_ax.set_title(
            f"vertical road velocity at {case.road.speed * 3.6:.0f} km/h"
            + (f"  |  peak {road.peak_velocity():.2f} m/s" if road else "")
        )

        refresh_road(plot, road, selected, rescale=True)

        if road is None:
            profile_ax.text(0.5, 0.5, problem, transform=profile_ax.transAxes,
                            ha="center", va="center", fontsize=9, color=INK_SECONDARY)

    return plot


# ---------------------------------------------------------------------------
# 4. RESPONSE VIEW (ONE RUN)
# ---------------------------------------------------------------------------

def _airborne_spans(time, contact_force):
    """(start, end) time pairs where the tire is off the ground."""

    airborne = contact_force <= 0.0
    edges = np.flatnonzero(np.diff(airborne.astype(int)))

    starts = list(edges[airborne[edges + 1]] + 1)
    ends = list(edges[~airborne[edges + 1]])

    if airborne[0]:
        starts.insert(0, 0)
    if airborne[-1]:
        ends.append(len(airborne) - 1)

    return [(time[a], time[b]) for a, b in zip(starts, ends)]


def plot_response(fig, evaluation):
    """Six panels: displacements, travel, body accel, ride height, tire load, damper."""

    result = evaluation.result
    metrics = evaluation.metrics
    limits = evaluation.case.limits
    passed = {check.key: check.passed for check in evaluation.checks}

    time = result.time

    with matplotlib.rc_context(STYLE):

        _new_page(fig)

        axes = fig.subplots(2, 3)
        (disp_ax, travel_ax, accel_ax), (height_ax, tire_ax, damper_ax) = axes

        # One shared time axis; units are in the titles to save space
        for ax in (travel_ax, accel_ax, height_ax, tire_ax):
            ax.sharex(disp_ax)

        for ax in (disp_ax, travel_ax):
            ax.tick_params(labelbottom=False)

        for ax in (height_ax, tire_ax):
            ax.set_xlabel("time (s)")

        # --------------------------------------------------
        # Displacements
        # --------------------------------------------------

        disp_ax.fill_between(time, result.road_displacement * 1000, 0,
                             color=ROAD_FILL, linewidth=0)
        disp_ax.plot(time, result.road_displacement * 1000, color=ROAD, linewidth=1.2, label="road")
        disp_ax.plot(time, result.unsprung_displacement * 1000, color=WHEEL, label="wheel")
        disp_ax.plot(time, result.sprung_displacement * 1000, color=BODY, label="body")
        disp_ax.set_title("displacement (mm)")
        disp_ax.legend(loc="upper right", ncols=3, handlelength=1.4, columnspacing=1.0)
        disp_ax.set_xlim(time[0], time[-1])

        # --------------------------------------------------
        # Suspension travel (+ = rebound, - = compression)
        # --------------------------------------------------

        travel = result.suspension_travel * 1000

        travel_ax.axhline(0, color=AXIS, linewidth=0.8)
        travel_ax.plot(time, travel, color=BODY)
        _limit_line(travel_ax, limits.max_rebound * 1000, "rebound limit", label_below=True)
        _limit_line(travel_ax, -limits.max_compression * 1000, "compression limit")
        travel_ax.set_title("suspension travel (mm, + = rebound)")
        travel_ax.set_ylim(
            1.15 * min(travel.min(), -limits.max_compression * 1000),
            1.15 * max(travel.max(), limits.max_rebound * 1000),
        )

        i = int(np.argmin(travel))
        _mark_extreme(travel_ax, time[i], travel[i], f"comp {-travel[i]:.1f} mm",
                      not passed["compression"])

        # --------------------------------------------------
        # Body acceleration
        # --------------------------------------------------

        accel = result.sprung_acceleration / GRAVITY
        accel_limit = limits.max_body_acceleration / GRAVITY

        accel_ax.axhline(0, color=AXIS, linewidth=0.8)
        accel_ax.plot(time, accel, color=BODY)
        _limit_line(accel_ax, accel_limit, f"limit {accel_limit:.2f} g", label_below=True)
        _limit_line(accel_ax, -accel_limit, "")
        accel_ax.set_title("body acceleration (g)")
        accel_reach = 1.15 * max(np.abs(accel).max(), accel_limit)
        accel_ax.set_ylim(-accel_reach, accel_reach)

        i = int(np.argmax(np.abs(accel)))
        _mark_extreme(accel_ax, time[i], accel[i], f"{abs(accel[i]):.2f} g",
                      not passed["body_acceleration"])

        # --------------------------------------------------
        # Ride height
        # --------------------------------------------------

        ride_height = result.ride_height * 1000

        height_ax.plot(time, ride_height, color=BODY)
        _limit_line(height_ax, limits.min_ride_height * 1000,
                    f"min {limits.min_ride_height * 1000:.1f} mm")
        height_ax.set_title("ride height at this corner (mm)")
        height_ax.set_ylim(
            min(limits.min_ride_height * 1000, ride_height.min()) - 2,
            ride_height.max() + 0.12 * (ride_height.max() - limits.min_ride_height * 1000),
        )

        i = int(np.argmin(ride_height))
        _mark_extreme(height_ax, time[i], ride_height[i], f"{ride_height[i]:.1f} mm",
                      not passed["ride_height"])

        # --------------------------------------------------
        # Tire contact force (shaded = tire in the air)
        # --------------------------------------------------

        for start, end in _airborne_spans(time, result.contact_force):
            tire_ax.axvspan(start, end, color=LIMIT, alpha=0.12, linewidth=0)

        tire_ax.axhline(result.static_tire_load, color=AXIS, linewidth=1.0)
        tire_ax.annotate("static", xy=(1.0, result.static_tire_load),
                         xycoords=("axes fraction", "data"), xytext=(-3, 2),
                         textcoords="offset points", ha="right", va="bottom",
                         fontsize=7.5, color=INK_SECONDARY)
        tire_ax.plot(time, result.contact_force, color=WHEEL)
        tire_ax.set_ylim(0, result.contact_force.max() * 1.1)

        air_text = f"  |  airborne {metrics.air_time * 1000:.0f} ms" if metrics.air_time > 0 else ""
        tire_ax.set_title(f"tire load (N){air_text}")

        i = int(np.argmin(result.contact_force))
        _mark_extreme(tire_ax, time[i], result.contact_force[i],
                      f"{result.contact_force[i]:.0f} N ({metrics.max_tire_load_loss * 100:.0f} % lost)",
                      not passed["contact"])

        # --------------------------------------------------
        # Damper (shaft / dyno view)
        # --------------------------------------------------

        motion_ratio = evaluation.case.corner.motion_ratio
        damper = build_damper(evaluation.case.corner)

        reach = max(np.abs(result.damper_velocity).max() * 1.15, 0.05)
        shaft_velocity = np.linspace(-reach, reach, 301)
        shaft_force = damper.curve(shaft_velocity / motion_ratio) / motion_ratio

        damper_ax.axhline(0, color=AXIS, linewidth=0.8)
        damper_ax.axvline(0, color=AXIS, linewidth=0.8)
        damper_ax.plot(shaft_velocity, shaft_force, color=INK_MUTED, linewidth=1.2,
                       label="damper curve")
        damper_ax.plot(result.damper_velocity, result.damper_force, color=BODY,
                       linewidth=1.4, label="this run")
        damper_ax.set_title("damper force at shaft (N)")
        damper_ax.set_xlabel("shaft velocity (m/s, + = rebound)")
        damper_ax.legend(loc="upper left", handlelength=1.4)


# ---------------------------------------------------------------------------
# 5. SWEEP VIEW
# ---------------------------------------------------------------------------

@dataclass
class SweepPlot:
    """What the app needs to make the sweep charts interactive."""

    map_ax: object = None
    trade_ax: object = None
    trade_points: list = field(default_factory=list)       # sweep points, scatter order
    trade_xy: np.ndarray = None                            # their (x, y) in data units
    cell_points: dict = field(default_factory=dict)        # (col, row) -> best point there
    map_axes: tuple = ()


def _tick_labels(spec, values, max_labels=9):
    """Formatted tick labels, thinned out if there are many values."""

    step = max(1, int(np.ceil(len(values) / max_labels)))

    positions = list(range(0, len(values), step))

    return positions, [spec.format(values[i]) for i in positions]


def _axis_title(spec):
    unit = f" ({spec.unit})" if spec.unit and spec.unit != "-" else ""
    return f"{spec.label}{unit}"


def plot_sweep(fig, sweep, metric, x_axis=0, y_axis=1):
    """
    Left: best passing value of `metric` for each combination of two swept
    variables (a line if only one is swept). Right: every setup on a
    body-accel vs grip chart.
    """

    info = SweepPlot()

    valid = [point for point in sweep.points if point.evaluation is not None]

    if not valid:
        plot_message(fig, "no sweep points could be run")
        return info

    rank = RANK_METRICS[metric]
    best = sweep.best(metric)
    unit = f" {rank.unit}"

    with matplotlib.rc_context(STYLE):

        _new_page(fig)

        map_ax, trade_ax = fig.subplots(1, 2, width_ratios=[1.1, 1.0])
        info.map_ax, info.trade_ax = map_ax, trade_ax

        # --------------------------------------------------
        # Metric map
        # --------------------------------------------------

        # Variables not on the map: each cell shows the best setup over them
        other = [axis.spec.name for i, axis in enumerate(sweep.axes) if i not in (x_axis, y_axis)]
        if other:
            map_ax.set_title(f"best over {', '.join(other)}", loc="right",
                             fontsize=7.5, color=INK_MUTED)

        two_d = len(sweep.axes) >= 2 and y_axis is not None

        x_spec = sweep.axes[x_axis].spec
        x_values = sweep.grids[x_axis]

        info.cell_points = sweep.best_per_cell(metric, x_axis, y_axis if two_d else None)

        if two_d:

            info.map_axes = (x_axis, y_axis)

            y_spec = sweep.axes[y_axis].spec
            y_values = sweep.grids[y_axis]

            values = np.full((len(y_values), len(x_values)), np.nan)
            for (column, row), point in info.cell_points.items():
                values[row, column] = rank.display(point.evaluation.metrics)

            # Gray only where setups were run and none passed
            # (a cancelled sweep leaves cells that were never run blank)
            ran = np.zeros(values.shape, dtype=bool)
            for point in valid:
                ran[point.index[y_axis], point.index[x_axis]] = True

            failed = np.isnan(values) & ran

            x_edges = np.arange(len(x_values) + 1) - 0.5
            y_edges = np.arange(len(y_values) + 1) - 0.5

            map_ax.grid(False)

            if (~np.isnan(values)).any():
                mesh = map_ax.pcolormesh(
                    x_edges, y_edges, np.ma.masked_invalid(values), cmap=MAP_COLORS,
                    edgecolors=SURFACE, linewidth=2,
                )
                colorbar = fig.colorbar(mesh, ax=map_ax, shrink=0.9, pad=0.02)
                colorbar.set_label(f"{rank.label} ({rank.unit})")
                colorbar.outline.set_visible(False)
                colorbar.ax.tick_params(labelsize=7.5)

            if failed.any():
                map_ax.pcolormesh(
                    x_edges, y_edges, np.ma.masked_where(~failed, np.ones_like(values)),
                    cmap=ListedColormap([FAILED]), edgecolors=SURFACE, linewidth=2,
                )

            if best is not None and best.feasible:
                bx, by = best.index[x_axis], best.index[y_axis]
                map_ax.add_patch(Rectangle((bx - 0.5, by - 0.5), 1, 1, fill=False,
                                           edgecolor=INK, linewidth=2.2, zorder=4))
                # Lightest cell when lower is better, darkest when higher is
                map_ax.annotate(f"best\n{rank.format(best.evaluation.metrics)}{unit}",
                                xy=(bx, by), ha="center", va="center", fontsize=7.5,
                                zorder=5, color=INK if rank.lower_is_better else SURFACE)

            positions, labels = _tick_labels(x_spec, x_values)
            map_ax.set_xticks(positions, labels)
            positions, labels = _tick_labels(y_spec, y_values)
            map_ax.set_yticks(positions, labels)
            map_ax.set_xlim(x_edges[0], x_edges[-1])
            map_ax.set_ylim(y_edges[0], y_edges[-1])
            map_ax.set_xlabel(_axis_title(x_spec))
            map_ax.set_ylabel(_axis_title(y_spec))
            map_ax.set_title(f"{rank.label} (gray = fails)")

        else:

            info.map_axes = (x_axis,)

            positions = np.arange(len(x_values))
            values = np.full(len(x_values), np.nan)
            for (column, _), point in info.cell_points.items():
                values[column] = rank.display(point.evaluation.metrics)

            map_ax.plot(positions, values, color=BODY, marker="o", markersize=5,
                        markeredgecolor=SURFACE, markeredgewidth=1.2, label="passes")

            # Values where setups ran but none passed: x along the bottom edge
            ran = {point.index[x_axis] for point in valid}
            failing = [i for i in positions if np.isnan(values[i]) and i in ran]
            if failing:
                map_ax.plot(failing, [0.04] * len(failing), transform=map_ax.get_xaxis_transform(),
                            linestyle="none", marker="x", color=FAILED, label="fails a limit")

            ticks, labels = _tick_labels(x_spec, x_values)
            map_ax.set_xticks(ticks, labels)
            map_ax.set_xlim(-0.5, len(x_values) - 0.5)
            map_ax.set_xlabel(_axis_title(x_spec))
            map_ax.set_ylabel(f"{rank.label} ({rank.unit})")
            map_ax.set_title(f"best {rank.label}")
            map_ax.legend(loc="best")

        # --------------------------------------------------
        # Trade-off: body acceleration vs tire load loss
        # --------------------------------------------------

        accel = np.array([p.evaluation.metrics.max_body_acceleration / GRAVITY for p in valid])
        load_loss = np.array([p.evaluation.metrics.max_tire_load_loss * 100 for p in valid])
        feasible = np.array([p.feasible for p in valid])

        info.trade_points = valid
        info.trade_xy = np.column_stack([accel, load_loss])

        if (~feasible).any():
            trade_ax.scatter(accel[~feasible], load_loss[~feasible], marker="x", s=22,
                             color=FAILED, linewidths=1.2, label="fails a limit", zorder=2)

        if feasible.any():
            trade_ax.scatter(accel[feasible], load_loss[feasible], marker="o", s=30,
                             color=BODY, edgecolors=SURFACE, linewidths=1.0,
                             label="passes", zorder=3)

        if best is not None and best.feasible:
            bx = best.evaluation.metrics.max_body_acceleration / GRAVITY
            by = best.evaluation.metrics.max_tire_load_loss * 100
            trade_ax.scatter([bx], [by], marker="o", s=90, color=INK, edgecolors=SURFACE,
                             linewidths=1.5, zorder=4, label=f"best {rank.label}")
            trade_ax.annotate("best", xy=(bx, by), xytext=(7, -2), textcoords="offset points",
                              fontsize=8, color=INK)

        accel_limit = valid[0].evaluation.case.limits.max_body_acceleration / GRAVITY
        if accel_limit <= accel.max() * 1.6:
            _limit_line(trade_ax, accel_limit, f"limit {accel_limit:.2f} g", horizontal=False)

        trade_ax.set_title("trade-off  |  body control vs grip")
        trade_ax.set_title("lower left = better", loc="right", fontsize=7.5, color=INK_MUTED)
        trade_ax.set_xlabel("peak body acceleration (g)")
        trade_ax.set_ylabel("most tire load lost (%)")
        trade_ax.set_ylim(min(-2, load_loss.min() - 4), 104)
        trade_ax.legend(loc="best")

    return info
