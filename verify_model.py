"""
verify_model.py
---------------
Independent checks of the v2 quarter-car physics (the quartercar package).

Ported from verify_quartercar.py (v1), plus checks for what v2 added
(vehicle speed, solver restarts at the road corners, wheel lift-off).

Usage:
    python verify_model.py                  # all checks
    python verify_model.py --speed-sweep    # also print a speed sweep of the default bump

Checks:
  1. Unit conversion lbf/in -> N/m
  2. Damper curve: zero at rest, continuous at the knees, never adds energy
  3. Equations of motion vs an independently written model that INCLUDES gravity
     (absolute coordinates, started from static sag) -> justifies leaving gravity out
  4. Linear-damper case vs exact state-space solution (scipy.signal.lsim)
  5. Road step: car must settle with body and wheel both raised by the step
  6. Default solver settings vs a tight-tolerance reference
  7. Solver robustness: move the bump to other start times -> same answer
  8. Wheel lift-off: tire never pulls, and the lift-off model matches an
     independent gravity model while the wheel is in the air
  9. Road profiles: velocity = slope of displacement, peak = height
 10. Corner mass helper (one corner, not the whole car)
"""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
from scipy import signal
from scipy.integrate import solve_ivp

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quartercar import DesignCase, corner_sprung_mass, linear_modes, simulate  # noqa: E402
from quartercar.config import GRAVITY, LBF_IN_TO_N_M, KPH_TO_M_S  # noqa: E402
from quartercar.damper import build_damper  # noqa: E402
from quartercar.metrics import compute_metrics  # noqa: E402
from quartercar.road import PROFILE_DEFAULTS, ROAD_PROFILES, RoadProfile, make_road  # noqa: E402

results = []


def report(name, ok, detail):
    tag = "PASS" if ok else "FAIL"
    results.append(tag)
    print(f"[{tag}] {name}\n        {detail}")


def tight(case):
    """Same case with very tight solver settings."""
    return replace(case, sim=replace(case.sim, rtol=1e-10, atol=1e-13, max_step=5e-4))


def gravity_model(case, lift_off):
    """Independent equations in absolute coordinates, with gravity. Returns rhs and static sag."""

    corner = case.corner
    ms, mu = corner.sprung_mass, corner.unsprung_mass
    kw, kt, ct = corner.wheel_rate, corner.tire_spring_rate, corner.tire_damping
    damper = build_damper(corner)
    road = make_road(case.road)

    def rhs(t, y):
        zs, vs, zu, vu = y
        zr, vr = road.road_input(t)
        f_susp = -kw * (zs - zu) - damper.force(vs - vu)          # on the sprung mass
        f_tire = -kt * (zu - zr) - ct * (vu - vr)                  # road on the wheel
        if lift_off and (zu - zr >= 0 or f_tire < 0):              # tire length is 0 at zu = zr
            f_tire = 0.0
        return [vs, (f_susp - ms * GRAVITY) / ms, vu, (-f_susp + f_tire - mu * GRAVITY) / mu]

    zu0 = -(ms + mu) * GRAVITY / kt
    zs0 = zu0 - ms * GRAVITY / kw

    return rhs, zs0, zu0, road


def solve_reference(rhs, y0, case, times):
    road = make_road(case.road)
    edges = sorted({0.0, times[-1], *[b for b in road.breakpoints() if 0 < b < times[-1]]})
    out = np.zeros((4, len(times)))
    state = np.array(y0, dtype=float)
    for a, b in zip(edges[:-1], edges[1:]):
        s = solve_ivp(rhs, [a, b], state, method="LSODA", rtol=1e-10, atol=1e-13,
                      max_step=2e-4, dense_output=True)
        inside = (times >= a) & (times <= b)
        out[:, inside] = s.sol(times[inside])
        state = s.y[:, -1]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed-sweep", action="store_true",
                    help="print compression, rebound and air time vs speed for the default bump")
    args = ap.parse_args()

    case = DesignCase()
    corner = case.corner
    print("Verifying the quartercar package (v2)\n")

    # 1. Units
    exact = 4.4482216152605 / 0.0254
    report("1. lbf/in -> N/m conversion", abs(LBF_IN_TO_N_M - exact) / exact < 1e-6,
           f"code {LBF_IN_TO_N_M}, exact {exact:.6f}")

    # 2. Damper curve
    damper = build_damper(corner)
    v = np.linspace(-2, 2, 40001)
    F = damper.curve(v)
    knees = (damper.knee_rebound, -damper.knee_compression)
    jumps = [abs(damper.force(k + 1e-9) - damper.force(k - 1e-9)) for k in knees]
    ok = abs(damper.force(0.0)) < 1e-12 and np.all(F * v >= -1e-12) and max(jumps) < 1e-3
    report("2. Damper: F(0)=0, continuous at knees, always opposes motion", ok,
           f"largest jump at a knee {max(jumps):.2e} N, wheel knees "
           f"{damper.knee_compression:.4f} / {damper.knee_rebound:.4f} m/s (shaft knee / MR)")

    # 3. Equations vs independent gravity model (no lift-off in the default case)
    reference_case = tight(case)
    mine = simulate(reference_case)
    rhs, zs0, zu0, _ = gravity_model(case, lift_off=False)
    ref = solve_reference(rhs, (zs0, 0, zu0, 0), case, mine.time)
    err = max(np.abs(ref[0] - zs0 - mine.sprung_displacement).max(),
              np.abs(ref[2] - zu0 - mine.unsprung_displacement).max())
    report("3. Equations of motion match an independent model that includes gravity", err < 1e-9,
           f"max difference {err:.1e} m (static sag: tire {-zu0 * 1000:.2f} mm, "
           f"suspension {corner.sprung_mass * GRAVITY / corner.wheel_rate * 1000:.2f} mm)")

    # 4. Linear damper vs exact state-space
    linear_damper = replace(corner.damper, LSC_ratio=0.5, HSC_ratio=0.5, LSR_ratio=0.5, HSR_ratio=0.5)
    linear_case = tight(replace(case, corner=replace(corner, damper=linear_damper)))
    lin = simulate(linear_case)
    c = 0.5 * corner.critical_damping
    ms, mu = corner.sprung_mass, corner.unsprung_mass
    kw, kt, ct = corner.wheel_rate, corner.tire_spring_rate, corner.tire_damping
    M = np.diag([ms, mu])
    K = np.array([[kw, -kw], [-kw, kw + kt]])
    C = np.array([[c, -c], [-c, c + ct]])
    A = np.block([[np.zeros((2, 2)), np.eye(2)], [-np.linalg.solve(M, K), -np.linalg.solve(M, C)]])
    B = np.zeros((4, 2))
    B[3] = [kt / mu, ct / mu]
    tf = np.arange(0, lin.time[-1] + 1e-12, 1e-5)
    U = np.column_stack(make_road(case.road).sample(tf))
    _, Y, _ = signal.lsim(signal.StateSpace(A, B, np.eye(4), np.zeros((4, 2))), U, tf)
    zs_exact = np.interp(lin.time, tf, Y[:, 0])       # state-space order: zs, zu, vs, vu
    zu_exact = np.interp(lin.time, tf, Y[:, 1])
    err = max(np.abs(lin.sprung_displacement - zs_exact).max(),
              np.abs(lin.unsprung_displacement - zu_exact).max())
    report("4. Linear-damper case matches exact state-space solution", err < 1e-6,
           f"max difference {err:.1e} m")

    # 5. Road step (a test-only profile)
    class RoadStep(RoadProfile):
        name = "step"

        def road_input(self, t):
            return (self.height if t >= self.start_time else 0.0), 0.0

    ROAD_PROFILES["step"] = RoadStep
    try:
        step_case = replace(case, road=replace(case.road, profile="step", height=0.01, start_time=0.5),
                            sim=replace(case.sim, settle_time=6.0))
        s = simulate(step_case)
    finally:
        del ROAD_PROFILES["step"]
    ok = abs(s.sprung_displacement[-1] - 0.01) < 1e-6 and abs(s.unsprung_displacement[-1] - 0.01) < 1e-6
    report("5. 10 mm road step: body and wheel settle 10 mm higher", ok,
           f"final body {s.sprung_displacement[-1] * 1000:.4f} mm, wheel {s.unsprung_displacement[-1] * 1000:.4f} mm")

    # 6. Default solver settings vs tight reference
    own = simulate(case)
    travel_ref = np.abs(mine.suspension_travel).max()
    travel_own = np.abs(own.suspension_travel).max()
    err = np.abs(own.suspension_travel - mine.suspension_travel).max()
    report("6. Default solver settings vs tight-tolerance reference",
           abs(travel_own - travel_ref) < 0.02 * travel_ref and err < 1e-6,
           f"max travel: default {travel_own * 1000:.4f} mm, reference {travel_ref * 1000:.4f} mm, "
           f"largest difference {err * 1000:.1e} mm")

    # 7. Robustness: same solver settings, bump moved
    missed = []
    for start in np.round(np.arange(0.2, 4.6, 0.2), 2):
        moved = replace(case, road=replace(case.road, start_time=float(start)))
        got = np.abs(simulate(moved).suspension_travel).max()
        if abs(got - travel_own) > 0.01 * travel_own:
            missed.append((start, got))
    report("7. Solver catches the bump wherever it is placed", not missed,
           "bump resolved at every start time tested (0.2 to 4.4 s)" if not missed else
           ", ".join(f"start {b}s -> {g * 1000:.2f} mm" for b, g in missed[:4]))

    # 8. Lift-off: cone strike launches the wheel
    cone_case = replace(case, road=replace(case.road, profile="cone", **PROFILE_DEFAULTS["cone"]))
    cone = simulate(tight(cone_case))
    air_time = compute_metrics(cone).air_time
    rhs, zs0, zu0, _ = gravity_model(cone_case, lift_off=True)
    ref = solve_reference(rhs, (zs0, 0, zu0, 0), cone_case, cone.time)
    err = max(np.abs(ref[0] - zs0 - cone.sprung_displacement).max(),
              np.abs(ref[2] - zu0 - cone.unsprung_displacement).max())
    ok = cone.contact_force.min() >= 0 and air_time > 0 and err < 1e-6
    report("8. Wheel lift-off: tire never pulls, matches independent gravity model in the air", ok,
           f"cone strike: air time {air_time * 1000:.1f} ms, min contact {cone.contact_force.min():.1f} N, "
           f"max difference {err:.1e} m")

    # 9. Road profiles
    worst = 0.0
    peaks = []
    for name, shape in PROFILE_DEFAULTS.items():
        road = make_road(replace(case.road, profile=name, **shape))
        t = np.linspace(road.start_time - 0.01, road.end_time + 0.01, 20001)
        z, zd = road.sample(t)
        slope = np.gradient(z, t)
        corners = np.array(road.breakpoints())
        smooth = np.min(np.abs(t[:, None] - corners[None, :]), axis=1) > 3 * (t[1] - t[0])
        scale = np.abs(zd).max()
        worst = max(worst, np.abs(slope - zd)[smooth].max() / scale)
        peaks.append(abs(z.max() - road.height) / road.height)
    report("9. Road profiles: velocity = slope of displacement, peak = height",
           worst < 2e-3 and max(peaks) < 1e-3,
           f"worst velocity mismatch {worst * 100:.3f} % of peak, worst peak error {max(peaks) * 100:.3f} %")

    # 10. Corner mass helper
    sprung = corner_sprung_mass(300.0, 8.4354, 0.53)
    expected = (300.0 - 4 * 8.4354) * 0.53 / 2
    report("10. Corner sprung mass helper", abs(sprung - expected) < 1e-9,
           f"300 kg car, 8.44 kg unsprung corners, 53 % on the axle -> {sprung:.2f} kg per corner")

    # Info
    print("\nINFO")
    modes = linear_modes(corner)
    print(f"  natural frequencies: body {modes['body_frequency']:.2f} Hz, "
          f"wheel hop {modes['wheel_hop_frequency']:.2f} Hz")
    print(f"  2-DOF body-mode damping (low-speed slopes): {modes['body_damping_ratio']:.3f}")
    print(f"  default road: {make_road(case.road).describe()}")

    if args.speed_sweep:
        print(f"\nSPEED SWEEP: {case.road.height * 1000:.1f} mm tall x {case.road.length:.2f} m long half-sine bump")
        for kph in (5, 10, 15, 20, 30, 40, 50, 60, 80):
            run = simulate(replace(case, road=replace(case.road, speed=kph * KPH_TO_M_S)))
            m = compute_metrics(run)
            flag = "  <-- wheel leaves the ground" if m.air_time > 0 else ""
            print(f"  {kph:3d} km/h: compression {m.max_compression * 1000:5.2f} mm, "
                  f"rebound {m.max_rebound * 1000:5.2f} mm, min contact {m.min_contact_force:6.1f} N, "
                  f"air {m.air_time * 1000:5.1f} ms{flag}")

    print(f"\nSUMMARY: {results.count('PASS')} passed, {results.count('FAIL')} failed")
    return 0 if "FAIL" not in results else 1


if __name__ == "__main__":
    sys.exit(main())
