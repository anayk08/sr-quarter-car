"""
Design configuration for the SR-18 Quarter Car Modeling Tool.

Every number the model uses lives in the dataclasses below. The other modules
only read from these objects, so no physics value is hard-coded anywhere else.
"""

# ---------------------------------------------------------------------------
# CONFIGURATION
#
#   CornerParams   - masses, spring, motion ratio, tire, damper, equilibrium height
#   RoadParams     - preset card or custom road, and the vehicle speed
#   DesignLimits   - hard constraints a setup must satisfy
#   SimSettings    - solver and output settings
#   DesignCase     - one complete case = all of the above
#
# MODEL INTERPRETATION: ONE WHEEL CORNER, NOT THE WHOLE CAR
#
#   Sprung mass   = share of chassis + driver carried by THIS corner
#                   = (car mass - 4 x unsprung mass) x axle weight share / 2
#   Unsprung mass = wheel + tire + upright + hub + brake of THIS corner
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
    tire_radius: float = 0.203                          # m, loaded (sets how far it drops into a hole)

    # Damper
    damper: DamperSettings = field(default_factory=DamperSettings)

    # Ride height and downforce
    default_equilibrium_height: float = 0.030    # m, equilibrium height with no downforce (parked)
    downforce: float = 0.0               # N on this corner at the run speed

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
    def static_normal_force(self):
        # Normal force on the wheel when driving on a flat road (weight + downforce)
        return (self.sprung_mass + self.unsprung_mass) * GRAVITY + self.downforce

    @property
    def downforce_sink(self):
        # Ride height lost to downforce: spring and tire both compress
        return self.downforce / self.ride_rate

    @property
    def equilibrium_height_at_speed(self):
        return self.default_equilibrium_height - self.downforce_sink


# ---------------------------------------------------------------------------
# 5. ROAD
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RoadParams:
    """
    Road under the tire. The car is at x = 0 at t = 0 and drives at `speed`.

    profile = a preset card ("bump", "ditch", "triangle", "rumble strip"):
        its features come from the size values below (see road.py).
        For the ditch, height is the depth and length is the width.
    profile = "custom":
        the features are the ones drawn in the road editor.
    """

    profile: str = "bump"

    speed: float = 50 * KPH_TO_M_S    # m/s

    # Preset size
    height: float = 0.0127        # m, 0.5 in
    length: float = 0.30          # m, along the road
    start_time: float = 0.10      # s, when the tire reaches the feature

    # Rumble strip only
    pitch: float = 0.30           # m, start-to-start spacing of the strips
    count: int = 8                # number of strips

    # Custom road: tuple of road.Feature
    features: tuple = ()


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
# 7. SIMULATION SETTINGS
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SimSettings:
    settle_time: float = 1.0          # s simulated after the last road feature
    sample_rate: float = 2000.0       # Hz, output samples

    method: str = "RK45"              # scipy solve_ivp method
    rtol: float = 1e-6
    atol: float = 1e-9

    max_step: float = 0.005           # s, largest solver step on flat road
    steps_per_feature: int = 20       # max_step on the road features = shortest piece / this


# ---------------------------------------------------------------------------
# 8. DESIGN CASE
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DesignCase:
    """One complete, self-contained case: everything needed for one run."""

    corner: CornerParams = field(default_factory=CornerParams)
    road: RoadParams = field(default_factory=RoadParams)
    limits: DesignLimits = field(default_factory=DesignLimits)
    sim: SimSettings = field(default_factory=SimSettings)


# ---------------------------------------------------------------------------
# 9. HELPERS
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
