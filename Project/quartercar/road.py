"""
Road input: vertical road displacement and velocity under the tire.
"""

# ---------------------------------------------------------------------------
# ROAD INPUT
#
#   A road is a list of features placed along it. Each feature has a shape,
#   a start position, a length and a height (negative height = a dip):
#
#     bump      half-sine:  z = h * sin(pi * u / L),   u = distance into it
#     triangle  straight ramp up to h at mid-length, straight ramp down
#     hole      a sharp-edged hole of depth -h. A point-contact tire would
#               drop straight to the bottom, so the input is the path of a
#               rigid wheel (the tire radius) rolling over it: down over the
#               near edge, along the bottom if it reaches it, then up over
#               the far edge (the hard hit)
#
#   Overlapping features add up. The car is at x = 0 at t = 0 and drives at
#   a constant speed, so x = speed * t and road velocity = slope * speed.
#
#   The preset cards build their features from a few size values:
#     bump      one bump                 ditch          one hole
#     triangle  one triangle             rumble strip   `count` bumps, one every `pitch`
#   A custom road is any list of features, drawn in the road editor.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 1. IMPORTS
# ---------------------------------------------------------------------------

import math
from dataclasses import dataclass

import numpy as np

from .config import RoadParams


# ---------------------------------------------------------------------------
# 2. FEATURES
# ---------------------------------------------------------------------------

SHAPES = ("bump", "triangle", "hole")


@dataclass(frozen=True)
class Feature:
    """One road feature. Positions are along the road from the car's start (m)."""

    shape: str = "bump"
    start: float = 0.0          # m
    length: float = 0.30        # m
    height: float = 0.0127      # m, + = up, - = down (a hole is always down)

    @property
    def end(self):
        return self.start + self.length

    @property
    def centre(self):
        return self.start + self.length / 2


def _hole(u, length, depth, radius):
    """Height (<= 0) and slope of a rigid wheel's centre path over a hole."""

    # The wheel can rest on the near edge, on the bottom or on the far edge.
    # Its centre sits on whichever holds it highest.
    supports = [(radius - depth, 0.0)]

    if u < radius:
        near = math.sqrt(radius**2 - u**2)
        supports.append((near, -u / near))

    if length - u < radius:
        far = math.sqrt(radius**2 - (length - u) ** 2)
        supports.append((far, (length - u) / far))

    centre, slope = max(supports)

    return centre - radius, slope


def _shape(feature, u, radius):
    """Height (m) and slope of one feature, u metres past its start."""

    length, height = feature.length, feature.height

    if feature.shape == "bump":
        angle = math.pi * u / length
        return height * math.sin(angle), height * math.pi / length * math.cos(angle)

    if feature.shape == "triangle":
        ramp = 2 * height / length
        return (ramp * u, ramp) if u <= length / 2 else (ramp * (length - u), -ramp)

    return _hole(u, length, -height, radius)


def hole_reach(depth, radius):
    """How far past the edge a wheel rolls before it touches the bottom (m)."""

    return math.sqrt(depth * (2 * radius - depth))


def _kinks(feature, radius):
    """Positions (m) where the slope of a feature jumps."""

    length = feature.length

    if feature.shape == "triangle":
        inside = [length / 2]

    elif feature.shape == "hole":
        reach = hole_reach(-feature.height, radius)
        # Wide hole: lands on the bottom, then hits the far edge.
        # Narrow hole: bridged, goes straight from the near to the far edge.
        inside = [reach, length - reach] if 2 * reach < length else [length / 2]

    else:
        inside = []

    return [feature.start + u for u in [0.0, *inside, length]]


def _check_feature(feature, radius):

    if feature.shape not in SHAPES:
        raise ValueError(f"unknown feature shape '{feature.shape}'")

    if feature.length <= 0:
        raise ValueError("feature length must be greater than 0")

    if feature.start < 0:
        raise ValueError("features cannot start before the car (x < 0)")

    if feature.height == 0:
        raise ValueError("feature height cannot be 0")

    if feature.shape == "hole" and feature.height > 0:
        raise ValueError("a hole must go down (negative height)")

    if feature.shape == "hole" and -feature.height >= radius:
        raise ValueError("a hole must be shallower than the tire radius")


# ---------------------------------------------------------------------------
# 3. ROAD
# ---------------------------------------------------------------------------

class Road:
    """A list of features, driven over at a constant speed."""

    def __init__(self, features, speed, tire_radius):

        if speed <= 0:
            raise ValueError("vehicle speed must be greater than 0")

        if not features:
            raise ValueError("the road is flat: double-click the road to add a feature")

        for feature in features:
            _check_feature(feature, tire_radius)

        self.features = list(features)
        self.speed = speed
        self.tire_radius = tire_radius

        self.start = min(feature.start for feature in features)     # m
        self.end = max(feature.end for feature in features)         # m

    @property
    def start_time(self):
        return self.start / self.speed

    @property
    def end_time(self):
        return self.end / self.speed

    def breakpoints(self):
        """
        Times where the road velocity jumps. The solver restarts at each one,
        so it can never step over a feature.
        """

        kinks = {x for feature in self.features for x in _kinks(feature, self.tire_radius)}

        return sorted(x / self.speed for x in kinks)

    @property
    def shortest_piece(self):
        """Shortest smooth piece of the input (s), used to limit the solver step."""

        times = self.breakpoints()
        gaps = [b - a for a, b in zip(times, times[1:]) if b - a > 1e-9]

        return min(gaps, default=self.end_time - self.start_time)

    def height(self, x):
        """Road height (m) and slope at x metres along the road."""

        z = slope = 0.0

        for feature in self.features:
            if feature.start <= x <= feature.end:
                dz, dslope = _shape(feature, x - feature.start, self.tire_radius)
                z += dz
                slope += dslope

        return z, slope

    def road_input(self, t):
        """Road displacement (m) and road vertical velocity (m/s) at time t."""

        z, slope = self.height(self.speed * t)

        return z, slope * self.speed

    def profile(self, positions):
        """Road height and slope for an array of positions (m)."""

        values = np.array([self.height(x) for x in np.asarray(positions, dtype=float)])

        return values[:, 0], values[:, 1]

    def sample(self, times):
        """Road displacement and velocity for an array of times."""

        z, slope = self.profile(np.asarray(times, dtype=float) * self.speed)

        return z, slope * self.speed

    def peak_velocity(self):
        """Largest vertical road velocity (m/s), checked just inside every smooth piece."""

        edges = [t * self.speed for t in self.breakpoints()]
        positions = np.concatenate([
            np.linspace(a + 1e-9 * (b - a), b - 1e-9 * (b - a), 25)
            for a, b in zip(edges, edges[1:]) if b > a
        ])

        _, slope = self.profile(positions)

        return float(np.abs(slope).max() * self.speed)

    def surface(self, x):
        """Height of the road surface itself (holes have vertical walls)."""

        z = 0.0

        for feature in self.features:
            if feature.shape == "hole":
                if feature.start < x < feature.end:
                    z += feature.height
            elif feature.start <= x <= feature.end:
                z += _shape(feature, x - feature.start, self.tire_radius)[0]

        return z


# ---------------------------------------------------------------------------
# 4. PRESET CARDS
# ---------------------------------------------------------------------------

PRESETS = ("bump", "ditch", "triangle", "rumble strip")       # card order

# Size values loaded when a card is first picked (SI units)
PRESET_DEFAULTS = {
    "bump": dict(height=0.0127, length=0.30),
    "ditch": dict(height=0.025, length=0.30),
    "triangle": dict(height=0.020, length=0.50),
    "rumble strip": dict(height=0.010, length=0.15, pitch=0.30, count=8),
}

# Size fields that read differently for one preset
PRESET_LABELS = {"ditch": {"height": "depth", "length": "width"}}


def preset_features(road):
    """Features of a preset card, built from its size values."""

    start = road.speed * road.start_time

    if road.profile == "bump":
        return [Feature("bump", start, road.length, road.height)]

    if road.profile == "ditch":
        return [Feature("hole", start, road.length, -road.height)]

    if road.profile == "triangle":
        return [Feature("triangle", start, road.length, road.height)]

    if road.profile == "rumble strip":
        return [
            Feature("bump", start + strip * road.pitch, road.length, road.height)
            for strip in range(int(road.count))
        ]

    raise ValueError(f"unknown road profile '{road.profile}'")


def _check_preset(road):

    if road.height <= 0 or road.length <= 0:
        raise ValueError("road size must be greater than 0")

    if road.start_time < 0:
        raise ValueError("road start time cannot be negative")

    if road.profile == "rumble strip":

        if road.count < 1 or road.pitch <= 0:
            raise ValueError("rumble strip needs at least 1 strip and a pitch above 0")

        if road.length > road.pitch:
            raise ValueError("rumble strip length cannot be longer than its pitch")


def road_features(road):
    """Features of any RoadParams: the drawn ones, or the preset's."""

    if road.profile == "custom":
        return list(road.features)

    _check_preset(road)

    return preset_features(road)


def make_road(road, tire_radius):
    """The Road for a RoadParams and the tire radius."""

    return Road(road_features(road), road.speed, tire_radius)


def hole_drop(length, depth, radius):
    """How far the wheel centre actually drops into a hole (m): it may bridge it."""

    if 2 * hole_reach(depth, radius) < length:
        return depth

    return radius - math.sqrt(radius**2 - (length / 2) ** 2)


def describe(params, road):
    """One line about the road, for plot titles."""

    speed = f"at {params.speed * 3.6:.0f} km/h"

    if params.profile == "custom":
        count = len(road.features)
        return (f"custom: {count} feature{'s' * (count != 1)} over "
                f"{road.end - road.start:.2f} m {speed}")

    if params.profile == "ditch":
        drop = hole_drop(params.length, params.height, road.tire_radius)
        return (f"ditch: {params.height * 1000:.1f} mm deep x {params.length:.2f} m wide "
                f"{speed}, wheel drops {drop * 1000:.1f} mm")

    if params.profile == "rumble strip":
        return (f"rumble strip: {params.count} x {params.height * 1000:.1f} mm strips, "
                f"{params.length:.2f} m long every {params.pitch:.2f} m {speed} "
                f"({params.speed / params.pitch:.1f} Hz)")

    return (f"{params.profile}: {params.height * 1000:.1f} mm x {params.length:.2f} m {speed} "
            f"({params.length / params.speed * 1000:.1f} ms)")


# ---------------------------------------------------------------------------
# 5. SKETCHES (CARDS AND THE MODEL DRAWING)
# ---------------------------------------------------------------------------

def surface_outline(road, points=160, lead=0.15):
    """Road surface with x and z both scaled to 0..1, plus flat road at each end."""

    margin = lead * (road.end - road.start)
    positions = np.linspace(road.start - margin, road.end + margin, points)

    z = np.array([road.surface(x) for x in positions])
    span = z.max() - z.min()

    x = (positions - positions[0]) / (positions[-1] - positions[0])

    return x, (z - z.min()) / span if span > 0 else np.zeros_like(z)


# A short row of strips, and a narrow ditch with flat road around it
ICON_SIZES = {"ditch": dict(height=0.04, length=0.12), "rumble strip": dict(count=4)}
ICON_LEAD = {"ditch": 0.5}


def profile_icon(profile):
    """Outline of a preset card's road, for its card."""

    sizes = {**PRESET_DEFAULTS[profile], **ICON_SIZES.get(profile, {})}
    road = make_road(RoadParams(profile=profile, speed=1.0, start_time=0.0, **sizes), 1.0)

    return surface_outline(road, lead=ICON_LEAD.get(profile, 0.15))
