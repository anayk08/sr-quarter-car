import csv
import io
import math

import matplotlib
import matplotlib.pyplot as plt
import streamlit as st

from quartercar.config import (
    GRAVITY,
    KPH_TO_M_S,
    LBF_IN_TO_N_M,
    DesignCase,
    DesignLimits,
    RoadParams,
    ScoreWeights,
    SimSettings,
    with_value,
)
from quartercar.parameters import (
    DEFAULT_SWEEP_ROWS,
    DERIVED,
    DAMPING_SCALE,
    PARAMETERS,
    PARAMETER_BY_KEY,
    SECTIONS,
    SWEEP_VARIABLES,
)
from quartercar.road import PROFILE_DEFAULTS, ROAD_PROFILES, make_road
from quartercar.sweep import evaluate_design, run_sweep, sweep_size
from quartercar import plotting

matplotlib.use("Agg")


st.set_page_config(page_title="FSAE quarter-car sim", layout="wide")


def apply_spec_value(case, spec, display_value):
    value = spec.from_display(display_value)
    return spec.set(case, value)


def current_case():
    if "case" not in st.session_state:
        st.session_state.case = DesignCase()
    return st.session_state.case


def rebuild_case_from_form():
    case = current_case()
    for spec in PARAMETERS:
        if not spec.applies_to(case.road.profile):
            continue
        key = f"param_{spec.key}"
        if key in st.session_state:
            case = apply_spec_value(case, spec, float(st.session_state[key]))
    case = with_value(case, ("road", "profile"), case.road.profile)
    if "selected_profile" in st.session_state:
        case = with_value(case, ("road", "profile"), st.session_state.selected_profile)
    st.session_state.case = case
    return case


def update_profile(profile):
    case = current_case()
    case = with_value(case, ("road", "profile"), profile)
    for key, value in PROFILE_DEFAULTS.get(profile, {}).items():
        if key in [spec.key for spec in PARAMETERS]:
            spec = PARAMETER_BY_KEY[key]
            if spec.applies_to(profile):
                case = spec.set(case, value)
    st.session_state.selected_profile = profile
    st.session_state.case = case


def run_single_case(case):
    evaluation = evaluate_design(case)
    return evaluation


def render_profile_cards():
    cols = st.columns(2)
    for i, profile in enumerate(ROAD_PROFILES):
        with cols[i % 2]:
            label = profile
            selected = st.session_state.get("selected_profile", "bump") == profile
            if st.button(label, key=f"road_{profile}", use_container_width=True):
                update_profile(profile)
            elif selected:
                st.markdown("<div style='padding:4px 0 0 0;'></div>", unsafe_allow_html=True)


def render_setup_tab(case):
    for section in SECTIONS:
        st.markdown(f"### {section}")
        values = []
        for spec in PARAMETERS:
            if spec.section != section:
                continue
            if not spec.applies_to(case.road.profile):
                continue
            key = f"param_{spec.key}"
            display = spec.to_display(spec.get(case))
            default = float(display)
            value = st.number_input(
                spec.label,
                value=default,
                min_value=spec.minimum,
                max_value=spec.maximum,
                step=(10 ** (-spec.decimals)) if spec.decimals > 0 else 1,
                format=f"%.{spec.decimals}f" if spec.decimals > 0 else "%d",
                key=key,
                help=spec.help or None,
            )
            values.append((spec, value))
        st.markdown("---")
        for spec in DERIVED:
            if spec.section != section:
                continue
            if not spec.applies_to(case.road.profile):
                continue
            try:
                text = spec.text(case)
            except Exception:
                text = "-"
            st.caption(f"{spec.label}: {text}")
        st.write("")


def render_sweep_tab(case):
    st.caption("Every combination of the ticked variables is evaluated. Anything not swept keeps the setup value.")
    selected = []
    for index, (key, enabled) in enumerate(DEFAULT_SWEEP_ROWS):
        spec = SWEEP_VARIABLES[key]
        enabled_key = f"sweep_enabled_{key}"
        if enabled_key not in st.session_state:
            st.session_state[enabled_key] = enabled
        on = st.checkbox(spec.label, value=st.session_state[enabled_key], key=enabled_key)
        if on:
            selected.append((spec, key))
            st.write("")
            c1, c2, c3 = st.columns(3)
            start, stop, step = spec.sweep_range
            s = c1.number_input(f"{spec.label} start", value=float(start), key=f"sweep_{key}_start")
            t = c2.number_input(f"{spec.label} stop", value=float(stop), key=f"sweep_{key}_stop")
            u = c3.number_input(f"{spec.label} step", value=float(step), key=f"sweep_{key}_step")
            selected[-1] = (spec, key, s, t, u)
    st.write("")
    st.caption("Big sweeps use multiprocessing for speed.")
    return selected


def draw_case_diagnostics(case):
    corner = case.corner
    metrics = evaluate_design(case, keep_history=False).metrics
    st.subheader("results")
    cols = st.columns(5)
    values = [
        ("motion ratio", f"{corner.motion_ratio:.3f}", "spring / wheel travel"),
        ("spring rate", f"{corner.spring_rate / LBF_IN_TO_N_M:.0f} lbf/in", f"wheel {corner.wheel_rate / LBF_IN_TO_N_M:.0f} lbf/in"),
        ("min ride height", f"{metrics.min_ride_height * 1000:.1f} mm", f"limit {case.limits.min_ride_height * 1000:.1f} mm"),
        ("max travel", f"{metrics.max_compression * 1000:.1f} / {metrics.max_rebound * 1000:.1f} mm", f"limit {case.limits.max_compression * 1000:.1f} / {case.limits.max_rebound * 1000:.1f} mm"),
        ("max body accel", f"{metrics.max_body_acceleration / GRAVITY:.2f} g", f"limit {case.limits.max_body_acceleration / GRAVITY:.2f} g"),
    ]
    for col, (name, val, detail) in zip(cols, values):
        col.markdown(
            f"<div style='padding:10px; border:1px solid #222; border-radius:8px; background:#f5f5f5; height:120px'>"
            f"<div style='font-size:12px; color:#4a4a48'>{name}</div>"
            f"<div style='font-size:28px; font-weight:600; margin-top:10px'>{val}</div>"
            f"<div style='font-size:12px; color:#4a4a48; margin-top:8px'>{detail}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )


def render_results(case, evaluation):
    st.subheader("results")
    metrics = evaluation.metrics
    checks = {check.key: check for check in evaluation.checks}
    cols = st.columns(5)
    cells = [
        ("motion ratio", f"{case.corner.motion_ratio:.3f}", "spring / wheel travel"),
        ("spring rate", f"{case.corner.spring_rate / LBF_IN_TO_N_M:.0f} lbf/in", f"wheel {case.corner.wheel_rate / LBF_IN_TO_N_M:.0f} lbf/in"),
        ("ride height", f"{metrics.min_ride_height * 1000:.1f} mm", f"limit {case.limits.min_ride_height * 1000:.1f} mm", checks["ride_height"].passed),
        ("travel", f"{metrics.max_compression * 1000:.1f} / {metrics.max_rebound * 1000:.1f} mm", f"limit {case.limits.max_compression * 1000:.1f} / {case.limits.max_rebound * 1000:.1f} mm", checks["compression"].passed and checks["rebound"].passed),
        ("acceleration", f"{metrics.max_body_acceleration / GRAVITY:.2f} g", f"limit {case.limits.max_body_acceleration / GRAVITY:.2f} g", checks["body_acceleration"].passed),
    ]

    for col, item in zip(cols, cells):
        name, value, detail = item[:3]
        passed = item[3] if len(item) == 4 else None
        color = "#006300" if passed is True else "#b3261e" if passed is False else "#4a4a48"
        mark = "✓ " if passed is True else "✗ " if passed is False else ""
        col.markdown(
            f"<div style='padding:10px; border:1px solid #222; border-radius:8px; background:#f5f5f5; height:120px'>"
            f"<div style='font-size:12px; color:#4a4a48'>{name}</div>"
            f"<div style='font-size:28px; font-weight:600; margin-top:10px; color:{color}'>{mark}{value}</div>"
            f"<div style='font-size:12px; color:#4a4a48; margin-top:8px'>{detail}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    failed = [check.label for check in evaluation.checks if not check.passed]
    st.markdown(
        f"<div style='margin-top:18px; font-size:18px; font-weight:600; color:{'#006300' if not failed else '#b3261e'}'>"
        f"{'✓ passes every limit' if not failed else '✗ fails: ' + ', '.join(failed)}"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.caption(f"score {evaluation.score.total:.3f}  |  {('tire in the air ' + str(metrics.air_time * 1000) + ' ms') if metrics.air_time > 0 else 'tire stays on the ground'}")


def render_plots(case, evaluation=None, sweep=None):
    if evaluation is not None:
        fig = plt.figure(figsize=(10, 5), constrained_layout=True)
        plotting.plot_response(fig, evaluation)
        st.pyplot(fig)
    else:
        fig = plt.figure(figsize=(10, 5), constrained_layout=True)
        plotting.plot_road(fig, case)
        st.pyplot(fig)


def run_app():
    if "case" not in st.session_state:
        st.session_state.case = DesignCase()
        st.session_state.selected_profile = "bump"

    case = current_case()

    st.title("FSAE quarter-car suspension design tool")

    left, right = st.columns([0.9, 1.9])

    with left:
        tabs = st.tabs(["setup", "sweep"])
        with tabs[0]:
            render_setup_tab(case)
        with tabs[1]:
            render_sweep_tab(case)

        if st.button("run simulation", use_container_width=True):
            case = rebuild_case_from_form()
            evaluation = run_single_case(case)
            st.session_state.evaluation = evaluation
            st.session_state.view = "response"
            st.rerun()

        if st.button("run sweep", use_container_width=True):
            case = rebuild_case_from_form()
            axes = []
            for row in DEFAULT_SWEEP_ROWS:
                key, enabled = row
                state_key = f"sweep_enabled_{key}"
                if st.session_state.get(state_key, enabled):
                    spec = SWEEP_VARIABLES[key]
                    start = st.session_state.get(f"sweep_{key}_start", spec.sweep_range[0])
                    stop = st.session_state.get(f"sweep_{key}_stop", spec.sweep_range[1])
                    step = st.session_state.get(f"sweep_{key}_step", spec.sweep_range[2])
                    axis = spec.set(case, spec.from_display(start))
                    axes.append(type("Axis", (), {"key": key, "start": spec.from_display(start), "stop": spec.from_display(stop), "step": spec.from_display(step), "spec": spec})())
            # rebuild axis objects in the correct format for the sweep engine
            real_axes = []
            for row in DEFAULT_SWEEP_ROWS:
                key, enabled = row
                state_key = f"sweep_enabled_{key}"
                if st.session_state.get(state_key, enabled):
                    spec = SWEEP_VARIABLES[key]
                    start = st.session_state.get(f"sweep_{key}_start", spec.sweep_range[0])
                    stop = st.session_state.get(f"sweep_{key}_stop", spec.sweep_range[1])
                    step = st.session_state.get(f"sweep_{key}_step", spec.sweep_range[2])
                    real_axes.append(type("SweepAxis", (), {"key": key, "start": spec.from_display(start), "stop": spec.from_display(stop), "step": spec.from_display(step), "spec": spec, "values": lambda self: None})())
            # correct axis handling
            real_axes = []
            for row in DEFAULT_SWEEP_ROWS:
                key, enabled = row
                if not st.session_state.get(f"sweep_enabled_{key}", enabled):
                    continue
                spec = SWEEP_VARIABLES[key]
                start = st.session_state.get(f"sweep_{key}_start", spec.sweep_range[0])
                stop = st.session_state.get(f"sweep_{key}_stop", spec.sweep_range[1])
                step = st.session_state.get(f"sweep_{key}_step", spec.sweep_range[2])
                from quartercar.sweep import SweepAxis
                real_axes.append(SweepAxis(key, spec.from_display(start), spec.from_display(stop), spec.from_display(step)))
            if real_axes:
                result = run_sweep(case, real_axes)
                st.session_state.sweep = result
                st.session_state.evaluation = result.best().evaluation if result.best() else None
                st.session_state.view = "sweep"
                st.rerun()

    with right:
        profile_cols = st.columns(4)
        for idx, profile in enumerate(ROAD_PROFILES):
            with profile_cols[idx]:
                if st.button(profile, key=f"profile_{profile}", use_container_width=True):
                    update_profile(profile)
                    st.rerun()

        st.write("")

        if "evaluation" in st.session_state:
            render_results(case, st.session_state.evaluation)
        else:
            fig = plt.figure(figsize=(10, 5), constrained_layout=True)
            plotting.plot_road(fig, case)
            st.pyplot(fig)

        st.markdown("---")
        tabs = st.tabs(["road", "response", "sweep", "ranking"])
        with tabs[0]:
            fig = plt.figure(figsize=(10, 5), constrained_layout=True)
            plotting.plot_road(fig, case)
            st.pyplot(fig)
        with tabs[1]:
            if "evaluation" in st.session_state:
                fig = plt.figure(figsize=(10, 5), constrained_layout=True)
                plotting.plot_response(fig, st.session_state.evaluation)
                st.pyplot(fig)
            else:
                st.info("Press run simulation to populate the time-response plot.")
        with tabs[2]:
            if "sweep" in st.session_state:
                fig = plt.figure(figsize=(10, 5), constrained_layout=True)
                try:
                    plotting.plot_sweep(fig, st.session_state.sweep, 0, 1)
                    st.pyplot(fig)
                except Exception as exc:
                    st.error(str(exc))
            else:
                st.info("Press run sweep to populate the score map and trade-off chart.")
        with tabs[3]:
            if "sweep" in st.session_state:
                ranked = st.session_state.sweep.ranked()
                rows = []
                for rank, point in enumerate(ranked, start=1):
                    eval_ = point.evaluation
                    rows.append({
                        "rank": rank,
                        "result": "pass" if eval_.feasible else "fail",
                        "score": f"{eval_.score.total:.3f}",
                        **{axis.spec.name: axis.spec.format(value) for axis, value in zip(st.session_state.sweep.axes, point.values)},
                    })
                st.dataframe(rows)
            else:
                st.info("Run a sweep to see ranked setups.")


if __name__ == "__main__":
    run_app()
