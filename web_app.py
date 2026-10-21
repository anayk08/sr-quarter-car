import io
import math

import matplotlib
import matplotlib.pyplot as plt
import streamlit as st

from quartercar import plotting
from quartercar.config import (
    DesignCase,
    DesignLimits,
    RoadParams,
    ScoreWeights,
    SimSettings,
    CornerParams,
    LBF_IN_TO_N_M,
    KPH_TO_M_S,
)
from quartercar.sweep import evaluate_design

matplotlib.use("Agg")


st.set_page_config(page_title="FSAE quarter-car suspension design tool", layout="wide")


def init_state():
    defaults = {
        "sprung_mass": 61.22,
        "unsprung_mass": 8.4354,
        "spring_lbf_in": 629.0,
        "motion_ratio": 0.75,
        "tire_lbf_in": 493.0,
        "damping_scale": 1.0,
        "profile": "bump",
        "height_mm": 12.7,
        "length_m": 0.30,
        "speed_kph": 50.0,
        "sample_rate": 2000.0,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

    st.session_state.setdefault("last_case", None)
    st.session_state.setdefault("last_evaluation", None)


def build_case():
    spring_rate = float(st.session_state["spring_lbf_in"]) * LBF_IN_TO_N_M
    tire_rate = float(st.session_state["tire_lbf_in"]) * LBF_IN_TO_N_M

    damper = CornerParams().damper
    scaled = type(damper)(
        LSC_ratio=damper.LSC_ratio * float(st.session_state["damping_scale"]),
        HSC_ratio=damper.HSC_ratio * float(st.session_state["damping_scale"]),
        LSR_ratio=damper.LSR_ratio * float(st.session_state["damping_scale"]),
        HSR_ratio=damper.HSR_ratio * float(st.session_state["damping_scale"]),
        knee_compression=damper.knee_compression,
        knee_rebound=damper.knee_rebound,
    )

    corner = CornerParams(
        sprung_mass=float(st.session_state["sprung_mass"]),
        unsprung_mass=float(st.session_state["unsprung_mass"]),
        spring_rate=spring_rate,
        motion_ratio=float(st.session_state["motion_ratio"]),
        tire_spring_rate=tire_rate,
        damper=scaled,
    )

    road = RoadParams(
        profile=str(st.session_state["profile"]),
        height=float(st.session_state["height_mm"]) / 1000.0,
        length=float(st.session_state["length_m"]),
        speed=float(st.session_state["speed_kph"]) * KPH_TO_M_S,
    )

    case = DesignCase(
        corner=corner,
        road=road,
        limits=DesignLimits(),
        weights=ScoreWeights(),
        sim=SimSettings(sample_rate=float(st.session_state["sample_rate"])),
    )

    st.session_state["last_case"] = case
    return case


def run_case():
    try:
        case = build_case()
        evaluation = evaluate_design(case)
        st.session_state["last_evaluation"] = evaluation
        return evaluation
    except Exception as exc:
        st.session_state["last_evaluation"] = None
        st.error(f"Simulation failed: {type(exc).__name__}: {exc}")
        return None


def render_summary_cards(case, evaluation):
    if evaluation is None:
        st.info("Run a simulation to view the results.")
        return

    metrics = evaluation.metrics
    checks = {check.key: check for check in evaluation.checks}

    cards = [
        (
            "body accel",
            f"{metrics.max_body_acceleration / 9.81:.2f} g",
            f"limit {case.limits.max_body_acceleration / 9.81:.2f} g",
            checks["body_acceleration"].passed,
        ),
        (
            "ride height",
            f"{metrics.min_ride_height * 1000:.1f} mm",
            f"limit {case.limits.min_ride_height * 1000:.1f} mm",
            checks["ride_height"].passed,
        ),
        (
            "travel",
            f"{metrics.max_compression * 1000:.1f} / {metrics.max_rebound * 1000:.1f} mm",
            f"limit {case.limits.max_compression * 1000:.1f} / {case.limits.max_rebound * 1000:.1f} mm",
            checks["compression"].passed and checks["rebound"].passed,
        ),
        (
            "tire load loss",
            f"{metrics.max_tire_load_loss * 100:.1f}%",
            "peak load lost",
            checks["contact"].passed,
        ),
    ]

    cols = st.columns(4)
    for col, (label, value, detail, passed) in zip(cols, cards):
        color = "#006300" if passed else "#b3261e" if passed is False else "#4a4a48"
        marker = "✓ " if passed is True else "✗ " if passed is False else ""
        col.markdown(
            f"<div style='padding:10px; border:1px solid #222; border-radius:8px; background:#f5f5f5; height:120px'>"
            f"<div style='font-size:12px; color:#4a4a48'>{label}</div>"
            f"<div style='font-size:28px; font-weight:600; margin-top:10px; color:{color}'>{marker}{value}</div>"
            f"<div style='font-size:12px; color:#4a4a48; margin-top:8px'>{detail}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    failed = [check.label for check in evaluation.checks if not check.passed]
    if failed:
        st.markdown(
            f"<div style='margin-top:16px; font-size:18px; font-weight:600; color:#b3261e'>✗ fails: {', '.join(failed)}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='margin-top:16px; font-size:18px; font-weight:600; color:#006300'>✓ passes every limit</div>",
            unsafe_allow_html=True,
        )

    st.caption(f"Score: {evaluation.score.total:.3f} | air time: {metrics.air_time * 1000:.1f} ms")


def render_plots(case, evaluation):
    if evaluation is None:
        fig = plt.figure(figsize=(11, 5), constrained_layout=True)
        plotting.plot_road(fig, case)
        st.pyplot(fig)
        return

    tabs = st.tabs(["road", "response"])
    with tabs[0]:
        fig = plt.figure(figsize=(11, 5), constrained_layout=True)
        plotting.plot_road(fig, case)
        st.pyplot(fig)
    with tabs[1]:
        fig = plt.figure(figsize=(11, 5), constrained_layout=True)
        plotting.plot_response(fig, evaluation)
        st.pyplot(fig)


def main():
    init_state()
    st.title("FSAE quarter-car suspension design tool")

    with st.sidebar:
        with st.form("sim_form"):
            st.header("Corner")
            st.number_input("sprung mass (kg)", key="sprung_mass", min_value=0.0, value=float(st.session_state["sprung_mass"]), step=0.01)
            st.number_input("unsprung mass (kg)", key="unsprung_mass", min_value=0.0, value=float(st.session_state["unsprung_mass"]), step=0.01)

            st.header("Spring / motion ratio")
            st.number_input("spring rate (lbf/in)", key="spring_lbf_in", min_value=0.0, value=float(st.session_state["spring_lbf_in"]), step=1.0)
            st.number_input("motion ratio", key="motion_ratio", min_value=0.0, value=float(st.session_state["motion_ratio"]), step=0.01)

            st.header("Tire")
            st.number_input("tire spring rate (lbf/in)", key="tire_lbf_in", min_value=0.0, value=float(st.session_state["tire_lbf_in"]), step=1.0)

            st.header("Damper")
            st.slider("damping scale", key="damping_scale", min_value=0.1, max_value=2.0, value=float(st.session_state["damping_scale"]), step=0.05)

            st.header("Road")
            st.selectbox("profile", options=("bump", "cone", "triangle", "rumble strip"), key="profile")
            st.number_input("feature height (mm)", key="height_mm", min_value=0.0, value=float(st.session_state["height_mm"]), step=0.1)
            st.number_input("feature length (m)", key="length_m", min_value=0.01, value=float(st.session_state["length_m"]), step=0.01)
            st.number_input("vehicle speed (km/h)", key="speed_kph", min_value=0.1, value=float(st.session_state["speed_kph"]), step=1.0)

            st.header("Simulation")
            st.number_input("sample rate (Hz)", key="sample_rate", min_value=10.0, value=float(st.session_state["sample_rate"]), step=10.0)

            st.write("")
            submitted = st.form_submit_button("Run simulation")

    if submitted:
        run_case()

    case = st.session_state.get("last_case") or build_case()
    evaluation = st.session_state.get("last_evaluation")

    render_summary_cards(case, evaluation)
    st.write("")
    render_plots(case, evaluation)

    if evaluation is not None:
        csv_buffer = io.StringIO()
        csv_buffer.write("metric,value\n")
        csv_buffer.write(f"max body accel (g),{evaluation.metrics.max_body_acceleration / 9.81:.6f}\n")
        csv_buffer.write(f"max tire load loss (%),{evaluation.metrics.max_tire_load_loss * 100:.6f}\n")
        csv_buffer.write(f"max compression (mm),{evaluation.metrics.max_compression * 1000:.6f}\n")
        csv_buffer.write(f"max rebound (mm),{evaluation.metrics.max_rebound * 1000:.6f}\n")
        st.download_button("Download metrics CSV", data=csv_buffer.getvalue(), file_name="metrics.csv", mime="text/csv")


if __name__ == "__main__":
    main()
