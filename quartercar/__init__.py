"""
FSAE quarter-car suspension design tool.

One wheel corner, 2 DOF: sprung mass (this corner's share of chassis +
driver) on a spring and nonlinear damper, over the unsprung mass on a tire
that can leave the ground, driven by a road made of bumps, dips and holes.

    from quartercar import DesignCase, evaluate_design
    evaluation = evaluate_design(DesignCase())

Run the app with:  python run_app.py
"""

from .config import (
    CornerParams,
    DamperSettings,
    DesignCase,
    DesignLimits,
    RoadParams,
    SimSettings,
)
from .model import linear_modes, simulate
from .road import Feature
from .sweep import SweepAxis, evaluate_design, run_sweep

__all__ = [
    "CornerParams",
    "DamperSettings",
    "DesignCase",
    "DesignLimits",
    "Feature",
    "RoadParams",
    "SimSettings",
    "SweepAxis",
    "evaluate_design",
    "linear_modes",
    "run_sweep",
    "simulate",
]
