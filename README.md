# FSAE quarter-car suspension design tool

A desktop app for sizing one wheel corner of an FSAE car. You build a road
(presets or your own), sweep motion ratio, spring rate, damping, downforce,
road input and masses, check every setup against hard design limits, and
rank the setups that pass by the number you care about.

It grew out of the v1 script (`Context+Materials/QuarterCar.py`) and keeps
its equations, names and sign conventions.

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
| **parameters**, sweep tab | Up to four swept variables, each with start / stop / step, and what to rank and map the results by. |
| **the road** | Four views: `road` (model sketch and the road editor), `response` (time histories of the last run), `sweep` (metric map and trade-off chart), `ranking` (every swept setup in a table). |
| road cards | Presets: bump, ditch, triangle, rumble strip. Each remembers its own size. |
| **results** | Motion ratio, spring rate, minimum ride height, max travel (compression / rebound) and max body acceleration, each with its limit and a pass / fail mark. |

A typical session:

1. Enter the corner data. Check that "whole car if 4 such corners" is close
   to the car + driver mass.
2. Pick a road card, or build a custom road in the road view (below).
3. Press **run simulation** (F5) and read the `response` view and the results.
4. On the sweep tab, tick variables and set ranges, then press **run sweep** (F6).
   Esc cancels a sweep; setups that already finished are kept.
5. In the `sweep` view, hover a setup for its numbers and double-click it to
   load and simulate it. The `ranking` view lists every setup (click a heading
   to rank by it) and can export it to CSV.

### Building a road

The road view works like an EQ: every road feature has a point you can grab.

| Action | Effect |
|---|---|
| drag a point | move the feature along the road and set its height (below zero = a dip) |
| scroll on a point | make it longer or shorter |
| double-click the road | add a bump there (below the zero line: a dip) |
| right-click | add a bump, dip or hole, change a feature's shape, or delete it |
| Delete key | delete the selected feature |
| bar above the plot | the selected feature's shape, start, length and height, for exact values |

Moving or resizing a preset keeps it a preset; it just changes its size values
in the setup tab. Adding, deleting or reshaping a feature turns the road into a
**custom road**, so the presets themselves never change. Pick a card to go back
to a preset, and press **custom road** to get your custom road back.

## Model

**One wheel corner (quarter car), 2 DOF.** The whole-car mass is never
lumped onto one wheel.

- sprung mass = the share of chassis + driver carried by this corner,
  `(car mass - 4 x unsprung) x axle weight fraction / 2`
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
| Downforce | This corner's share, constant during a run. It lowers the ride height by `downforce / ride_rate` and adds to the static tire load. |
| Road | A list of features along the road. The car starts at x = 0 and drives at a set speed, so `x = speed x t` and road velocity = slope x speed. Overlapping features add up. |
| Solver | `scipy.integrate.solve_ivp` (RK45). The run restarts at every corner of the road input, with `max_step = shortest piece / 20` on the road, so the solver cannot step over a feature. |

Feature shapes:

| Shape | Input to the tire |
|---|---|
| bump | Half-sine. A negative height makes a smooth dip. |
| triangle | Straight ramp up, then down. Constant road velocity, so it is a clean damper test. |
| hole | A sharp-edged hole. A point-contact tire would drop straight to the bottom, so the input is the path of a rigid wheel (the tire radius) rolling over it: down over the near edge, along the bottom if it gets there, then a hard hit climbing out over the far edge. A narrow hole is bridged: the wheel drops less than the hole is deep. The road view shows the hole's walls dashed and the wheel path solid. |

Presets: **bump** = one bump, **ditch** = one hole (its height and length
read as depth and width), **triangle** = one triangle, **rumble strip** =
a row of bumps at a set pitch (excitation frequency = speed / pitch).

## Limits, ranking, sweep

A setup **passes** only if all of these hold for the whole run:

| Limit | Check |
|---|---|
| min ride height | lowest chassis height at this corner >= limit |
| max compression travel | bump travel at the wheel <= limit |
| max rebound travel | droop travel at the wheel <= limit |
| max body acceleration | peak body acceleration <= limit |
| max tire air time | time with the tire off the ground <= limit (0 = never) |

Setups that pass are ranked by one value you pick ("rank by" on the sweep tab):
tire load lost, RMS tire load change, peak or RMS body acceleration,
compression or rebound travel, min ride height, or tire air time. Setups that
fail come last, ordered by how far past the limits they are ("over limit %").

A **sweep** runs every combination of the ticked variables. Anything not swept
keeps its value from the setup tab. `damping scale` multiplies all four
damping ratios together, so their balance is kept. Road height, length and
pitch only apply to the preset cards; speed and downforce apply to any road.
Large sweeps run on several CPU cores.

If the best setup sits at the edge of a swept range, the results bar says so.
Widen that range, because the optimum may lie outside it.


## Files

```
run_app.py              start the app
quartercar/
  config.py             all inputs (dataclasses) and unit constants
  damper.py             nonlinear 4-way damper
  road.py               road features, presets, the road a tire sees
  model.py              equations of motion, simulation, linear modes
  metrics.py            time histories -> key numbers; what a sweep can rank by
  constraints.py        pass / fail against the design limits
  sweep.py              evaluate one design, run a sweep, rank it
  parameters.py         labels, units and ranges for the GUI and the sweep
  plotting.py           matplotlib figures (no Tk, also usable in scripts or a web app)
  gui/                  Tkinter app: theme, widgets, forms, road editor, main window
```

## Extending

- **New input:** add a field to a dataclass in `config.py` and a `ParamSpec`
  in `parameters.py`. It then appears in the form and can be swept.
- **New feature shape:** add it to `SHAPES` and `_shape()` (and `_kinks()` if
  its slope jumps) in `road.py`. The editor offers it automatically.
- **New preset card:** add it to `PRESETS`, `PRESET_DEFAULTS` and
  `preset_features()` in `road.py`.
- **New limit or ranking value:** `constraints.py` / `RANK_METRICS` in `metrics.py`.
- **Better tire model:** replace `tire_contact_force()` in `model.py`.
- **Half car or web front end:** `model.py`, `sweep.py` and `plotting.py`
  have no GUI code, so a new model class or a web page can reuse them.

## Assumptions and limits of the model

- The spring is linear, with no bump stop or top-out. Running past a travel
  limit is flagged as a failed limit, not modelled.
- The chassis sits over flat ground; the road acts at the tire only.
- Downforce is constant during a run and does not change when speed is swept.
- Bumps and triangles meet a point-contact tire directly; only holes use the
  rigid-wheel path. Overlapping features simply add.
- The damping ratios are single-DOF values, like the spreadsheet. The real
  body-mode damping of the 2-DOF model is shown as "2-DOF modal damping" and
  is lower.
