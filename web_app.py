import io
import matplotlib
matplotlib.use("Agg")

import streamlit as st
import matplotlib.pyplot as plt

from quartercar.config import (
    DesignCase, CornerParams, RoadParams, DesignLimits, ScoreWeights, SimSettings,
    LBF_IN_TO_N_M, KPH_TO_M_S,
)
from quartercar.sweep import evaluate_design
from quartercar import plotting


st.set_page_config(page_title="Quarter-car (web)", layout="wide")

st.title("fsae quarter-car sim")

# Sidebar: basic inputs (a small but useful subset)
st.sidebar.header("Corner (sprung / unsprung)")
sprung_mass = st.sidebar.number_input("sprung mass (kg)", value=61.22, format="%.3f")
unsprung_mass = st.sidebar.number_input("unsprung mass (kg)", value=8.4354, format="%.3f")

st.sidebar.header("Spring & motion ratio")
spring_lbf_in = st.sidebar.number_input("spring rate (lbf/in)", value=629.0, format="%.3f")
motion_ratio = st.sidebar.number_input("motion ratio (spring travel / wheel travel)", value=0.75, format="%.3f")

st.sidebar.header("Tire")
tire_lbf_in = st.sidebar.number_input("tire spring rate (lbf/in)", value=493.0, format="%.3f")

st.sidebar.header("Damper (knee speeds and ratios)")
damping_scale = st.sidebar.slider("damping scale (multiplies damper ratios)", 0.1, 2.0, 1.0, 0.05)

st.sidebar.header("Road")
profile = st.sidebar.selectbox("profile", options=("bump", "cone", "triangle", "rumble strip"))
height_mm = st.sidebar.number_input("feature height (mm)", value=12.7, format="%.3f")
length_m = st.sidebar.number_input("feature length (m)", value=0.30, format="%.3f")
speed_kph = st.sidebar.number_input("vehicle speed (km/h)", value=50.0, format="%.3f")

st.sidebar.header("Simulation")
sample_rate = st.sidebar.number_input("sample rate (Hz)", value=2000.0)

run = st.button("Run simulation")

st.markdown("---")

if run:
    spring_rate = float(spring_lbf_in) * LBF_IN_TO_N_M
    tire_rate = float(tire_lbf_in) * LBF_IN_TO_N_M
    road_height = float(height_mm) / 1000.0

    road = RoadParams(
        profile=profile if profile != "rumble strip" else "rumble strip",
        height=road_height,
        length=float(length_m),
        speed=float(speed_kph) * KPH_TO_M_S,
    )

    corner = CornerParams(
        sprung_mass=float(sprung_mass),
        unsprung_mass=float(unsprung_mass),
        spring_rate=spring_rate,
        motion_ratio=float(motion_ratio),
        tire_spring_rate=tire_rate,
    )

    damper = corner.damper
    scaled_damper = type(damper)(
        LSC_ratio=damper.LSC_ratio * damping_scale,
        HSC_ratio=damper.HSC_ratio * damping_scale,
        LSR_ratio=damper.LSR_ratio * damping_scale,
        HSR_ratio=damper.HSR_ratio * damping_scale,
        knee_compression=damper.knee_compression,
        knee_rebound=damper.knee_rebound,
    )
    corner = CornerParams(
        sprung_mass=corner.sprung_mass,
        unsprung_mass=corner.unsprung_mass,
        spring_rate=corner.spring_rate,
        motion_ratio=corner.motion_ratio,
        tire_spring_rate=corner.tire_spring_rate,
        damper=scaled_damper,
        static_ride_height=corner.static_ride_height,
        aero_load=corner.aero_load,
    )

    case = DesignCase(
        corner=corner,
        road=road,
        limits=DesignLimits(),
        weights=ScoreWeights(),
        sim=SimSettings(sample_rate=float(sample_rate)),
    )

    st.info("Running simulation (this may take a second)...")

    try:
        evaluation = evaluate_design(case)

        fig = plt.Figure(figsize=(10, 5), dpi=100)
        plotting.plot_response(fig, evaluation)

        st.pyplot(fig)

        verdict = "passes every limit ✅" if evaluation.feasible else "fails a limit ✗"
        st.markdown(f"**Verdict:** {verdict}")
        st.markdown(f"**Score:** {evaluation.score.total:.3f}")

        import csv
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["metric", "value"])
        writer.writerow(["max body accel (g)", evaluation.metrics.max_body_acceleration / 9.81])
        writer.writerow(["max tire load loss (%)", evaluation.metrics.max_tire_load_loss * 100])
        writer.writerow(["max compression (mm)", evaluation.metrics.max_compression * 1000])
        writer.writerow(["max rebound (mm)", evaluation.metrics.max_rebound * 1000])

        st.download_button("Download metrics CSV", data=buf.getvalue(), file_name="metrics.csv", mime="text/csv")

    except Exception as e:
        st.error(f"Simulation failed: {type(e).__name__}: {e}")

else:
    st.info("Adjust parameters in the sidebar and press Run simulation. For larger sweeps use the desktop app or ask for a sweep page.")
