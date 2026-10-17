# FSAE quarter-car suspension design tool (v2)

A desktop app for sizing one wheel corner of an FSAE car: sweep motion ratio,
spring rate, damping, road input and masses, check every setup against hard
design limits, and rank the setups that pass.

It is the v1 script (`Context+Materials/QuarterCar.py`) grown into a small
package. It keeps the same equations, names and sign conventions, and fixes
what the v1 verification report asked for (vehicle speed, solver skipping
the bump, wheel lift-off).

## Setup

Needs Python 3.9 or newer. The python.org installers for Windows and macOS
include Tkinter.

```
pip install -r requirements.txt
python run_app.py
```

`python -m quartercar` also starts it. On Linux, install Tk first
(`sudo apt install python3-tk`).

## Using the app

| Area | What it does |
|---|---|
| **parameters**, setup tab | Every input, grouped. Gray rows are derived values (wheel rate, natural frequencies, damper coefficients, ...) that update while you type. Boxes with bad values turn red. Hover a label for help. |
| **parameters**, sweep tab | Up to four swept variables, each with start / stop / step. Also picks the axes of the score map. |
| **the road** | Four views: `road` (model sketch and road preview), `response` (time histories of the last run), `sweep` (score map and trade-off chart), `ranking` (every swept setup in a table). |
| road cards | bump, cone, triangle, rumble strip. Each profile remembers its own height, length, etc. |
| **results** | Motion ratio, spring rate, minimum ride height, max travel (compression / rebound) and max body acceleration, each with its limit and a pass / fail mark. |

A typical session:

1. Enter the corner data. Check that "whole car if 4 such corners" is close
   to the car + driver mass.
2. Pick a road card and set its size and the vehicle speed.
3. Press **run simulation** (F5) and read the `response` view and the results.
4. On the sweep tab, tick variables and set ranges, then press **run sweep** (F6).
   Esc cancels a sweep; setups that already finished are kept.
5. In the `sweep` view, hover a setup for its numbers and double-click it to
   load and simulate it. The `ranking` view lists every setup and can export
   it to CSV.

If the best setup sits at the edge of a swept range, the results bar says so.
Widen that range, because the optimum may lie outside it.

## Model

**One wheel corner (quarter car), 2 DOF.** The whole-car mass is never
lumped onto one wheel.

- sprung mass = the share of chassis + driver carried by this corner,
  `(car mass - 4 x unsprung) x axle weight fraction / 2`
  (`quartercar.corner_sprung_mass()` does this calculation)
- unsprung mass = wheel + tire + upright + hub + brake of this corner

```
ms * zs'' = - spring_force - damping_force
mu * zu'' =   spring_force + damping_force - tire_force

spring_force  = wheel_rate * (zs - zu)
damping_force = damper(vs - vu)
tire_force    = static_tire_load - contact_force
```

Same conventions as v1. z is positive up and measured from static
equilibrium. Suspension travel = `zs - zu`, with + = rebound. States are
`[zs, vs, zu, vu]`.

| Part | Definition |
|---|---|
| Spring | `wheel_rate = spring_rate x MR^2`, where MR = spring travel / wheel travel. Spring and damper share one MR (coilover). |
| Damper | Four damping ratios (LSC, HSC, LSR, HSR) times `c_critical = 2 sqrt(wheel_rate x sprung_mass)`, as in the v1 spreadsheet. Knee speeds are **damper shaft** speeds; the model divides them by MR to get wheel speeds. |
| Tire | Point contact. The spring plus `tire_damping_ratio x 2 sqrt(kt x mu)`. It pushes but never pulls, and the wheel can leave the ground. |
| Aero | Constant downforce on this corner. It lowers the ride height by `aero_load / ride_rate` and adds to the static tire load. |
| Road | Defined in space (height, length) and driven at a set speed, so `duration = length / speed`. |
| Solver | `scipy.integrate.solve_ivp` (RK45). The run restarts at every corner of the road input, with `max_step = feature / 20` on the feature, so the solver cannot step over a bump. |

Road profiles:

| Profile | Shape |
|---|---|
| bump | Half-sine (the default) |
| cone | Running over a knocked-down cone, modelled as a round obstacle: the circular arc a rigid wheel follows. Steep entry and a rounded top. |
| triangle | Straight ramp up, then down. Constant road velocity, so it is a clean damper test. |
| rumble strip | A row of half-sine strips at a set pitch. Excitation frequency = speed / pitch. |

## Limits, score, sweep

A setup **passes** only if all of these hold for the whole run:

| Limit | Check |
|---|---|
| min ride height | lowest chassis height at this corner >= limit |
| max compression travel | bump travel at the wheel <= limit |
| max rebound travel | droop travel at the wheel <= limit |
| max body acceleration | peak body acceleration <= limit |
| max tire air time | time with the tire off the ground <= limit (0 = never) |

Setups that pass are ranked by **score**, where lower is better. The score is
a weighted average of how much of each budget the setup uses:

- peak body accel / allowed body accel
- share of static tire load lost at the worst instant
- travel used / travel available
- ground clearance used / clearance available

You can change the weights in the setup tab. Setups that fail rank last,
ordered by how far they miss.

A **sweep** runs every combination of the ticked variables. Anything not swept
keeps its value from the setup tab. `damping scale` multiplies all four
damping ratios together, so their balance is kept. Large sweeps run on
several CPU cores.

## Checking the physics

```
python verify_model.py              # 10 checks, ported from verify_quartercar.py
python verify_model.py --speed-sweep
```

The checks compare the model against an independent model that includes
gravity (with and without lift-off), an exact state-space solution, and a
road-step settle test. They also move the bump to other start times to
confirm the solver never skips it.

## Files

```
run_app.py              start the app
verify_model.py         physics checks
quartercar/
  config.py             all inputs (dataclasses) and unit constants
  damper.py             nonlinear 4-way damper
  road.py               road profiles
  model.py              equations of motion, simulation, linear modes
  metrics.py            time histories -> key numbers
  constraints.py        pass / fail against the design limits
  scoring.py            ranking score
  sweep.py              evaluate one design, run a sweep
  parameters.py         labels, units and ranges for the GUI and the sweep
  plotting.py           matplotlib figures (no Tk, also usable in scripts or a web app)
  gui/                  Tkinter app: theme, widgets, forms, main window
```

## Extending

- **New input:** add a field to a dataclass in `config.py` and a `ParamSpec`
  in `parameters.py`. It then appears in the form and can be swept.
- **New road profile:** subclass `RoadProfile` in `road.py`, then add it to
  `ROAD_PROFILES` and `PROFILE_DEFAULTS`. It gets a card automatically.
- **New limit or score term:** `constraints.py` / `scoring.py`.
- **Better tire model:** replace `tire_contact_force()` in `model.py`.
- **Half car or web front end:** `model.py`, `sweep.py` and `plotting.py`
  have no GUI code, so a new model class or a web page can reuse them.

## Assumptions and limits of the model

- The spring is linear, with no bump stop or top-out. Running past a travel
  limit is flagged as a failed limit, not modelled.
- The chassis sits over flat ground; the road feature acts at the tire only.
- Aero load is constant during a run and does not change when speed is swept.
- The damping ratios are single-DOF values, like the spreadsheet. The real
  body-mode damping of the 2-DOF model is shown as "2-DOF modal damping" and
  is lower.
