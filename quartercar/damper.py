"""
Nonlinear (piecewise-linear) four-way suspension damper.
"""

# ---------------------------------------------------------------------------
# NONLINEAR DAMPER
#
#   Force-velocity curve with a low-speed and a high-speed slope in both
#   rebound and compression:
#
#                 force
#                   |              ___--- HSR (high-speed rebound)
#                   |        __---
#                   |      / LSR (low-speed rebound)
#                   |    /
#   ----------------+------------------ velocity  (vs - vu, + = rebound)
#               /   |
#    LSC      /     |
#   ___---- HSC     |
#
#   The two slopes meet at the knee velocity, so the curve is continuous.
#   The force is zero at rest and always opposes the motion.
#
# Sign convention (same as v1):
#   relative_velocity = vs - vu     + = rebound (extension)
#   force             > 0 in rebound, < 0 in compression
#
# All values in this file are AT THE WHEEL (the model works at the wheel).
# build_damper() converts the user's damping ratios and shaft knee speeds.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

from dataclasses import dataclass

import numpy as np


# ---------------------------------------------------------------------------
# 2. DAMPER CURVE
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PiecewiseDamper:
    """Damper coefficients (N*s/m) and knee velocities (m/s), all at the wheel."""

    c_LSC: float
    c_HSC: float

    c_LSR: float
    c_HSR: float

    knee_compression: float
    knee_rebound: float

    def force(self, relative_velocity):
        """Damper force at the wheel (N) for wheel-relative velocity vs - vu (m/s)."""

        # --------------------------------------------------
        # REBOUND
        # --------------------------------------------------

        if relative_velocity >= 0:

            velocity = relative_velocity

            # Low-speed rebound
            if velocity <= self.knee_rebound:

                return self.c_LSR * velocity

            # High-speed rebound
            force_at_knee = self.c_LSR * self.knee_rebound

            return force_at_knee + self.c_HSR * (velocity - self.knee_rebound)

        # --------------------------------------------------
        # COMPRESSION
        # --------------------------------------------------

        # Use positive magnitude while calculating force
        velocity = -relative_velocity

        # Low-speed compression
        if velocity <= self.knee_compression:

            force = self.c_LSC * velocity

        # High-speed compression
        else:

            force_at_knee = self.c_LSC * self.knee_compression

            force = force_at_knee + self.c_HSC * (velocity - self.knee_compression)

        # Compression force acts in the opposite direction
        return -force

    def curve(self, velocities):
        """Force for an array of velocities (for plots)."""

        return np.array([self.force(v) for v in np.asarray(velocities, dtype=float)])

    @property
    def low_speed_average(self):
        # Average of compression and rebound low-speed slopes (used for linear estimates)
        return 0.5 * (self.c_LSC + self.c_LSR)


# ---------------------------------------------------------------------------
# 3. BUILD THE DAMPER FROM THE DESIGN INPUTS
# ---------------------------------------------------------------------------

def build_damper(corner):
    """
    Turn the corner's damping ratios into a wheel-level damper curve.

        c = ratio * c_critical,   c_critical = 2 * sqrt(wheel_rate * sprung_mass)

    Knee speeds are given at the damper shaft. Shaft velocity = MR * wheel
    velocity, so the knee seen at the wheel is the shaft knee / MR.
    """

    settings = corner.damper
    critical_damping = corner.critical_damping

    return PiecewiseDamper(
        c_LSC=settings.LSC_ratio * critical_damping,
        c_HSC=settings.HSC_ratio * critical_damping,
        c_LSR=settings.LSR_ratio * critical_damping,
        c_HSR=settings.HSR_ratio * critical_damping,
        knee_compression=settings.knee_compression / corner.motion_ratio,
        knee_rebound=settings.knee_rebound / corner.motion_ratio,
    )


def wheel_to_shaft(motion_ratio, wheel_velocity, wheel_force):
    """
    Convert wheel-level velocity and force to the damper shaft (dyno view).

        shaft velocity = MR * wheel velocity
        shaft force    = wheel force / MR      (same power at both ends)
    """

    return motion_ratio * wheel_velocity, wheel_force / motion_ratio
