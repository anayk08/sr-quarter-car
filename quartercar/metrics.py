"""
Key performance numbers of one simulation run.
"""

# ---------------------------------------------------------------------------
# METRICS
#
#   Turns the time histories of one run into the numbers a designer
#   compares setups on. Compression and rebound are reported separately
#   (v1 combined them into one "maximum travel").
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

from dataclasses import dataclass

import numpy as np


# ---------------------------------------------------------------------------
# 2. METRICS
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Metrics:
    """All values in SI units. Travel values are positive magnitudes at the wheel."""

    max_compression: float           # m, largest bump travel
    max_rebound: float               # m, largest droop travel

    min_ride_height: float           # m, lowest chassis height at this corner
    ride_height_at_speed: float      # m, starting height (static minus aero sink)

    max_body_acceleration: float     # m/s^2, largest |zs''|
    rms_body_acceleration: float     # m/s^2

    static_tire_load: float          # N
    min_contact_force: float         # N
    max_tire_load_loss: float        # fraction of static load lost at the worst instant
    rms_tire_load_variation: float   # RMS of (contact - static) / static

    air_time: float                  # s, total time with the tire off the ground

    max_damper_speed_compression: float   # m/s at the damper shaft
    max_damper_speed_rebound: float       # m/s at the damper shaft


def compute_metrics(result):
    """Metrics of one SimulationResult."""

    travel = result.suspension_travel

    sample_time = result.time[1] - result.time[0]

    static_load = result.static_tire_load

    load_change = (result.contact_force - static_load) / static_load

    return Metrics(
        max_compression=max(0.0, float(-travel.min())),
        max_rebound=max(0.0, float(travel.max())),

        min_ride_height=float(result.ride_height.min()),
        ride_height_at_speed=float(result.ride_height[0]),

        max_body_acceleration=float(np.abs(result.sprung_acceleration).max()),
        rms_body_acceleration=float(np.sqrt(np.mean(result.sprung_acceleration**2))),

        static_tire_load=static_load,
        min_contact_force=float(result.contact_force.min()),
        max_tire_load_loss=float(max(0.0, -load_change.min())),
        rms_tire_load_variation=float(np.sqrt(np.mean(load_change**2))),

        air_time=float(np.count_nonzero(result.contact_force <= 0.0) * sample_time),

        max_damper_speed_compression=max(0.0, float(-result.damper_velocity.min())),
        max_damper_speed_rebound=max(0.0, float(result.damper_velocity.max())),
    )
