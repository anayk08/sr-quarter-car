"""
Road input profiles: vertical road displacement and velocity under the tire.
"""

# ---------------------------------------------------------------------------
# ROAD INPUT
#
#   Each profile is a shape in SPACE (height, length) that the car drives
#   over at a set speed. Distance along the road is x = speed * time, so
#
#       duration of one feature = length / speed
#       road velocity           = road slope * speed
#
#   Profiles:
#     bump          half-sine bump (default)
#     cone          running over a knocked-down cone: a round obstacle,
#                   modelled as a circular arc (what a rigid wheel rolls over)
#     triangle      straight ramp up, straight ramp down
#     rumble strip  a row of short half-sine strips at a set pitch
#
#   To add a profile: write a subclass of RoadProfile, then add it to
#   ROAD_PROFILES and PROFILE_DEFAULTS at the bottom of this file.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

import math

import numpy as np

from .config import RoadParams


# ---------------------------------------------------------------------------
# 2. BASE CLASS
# ---------------------------------------------------------------------------

class RoadProfile:
    """One road feature that the tire reaches at start_time. Flat road elsewhere."""

    name = "flat"
    summary = "flat road"

    def __init__(self, road):

        self.height = road.height
        self.length = road.length
        self.speed = road.speed
        self.start_time = road.start_time

        self.validate()

        # Time the tire spends on one feature
        self.duration = self.length / self.speed

    def validate(self):
        """Raise ValueError with a readable message if the inputs make no sense."""

        if self.height <= 0:
            raise ValueError("road height must be greater than 0")

        if self.length <= 0:
            raise ValueError("road length must be greater than 0")

        if self.speed <= 0:
            raise ValueError("vehicle speed must be greater than 0")

        if self.start_time < 0:
            raise ValueError("road start time cannot be negative")

    @property
    def end_time(self):
        return self.start_time + self.duration

    @property
    def shortest_piece(self):
        # Shortest smooth piece of the input, used to limit the solver step
        return self.duration

    def breakpoints(self):
        """
        Times where the road input has a corner (road velocity jumps).
        The solver restarts at each one, so it can never step over a feature.
        """

        return [self.start_time, self.end_time]

    def road_input(self, t):
        """Road displacement (m) and road vertical velocity (m/s) at time t."""

        raise NotImplementedError

    def sample(self, times):
        """Road displacement and velocity for an array of times."""

        values = np.array([self.road_input(t) for t in np.asarray(times, dtype=float)])

        return values[:, 0], values[:, 1]

    def peak_velocity(self, points=400):
        """Largest vertical road velocity over the feature (m/s)."""

        times = np.linspace(self.start_time, self.end_time, points)
        _, road_velocity = self.sample(times)

        return float(np.max(np.abs(road_velocity)))

    def describe(self):
        return (
            f"{self.name}: {self.height * 1000:.1f} mm x {self.length:.2f} m "
            f"at {self.speed * 3.6:.0f} km/h ({self.duration * 1000:.1f} ms)"
        )


# ---------------------------------------------------------------------------
# 3. HALF-SINE BUMP (DEFAULT)
# ---------------------------------------------------------------------------

class HalfSineBump(RoadProfile):
    """
    zr = h * sin(pi * tau / T)    for 0 <= tau <= T,   tau = t - start_time

    Smooth over the top. The road velocity steps from 0 to h*pi/T at the
    entry and exit edges (a real bump has an edge too).
    """

    name = "bump"
    summary = "half-sine bump"

    def road_input(self, t):

        if self.start_time <= t <= self.end_time:

            bump_time = t - self.start_time

            zr = self.height * math.sin(math.pi * bump_time / self.duration)

            road_velocity = (
                self.height
                * math.pi
                / self.duration
                * math.cos(math.pi * bump_time / self.duration)
            )

            return zr, road_velocity

        return 0.0, 0.0


# ---------------------------------------------------------------------------
# 4. CONE STRIKE (ROUND OBSTACLE)
# ---------------------------------------------------------------------------

class ConeObstacle(RoadProfile):
    """
    Running over a knocked-down traffic cone lying across the wheel path.

    A rigid wheel rolling over a round object follows a circular arc, so the
    input is the arc through (0, 0), (L/2, h) and (L, 0):

        arc radius  R = L^2 / (8 h) + h / 2
        zr(x)       = sqrt(R^2 - (x - L/2)^2) - (R - h)

    Steep entry and exit, rounded top. Needs h < L / 2.
    """

    name = "cone"
    summary = "knocked-down cone (round obstacle)"

    def __init__(self, road):

        super().__init__(road)

        self.arc_radius = self.length**2 / (8 * self.height) + self.height / 2

    def validate(self):

        super().validate()

        if self.height >= self.length / 2:
            raise ValueError("cone height must be less than half of its length")

    def road_input(self, t):

        if self.start_time <= t <= self.end_time:

            distance = self.speed * (t - self.start_time)

            # Horizontal distance from the top of the arc
            offset = distance - self.length / 2

            root = math.sqrt(self.arc_radius**2 - offset**2)

            zr = root - (self.arc_radius - self.height)

            road_slope = -offset / root

            return zr, road_slope * self.speed

        return 0.0, 0.0


# ---------------------------------------------------------------------------
# 5. TRIANGLE BUMP
# ---------------------------------------------------------------------------

class TriangleBump(RoadProfile):
    """
    Straight ramp up to h at mid-length, straight ramp back down.
    Constant road velocity of +-2h/T on each ramp (a clean damper test).
    """

    name = "triangle"
    summary = "triangular ramp"

    @property
    def shortest_piece(self):
        return self.duration / 2

    def breakpoints(self):
        return [self.start_time, self.start_time + self.duration / 2, self.end_time]

    def road_input(self, t):

        if self.start_time <= t <= self.end_time:

            ramp_velocity = 2 * self.height / self.duration

            time_on_ramp = t - self.start_time

            # Ramp up
            if time_on_ramp <= self.duration / 2:
                return ramp_velocity * time_on_ramp, ramp_velocity

            # Ramp down
            return ramp_velocity * (self.duration - time_on_ramp), -ramp_velocity

        return 0.0, 0.0


# ---------------------------------------------------------------------------
# 6. RUMBLE STRIP
# ---------------------------------------------------------------------------

class RumbleStrip(RoadProfile):
    """
    A row of `count` half-sine strips, each `length` long, starting every
    `pitch` metres. Excitation frequency = speed / pitch.
    """

    name = "rumble strip"
    summary = "row of short strips"

    def __init__(self, road):

        self.pitch = road.pitch
        self.count = int(road.count)

        super().__init__(road)

        # Time from the start of one strip to the start of the next
        self.period = self.pitch / self.speed

    def validate(self):

        super().validate()

        if self.count < 1:
            raise ValueError("rumble strip needs at least 1 strip")

        if self.pitch <= 0:
            raise ValueError("rumble strip pitch must be greater than 0")

        if self.length > self.pitch:
            raise ValueError("rumble strip length cannot be longer than its pitch")

    @property
    def end_time(self):
        return self.start_time + (self.count - 1) * self.period + self.duration

    def breakpoints(self):

        times = []

        for strip in range(self.count):

            strip_start = self.start_time + strip * self.period

            times += [strip_start, strip_start + self.duration]

        return times

    def road_input(self, t):

        elapsed = t - self.start_time

        if elapsed < 0:
            return 0.0, 0.0

        # Which strip the tire is on (or has just left)
        strip = min(int(elapsed // self.period), self.count - 1)

        strip_time = elapsed - strip * self.period

        if strip_time > self.duration:
            return 0.0, 0.0

        zr = self.height * math.sin(math.pi * strip_time / self.duration)

        road_velocity = (
            self.height
            * math.pi
            / self.duration
            * math.cos(math.pi * strip_time / self.duration)
        )

        return zr, road_velocity

    def describe(self):
        return (
            f"{self.name}: {self.count} x {self.height * 1000:.1f} mm strips, "
            f"{self.length:.2f} m long every {self.pitch:.2f} m "
            f"at {self.speed * 3.6:.0f} km/h ({self.speed / self.pitch:.1f} Hz)"
        )


# ---------------------------------------------------------------------------
# 7. REGISTRY
# ---------------------------------------------------------------------------

# Order here = order of the profile cards in the GUI
ROAD_PROFILES = {
    "bump": HalfSineBump,
    "cone": ConeObstacle,
    "triangle": TriangleBump,
    "rumble strip": RumbleStrip,
}


# Shape values loaded when a profile is first selected (SI units)
PROFILE_DEFAULTS = {
    "bump": dict(height=0.0127, length=0.30),
    "cone": dict(height=0.050, length=0.30),
    "triangle": dict(height=0.020, length=0.50),
    "rumble strip": dict(height=0.010, length=0.15, pitch=0.30, count=8),
}


def make_road(road):
    """Build the road profile object for a RoadParams."""

    if road.profile not in ROAD_PROFILES:
        raise ValueError(f"unknown road profile '{road.profile}'")

    return ROAD_PROFILES[road.profile](road)


# Card sketches: a short row of rumble strips, and a rounder, narrower cone
# so that it does not look like the bump. Lead = flat road on each side.
ICON_SHAPES = {
    "cone": dict(height=0.042, length=0.10),
    "rumble strip": dict(count=4),
}
ICON_LEAD = {"cone": 0.6}


def profile_icon(profile, points=120):
    """Normalised outline (x and z both 0..1) of a profile, for the GUI cards."""

    shape = {**PROFILE_DEFAULTS[profile], **ICON_SHAPES.get(profile, {})}

    road = make_road(RoadParams(profile=profile, speed=1.0, start_time=0.0, **shape))

    # A little flat road before and after the feature
    lead = ICON_LEAD.get(profile, 0.15) * road.end_time
    times = np.linspace(-lead, road.end_time + lead, points)

    zr, _ = road.sample(times)

    x = (times - times[0]) / (times[-1] - times[0])

    return x, zr / road.height
