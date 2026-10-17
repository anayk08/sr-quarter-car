"""
Design configuration for the FSAE quarter-car tool.

Every number the model uses lives in the dataclasses below. The other modules
only read from these objects, so no physics value is hard-coded anywhere else.
"""

# ---------------------------------------------------------------------------
# CONFIGURATION
#
#   CornerParams   - masses, spring, motion ratio, tire, damper, ride height
#   RoadParams     - road profile, its size, and the vehicle speed
#   DesignLimits   - hard constraints a setup must satisfy
#   ScoreWeights   - how the setups that pass are ranked
#   SimSettings    - solver and output settings
#   DesignCase     - one complete case = all of the above
#
# MODEL INTERPRETATION: ONE WHEEL CORNER, NOT THE WHOLE CAR
#
#   Sprung mass   = share of chassis + driver carried by THIS corner
#                   e.g. (car mass - 4 x unsprung mass) x axle share / 2
#   Unsprung mass = wheel + tire + upright + hub + brake of THIS corner
#
#   The whole-car mass is never put on one wheel. Use corner_sprung_mass()
#   at the bottom of this file to get the corner value from whole-car data.
#
# UNITS
#
#   Inside the model everything is SI (kg, m, s, N).
#   The GUI shows engineering units (lbf/in, mm, km/h, g) and converts.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field, replace


# ---------------------------------------------------------------------------
# 2. CONSTANTS AND UNIT CONVERSIONS
# ---------------------------------------------------------------------------

GRAVITY = 9.81                 # m/s^2

LBF_IN_TO_N_M = 175.126835     # 1 lbf/in = 175.126835 N/m (same as v1)

KPH_TO_M_S = 1 / 3.6           # 1 km/h = 0.2778 m/s


# ---------------------------------------------------------------------------
# 3. DAMPER SETTINGS
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DamperSettings:
    """
    Four-way damper, defined the same way as the v1 spreadsheet values.

    Each slope is a damping ratio = fraction of critical damping, where

        c_critical = 2 * sqrt(wheel_rate * sprung_mass)

    so the damper coefficients follow the spring and mass when those change
    (the damper is "re-valved" to the same ratios).

    Knee velocities are DAMPER SHAFT speeds (what a damper dyno measures).
    The model converts them to wheel speeds with the motion ratio.
    """

    LSC_ratio: float = 0.70           # Low-Speed Compression
    HSC_ratio: float = 0.30           # High-Speed Compression

    LSR_ratio: float = 1.00           # Low-Speed Rebound
    HSR_ratio: float = 0.50           # High-Speed Rebound

    knee_compression: float = 0.0541  # m/s at the damper shaft
    knee_rebound: float = 0.0587      # m/s at the damper shaft


# ---------------------------------------------------------------------------
# 4. CORNER PARAMETERS (ONE WHEEL)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CornerParams:
    """
    Physical parameters of one wheel corner.

    Motion ratio convention (same as v1):
        motion_ratio = spring (damper) travel / wheel travel
        wheel_rate   = spring_rate * motion_ratio^2

    The spring and damper share one motion ratio (coilover).
    """

    # Masses
    sprung_mass: float = 61.22           # kg, this corner's share of chassis + driver
    unsprung_mass: float = 8.4354        # kg, wheel/tire/upright/hub

    # Suspension spring
    spring_rate: float = 629.0 * LBF_IN_TO_N_M     # N/m at the spring
    motion_ratio: float = 0.75                     # spring travel / wheel travel

    # Tire
    tire_spring_rate: float = 493.0 * LBF_IN_TO_N_M    # N/m
    tire_damping_ratio: float = 0.05                    # fraction of tire critical damping

    # Damper
    damper: DamperSettings = field(default_factory=DamperSettings)

    # Ride height and aero
    static_ride_height: float = 0.030    # m, parked (no aero load)
    aero_load: float = 0.0               # N, downforce on this corner at speed

    # -------------------------------------------------------------------
    # Derived quantities
    # -------------------------------------------------------------------

    @property
    def wheel_rate(self):
        # Wheel Rate = Spring Rate * Motion Ratio^2
        return self.spring_rate * self.motion_ratio**2

    @property
    def ride_rate(self):
        # Wheel rate and tire rate act in series
        return (
            self.wheel_rate * self.tire_spring_rate
            / (self.wheel_rate + self.tire_spring_rate)
        )

    @property
    def critical_damping(self):
        # c_critical = 2 * sqrt(k * m)   (single-DOF, wheel rate on sprung mass, as in v1)
        return 2 * (self.wheel_rate * self.sprung_mass) ** 0.5

    @property
    def tire_damping(self):
        # Tire critical damping is based on unsprung mass (as in v1)
        tire_critical_damping = 2 * (self.tire_spring_rate * self.unsprung_mass) ** 0.5
        return self.tire_damping_ratio * tire_critical_damping

    @property
    def static_tire_load(self):
        # Load on the tire when driving on a flat road (weight + downforce)
        return (self.sprung_mass + self.unsprung_mass) * GRAVITY + self.aero_load

    @property
    def aero_sink(self):
        # Ride height lost to downforce: spring and tire both compress
        return self.aero_load / self.ride_rate

    @property
    def ride_height_at_speed(self):
        return self.static_ride_height - self.aero_sink


# ---------------------------------------------------------------------------
# 5. ROAD
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RoadParams:
    """
    Road input under the tire.

    Profiles are defined in space (height and length) and turned into time
    with the vehicle speed:  duration = length / speed.
    See road.py for the shape of each profile.
    """

    profile: str = "bump"         # key in road.ROAD_PROFILES

    height: float = 0.0127        # m, 0.5 in
    length: float = 0.30          # m, length of one feature along the road
    speed: float = 50 * KPH_TO_M_S    # m/s

    start_time: float = 0.10      # s, when the tire reaches the feature

    # Rumble strip only
    pitch: float = 0.30           # m, start-to-start spacing of the strips
    count: int = 8                # number of strips


# ---------------------------------------------------------------------------
# 6. DESIGN LIMITS (HARD CONSTRAINTS)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DesignLimits:
    """A setup passes only if every limit below is met over the whole run."""

    min_ride_height: float = 0.010            # m, lowest allowed chassis height at this corner

    max_compression: float = 0.0254           # m of wheel travel in bump (FSAE minimum is 25.4 mm)
    max_rebound: float = 0.0254               # m of wheel travel in droop

    max_body_acceleration: float = 2.0 * GRAVITY  # m/s^2, peak vertical acceleration of the body

    max_air_time: float = 0.0                 # s, total time the tire may be off the ground


# ---------------------------------------------------------------------------
# 7. SCORE WEIGHTS
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoreWeights:
    """
    Relative importance of each score term (see scoring.py).
    Only the ratios matter. Set a weight to 0 to ignore that term.
    """

    body_acceleration: float = 1.0    # ride / platform control
    tire_load: float = 1.0            # grip: how much tire load is lost
    travel: float = 0.5               # use of the available suspension travel
    ride_height: float = 0.5          # use of the available ground clearance


# ---------------------------------------------------------------------------
# 8. SIMULATION SETTINGS
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SimSettings:
    settle_time: float = 1.0          # s simulated after the road feature ends
    sample_rate: float = 2000.0       # Hz, output samples

    method: str = "RK45"              # scipy solve_ivp method
    rtol: float = 1e-6
    atol: float = 1e-9

    max_step: float = 0.005           # s, largest solver step on flat road
    steps_per_feature: int = 20       # max_step on a feature = feature duration / this


# ---------------------------------------------------------------------------
# 9. DESIGN CASE
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DesignCase:
    """One complete, self-contained case: everything needed for one run."""

    corner: CornerParams = field(default_factory=CornerParams)
    road: RoadParams = field(default_factory=RoadParams)
    limits: DesignLimits = field(default_factory=DesignLimits)
    weights: ScoreWeights = field(default_factory=ScoreWeights)
    sim: SimSettings = field(default_factory=SimSettings)


# ---------------------------------------------------------------------------
# 10. HELPERS
# ---------------------------------------------------------------------------

def get_value(obj, path):
    """Read a nested field, e.g. get_value(case, ("corner", "spring_rate"))."""

    for name in path:
        obj = getattr(obj, name)

    return obj


def with_value(obj, path, value):
    """Return a copy of a (frozen) dataclass with one nested field changed."""

    name = path[0]

    if len(path) == 1:
        return replace(obj, **{name: value})

    child = getattr(obj, name)

    return replace(obj, **{name: with_value(child, path[1:], value)})


def corner_sprung_mass(car_mass, unsprung_mass_per_corner, axle_weight_fraction):
    """
    Sprung mass carried by ONE corner, from whole-car data.

        car_mass                 = full car + driver (kg)
        unsprung_mass_per_corner = kg
        axle_weight_fraction     = share of the weight on this axle (e.g. 0.53 rear)

    sprung corner mass = (car mass - 4 x unsprung) x axle fraction / 2
    """

    total_sprung_mass = car_mass - 4 * unsprung_mass_per_corner

    return total_sprung_mass * axle_weight_fraction / 2
