"""
Design evaluation and parameter sweep engine.
"""

# ---------------------------------------------------------------------------
# SWEEP ENGINE
#
#   evaluate_design(case)
#       simulate -> metrics -> constraint checks -> score
#
#   run_sweep(base_case, axes)
#       Every combination of the axis values (full grid). Anything not swept
#       keeps its value from base_case. Each point is evaluated on its own;
#       big sweeps are spread over several processes (one per CPU core).
#
#   SweepResult.ranked()
#       Feasible setups first, best (lowest) score first, then the setups
#       that fail, smallest violation first.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

import itertools
import math
import os
import time as clock
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .constraints import check_constraints, is_feasible, total_violation
from .metrics import compute_metrics
from .model import simulate
from .parameters import SWEEP_VARIABLES
from .scoring import score_design


# ---------------------------------------------------------------------------
# 2. EVALUATE ONE DESIGN
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Evaluation:
    case: object
    metrics: object
    checks: list
    feasible: bool
    violation: float
    score: object
    result: Optional[object] = None     # time histories (dropped in sweeps)


def evaluate_design(case, keep_history=True):
    """Simulate one case and judge it against the limits."""

    result = simulate(case)

    metrics = compute_metrics(result)

    checks = check_constraints(metrics, case.limits)

    return Evaluation(
        case=case,
        metrics=metrics,
        checks=checks,
        feasible=is_feasible(checks),
        violation=total_violation(checks),
        score=score_design(metrics, case.limits, case.weights),
        result=result if keep_history else None,
    )


# ---------------------------------------------------------------------------
# 3. SWEEP AXES
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SweepAxis:
    """One swept variable. start / stop / step are SI values (stop included)."""

    key: str
    start: float
    stop: float
    step: float

    @property
    def spec(self):
        return SWEEP_VARIABLES[self.key]

    def values(self):

        if math.isclose(self.start, self.stop):
            return np.array([self.start])

        if self.step <= 0:
            raise ValueError(f"{self.spec.label}: step must be greater than 0")

        if self.stop < self.start:
            raise ValueError(f"{self.spec.label}: stop must be larger than start")

        count = int(math.floor((self.stop - self.start) / self.step + 1e-9)) + 1

        values = self.start + self.step * np.arange(count)

        if self.spec.integer:
            values = np.unique(np.round(values))

        return values


def sweep_size(axes):
    return int(np.prod([len(axis.values()) for axis in axes])) if axes else 0


def apply_point(case, axes, values):
    """Set the swept values on a case. The damping scale goes last (it multiplies)."""

    pairs = sorted(zip(axes, values), key=lambda pair: pair[0].key == "damping_scale")

    for axis, value in pairs:
        case = axis.spec.set(case, float(value))

    return case


# ---------------------------------------------------------------------------
# 4. SWEEP RESULT
# ---------------------------------------------------------------------------

@dataclass
class SweepPoint:
    index: tuple                       # position in the grid
    values: tuple                      # swept values (SI), same order as the axes
    evaluation: Optional[Evaluation]   # None if the point could not be run
    error: str = ""

    @property
    def feasible(self):
        return self.evaluation is not None and self.evaluation.feasible


@dataclass
class SweepResult:
    axes: list
    grids: list
    points: list = field(default_factory=list)
    cancelled: bool = False
    elapsed: float = 0.0

    @property
    def feasible_count(self):
        return sum(point.feasible for point in self.points)

    def ranked(self):
        """Feasible by score, then failing by violation. Points that errored are left out."""

        valid = [point for point in self.points if point.evaluation is not None]

        feasible = sorted(
            (point for point in valid if point.feasible),
            key=lambda point: point.evaluation.score.total,
        )

        failing = sorted(
            (point for point in valid if not point.feasible),
            key=lambda point: (point.evaluation.violation, point.evaluation.score.total),
        )

        return feasible + failing

    def best(self):
        ranked = self.ranked()
        return ranked[0] if ranked else None

    def score_map(self, x_axis, y_axis=None):
        """
        Best feasible score for each (x, y) cell, taken over every other swept
        axis. NaN where no setup in that cell passes the limits.
        Shape: (len(y values), len(x values)), or (len(x values),) without y.
        """

        shape = (
            (len(self.grids[y_axis]), len(self.grids[x_axis]))
            if y_axis is not None else (len(self.grids[x_axis]),)
        )

        best = np.full(shape, np.nan)

        for point in self.points:

            if not point.feasible:
                continue

            cell = (
                (point.index[y_axis], point.index[x_axis])
                if y_axis is not None else (point.index[x_axis],)
            )

            score = point.evaluation.score.total

            if np.isnan(best[cell]) or score < best[cell]:
                best[cell] = score

        return best


# ---------------------------------------------------------------------------
# 5. RUN A SWEEP
# ---------------------------------------------------------------------------

# Below this many points, starting worker processes costs more than it saves
PARALLEL_MIN_POINTS = 24


def default_workers():
    """Worker processes for big sweeps: all cores but one, at most 8."""

    return max(1, min((os.cpu_count() or 1) - 1, 8))


def _evaluate_point(case):
    """Evaluate one sweep point. Runs in a worker process for big sweeps."""

    try:
        return evaluate_design(case, keep_history=False), ""

    except (ValueError, RuntimeError) as error:
        return None, str(error)


def _finished_points(cases, workers, should_stop):
    """Yield (position, (evaluation, error)) as each point finishes."""

    # Small sweep: one after the other in this process
    if workers <= 1 or len(cases) < PARALLEL_MIN_POINTS:

        for position, case in enumerate(cases):

            if should_stop():
                return

            yield position, _evaluate_point(case)

        return

    # Big sweep: spread the points over worker processes
    with ProcessPoolExecutor(max_workers=workers) as pool:

        futures = {
            pool.submit(_evaluate_point, case): position
            for position, case in enumerate(cases)
        }

        for future in as_completed(futures):

            yield futures[future], future.result()

            if should_stop():
                pool.shutdown(wait=False, cancel_futures=True)
                return


def run_sweep(base_case, axes, on_progress=None, should_stop=None, workers=None):
    """
    Evaluate every combination of the axis values.

        on_progress(done, total)   called after each point
        should_stop()              return True to cancel (finished points are kept)
        workers                    processes to use (default: default_workers())
    """

    keys = [axis.key for axis in axes]

    if len(set(keys)) != len(keys):
        raise ValueError("each variable can only be swept once")

    grids = [axis.values() for axis in axes]

    index_ranges = [range(len(grid)) for grid in grids]

    indices = list(itertools.product(*index_ranges)) if grids else []

    values = [tuple(grid[i] for grid, i in zip(grids, index)) for index in indices]

    cases = [apply_point(base_case, axes, point_values) for point_values in values]

    started = clock.perf_counter()

    outcomes = [None] * len(cases)

    finished = _finished_points(
        cases,
        default_workers() if workers is None else workers,
        should_stop or (lambda: False),
    )

    for done, (position, outcome) in enumerate(finished, start=1):

        outcomes[position] = outcome

        if on_progress is not None:
            on_progress(done, len(cases))

    result = SweepResult(axes=list(axes), grids=grids)

    for index, point_values, outcome in zip(indices, values, outcomes):

        if outcome is None:
            result.cancelled = True
            continue

        evaluation, error = outcome
        result.points.append(SweepPoint(index, point_values, evaluation, error))

    result.elapsed = clock.perf_counter() - started

    return result
