"""
Score used to rank setups that pass every constraint.
"""

# ---------------------------------------------------------------------------
# SCORING
#
#   Each term is a "utilisation": how much of a budget the setup uses.
#   0 = none of it, 1 = all of it. Lower total score = better setup.
#
#     body_acceleration   peak body accel / allowed body accel
#     tire_load           largest fraction of static tire load lost
#                         (1 = the wheel is fully unloaded / airborne)
#     travel              larger of compression and rebound, / their limits
#     ride_height         ground clearance used / clearance available
#
#   total = sum(weight * term) / sum(weight)       (weights from ScoreWeights)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# 2. SCORE
# ---------------------------------------------------------------------------

SCORE_TERMS = {
    "body_acceleration": "body accel",
    "tire_load": "tire load loss",
    "travel": "travel used",
    "ride_height": "clearance used",
}


@dataclass(frozen=True)
class Score:
    total: float
    terms: dict


def score_terms(metrics, limits):
    """Utilisation of each budget (dimensionless)."""

    clearance_available = metrics.ride_height_at_speed - limits.min_ride_height
    clearance_used = metrics.ride_height_at_speed - metrics.min_ride_height

    if clearance_available > 0:
        ride_height_term = max(0.0, clearance_used) / clearance_available
    else:
        ride_height_term = 1.0 + max(0.0, clearance_used) / 0.001

    return {
        "body_acceleration": metrics.max_body_acceleration / limits.max_body_acceleration,
        "tire_load": min(metrics.max_tire_load_loss, 1.0),
        "travel": max(
            metrics.max_compression / limits.max_compression,
            metrics.max_rebound / limits.max_rebound,
        ),
        "ride_height": ride_height_term,
    }


def score_design(metrics, limits, weights):
    """Weighted average utilisation. Lower is better."""

    terms = score_terms(metrics, limits)

    weight_of = {
        "body_acceleration": weights.body_acceleration,
        "tire_load": weights.tire_load,
        "travel": weights.travel,
        "ride_height": weights.ride_height,
    }

    weight_sum = sum(weight_of.values())

    if weight_sum <= 0:
        return Score(total=0.0, terms=terms)

    total = sum(weight_of[name] * terms[name] for name in terms) / weight_sum

    return Score(total=total, terms=terms)
