import io
import sys
from typing import Dict

import matplotlib
import matplotlib.pyplot as plt
import streamlit as st

matplotlib.use("Agg")

from quartercar.config import (
    DesignCase,
    CornerParams,
    DesignLimits,
    RoadParams,
    ScoreWeights,
    SimSettings,
    LBF_IN_TO_N_M,
    KPH_TO_M_S,
)
from quartercar import plotting
from quartercar.sweep import evaluate_design


st.set_page_config(page_title="Quarter-car design tool", layout="wide")

# ---- Styling to mimic the desktop app -----------------
CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    html, body, [data-testid="stAppViewContainer"] {
        background: #efefee;
        font-family: 'Inter', sans-serif;
    }

    .app-shell {
        background: #efefee;
        padding: 0;
    }

    .panel {
        background: #f6f5f4;
        border: 1px solid #d8d6d2;
        border-radius: 10px;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.8);
        padding: 12px 12px 8px 12px;
    }

    .left-panel {
        background: #f4f3f2;
        border: 1px solid #d4d2cf;
        border-radius: 10px;
        padding: 10px;
        min-height: 760px;
    }

    .right-panel {
        background: #f4f3f2;
        border: 1px solid #d4d2cf;
        border-radius: 10px;
        padding: 10px;
        min-height: 760px;
    }

    .soft-button {
        background: #e9e8e7 !important;
        border: 1px solid #d1d0ce !important;
        border-radius: 8px !important;
        color: #1b1b1b !important;
        font-weight: 600 !important;
        padding: 0.45rem 0.8rem !important;
    }

    .tile {
        background: #f2f1ef;
        border: 1px solid #cfcac5;
        border-radius: 8px;
        padding: 8px 10px;
        margin: 6px 0;
        text-align: center;
        cursor: pointer;
        color: #1f1f1f;
        font-weight: 600;
    }

    .tile.active {
        background: #dfeaf8;
        border-color: #a8c7f3;
    }

    .metric-box {
        background: #f4f3f2;
        border: 1px solid #d4d2cf;
        border-radius: 8px;
        padding: 10px 12px;
        min-height: 92px;
    }

    .metric-box h4 {
        margin: 0 0 6px 0;
        font-size: 0.8rem;
        font-weight: 600;
        color: #4d4a46;
    }

    .metric-box .value {
        font-size: 1.4rem;
        font-weight: 700;
        color: #1b1b1b;
    }

    .metric-box .sub {
        color: #66625d;
        font-size: 0.78rem;
    }

    div[data-testid="stSidebar"] {
        background: #f0efee;
    }

    section[data-testid="stSidebar"] > div {
        padding: 0.5rem 0.8rem;
    }

    .stSelectbox, .stNumberInput, .stSlider {
        background: #f8f7f6;
    }

    .stButton > button {
        background: #e9e8e7;
        border: 1px solid #d0d0ce;
        color: #1a1c1d;
        border-radius: 8px;
        font-weight: 600;
    }

    .stTabs [role="tablist"] {
        gap: 0.25rem;
    }

    .stTabs [role="tab"] {
        background: transparent;
        border: 1px solid transparent;
        border-radius: 8px 8px 0 0;
        padding: 0.55rem 1rem;
        color: #45413c;
    }

    .stTabs [role="tab"][aria-selected="true"] {
        background: #e9f0fb;
        border-color: #bdd0ee;
        color: #1a1d20;
        font-weight: 600;
    }
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


# --------- Helpers ------------------------------------------------------------------
def build_case_from_state() -> DesignCase:
    """Build the main DesignCase from the form values."""
    spring_rate = float(st.session_state["spring_lbf_in"]) * LBF_IN_TO_N_M
    tire_rate = float(st.session_state["tire_lbf_in"]) * LBF_IN_TO_N_M
    road_height = float(st.session_state["road_height_mm"]) / 1000.0

    road = RoadParams(
        profile=st.session_state["road_profile"],
        height=road_height,
        length=float(st.session_state["road_length_m"]),
        speed=float(st.session_state["road_speed_kph"]) * KPH_TO_M_S,
    )

    corner = CornerParams(
        sprung_mass=float(st.session_state["sprung_mass"]),
        unsprung_mass=float(st.session_state["unsprung_mass"]),
        spring_rate=spring_rate,
        motion_ratio=float(st.session_state["motion_ratio"]),
        tire_spring_rate=tire_rate,
        static_ride_height=0.030,
    )

    # Apply a simplified damping-scale multiplier to the default damper ratios.
    damper = corner.damper
    damper_scaled = type(damper)(
        LSC_ratio=damper.LSC_ratio * float(st.session_state["damping_scale"]),
        HSC_ratio=damper.HSC_ratio * float(st.session_state["damping_scale"]),
        LSR_ratio=damper.LSR_ratio * float(st.session_state["damping_scale"]),
        HSR_ratio=damper.HSR_ratio * float(st.session_state["damping_scale"]),
        knee_compression=damper.knee_compression,
        knee_rebound=damper.knee_rebound,
    )

    corner = CornerParams(
        sprung_mass=corner.sprung_mass,
        unsprung_mass=corner.unsprung_mass,
        spring_rate=corner.spring_rate,
        motion_ratio=corner.motion_ratio,
        tire_spring_rate=corner.tire_spring_rate,
        damper=damper_scaled,
        static_ride_height=corner.static_ride_height,
        aero_load=corner.aero_load,
    )

    return DesignCase(
        corner=corner,
        road=road,
        limits=DesignLimits(),
        weights=ScoreWeights(),
        sim=SimSettings(sample_rate=float(st.session_state["sample_rate"])),
    )


# --------- Defaults -----------------------------------------------------------------
def init_state():
    defaults = {
        "tab": "setup",
        "view": "road",
        "sprung_mass": 61.22,
        "unsprung_mass": 8.4354,
        "spring_lbf_in": 629.0,
        "motion_ratio": 0.75,
        "tire_lbf_in": 493.0,
        "damping_scale": 1.0,
        "road_profile": "bump",
        "road_height_mm": 12.7,
        "road_length_m": 0.30,
        "road_speed_kph": 50.0,
        "sample_rate": 2000.0,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


init_state()

# --------- Layout -------------------------------------------------------------------
left_col, right_col = st.columns([0.42, 0.58])

# ---------- Left column ---------------------------------------------------------------
with left_col:
    st.markdown('<div class="left-panel">', unsafe_allow_html=True)
    tab_choice = st.radio("", ["setup", "sweep"], horizontal=True, index=0, key="tab")
    st.markdown("<div class='panel'>", unsafe_allow_html=True)

    if tab_choice == "setup":
        st.number_input("sprung mass", value=st.session_state["sprung_mass"], min_value=0.0, format="%.3f", key="sprung_mass")
        st.number_input("unsprung mass", value=st.session_state["unsprung_mass"], min_value=0.0, format="%.3f", key="unsprung_mass")
        st.number_input("spring rate (lbf/in)", value=st.session_state["spring_lbf_in"], min_value=0.0, format="%.3f", key="spring_lbf_in")
        st.number_input("motion ratio", value=st.session_state["motion_ratio"], min_value=0.0, max_value=2.0, format="%.3f", key="motion_ratio")
        st.number_input("tire spring rate (lbf/in)", value=st.session_state["tire_lbf_in"], min_value=0.0, format="%.3f", key="tire_lbf_in")
        st.slider("damping scale", min_value=0.1, max_value=2.0, value=st.session_state["damping_scale"], step=0.05, key="damping_scale")

        st.subheader("road")
        st.selectbox("profile", ["bump", "cone", "triangle", "rumble strip"], index=["bump", "cone", "triangle", "rumble strip"].index(st.session_state["road_profile"]), key="road_profile")
        st.number_input("feature height (mm)", value=st.session_state["road_height_mm"], min_value=0.0, format="%.3f", key="road_height_mm")
        st.number_input("feature length (m)", value=st.session_state["road_length_m"], min_value=0.0, format="%.3f", key="road_length_m")
        st.number_input("vehicle speed (km/h)", value=st.session_state["road_speed_kph"], min_value=0.0, format="%.3f", key="road_speed_kph")

    else:
        st.caption("Sweep setup")
        st.number_input("damping scale range", value=1.0, min_value=0.0, format="%.3f")
        st.number_input("spring rate sweep", value=629.0, min_value=0.0, format="%.3f")
        st.number_input("motion ratio sweep", value=0.75, min_value=0.0, max_value=2.0, format="%.3f")
        st.number_input("road speed sweep", value=50.0, min_value=0.0, format="%.3f")

    st.markdown("</div>", unsafe_allow_html=True)

    action_row = st.columns([1, 1, 1])
    with action_row[0]:
        if st.button("run simulation", use_container_width=True):
            st.session_state["run_sim"] = True
    with action_row[1]:
        if st.button("run sweep", use_container_width=True):
            st.session_state["run_sweep"] = True
    with action_row[2]:
        if st.button("reset", use_container_width=True):
            for key in list(st.session_state.keys()):
                if key in ["tab", "view", "run_sim", "run_sweep"]:
                    continue
                del st.session_state[key]
            init_state()

    st.progress(0.0, text="ready")
    st.caption("ready")
    st.markdown('</div>', unsafe_allow_html=True)

# ---------- Right column --------------------------------------------------------------
with right_col:
    st.markdown('<div class="right-panel">', unsafe_allow_html=True)

    top_bar = st.columns([1, 1])
    with top_bar[0]:
        view_choice = st.radio("", ["road", "response", "sweep", "ranking"], horizontal=True, index=0, key="view")
    with top_bar[1]:
        st.empty()

    # road profile cards row
    road_cards = st.columns(2)
    for i, profile_name in enumerate(["bump", "cone", "triangle", "rumble strip"]):
        with road_cards[i % 2]:
            c = st.container()
            active = profile_name == st.session_state["road_profile"]
            if c.button(profile_name, key=f"profile_{profile_name}", use_container_width=True):
                st.session_state["road_profile"] = profile_name
            if active:
                st.caption("selected")

    # Results summary row
    result_cols = st.columns(4)
    for idx, label in enumerate(["motion ratio", "spring rate", "min ride height", "max travel"]):
        with result_cols[idx]:
            st.markdown("<div class='metric-box'>", unsafe_allow_html=True)
            st.markdown(f"<h4>{label}</h4>", unsafe_allow_html=True)
            st.markdown("<div class='value'>--</div>", unsafe_allow_html=True)
            st.markdown("<div class='sub'>pending</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<hr>", unsafe_allow_html=True)

    # Main plot area
    if "run_sim" in st.session_state and st.session_state["run_sim"]:
        case = build_case_from_state()
        evaluation = evaluate_design(case)
        st.session_state["evaluation"] = evaluation
        st.session_state["run_sim"] = False

    if "evaluation" in st.session_state:
        fig = plt.Figure(figsize=(12, 6), dpi=110)
        if st.session_state["view"] == "road":
            plotting.plot_road(fig, st.session_state["evaluation"].case)
        elif st.session_state["view"] == "response":
            plotting.plot_response(fig, st.session_state["evaluation"])
        else:
            # for non-response views use a message panel
            plotting.plot_message(fig, f"{st.session_state['view']} view is available in the desktop app; this browser version focuses on the simulation and road/response plots.")
        st.pyplot(fig)
    else:
        fig = plt.Figure(figsize=(12, 6), dpi=110)
        plotting.plot_message(fig, "press  run simulation  to see the response")
        st.pyplot(fig)

    st.markdown('</div>', unsafe_allow_html=True)

# ---------- Footer note ----------------------------------------------------------------
st.caption("This browser build is a simplified web wrapper around the original desktop app logic.")

# To keep the app predictable across refreshes we don't force a run automatically.
