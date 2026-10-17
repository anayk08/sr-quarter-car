"""
Quarter-car model (2 DOF, one wheel corner) and its time simulation.
"""

# ---------------------------------------------------------------------------
# QUARTER-CAR MODEL
#
#   2 DOF:
#     Sprung mass   = this corner's share of chassis + driver
#     Unsprung mass = wheel / tire / upright / hub
#
#            zs ^  +-----------------+
#               |  |   sprung mass   |
#                  +-----------------+
#                     |           |
#        wheel rate   /          [=]  nonlinear damper
#                     \           |
#            zu ^  +-----------------+
#               |  |  unsprung mass  |
#                  +-----------------+
#                     |           |
#         tire rate   /          [=]  tire damping
#                     \           |
#            zr ^  ~~~~~~~~~~~~~~~~~~~  road
#
#   States (same order as v1):   y = [zs, vs, zu, vu]
#
#   Sign conventions (same as v1):
#     z positive up, displacements measured from static equilibrium
#     suspension travel = zs - zu    (+ = rebound / extension, - = compression)
#     damper velocity   = vs - vu    (+ = rebound)
#
#   Equations of motion:
#     ms * zs'' = - spring_force - damping_force
#     mu * zu'' =   spring_force + damping_force - tire_force
#
#     spring_force  = wheel_rate * (zs - zu)
#     damping_force = damper(vs - vu)                     (damper.py)
#     tire_force    = static_tire_load - contact_force    (change in tire load)
#     contact_force = kt * compression + ct * compression rate,
#                     never below 0, and 0 when the tire is off the ground
#
#   Gravity and aero load are carried by the static spring and tire preload,
#   so they cancel out of the equations (checked in v1 verification, check 3).
#   They only appear in static_tire_load, which decides when the tire lifts.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_ivp

from .damper import build_damper, wheel_to_shaft
from .road import make_road


# ---------------------------------------------------------------------------
# 2. TIRE
# ---------------------------------------------------------------------------

def tire_contact_force(tire_compression, compression_rate, tire_spring_rate, tire_damping):
    """
    Point-contact tire: vertical force from the road on the wheel (N, + = up).

    The tire can push but never pull:
      off the ground (no compression) -> 0
      on the ground                   -> kt * compression + ct * rate, floored at 0

    Swap this function for a better tire model later (e.g. an enveloping tire).
    """

    if tire_compression <= 0.0:
        return 0.0

    force = tire_spring_rate * tire_compression + tire_damping * compression_rate

    return max(force, 0.0)


# ---------------------------------------------------------------------------
# 3. EQUATIONS OF MOTION
# ---------------------------------------------------------------------------

class QuarterCarModel:
    """Equations of motion for one wheel corner, built from a DesignCase."""

    def __init__(self, case):

        corner = case.corner

        # Masses
        self.sprung_mass = corner.sprung_mass
        self.unsprung_mass = corner.unsprung_mass

        # Suspension spring and damper (both at the wheel)
        self.motion_ratio = corner.motion_ratio
        self.wheel_rate = corner.wheel_rate
        self.damper = build_damper(corner)

        # Tire
        self.tire_spring_rate = corner.tire_spring_rate
        self.tire_damping = corner.tire_damping
        self.static_tire_load = corner.static_tire_load

        # Tire compression at static equilibrium
        self.static_tire_deflection = self.static_tire_load / self.tire_spring_rate

        # Road
        self.road = make_road(case.road)

    def forces(self, t, zs, vs, zu, vu, road_time=None):
        """
        Every force at one instant.

        road_time lets the solver read the road just inside the current
        integration segment (see simulate). It defaults to t.
        """

        # Road
        zr, vr = self.road.road_input(t if road_time is None else road_time)

        # --------------------------------------------------
        # Suspension spring
        # --------------------------------------------------

        suspension_deflection = zs - zu

        spring_force = self.wheel_rate * suspension_deflection

        # --------------------------------------------------
        # Suspension damper
        # --------------------------------------------------

        damper_velocity = vs - vu

        damping_force = self.damper.force(damper_velocity)

        # --------------------------------------------------
        # Tire (can lift off)
        # --------------------------------------------------

        tire_compression = self.static_tire_deflection - (zu - zr)

        compression_rate = vr - vu

        contact_force = tire_contact_force(
            tire_compression,
            compression_rate,
            self.tire_spring_rate,
            self.tire_damping,
        )

        # Change in tire load from static (same meaning as v1's tire_force)
        tire_force = self.static_tire_load - contact_force

        return zr, vr, spring_force, damping_force, contact_force, tire_force

    def quarter_car(self, t, y, road_time=None):
        """State derivatives [vs, as, vu, au] for solve_ivp."""

        zs, vs, zu, vu = y

        _, _, spring_force, damping_force, _, tire_force = self.forces(
            t, zs, vs, zu, vu, road_time
        )

        # Sprung mass acceleration
        sprung_acceleration = (
            -spring_force
            - damping_force
        ) / self.sprung_mass

        # Unsprung mass acceleration
        unsprung_acceleration = (
            spring_force
            + damping_force
            - tire_force
        ) / self.unsprung_mass

        return [vs, sprung_acceleration, vu, unsprung_acceleration]


# ---------------------------------------------------------------------------
# 4. SIMULATION RESULT
# ---------------------------------------------------------------------------

@dataclass
class SimulationResult:
    """Time histories of one run. Displacements in m, forces in N."""

    case: object

    time: np.ndarray

    road_displacement: np.ndarray
    road_velocity: np.ndarray

    sprung_displacement: np.ndarray
    sprung_velocity: np.ndarray
    sprung_acceleration: np.ndarray

    unsprung_displacement: np.ndarray
    unsprung_velocity: np.ndarray

    suspension_travel: np.ndarray       # zs - zu, + = rebound
    spring_force: np.ndarray            # at the wheel
    damping_force: np.ndarray           # at the wheel
    contact_force: np.ndarray           # tire-road force, 0 = airborne

    ride_height: np.ndarray             # chassis height above flat ground at this corner

    damper_velocity: np.ndarray         # at the damper shaft, + = rebound
    damper_force: np.ndarray            # at the damper shaft

    static_tire_load: float
    event_start: float
    event_end: float
    solver_evaluations: int


# ---------------------------------------------------------------------------
# 5. SIMULATION
# ---------------------------------------------------------------------------

def segment_edges(breakpoints, end_time, min_gap=1e-9):
    """Sorted segment edges from 0 to end_time, merging edges closer than min_gap."""

    edges = [0.0]

    for time in sorted(breakpoints) + [end_time]:

        if min_gap < time <= end_time and time - edges[-1] > min_gap:
            edges.append(time)

    if end_time - edges[-1] > 0:
        edges[-1] = end_time

    return edges


def simulate(case):
    """
    Run one quarter-car simulation with scipy solve_ivp.

    The run is split at every corner of the road input (road.breakpoints).
    Each piece is integrated on its own, so the solver can never step over a
    bump, and on the road feature the step is limited to

        max_step = shortest piece / steps_per_feature

    (the v1 verification found the solver could skip the bump entirely).
    """

    model = QuarterCarModel(case)
    road = model.road
    sim = case.sim

    end_time = road.end_time + sim.settle_time

    # Output times
    sample_count = int(round(end_time * sim.sample_rate)) + 1

    TIME = np.linspace(0.0, end_time, sample_count)

    # Initial conditions: model is referenced about static equilibrium,
    # so all initial values are zero (as in v1)
    state = np.zeros(4)
    states = np.zeros((4, sample_count))

    feature_step = min(sim.max_step, road.shortest_piece / sim.steps_per_feature)

    evaluations = 0

    edges = segment_edges(road.breakpoints(), end_time)

    for segment_start, segment_end in zip(edges[:-1], edges[1:]):

        on_feature = road.start_time <= segment_start < road.end_time

        # Read the road just inside this segment, so each segment sees one
        # smooth piece of road (no velocity jump exactly at its ends)
        nudge = 1e-9 * (segment_end - segment_start)
        road_first = segment_start + nudge
        road_last = segment_end - nudge

        def equations(t, y):
            road_time = min(max(t, road_first), road_last)
            return model.quarter_car(t, y, road_time)

        solution = solve_ivp(
            equations,
            [segment_start, segment_end],
            state,
            method=sim.method,
            rtol=sim.rtol,
            atol=sim.atol,
            max_step=feature_step if on_feature else sim.max_step,
            dense_output=True,
        )

        if not solution.success:
            raise RuntimeError(f"solver failed at t = {segment_start:.4f} s: {solution.message}")

        evaluations += solution.nfev

        in_segment = (TIME >= segment_start) & (TIME <= segment_end)
        states[:, in_segment] = solution.sol(TIME[in_segment])

        state = solution.y[:, -1]

    return build_result(case, model, TIME, states, evaluations)


def build_result(case, model, TIME, states, evaluations):
    """Recompute every force at the output times and pack the time histories."""

    sprung_displacement, sprung_velocity, unsprung_displacement, unsprung_velocity = states

    sample_count = len(TIME)

    road_displacement = np.zeros(sample_count)
    road_velocity = np.zeros(sample_count)
    spring_force = np.zeros(sample_count)
    damping_force = np.zeros(sample_count)
    contact_force = np.zeros(sample_count)

    for i in range(sample_count):

        (
            road_displacement[i],
            road_velocity[i],
            spring_force[i],
            damping_force[i],
            contact_force[i],
            _,
        ) = model.forces(
            TIME[i],
            sprung_displacement[i],
            sprung_velocity[i],
            unsprung_displacement[i],
            unsprung_velocity[i],
        )

    # Suspension travel (+ = rebound, as in v1)
    suspension_travel = sprung_displacement - unsprung_displacement

    # Body acceleration from the same forces the solver used
    sprung_acceleration = (-spring_force - damping_force) / model.sprung_mass

    # Chassis height at this corner (flat ground under the chassis)
    ride_height = case.corner.ride_height_at_speed + sprung_displacement

    # Damper shaft (dyno) view
    damper_velocity, damper_force = wheel_to_shaft(
        model.motion_ratio,
        sprung_velocity - unsprung_velocity,
        damping_force,
    )

    return SimulationResult(
        case=case,
        time=TIME,
        road_displacement=road_displacement,
        road_velocity=road_velocity,
        sprung_displacement=sprung_displacement,
        sprung_velocity=sprung_velocity,
        sprung_acceleration=sprung_acceleration,
        unsprung_displacement=unsprung_displacement,
        unsprung_velocity=unsprung_velocity,
        suspension_travel=suspension_travel,
        spring_force=spring_force,
        damping_force=damping_force,
        contact_force=contact_force,
        ride_height=ride_height,
        damper_velocity=damper_velocity,
        damper_force=damper_force,
        static_tire_load=model.static_tire_load,
        event_start=model.road.start_time,
        event_end=model.road.end_time,
        solver_evaluations=evaluations,
    )


# ---------------------------------------------------------------------------
# 6. LINEAR MODES (DESIGN ESTIMATES)
# ---------------------------------------------------------------------------

def linear_modes(corner):
    """
    Natural frequencies and modal damping of the linearised 2-DOF model.

    Uses the average low-speed damper slope (compression and rebound) and
    the tire damping. Damping ratios are None for a mode that is overdamped.

    Note: the body-mode damping of the 2-DOF model is lower than the
    single-DOF damping ratios used to set the damper (v1 verification note).
    """

    sprung_mass = corner.sprung_mass
    unsprung_mass = corner.unsprung_mass

    wheel_rate = corner.wheel_rate
    tire_rate = corner.tire_spring_rate

    damping = build_damper(corner).low_speed_average
    tire_damping = corner.tire_damping

    M = np.diag([sprung_mass, unsprung_mass])
    K = np.array([[wheel_rate, -wheel_rate], [-wheel_rate, wheel_rate + tire_rate]])
    C = np.array([[damping, -damping], [-damping, damping + tire_damping]])

    # Undamped natural frequencies
    omega_squared = np.sort(np.linalg.eigvals(np.linalg.solve(M, K)).real)
    body_omega, hop_omega = np.sqrt(omega_squared)

    # Damped modes from the state matrix
    A = np.block([
        [np.zeros((2, 2)), np.eye(2)],
        [-np.linalg.solve(M, K), -np.linalg.solve(M, C)],
    ])

    oscillating = sorted(
        (root for root in np.linalg.eigvals(A) if root.imag > 1e-9),
        key=abs,
    )

    body_damping = hop_damping = None

    for root in oscillating:

        ratio = -root.real / abs(root)

        # Assign the mode to the closer undamped frequency
        if abs(abs(root) - body_omega) < abs(abs(root) - hop_omega):
            body_damping = ratio
        else:
            hop_damping = ratio

    return dict(
        body_frequency=body_omega / (2 * np.pi),
        wheel_hop_frequency=hop_omega / (2 * np.pi),
        body_damping_ratio=body_damping,
        wheel_hop_damping_ratio=hop_damping,
    )
