"""
FSAE quarter-car suspension design tool.

One wheel corner, 2 DOF: sprung mass (this corner's share of chassis +
driver) on a spring and nonlinear damper, over the unsprung mass on a tire
that can leave the ground, driven by a road profile.

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
    ScoreWeights,
    SimSettings,
    corner_sprung_mass,
)
from .model import linear_modes, simulate
from .sweep import SweepAxis, evaluate_design, run_sweep

__all__ = [
    "CornerParams",
    "DamperSettings",
    "DesignCase",
    "DesignLimits",
    "RoadParams",
    "ScoreWeights",
    "SimSettings",
    "SweepAxis",
    "corner_sprung_mass",
    "evaluate_design",
    "linear_modes",
    "run_sweep",
    "simulate",
]
