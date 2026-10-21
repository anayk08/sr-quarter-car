"""Streamlit front end for the shared quarter-car design and sweep engine."""

import csv
import io
import math
import queue
import threading

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import streamlit as st

from quartercar import plotting
from quartercar.config import GRAVITY, LBF_IN_TO_N_M, DesignCase, with_value
from quartercar.parameters import (
    DERIVED,
    DEFAULT_SWEEP_ROWS,
    PARAMETERS,
    PARAMETER_BY_KEY,
    SECTIONS,
    SWEEP_VARIABLES,
)
from quartercar.road import PROFILE_DEFAULTS, ROAD_PROFILES, make_road, profile_icon
from quartercar.scoring import SCORE_TERMS
from quartercar.sweep import SweepAxis, default_workers, evaluate_design, run_sweep, sweep_size


st.set_page_config(page_title="FSAE quarter-car suspension design tool", layout="wide")

ROAD_SHAPE_KEYS = ("height", "length", "pitch", "count")
VIEWS = ("road", "response", "sweep", "ranking")
CONFIRM_RUNS = 3000


def _input_key(key):
    return f"input_{key}"


def _apply_theme():
    st.markdown(
        """
        <style>
        .stApp, [data-testid="stAppViewContainer"] { background: #d9d9d9; color: #111111; }
        [data-testid="stHeader"], [data-testid="stToolbar"] { display: none; }
        .block-container { max-width: none; padding: 0.7rem 0.7rem 1.2rem; }
        h1, h2, h3, p, label, [data-testid="stMarkdownContainer"] {
          font-family: "Segoe UI", Arial, sans-serif;
        }
        .stApp h1 { text-align: center; font-size: 1.35rem !important;
          line-height: 1.25 !important; margin: 0 0 0.5rem; }
        h2, h3 { font-size: 1.05rem; }
        div[data-testid="stVerticalBlockBorderWrapper"] > div {
          border: 2px solid #000 !important; border-radius: 0 !important;
          background: #d9d9d9 !important;
        }
        [data-baseweb="input"], [data-baseweb="select"] > div {
          background: #f4f4f2 !important; border-radius: 0 !important;
          border-color: #111 !important;
        }
        div[data-testid="stNumberInput"] input {
          background: #f4f4f2 !important; color: #111 !important;
          border-radius: 0 !important; border-color: #111 !important;
        }
        div[data-testid="stNumberInput"] button {
          background: #d9d9d9 !important; color: #111 !important;
          border-radius: 0 !important; border-color: #111 !important;
        }
        button { border: 2px solid #000 !important; border-radius: 0 !important;
          background: #d9d9d9 !important; color: #111 !important; }
        button:hover { background: #cbcbcb !important; border-color: #000 !important; }
        button[kind="primary"], button[data-testid="stBaseButton-primary"] {
          background: #111 !important; color: #f4f4f2 !important;
        }
        div[data-testid="stMetric"] {
          border: 2px solid #000; padding: 0.5rem; color: #111 !important;
          opacity: 1 !important; animation: none !important; transition: none !important;
        }
        div[data-testid="stMetric"] *,
        div[data-testid="stMetric"] label,
        div[data-testid="stMetric"] [data-testid="stMetricLabel"],
        div[data-testid="stMetric"] [data-testid="stMetricValue"],
        div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
          color: #111 !important; opacity: 1 !important;
          animation: none !important; transition: none !important;
          -webkit-text-fill-color: #111 !important;
        }
        [data-testid="stCaptionContainer"] { color: #4a4a48; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _init_state():
    defaults = DesignCase()
    for spec in PARAMETERS:
        st.session_state.setdefault(_input_key(spec.key), float(spec.format(spec.get(defaults))))

    st.session_state.setdefault("profile", defaults.road.profile)
    st.session_state.setdefault("road_memory", {})
    st.session_state.setdefault("parameter_tab", "setup")
    st.session_state.setdefault("view", "road")
    st.session_state.setdefault("last_evaluation", None)
    st.session_state.setdefault("last_sweep", None)
    st.session_state.setdefault("result_source_case", None)
    st.session_state.setdefault("sweep_active", False)
    st.session_state.setdefault("sweep_progress", (0, 0))
    st.session_state.setdefault("allow_large_sweep", False)
    st.session_state.setdefault("run_after_load", False)
    st.session_state.setdefault("sweep_version", 0)

    for index, (key, enabled) in enumerate(DEFAULT_SWEEP_ROWS):
        axis = SWEEP_VARIABLES[key]
        start, stop, step = axis.sweep_range
        st.session_state.setdefault(f"sweep_{index}_enabled", enabled)
        st.session_state.setdefault(f"sweep_{index}_key", key)
        st.session_state.setdefault(f"sweep_{index}_start", float(start))
        st.session_state.setdefault(f"sweep_{index}_stop", float(stop))
        st.session_state.setdefault(f"sweep_{index}_step", float(step))


def _select_profile(profile):
    old_profile = st.session_state["profile"]
    memory = st.session_state["road_memory"]
    memory[old_profile] = {
        key: st.session_state[_input_key(key)]
        for key in ROAD_SHAPE_KEYS
        if key in PARAMETER_BY_KEY
    }

    st.session_state["profile"] = profile
    saved = memory.get(profile, {})
    for key, value in PROFILE_DEFAULTS[profile].items():
        spec = PARAMETER_BY_KEY[key]
        st.session_state[_input_key(key)] = saved.get(key, float(spec.format(value)))


def _set_parameter_tab(name):
    st.session_state["parameter_tab"] = name


def _set_view(name):
    st.session_state["view"] = name


def _case_from_state():
    case = DesignCase()
    errors = {}
    profile = st.session_state["profile"]

    case = with_value(case, ("road", "profile"), profile)

    for spec in PARAMETERS:
        if not spec.applies_to(profile):
            continue
        shown = float(st.session_state[_input_key(spec.key)])
        message = spec.check(shown)
        if message:
            errors[spec.key] = f"{spec.label}: {message}"
            continue
        case = spec.set(case, spec.from_display(shown))

    if not errors:
        try:
            make_road(case.road)
        except ValueError as error:
            for key in ROAD_SHAPE_KEYS:
                spec = PARAMETER_BY_KEY.get(key)
                if spec and spec.applies_to(profile):
                    errors[key] = f"{spec.label}: {error}"

        weights = case.weights
        if weights.body_acceleration + weights.tire_load + weights.travel + weights.ride_height <= 0:
            errors["w_body_acceleration"] = "At least one score weight must be above 0."

    return case, errors


def _format_axis(axis, value):
    unit = "" if axis.spec.unit in ("", "-") else f" {axis.spec.unit}"
    return f"{axis.spec.name} {axis.spec.format(value)}{unit}"


def _read_sweep_axes():
    axes = []
    errors = []
    for index in range(len(DEFAULT_SWEEP_ROWS)):
        if not st.session_state[f"sweep_{index}_enabled"]:
            continue
        key = st.session_state[f"sweep_{index}_key"]
        spec = SWEEP_VARIABLES[key]
        try:
            start = float(st.session_state[f"sweep_{index}_start"])
            stop = float(st.session_state[f"sweep_{index}_stop"])
            step = float(st.session_state[f"sweep_{index}_step"])
        except (TypeError, ValueError):
            errors.append(f"{spec.label}: start, stop and step must be numbers")
            continue

        message = spec.check(start) or spec.check(stop)
        if message:
            errors.append(f"{spec.label}: {message}")
            continue

        axis = SweepAxis(key, spec.from_display(start), spec.from_display(stop),
                         spec.from_display(step))
        try:
            axis.values()
        except ValueError as error:
            errors.append(str(error))
            continue
        axes.append(axis)

    keys = [axis.key for axis in axes]
    if len(set(keys)) != len(keys):
        errors.append("Each variable can only be swept once.")
    return axes, errors


def _load_case(case):
    old_profile = st.session_state["profile"]
    st.session_state["road_memory"][old_profile] = {
        key: st.session_state[_input_key(key)]
        for key in ROAD_SHAPE_KEYS
        if key in PARAMETER_BY_KEY
    }
    st.session_state["profile"] = case.road.profile
    for spec in PARAMETERS:
        st.session_state[_input_key(spec.key)] = float(spec.format(spec.get(case)))
    st.session_state["road_memory"][case.road.profile] = {
        key: st.session_state[_input_key(key)]
        for key in ROAD_SHAPE_KEYS
        if key in PARAMETER_BY_KEY
    }
    st.session_state["parameter_tab"] = "setup"
    st.session_state["view"] = "response"
    st.session_state["run_after_load"] = True


def _reset():
    defaults = DesignCase()
    for spec in PARAMETERS:
        st.session_state[_input_key(spec.key)] = float(spec.format(spec.get(defaults)))
    st.session_state["profile"] = defaults.road.profile
    st.session_state["road_memory"] = {}
    st.session_state["parameter_tab"] = "setup"
    st.session_state["view"] = "road"
    st.session_state["last_evaluation"] = None
    st.session_state["last_sweep"] = None
    st.session_state["result_source_case"] = None
    st.session_state["allow_large_sweep"] = False
    for index, (key, enabled) in enumerate(DEFAULT_SWEEP_ROWS):
        axis = SWEEP_VARIABLES[key]
        start, stop, step = axis.sweep_range
        st.session_state[f"sweep_{index}_enabled"] = enabled
        st.session_state[f"sweep_{index}_key"] = key
        st.session_state[f"sweep_{index}_start"] = float(start)
        st.session_state[f"sweep_{index}_stop"] = float(stop)
        st.session_state[f"sweep_{index}_step"] = float(step)


def _request_cancel():
    event = st.session_state.get("sweep_cancel_event")
    if event is not None:
        event.set()


def _sweep_variable_changed(index):
    key = st.session_state[f"sweep_{index}_key"]
    start, stop, step = SWEEP_VARIABLES[key].sweep_range
    st.session_state[f"sweep_{index}_start"] = float(start)
    st.session_state[f"sweep_{index}_stop"] = float(stop)
    st.session_state[f"sweep_{index}_step"] = float(step)


def _start_sweep(case, axes):
    result_queue = queue.Queue()
    cancel_event = threading.Event()
    st.session_state["sweep_queue"] = result_queue
    st.session_state["sweep_cancel_event"] = cancel_event
    st.session_state["sweep_base_case"] = case
    st.session_state["sweep_progress"] = (0, sweep_size(axes))
    st.session_state["sweep_active"] = True

    def work():
        try:
            result = run_sweep(
                case,
                axes,
                on_progress=lambda done, total: result_queue.put(("progress", done, total)),
                should_stop=cancel_event.is_set,
                workers=default_workers(),
            )
            result_queue.put(("done", result))
        except Exception as error:
            result_queue.put(("error", f"{type(error).__name__}: {error}"))

    threading.Thread(target=work, daemon=True).start()


@st.fragment(run_every=0.5)
def _sweep_monitor():
    if not st.session_state.get("sweep_active"):
        return

    result_queue = st.session_state["sweep_queue"]
    finished = None
    while True:
        try:
            message = result_queue.get_nowait()
        except queue.Empty:
            break
        if message[0] == "progress":
            st.session_state["sweep_progress"] = (message[1], message[2])
        else:
            finished = message

    if finished is not None:
        st.session_state["sweep_active"] = False
        if finished[0] == "error":
            st.session_state["sweep_error"] = finished[1]
            st.rerun(scope="app")
            return

        sweep = finished[1]
        st.session_state["last_sweep"] = sweep
        st.session_state["sweep_version"] += 1
        st.session_state["result_source_case"] = st.session_state["sweep_base_case"]
        best = sweep.best()
        st.session_state["last_evaluation"] = best.evaluation if best else None
        st.session_state["view"] = "sweep"
        st.rerun(scope="app")
        return

    done, total = st.session_state["sweep_progress"]
    st.progress(done / total if total else 0.0, text=f"sweep  {done} / {total}")
    st.button("Cancel sweep", on_click=_request_cancel, disabled=st.session_state["sweep_cancel_event"].is_set())
    if st.session_state["sweep_cancel_event"].is_set():
        st.caption("Cancelling; completed setups will be kept.")


def _render_parameters(case, errors):
    tab_cols = st.columns(2)
    for column, name in zip(tab_cols, ("setup", "sweep")):
        column.button(
            name,
            key=f"tab_{name}",
            type="primary" if st.session_state["parameter_tab"] == name else "secondary",
            on_click=_set_parameter_tab,
            args=(name,),
            use_container_width=True,
        )
    active_tab = st.session_state["parameter_tab"]

    if active_tab == "sweep":
        _render_sweep_form()
        return

    st.caption("Gray values are calculated from the inputs. Invalid values are marked below.")
    for section in SECTIONS:
        st.markdown(f"**{section}**")
        st.markdown(
            "<hr style='margin:0.15rem 0 0.4rem 0;border-color:#777'>",
            unsafe_allow_html=True,
        )
        for spec in PARAMETERS:
            if spec.section != section or not spec.applies_to(st.session_state["profile"]):
                continue
            lower = spec.minimum if math.isfinite(spec.minimum) else None
            upper = spec.maximum if math.isfinite(spec.maximum) else None
            lower = float(lower) if lower is not None else None
            upper = float(upper) if upper is not None else None
            if spec.positive:
                lower = max(lower if lower is not None else 0.0, 1e-12)
            step = float(1 if spec.integer else 10 ** (-spec.decimals))
            label_col, input_col = st.columns([1.5, 1])
            unit = "" if spec.unit in ("", "-") else f" ({spec.unit})"
            label_col.markdown(f"{spec.label}{unit}")
            input_col.number_input(
                spec.label,
                value=None,
                min_value=lower,
                max_value=upper,
                step=step,
                format=f"%.{spec.decimals}f",
                key=_input_key(spec.key),
                help=spec.help or None,
                label_visibility="collapsed",
            )
            if spec.key in errors:
                st.error(errors[spec.key])
        for derived in DERIVED:
            if derived.section == section and derived.applies_to(st.session_state["profile"]):
                st.caption(f"{derived.label}: **{derived.text(case)}**")


def _render_sweep_form():
    st.caption(
        "Every combination of the checked variables is run. Anything not swept keeps "
        "its value from the setup tab. The damping scale multiplies all four damper "
        "ratios together, keeping their balance."
    )

    labels = {
        key: f"{spec.label} ({spec.unit})" if spec.unit not in ("", "-") else spec.label
        for key, spec in SWEEP_VARIABLES.items()
    }
    selected = []
    for index in range(len(DEFAULT_SWEEP_ROWS)):
        with st.container(border=True):
            enabled_col, variable_col = st.columns([0.12, 0.88])
            enabled_col.checkbox("run", key=f"sweep_{index}_enabled", label_visibility="collapsed")
            key = variable_col.selectbox(
                "variable",
                list(SWEEP_VARIABLES),
                format_func=lambda value: labels[value],
                key=f"sweep_{index}_key",
                label_visibility="collapsed",
                on_change=_sweep_variable_changed,
                args=(index,),
            )
            spec = SWEEP_VARIABLES[key]
            value_cols = st.columns(3)
            for name, column in zip(("start", "stop", "step"), value_cols):
                column.number_input(
                    name,
                    value=None,
                    key=f"sweep_{index}_{name}",
                    step=float(10 ** (-spec.decimals)),
                    format=f"%.{spec.decimals}f",
                )
            if st.session_state[f"sweep_{index}_enabled"]:
                selected.append(key)

    axes, errors = _read_sweep_axes()
    if errors:
        for error in errors:
            st.error(error)
    elif axes:
        counts = [len(axis.values()) for axis in axes]
        total = sweep_size(axes)
        st.info(f"{' x '.join(map(str, counts))} = {total} setups")
    else:
        st.info("Check at least one variable to run a sweep.")
    if len(selected) != len(set(selected)):
        st.error("Each variable can only be swept once.")
    st.caption(f"Large sweeps use up to {default_workers()} CPU processes.")


def _render_road_cards():
    for row in range(2):
        cards = st.columns(2)
        for column, profile in zip(cards, tuple(ROAD_PROFILES)[row * 2:row * 2 + 2]):
            with column.container(border=True):
                x, z = profile_icon(profile)
                fig, ax = plt.subplots(figsize=(2.2, 0.6))
                ax.plot(x, z, color="#0b0b0b", linewidth=2)
                ax.fill_between(x, z, 0, color="#d6d5ce")
                ax.set_axis_off()
                ax.margins(x=0.04, y=0.2)
                column.pyplot(fig, use_container_width=True)
                plt.close(fig)
                column.button(
                    profile,
                    key=f"profile_{profile}",
                    type="primary" if st.session_state["profile"] == profile else "secondary",
                    on_click=_select_profile,
                    args=(profile,),
                    use_container_width=True,
                    disabled=st.session_state["sweep_active"],
                )


def _render_results(evaluation):
    st.subheader("Results")
    if evaluation is None:
        st.info("Run a simulation or sweep to see the results.")
        return

    case = evaluation.case
    metrics = evaluation.metrics
    checks = {check.key: check for check in evaluation.checks}
    cells = st.columns(5)
    values = (
        ("motion ratio", f"{case.corner.motion_ratio:.3f}", "spring / wheel travel", None),
        ("spring rate", f"{case.corner.spring_rate / LBF_IN_TO_N_M:.0f} lbf/in",
         f"wheel rate {case.corner.wheel_rate / LBF_IN_TO_N_M:.0f} lbf/in", None),
        ("min ride height", f"{metrics.min_ride_height * 1000:.1f} mm",
         f"limit {case.limits.min_ride_height * 1000:.1f} mm", checks["ride_height"].passed),
        ("travel comp / reb",
         f"{metrics.max_compression * 1000:.1f} / {metrics.max_rebound * 1000:.1f} mm",
         f"limits {case.limits.max_compression * 1000:.1f} / {case.limits.max_rebound * 1000:.1f} mm",
         checks["compression"].passed and checks["rebound"].passed),
        ("max body accel", f"{metrics.max_body_acceleration / GRAVITY:.2f} g",
         f"limit {case.limits.max_body_acceleration / GRAVITY:.2f} g",
         checks["body_acceleration"].passed),
    )
    for column, (label, value, detail, passed) in zip(cells, values):
        column.metric(label, value, help=detail)
        if passed is not None:
            column.caption("PASS" if passed else "FAIL")

    failed = [check.label for check in evaluation.checks if not check.passed]
    if failed:
        st.error("Fails: " + ", ".join(failed))
    else:
        st.success("Passes every limit")

    if metrics.air_time > 0:
        contact = (
            f"tire in the air {metrics.air_time * 1000:.1f} ms "
            f"(limit {case.limits.max_air_time * 1000:.1f} ms)"
        )
    else:
        contact = (
            f"tire stays on the ground, lowest load {metrics.min_contact_force:.0f} N "
            f"({metrics.max_tire_load_loss * 100:.0f}% lost)"
        )
    st.caption(f"Score {evaluation.score.total:.3f}  |  {contact}")


def _ranking_rows(sweep):
    ranked = sweep.ranked()
    rows = []
    for rank, point in enumerate(ranked, start=1):
        evaluation = point.evaluation
        metrics = evaluation.metrics
        row = {
            "#": rank,
            "result": "pass" if evaluation.feasible else "fail",
            "score": f"{evaluation.score.total:.3f}",
        }
        row.update({
            axis.spec.name: axis.spec.format(value)
            for axis, value in zip(sweep.axes, point.values)
        })
        row.update({
            "comp mm": f"{metrics.max_compression * 1000:.1f}",
            "reb mm": f"{metrics.max_rebound * 1000:.1f}",
            "min RH mm": f"{metrics.min_ride_height * 1000:.1f}",
            "accel g": f"{metrics.max_body_acceleration / GRAVITY:.2f}",
            "load lost %": f"{metrics.max_tire_load_loss * 100:.0f}",
            "air ms": f"{metrics.air_time * 1000:.1f}",
        })
        rows.append(row)
    return ranked, rows


def _render_sweep_view(sweep):
    if sweep is None or not sweep.points:
        fig = plt.figure(figsize=(10, 4))
        plotting.plot_message(fig, "Set sweep ranges and run a sweep to see this view.")
        st.pyplot(fig, use_container_width=True)
        plt.close(fig)
        return

    axis_names = [axis.spec.name for axis in sweep.axes]
    version = st.session_state["sweep_version"]
    map_cols = st.columns(2)
    x_axis = map_cols[0].selectbox("Score map x axis", range(len(axis_names)),
                                   format_func=lambda index: axis_names[index],
                                   key=f"map_x_{version}")
    if len(axis_names) > 1:
        default_y = 1 if x_axis == 0 else 0
        y_axis = map_cols[1].selectbox(
            "Score map y axis",
            range(len(axis_names)),
            index=default_y,
            format_func=lambda index: axis_names[index],
            key=f"map_y_{version}",
        )
        if x_axis == y_axis:
            y_axis = next(index for index in range(len(axis_names)) if index != x_axis)
    else:
        y_axis = None
        map_cols[1].caption("Only one variable was swept; showing a score line.")

    fig = plt.figure(figsize=(11, 5), constrained_layout=True)
    try:
        plotting.plot_sweep(fig, sweep, x_axis, y_axis)
        st.pyplot(fig, use_container_width=True)
    except ValueError as error:
        st.error(f"Cannot draw this view: {error}")
    finally:
        plt.close(fig)

    ranked, rows = _ranking_rows(sweep)
    if ranked:
        options = list(range(len(ranked)))
        selected = st.selectbox(
            "Choose a setup from the chart",
            options,
            format_func=lambda index: (
                f"#{index + 1}  "
                + " | ".join(_format_axis(axis, value)
                             for axis, value in zip(sweep.axes, ranked[index].values))
            ),
            key=f"chart_point_{version}",
        )
        point = ranked[selected]
        if point.evaluation is not None:
            metrics = point.evaluation.metrics
            st.caption(
                f"Score {point.evaluation.score.total:.3f} | "
                f"{'passes' if point.feasible else 'fails a limit'} | "
                f"accel {metrics.max_body_acceleration / GRAVITY:.2f} g | "
                f"load lost {metrics.max_tire_load_loss * 100:.0f}% | "
                f"compression {metrics.max_compression * 1000:.1f} mm"
            )
            st.button(
                "Load selected setup and simulate",
                key="load_chart_point",
                on_click=_load_case,
                args=(point.evaluation.case,),
            )

    best = sweep.best()
    if best is not None:
        valid = sum(point.evaluation is not None for point in sweep.points)
        header = [f"Best of {valid} setups ({sweep.feasible_count} pass)"]
        extra = [
            _format_axis(axis, value)
            for axis, value in zip(sweep.axes, best.values)
            if axis.key not in ("motion_ratio", "spring_rate")
        ]
        if extra:
            header.append(", ".join(extra))
        if not best.feasible:
            header.append("No setup passes every limit; this one misses by the least.")
        edges = [
            f"{axis.spec.name} ({'low' if best.index[index] == 0 else 'high'})"
            for index, axis in enumerate(sweep.axes)
            if len(sweep.grids[index]) >= 3
            and best.index[index] in (0, len(sweep.grids[index]) - 1)
        ]
        if edges:
            header.append(f"Best is at the range edge for {', '.join(edges)}; widen it.")
        st.caption("  |  ".join(header))


def _export_sweep(sweep):
    ranked = sweep.ranked()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    header = ["rank", "passes", "score"]
    header += [f"{axis.spec.label} ({axis.spec.unit})" for axis in sweep.axes]
    header += [
        "compression (mm)", "rebound (mm)", "min ride height (mm)",
        "peak body accel (g)", "rms body accel (g)", "tire load lost (%)",
        "min tire load (N)", "air time (ms)",
        "peak damper speed comp (m/s)", "peak damper speed reb (m/s)",
        "failed limits",
    ]
    header += [f"score term: {label}" for label in SCORE_TERMS.values()]
    writer.writerow(header)

    for rank, point in enumerate(ranked, start=1):
        evaluation = point.evaluation
        metrics = evaluation.metrics
        row = [rank, evaluation.feasible, round(evaluation.score.total, 5)]
        row += [axis.spec.format(value) for axis, value in zip(sweep.axes, point.values)]
        row += [
            round(metrics.max_compression * 1000, 3),
            round(metrics.max_rebound * 1000, 3),
            round(metrics.min_ride_height * 1000, 3),
            round(metrics.max_body_acceleration / GRAVITY, 4),
            round(metrics.rms_body_acceleration / GRAVITY, 4),
            round(metrics.max_tire_load_loss * 100, 2),
            round(metrics.min_contact_force, 1),
            round(metrics.air_time * 1000, 2),
            round(metrics.max_damper_speed_compression, 4),
            round(metrics.max_damper_speed_rebound, 4),
            "; ".join(check.label for check in evaluation.checks if not check.passed),
        ]
        row += [round(evaluation.score.terms[name], 4) for name in SCORE_TERMS]
        writer.writerow(row)
    return output.getvalue()


def _handle_loaded_case():
    if not st.session_state.get("run_after_load"):
        return
    st.session_state["run_after_load"] = False
    case, errors = _case_from_state()
    if errors:
        st.session_state["load_error"] = "; ".join(errors.values())
        return
    try:
        with st.spinner("Running simulation for the selected setup..."):
            evaluation = evaluate_design(case)
    except Exception as error:
        st.session_state["load_error"] = f"{type(error).__name__}: {error}"
        return
    st.session_state["last_evaluation"] = evaluation
    st.session_state["result_source_case"] = case


def _render_ranking(sweep):
    if sweep is None:
        st.info("Run a sweep first to see the ranking.")
        return
    ranked, rows = _ranking_rows(sweep)
    if not rows:
        st.info("No sweep setups could be run.")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)
    skipped = sum(point.evaluation is None for point in sweep.points)
    note = f"{len(ranked)} setups, {sweep.feasible_count} pass"
    if skipped:
        note += f", {skipped} could not run (invalid road size)"
    st.caption(note)
    selected = st.selectbox(
        "Setup to load",
        range(len(ranked)),
        format_func=lambda index: (
            f"#{index + 1}  "
            + " | ".join(_format_axis(axis, value)
                         for axis, value in zip(sweep.axes, ranked[index].values))
        ),
        key=f"ranking_point_{st.session_state['sweep_version']}",
    )
    st.button(
        "Load selected setup and simulate",
        key="load_ranking_point",
        on_click=_load_case,
        args=(ranked[selected].evaluation.case,),
    )
    st.download_button(
        "Export CSV",
        data=_export_sweep(sweep),
        file_name="sweep_results.csv",
        mime="text/csv",
    )


def main():
    _init_state()
    _handle_loaded_case()
    _apply_theme()
    st.title("FSAE quarter-car suspension design tool")

    if st.session_state.get("load_error"):
        st.error(st.session_state.pop("load_error"))
    if st.session_state.get("sweep_error"):
        st.error(f"Sweep failed: {st.session_state.pop('sweep_error')}")

    case, errors = _case_from_state()
    left, right = st.columns([0.26, 0.74], gap="small")

    with left:
        with st.container(border=True):
            st.markdown("<h3 style='text-align:center'>parameters</h3>", unsafe_allow_html=True)
            _render_parameters(case, errors)
            actions = st.columns(3)
            run_clicked = actions[0].button(
                "Run simulation",
                key="run_simulation",
                disabled=st.session_state["sweep_active"],
                use_container_width=True,
            )
            sweep_clicked = actions[1].button(
                "Run sweep",
                key="run_sweep",
                disabled=st.session_state["sweep_active"],
                use_container_width=True,
            )
            actions[2].button(
                "Reset",
                key="reset",
                on_click=_reset,
                disabled=st.session_state["sweep_active"],
                use_container_width=True,
            )

            axes, sweep_errors = _read_sweep_axes()
            if sweep_clicked:
                if errors:
                    st.error("Check the setup inputs: " + "; ".join(errors.values()))
                elif sweep_errors or not axes:
                    st.error("; ".join(sweep_errors) if sweep_errors else
                             "Check at least one variable on the sweep tab.")
                else:
                    total = sweep_size(axes)
                    if total > CONFIRM_RUNS and not st.session_state["allow_large_sweep"]:
                        st.warning(
                            f"This sweep has {total} setups. Check the box below to confirm "
                            "before running it."
                        )
                    else:
                        _start_sweep(case, axes)
            if run_clicked:
                if errors:
                    st.error("Check the setup inputs: " + "; ".join(errors.values()))
                else:
                    try:
                        with st.spinner("Running simulation..."):
                            evaluation = evaluate_design(case)
                        st.session_state["last_evaluation"] = evaluation
                        st.session_state["result_source_case"] = case
                        st.session_state["view"] = "response"
                    except Exception as error:
                        st.error(f"Simulation failed: {type(error).__name__}: {error}")
            if sweep_size(axes) > CONFIRM_RUNS:
                st.checkbox("I understand this sweep may take a while", key="allow_large_sweep")
            if st.session_state["sweep_active"]:
                _sweep_monitor()

    with right:
        with st.container(border=True):
            top_bar = st.columns([1, 1, 2])
            top_bar[0].caption("live preview of the inputs")
            top_bar[1].markdown("<h3 style='text-align:center'>the road</h3>",
                                unsafe_allow_html=True)
            view_cols = top_bar[2].columns(len(VIEWS))
            for column, name in zip(view_cols, VIEWS):
                column.button(
                    name,
                    key=f"view_{name}",
                    type="primary" if st.session_state["view"] == name else "secondary",
                    on_click=_set_view,
                    args=(name,),
                    use_container_width=True,
                )
            view = st.session_state["view"]
            previous_case = st.session_state.get("result_source_case")
            if previous_case is not None and case != previous_case:
                st.warning("Inputs changed since these results.")

            if view == "road":
                fig = plt.figure(figsize=(11, 5), constrained_layout=True)
                try:
                    if errors:
                        plotting.plot_message(fig, "Fix the setup inputs to preview this road.")
                    else:
                        plotting.plot_road(fig, case)
                    st.pyplot(fig, use_container_width=True)
                except ValueError as error:
                    st.error(f"Cannot draw this view: {error}")
                finally:
                    plt.close(fig)
            elif view == "response":
                evaluation = st.session_state.get("last_evaluation")
                fig = plt.figure(figsize=(11, 5), constrained_layout=True)
                if evaluation is None:
                    plotting.plot_message(fig, "Run a simulation to see the time response.")
                else:
                    plotting.plot_response(fig, evaluation)
                st.pyplot(fig, use_container_width=True)
                plt.close(fig)
            elif view == "sweep":
                _render_sweep_view(st.session_state.get("last_sweep"))
            else:
                _render_ranking(st.session_state.get("last_sweep"))

        with st.container(border=True):
            _render_road_cards()

        with st.container(border=True):
            _render_results(st.session_state.get("last_evaluation"))
            evaluation = st.session_state.get("last_evaluation")
            if evaluation is not None:
                metrics = evaluation.metrics
                csv_data = (
                    "metric,value\n"
                    f"max body accel (g),{metrics.max_body_acceleration / GRAVITY:.6f}\n"
                    f"max tire load loss (%),{metrics.max_tire_load_loss * 100:.6f}\n"
                    f"max compression (mm),{metrics.max_compression * 1000:.6f}\n"
                    f"max rebound (mm),{metrics.max_rebound * 1000:.6f}\n"
                )
                st.download_button(
                    "Download metrics CSV", csv_data, file_name="metrics.csv",
                    mime="text/csv",
                )


if __name__ == "__main__":
    main()
