"""
Key performance numbers of one simulation run.
"""

# ---------------------------------------------------------------------------
# METRICS
#
#   Turns the time histories of one run into the numbers a designer
#   compares setups on. Compression and rebound are reported separately.
#
#   RANK_METRICS lists the numbers a sweep can be ranked and mapped by,
#   with their display unit and which direction is better.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

from dataclasses import dataclass

import numpy as np

from .config import GRAVITY


# ---------------------------------------------------------------------------
# 2. METRICS
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Metrics:
    """All values in SI units. Travel values are positive magnitudes at the wheel."""

    max_compression: float           # m, largest bump travel
    max_rebound: float               # m, largest droop travel

    min_ride_height: float           # m, lowest chassis height at this corner

    max_body_acceleration: float     # m/s^2, largest |zs''|
    rms_body_acceleration: float     # m/s^2, over the whole run

    min_normal_force: float         # N
    max_normal_force_loss: float        # fraction of static normal force lost at the worst instant
    rms_normal_force_change: float   # RMS of (contact - static) / static, over the whole run

    air_time: float                  # s, total time with the tire off the ground


def compute_metrics(result):
    """Metrics of one SimulationResult."""

    travel = result.suspension_travel

    sample_time = result.time[1] - result.time[0]

    load_change = (result.normal_force - result.static_normal_force) / result.static_normal_force

    return Metrics(
        max_compression=max(0.0, float(-travel.min())),
        max_rebound=max(0.0, float(travel.max())),

        min_ride_height=float(result.ride_height.min()),

        max_body_acceleration=float(np.abs(result.sprung_acceleration).max()),
        rms_body_acceleration=float(np.sqrt(np.mean(result.sprung_acceleration**2))),

        min_normal_force=float(result.normal_force.min()),
        max_normal_force_loss=float(max(0.0, -load_change.min())),
        rms_normal_force_change=float(np.sqrt(np.mean(load_change**2))),

        air_time=float(np.count_nonzero(result.normal_force <= 0.0) * sample_time),
    )


# ---------------------------------------------------------------------------
# 3. METRICS A SWEEP CAN BE RANKED BY
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RankMetric:
    key: str                    # field of Metrics
    label: str
    short: str                  # table column heading
    unit: str
    scale: float                # display value = SI value * scale
    decimals: int = 1
    lower_is_better: bool = True

    def display(self, metrics):
        return getattr(metrics, self.key) * self.scale

    def format(self, metrics):
        return f"{self.display(metrics):.{self.decimals}f}"

    def sort_key(self, metrics):
        """Smaller = better."""

        value = getattr(metrics, self.key)

        return value if self.lower_is_better else -value


RANK_METRICS = {
    metric.key: metric
    for metric in [
        RankMetric("max_normal_force_loss", "normal force lost", "force lost", "%", 100, 0),
        RankMetric("rms_normal_force_change", "RMS normal force change", "RMS force", "%", 100),
        RankMetric("max_body_acceleration", "peak body accel", "accel", "g", 1 / GRAVITY, 2),
        RankMetric("rms_body_acceleration", "RMS body accel", "RMS accel", "g", 1 / GRAVITY, 3),
        RankMetric("max_compression", "compression travel", "comp", "mm", 1000),
        RankMetric("max_rebound", "rebound travel", "reb", "mm", 1000),
        RankMetric("min_ride_height", "min ride height", "min RH", "mm", 1000,
                   lower_is_better=False),
        RankMetric("air_time", "tire air time", "air", "ms", 1000),
    ]
}

DEFAULT_RANK_METRIC = "max_normal_force_loss"
