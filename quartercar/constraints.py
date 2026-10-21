"""
Hard design constraints: does a setup pass or fail?
"""

# ---------------------------------------------------------------------------
# CONSTRAINTS
#
#   Every check compares one metric with one limit from DesignLimits:
#
#     ride height    lowest chassis height      >= min_ride_height
#     compression    bump travel at the wheel   <= max_compression
#     rebound        droop travel at the wheel  <= max_rebound
#     body accel     peak |body acceleration|   <= max_body_acceleration
#     contact        time with tire in the air  <= max_air_time
#
#   A setup is feasible only if every check passes. Failed setups are
#   ranked by how far they miss (violation, as a fraction of the limit).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# 2. CONSTRAINT CHECK
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConstraintCheck:
    key: str
    label: str
    passed: bool
    violation: float    # 0 when passed, else how far past the limit (fraction)


def _check(key, label, miss, scale):
    """One check. `miss` > 0 means past the limit; `scale` turns it into a fraction."""

    passed = miss <= 1e-12

    return ConstraintCheck(key, label, passed, 0.0 if passed else miss / scale)


# ---------------------------------------------------------------------------
# 3. CHECK A RUN
# ---------------------------------------------------------------------------

def check_constraints(metrics, limits):
    """List of ConstraintCheck for one run."""

    # A floor on each scale avoids dividing by a zero limit
    return [
        _check(
            "ride_height", "min ride height",
            limits.min_ride_height - metrics.min_ride_height,
            max(limits.min_ride_height, 0.001),
        ),
        _check(
            "compression", "compression travel",
            metrics.max_compression - limits.max_compression,
            max(limits.max_compression, 0.001),
        ),
        _check(
            "rebound", "rebound travel",
            metrics.max_rebound - limits.max_rebound,
            max(limits.max_rebound, 0.001),
        ),
        _check(
            "body_acceleration", "body acceleration",
            metrics.max_body_acceleration - limits.max_body_acceleration,
            max(limits.max_body_acceleration, 0.1),
        ),
        _check(
            "contact", "tire air time",
            metrics.air_time - limits.max_air_time,
            max(limits.max_air_time, 0.010),
        ),
    ]


def is_feasible(checks):
    return all(check.passed for check in checks)


def total_violation(checks):
    return sum(check.violation for check in checks)
