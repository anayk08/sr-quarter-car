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
    value: float        # SI
    limit: float        # SI
    is_minimum: bool    # True: value must stay above the limit
    passed: bool
    violation: float    # 0 when passed, else how far past the limit (fraction)


def _check(key, label, value, limit, is_minimum, scale):
    """Build one check. `scale` turns the miss distance into a fraction."""

    if is_minimum:
        miss = limit - value
    else:
        miss = value - limit

    passed = miss <= 1e-12

    return ConstraintCheck(
        key=key,
        label=label,
        value=value,
        limit=limit,
        is_minimum=is_minimum,
        passed=passed,
        violation=0.0 if passed else miss / scale,
    )


# ---------------------------------------------------------------------------
# 3. CHECK A RUN
# ---------------------------------------------------------------------------

def check_constraints(metrics, limits):
    """List of ConstraintCheck for one run."""

    # Avoid dividing by a zero limit when sizing a violation
    def scale(limit, floor):
        return max(abs(limit), floor)

    return [
        _check(
            "ride_height", "min ride height",
            metrics.min_ride_height, limits.min_ride_height,
            is_minimum=True, scale=scale(limits.min_ride_height, 0.001),
        ),
        _check(
            "compression", "compression travel",
            metrics.max_compression, limits.max_compression,
            is_minimum=False, scale=scale(limits.max_compression, 0.001),
        ),
        _check(
            "rebound", "rebound travel",
            metrics.max_rebound, limits.max_rebound,
            is_minimum=False, scale=scale(limits.max_rebound, 0.001),
        ),
        _check(
            "body_acceleration", "body acceleration",
            metrics.max_body_acceleration, limits.max_body_acceleration,
            is_minimum=False, scale=scale(limits.max_body_acceleration, 0.1),
        ),
        _check(
            "contact", "tire air time",
            metrics.air_time, limits.max_air_time,
            is_minimum=False, scale=scale(limits.max_air_time, 0.010),
        ),
    ]


def is_feasible(checks):
    return all(check.passed for check in checks)


def total_violation(checks):
    return sum(check.violation for check in checks)
