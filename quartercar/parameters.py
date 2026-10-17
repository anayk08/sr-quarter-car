"""
Parameter registry: one entry per input, shared by the GUI form and the sweep.
"""

# ---------------------------------------------------------------------------
# PARAMETER REGISTRY
#
#   Each ParamSpec says where a value lives inside a DesignCase, how to show
#   it (label, unit, decimals) and what values are allowed. The GUI builds
#   its form from PARAMETERS, and the sweep engine sets values through the
#   same specs, so adding a parameter here adds it everywhere.
#
#   Display value = SI value * scale     (e.g. mm = m * 1000)
#
#   DERIVED holds read-only values shown in the form (wheel rate, natural
#   frequencies, ...). They update while you type.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

import math
from dataclasses import dataclass, replace
from typing import Callable, Optional

from .config import GRAVITY, LBF_IN_TO_N_M, get_value, with_value
from .damper import build_damper
from .model import linear_modes
from .road import make_road


# ---------------------------------------------------------------------------
# 2. PARAMETER SPEC
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParamSpec:

    key: str
    label: str
    section: str
    path: tuple

    unit: str = ""
    scale: float = 1.0              # display value = SI value * scale
    decimals: int = 2

    positive: bool = False          # must be > 0
    minimum: float = -math.inf      # display units, inclusive
    maximum: float = math.inf       # display units, inclusive
    integer: bool = False

    help: str = ""
    sweep_range: Optional[tuple] = None   # default (start, stop, step), display units
    profiles: tuple = ()                  # road profiles this applies to (empty = all)
    short: str = ""                       # shorter name for tables and charts

    # Optional custom access (used by the damping scale)
    getter: Optional[Callable] = None
    setter: Optional[Callable] = None

    @property
    def name(self):
        return self.short or self.label

    def get(self, case):
        """SI value from a case."""

        if self.getter is not None:
            return self.getter(case)

        return get_value(case, self.path)

    def set(self, case, value):
        """Copy of the case with this parameter set to an SI value."""

        if self.integer:
            value = int(round(value))

        if self.setter is not None:
            return self.setter(case, value)

        return with_value(case, self.path, value)

    def to_display(self, value):
        return value * self.scale

    def from_display(self, value):
        return value / self.scale

    def format(self, value):
        """SI value as display text."""

        return f"{self.to_display(value):.{self.decimals}f}"

    def check(self, display_value):
        """Error message for a display value, or None if it is allowed."""

        if not math.isfinite(display_value):
            return "must be a number"

        if self.integer and abs(display_value - round(display_value)) > 1e-9:
            return "must be a whole number"

        if self.positive and display_value <= 0:
            return "must be greater than 0"

        if display_value < self.minimum:
            return f"must be at least {self.minimum:g}"

        if display_value > self.maximum:
            return f"must be at most {self.maximum:g}"

        return None

    def applies_to(self, profile):
        return not self.profiles or profile in self.profiles


# ---------------------------------------------------------------------------
# 3. INPUT PARAMETERS
# ---------------------------------------------------------------------------

LBF_IN = 1 / LBF_IN_TO_N_M     # N/m -> lbf/in
MM = 1000.0                    # m -> mm

SECTIONS = [
    "corner mass",
    "spring",
    "tire",
    "damper",
    "ride height & aero",
    "road",
    "design limits",
    "score weights",
    "simulation",
]

PARAMETERS = [

    # --------------------------------------------------
    # Corner mass
    # --------------------------------------------------

    ParamSpec(
        "sprung_mass", "sprung mass (this corner)", "corner mass", ("corner", "sprung_mass"),
        short="sprung mass", unit="kg", decimals=2, positive=True, maximum=1000,
        help="This corner's share of chassis + driver. NOT the whole car.",
        sweep_range=(50, 75, 5),
    ),
    ParamSpec(
        "unsprung_mass", "unsprung mass", "corner mass", ("corner", "unsprung_mass"),
        unit="kg", decimals=2, positive=True, maximum=200,
        help="Wheel + tire + upright + hub + brake of this corner.",
        sweep_range=(6, 12, 1),
    ),

    # --------------------------------------------------
    # Spring
    # --------------------------------------------------

    ParamSpec(
        "motion_ratio", "motion ratio (spring/wheel)", "spring", ("corner", "motion_ratio"),
        short="motion ratio", unit="-", decimals=3, positive=True, maximum=5,
        help="Spring travel / wheel travel. Wheel rate = spring rate x MR^2.",
        sweep_range=(0.55, 0.95, 0.10),
    ),
    ParamSpec(
        "spring_rate", "spring rate", "spring", ("corner", "spring_rate"),
        unit="lbf/in", scale=LBF_IN, decimals=0, positive=True,
        help="Rate of the coil spring itself.",
        sweep_range=(400, 900, 100),
    ),

    # --------------------------------------------------
    # Tire
    # --------------------------------------------------

    ParamSpec(
        "tire_spring_rate", "tire spring rate", "tire", ("corner", "tire_spring_rate"),
        short="tire rate", unit="lbf/in", scale=LBF_IN, decimals=0, positive=True,
        sweep_range=(400, 700, 50),
    ),
    ParamSpec(
        "tire_damping_ratio", "tire damping ratio", "tire", ("corner", "tire_damping_ratio"),
        short="tire damping", unit="-", decimals=3, minimum=0, maximum=2,
        help="Fraction of tire critical damping, 2*sqrt(kt*mu).",
        sweep_range=(0.0, 0.10, 0.025),
    ),

    # --------------------------------------------------
    # Damper (damping ratios, as in the v1 spreadsheet)
    # --------------------------------------------------

    ParamSpec(
        "LSC_ratio", "low-speed compression", "damper", ("corner", "damper", "LSC_ratio"),
        short="LS comp", unit="ratio", decimals=2, minimum=0, maximum=10,
        help="Fraction of critical damping 2*sqrt(wheel rate * sprung mass).",
        sweep_range=(0.4, 1.0, 0.1),
    ),
    ParamSpec(
        "HSC_ratio", "high-speed compression", "damper", ("corner", "damper", "HSC_ratio"),
        short="HS comp", unit="ratio", decimals=2, minimum=0, maximum=10,
        sweep_range=(0.1, 0.5, 0.1),
    ),
    ParamSpec(
        "LSR_ratio", "low-speed rebound", "damper", ("corner", "damper", "LSR_ratio"),
        short="LS reb", unit="ratio", decimals=2, minimum=0, maximum=10,
        sweep_range=(0.6, 1.4, 0.2),
    ),
    ParamSpec(
        "HSR_ratio", "high-speed rebound", "damper", ("corner", "damper", "HSR_ratio"),
        short="HS reb", unit="ratio", decimals=2, minimum=0, maximum=10,
        sweep_range=(0.3, 0.7, 0.1),
    ),
    ParamSpec(
        "knee_compression", "knee speed, comp. (shaft)", "damper",
        ("corner", "damper", "knee_compression"),
        short="knee comp", unit="m/s", decimals=4, positive=True, maximum=10,
        help="Damper shaft speed where low-speed changes to high-speed.",
    ),
    ParamSpec(
        "knee_rebound", "knee speed, reb. (shaft)", "damper",
        ("corner", "damper", "knee_rebound"),
        short="knee reb", unit="m/s", decimals=4, positive=True, maximum=10,
    ),

    # --------------------------------------------------
    # Ride height and aero
    # --------------------------------------------------

    ParamSpec(
        "static_ride_height", "static ride height", "ride height & aero",
        ("corner", "static_ride_height"),
        short="ride height", unit="mm", scale=MM, decimals=1, positive=True,
        help="Chassis height at this corner, parked, with driver.",
        sweep_range=(20, 50, 5),
    ),
    ParamSpec(
        "aero_load", "aero load on this corner", "ride height & aero", ("corner", "aero_load"),
        short="aero load", unit="N", decimals=0, minimum=0,
        help="Downforce on this corner at the run speed (constant over the run).",
        sweep_range=(0, 300, 50),
    ),

    # --------------------------------------------------
    # Road
    # --------------------------------------------------

    ParamSpec(
        "height", "height", "road", ("road", "height"),
        short="road height", unit="mm", scale=MM, decimals=1, positive=True,
        sweep_range=(5, 30, 5),
    ),
    ParamSpec(
        "length", "length", "road", ("road", "length"),
        short="road length", unit="m", decimals=3, positive=True,
        help="Length of one feature along the road (one strip for a rumble strip).",
        sweep_range=(0.1, 1.0, 0.1),
    ),
    ParamSpec(
        "pitch", "strip pitch", "road", ("road", "pitch"),
        unit="m", decimals=3, positive=True, profiles=("rumble strip",),
        help="Start-to-start spacing of the strips.",
        sweep_range=(0.2, 1.0, 0.1),
    ),
    ParamSpec(
        "count", "number of strips", "road", ("road", "count"),
        unit="-", decimals=0, integer=True, minimum=1, maximum=200,
        profiles=("rumble strip",),
    ),
    ParamSpec(
        "speed", "vehicle speed", "road", ("road", "speed"),
        short="speed", unit="km/h", scale=3.6, decimals=1, positive=True, maximum=400,
        sweep_range=(20, 100, 10),
    ),
    ParamSpec(
        "start_time", "start time", "road", ("road", "start_time"),
        unit="s", decimals=3, minimum=0, maximum=60,
        help="When the tire reaches the road feature.",
    ),

    # --------------------------------------------------
    # Design limits
    # --------------------------------------------------

    ParamSpec(
        "min_ride_height", "min ride height", "design limits", ("limits", "min_ride_height"),
        unit="mm", scale=MM, decimals=1, minimum=0,
    ),
    ParamSpec(
        "max_compression", "max compression travel", "design limits",
        ("limits", "max_compression"),
        unit="mm", scale=MM, decimals=1, positive=True,
        help="Wheel travel available in bump.",
    ),
    ParamSpec(
        "max_rebound", "max rebound travel", "design limits", ("limits", "max_rebound"),
        unit="mm", scale=MM, decimals=1, positive=True,
        help="Wheel travel available in droop.",
    ),
    ParamSpec(
        "max_body_acceleration", "max body acceleration", "design limits",
        ("limits", "max_body_acceleration"),
        unit="g", scale=1 / GRAVITY, decimals=2, positive=True,
    ),
    ParamSpec(
        "max_air_time", "max tire air time", "design limits", ("limits", "max_air_time"),
        unit="ms", scale=1000, decimals=1, minimum=0,
        help="0 = the tire must never leave the ground.",
    ),

    # --------------------------------------------------
    # Score weights
    # --------------------------------------------------

    ParamSpec(
        "w_body_acceleration", "body acceleration", "score weights",
        ("weights", "body_acceleration"), decimals=2, minimum=0,
    ),
    ParamSpec(
        "w_tire_load", "tire load loss", "score weights", ("weights", "tire_load"),
        decimals=2, minimum=0,
    ),
    ParamSpec(
        "w_travel", "travel used", "score weights", ("weights", "travel"),
        decimals=2, minimum=0,
    ),
    ParamSpec(
        "w_ride_height", "clearance used", "score weights", ("weights", "ride_height"),
        decimals=2, minimum=0,
    ),

    # --------------------------------------------------
    # Simulation
    # --------------------------------------------------

    ParamSpec(
        "settle_time", "time after the feature", "simulation", ("sim", "settle_time"),
        unit="s", decimals=2, positive=True, maximum=30,
    ),
    ParamSpec(
        "sample_rate", "output rate", "simulation", ("sim", "sample_rate"),
        unit="Hz", decimals=0, minimum=100, maximum=50000,
    ),
]

PARAMETER_BY_KEY = {spec.key: spec for spec in PARAMETERS}


# ---------------------------------------------------------------------------
# 4. DAMPING SCALE (SWEEP ONLY)
# ---------------------------------------------------------------------------

def _scale_damping(case, factor):
    """Multiply all four damping ratios (keeps the LS/HS and comp/reb balance)."""

    damper = case.corner.damper

    scaled = replace(
        damper,
        LSC_ratio=damper.LSC_ratio * factor,
        HSC_ratio=damper.HSC_ratio * factor,
        LSR_ratio=damper.LSR_ratio * factor,
        HSR_ratio=damper.HSR_ratio * factor,
    )

    return with_value(case, ("corner", "damper"), scaled)


DAMPING_SCALE = ParamSpec(
    "damping_scale", "damping scale", "damper", (),
    unit="x", decimals=2, positive=True, maximum=10,
    help="Multiplies all four damping ratios from the form.",
    sweep_range=(0.50, 1.50, 0.25),
    getter=lambda case: 1.0,
    setter=_scale_damping,
)


# Order of the sweep drop-down lists
SWEEP_VARIABLES = {
    spec.key: spec
    for spec in [
        PARAMETER_BY_KEY["motion_ratio"],
        PARAMETER_BY_KEY["spring_rate"],
        DAMPING_SCALE,
        *[spec for spec in PARAMETERS
          if spec.sweep_range and spec.key not in ("motion_ratio", "spring_rate")],
    ]
}

# Default sweep rows in the GUI: (variable, enabled)
DEFAULT_SWEEP_ROWS = [
    ("motion_ratio", True),
    ("spring_rate", True),
    ("damping_scale", True),
    ("speed", False),
]


# ---------------------------------------------------------------------------
# 5. DERIVED VALUES (READ-ONLY, SHOWN IN THE FORM)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DerivedSpec:
    key: str
    label: str
    section: str
    compute: Callable          # case -> display text
    help: str = ""
    profiles: tuple = ()

    def text(self, case):
        try:
            return self.compute(case)
        except (ValueError, ZeroDivisionError, ArithmeticError):
            return "-"

    def applies_to(self, profile):
        return not self.profiles or profile in self.profiles


def _modes_text(case):
    modes = linear_modes(case.corner)
    return f"body {modes['body_frequency']:.2f} Hz  |  hop {modes['wheel_hop_frequency']:.1f} Hz"


def _modal_damping_text(case):

    modes = linear_modes(case.corner)

    def ratio(value):
        return "overdamped" if value is None else f"{value:.2f}"

    return (
        f"body {ratio(modes['body_damping_ratio'])}  |  "
        f"hop {ratio(modes['wheel_hop_damping_ratio'])}"
    )


def _damper_pair(case, compression, rebound):
    damper = build_damper(case.corner)
    return f"{getattr(damper, compression):.0f} / {getattr(damper, rebound):.0f} N*s/m"


def _road_timing_text(case):

    road = make_road(case.road)

    text = f"{road.duration * 1000:.1f} ms"

    if case.road.profile == "rumble strip":
        text += f"  |  {road.speed / road.pitch:.1f} Hz"

    return text


DERIVED = [
    DerivedSpec(
        "whole_car", "whole car if 4 such corners", "corner mass",
        lambda case: f"{4 * (case.corner.sprung_mass + case.corner.unsprung_mass):.0f} kg",
        help="Sanity check: should be close to car + driver mass.",
    ),
    DerivedSpec(
        "wheel_rate", "wheel rate", "spring",
        lambda case: (
            f"{case.corner.wheel_rate * LBF_IN:.0f} lbf/in  "
            f"({case.corner.wheel_rate / 1000:.1f} N/mm)"
        ),
    ),
    DerivedSpec(
        "ride_rate", "ride rate (with tire)", "spring",
        lambda case: f"{case.corner.ride_rate * LBF_IN:.0f} lbf/in",
    ),
    DerivedSpec("frequencies", "natural frequency", "spring", _modes_text),
    DerivedSpec(
        "tire_damping", "tire damping", "tire",
        lambda case: f"{case.corner.tire_damping:.0f} N*s/m",
    ),
    DerivedSpec(
        "critical_damping", "critical damping (wheel)", "damper",
        lambda case: f"{case.corner.critical_damping:.0f} N*s/m",
    ),
    DerivedSpec(
        "low_speed", "low-speed comp / reb (wheel)", "damper",
        lambda case: _damper_pair(case, "c_LSC", "c_LSR"),
    ),
    DerivedSpec(
        "high_speed", "high-speed comp / reb (wheel)", "damper",
        lambda case: _damper_pair(case, "c_HSC", "c_HSR"),
    ),
    DerivedSpec(
        "modal_damping", "2-DOF modal damping", "damper", _modal_damping_text,
        help="Actual damping of each mode in the 2-DOF model (low-speed slopes).",
    ),
    DerivedSpec(
        "ride_height_at_speed", "ride height at speed", "ride height & aero",
        lambda case: (
            f"{case.corner.ride_height_at_speed * MM:.1f} mm  "
            f"(aero sink {case.corner.aero_sink * MM:.1f})"
        ),
    ),
    DerivedSpec("road_timing", "time on feature", "road", _road_timing_text),
    DerivedSpec(
        "road_velocity", "peak road velocity", "road",
        lambda case: f"{make_road(case.road).peak_velocity():.2f} m/s",
    ),
]
