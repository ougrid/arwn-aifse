"""Streamlit dashboard for CS Shift Scheduling."""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from main import run_pipeline
from src.config import SHIFTS, SHIFT_IDS, CSAT_TARGET, MAX_WAIT_SECONDS

st.set_page_config(
    page_title="CS Shift Scheduler",
    page_icon="📅",
    layout="wide",
)


@st.cache_data(show_spinner="Running forecasting & scheduling pipeline...")
def get_results(csat_target: float, max_wait: float, solver_time: int) -> dict:
    """Cache pipeline results to avoid re-running on every interaction."""
    return run_pipeline(
        csat_target=csat_target,
        max_wait=max_wait,
        solver_time_limit=solver_time,
    )


def main():
    st.title("📅 CS Demand Forecasting & Shift Scheduling")
    st.caption("April 2026 — 50 Agents, 4 Shifts, 30 Days")

    # --- Sidebar Controls ---
    with st.sidebar:
        st.header("⚙️ Parameters")
        csat_target = st.slider(
            "CSAT Target", min_value=3.5, max_value=5.0,
            value=4.0, step=0.1, help="Minimum acceptable average CSAT score per shift",
        )
        max_wait = st.slider(
            "Max Wait Time (s)", min_value=30, max_value=120,
            value=60, step=5, help="Maximum acceptable average customer waiting time",
        )
        solver_time = st.slider(
            "Solver Time Limit (s)", min_value=30, max_value=300,
            value=120, step=30, help="Maximum time for the scheduling optimizer",
        )

        if st.button("🔄 Re-run Pipeline", type="primary", use_container_width=True):
            st.cache_data.clear()

    # --- Run pipeline ---
    results = get_results(csat_target, max_wait, solver_time)

    if "error" in results:
        st.error(results["error"])
        return

    # --- Top-level KPIs ---
    qs = results["quality_summary"]
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Avg CSAT", f"{qs['avg_projected_csat']:.2f}", delta="✓" if qs["avg_projected_csat"] >= csat_target else "✗")
    col2.metric("Avg Wait", f"{qs['avg_projected_wait']:.1f}s", delta="✓" if qs["avg_projected_wait"] <= max_wait else "✗")
    col3.metric("Targets Met", f"{qs['shifts_both_targets_met']}/{qs['total_shifts']}")
    col4.metric("Errors", results["num_errors"])
    col5.metric("Solver", f"{results['status']} ({results['solve_time']:.0f}s)")

    # --- Tabs ---
    tab_forecast, tab_schedule, tab_summary, tab_constraints, tab_agents = st.tabs([
        "📈 Forecast", "📅 Schedule", "📊 Shift Summary", "✅ Constraints", "👥 Agents",
    ])

    # === FORECAST TAB ===
    with tab_forecast:
        _render_forecast_tab(results)

    # === SCHEDULE TAB ===
    with tab_schedule:
        _render_schedule_tab(results)

    # === SHIFT SUMMARY TAB ===
    with tab_summary:
        _render_summary_tab(results)

    # === CONSTRAINTS TAB ===
    with tab_constraints:
        _render_constraints_tab(results)

    # === AGENTS TAB ===
    with tab_agents:
        _render_agents_tab(results)


def _render_forecast_tab(results: dict):
    """Render the forecasting results tab."""
    st.subheader("Ticket Volume Forecast — April 2026")

    vol = results["volume_predictions"].copy()
    vol["shift_name"] = vol["shift"].map(lambda s: SHIFTS[s]["name"])
    vol["date_str"] = vol["date"].dt.strftime("%Apr %d")

    fig = px.line(
        vol, x="date", y="predicted_volume", color="shift_name",
        title="Predicted Ticket Volume by Shift",
        labels={"predicted_volume": "Tickets", "date": "Date", "shift_name": "Shift"},
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)

    # Model metrics
    col1, col2, col3, col4 = st.columns(4)
    fm = results["forecast_metrics"]
    qm = results["quality_model_metrics"]
    col1.metric("Volume MAE", f"{fm['val_mae']:.1f}")
    col2.metric("Volume R²", f"{fm['val_r2']:.3f}")
    col3.metric("CSAT Model R²", f"{qm['csat_r2']:.3f}")
    col4.metric("Wait Model R²", f"{qm['wait_r2']:.3f}")

    # Staffing requirements table
    st.subheader("Staffing Requirements")
    staff = results["staffing_requirements"].copy()
    staff["shift_name"] = staff["shift"].map(lambda s: SHIFTS[s]["name"])
    staff["date_str"] = staff["date"].dt.strftime("%b %d")

    fig2 = px.bar(
        staff, x="date", y="total", color="shift_name",
        title="Required Total Staff per Shift",
        labels={"total": "Staff Needed", "date": "Date", "shift_name": "Shift"},
        barmode="group",
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig2.update_layout(height=400)
    st.plotly_chart(fig2, use_container_width=True)

    with st.expander("View raw staffing requirements"):
        display_cols = ["date_str", "shift_name", "predicted_volume", "senior", "junior", "english", "total"]
        st.dataframe(
            staff[display_cols].rename(columns={"date_str": "Date", "shift_name": "Shift"}),
            use_container_width=True, hide_index=True,
        )


def _render_schedule_tab(results: dict):
    """Render the monthly schedule calendar view."""
    st.subheader("Monthly Schedule — April 2026")

    schedule_df = results["schedule_df"].copy()
    agents_df = results["agents"]

    # Agent filter
    col1, col2 = st.columns(2)
    with col1:
        role_filter = st.multiselect("Role Level", ["Senior", "Junior"], default=["Senior", "Junior"])
    with col2:
        english_filter = st.checkbox("English-capable only", value=False)

    filtered_agents = agents_df[agents_df["role_level"].isin(role_filter)]
    if english_filter:
        filtered_agents = filtered_agents[filtered_agents["is_english"]]

    agent_list = filtered_agents["agent_id"].tolist()
    filtered_schedule = schedule_df[schedule_df["agent_id"].isin(agent_list)]

    # Pivot to calendar view
    pivot = filtered_schedule.pivot(index="agent_id", columns="date", values="assignment")
    pivot.columns = [c.strftime("%d") for c in pivot.columns]

    # Color-code assignments
    color_map = {
        "shift_1": "🟢",  # Morning
        "shift_2": "🔵",  # Afternoon
        "shift_3": "🟠",  # Evening
        "shift_4": "🟣",  # Night
        "leave": "⬜",    # Leave
    }

    display_df = pivot.map(lambda x: color_map.get(x, x))
    st.dataframe(display_df, use_container_width=True, height=min(len(agent_list) * 35 + 50, 600))

    st.caption("🟢 Morning | 🔵 Afternoon | 🟠 Evening | 🟣 Night | ⬜ Leave")

    # Download
    csv = schedule_df.to_csv(index=False)
    st.download_button("📥 Download Schedule CSV", csv, "schedule_apr2026.csv", "text/csv")


def _render_summary_tab(results: dict):
    """Render shift-level summary with projected quality."""
    st.subheader("Shift Summary — Headcount & Projected Quality")

    ss = results["shift_summary"].copy()
    ss["date_str"] = ss["date"].dt.strftime("%b %d")

    # Quality charts
    col1, col2 = st.columns(2)

    with col1:
        fig = px.scatter(
            ss, x="date", y="projected_csat", color="shift_name",
            title="Projected CSAT by Shift",
            labels={"projected_csat": "CSAT", "date": "Date"},
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig.add_hline(y=CSAT_TARGET, line_dash="dash", line_color="red",
                      annotation_text=f"Target ({CSAT_TARGET})")
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig2 = px.scatter(
            ss, x="date", y="projected_wait", color="shift_name",
            title="Projected Wait Time by Shift",
            labels={"projected_wait": "Wait (s)", "date": "Date"},
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig2.add_hline(y=MAX_WAIT_SECONDS, line_dash="dash", line_color="red",
                       annotation_text=f"Target ({MAX_WAIT_SECONDS}s)")
        fig2.update_layout(height=400)
        st.plotly_chart(fig2, use_container_width=True)

    # Headcount heatmap
    st.subheader("Daily Headcount by Shift")
    for shift in SHIFT_IDS:
        shift_data = ss[ss["shift"] == shift]
        shift_name = SHIFTS[shift]["name"]
        with st.expander(f"Shift {shift} — {shift_name}", expanded=(shift == 1)):
            display_cols = [
                "date_str", "total_assigned", "senior_assigned", "junior_assigned",
                "english_assigned", "predicted_volume", "projected_csat", "projected_wait",
            ]
            st.dataframe(
                shift_data[display_cols].rename(columns={
                    "date_str": "Date", "total_assigned": "Total",
                    "senior_assigned": "Sr", "junior_assigned": "Jr",
                    "english_assigned": "Eng", "predicted_volume": "Volume",
                    "projected_csat": "CSAT", "projected_wait": "Wait(s)",
                }),
                use_container_width=True, hide_index=True,
            )


def _render_constraints_tab(results: dict):
    """Render constraint validation report."""
    st.subheader("Constraint Validation Report")

    num_errors = results["num_errors"]
    num_warnings = results["num_warnings"]

    if num_errors == 0:
        st.success(f"✅ All hard constraints satisfied!")
    else:
        st.error(f"❌ {num_errors} hard constraint violations found")

    if num_warnings > 0:
        st.warning(f"⚠️ {num_warnings} soft constraint warnings")

    report = results["constraint_report"]
    if not report.empty:
        st.dataframe(report, use_container_width=True, hide_index=True)

    # Detailed violations
    if results["violations"]:
        with st.expander("View all violations"):
            violation_data = [
                {
                    "Constraint": v.constraint_name,
                    "Day": v.day + 1 if v.day >= 0 else "N/A",
                    "Severity": v.severity,
                    "Details": v.details,
                }
                for v in results["violations"]
            ]
            st.dataframe(pd.DataFrame(violation_data), use_container_width=True, hide_index=True)


def _render_agents_tab(results: dict):
    """Render per-agent summary."""
    st.subheader("Agent Summary")

    agent_sum = results["agent_summary"]

    # Night shift distribution
    fig = px.histogram(
        agent_sum, x="shift_4_count", nbins=10,
        title="Night Shift Distribution Across Agents",
        labels={"shift_4_count": "Night Shifts", "count": "Agents"},
        color_discrete_sequence=["#9b59b6"],
    )
    fig.update_layout(height=350)
    st.plotly_chart(fig, use_container_width=True)

    # Shift distribution per agent
    fig2 = px.bar(
        agent_sum.melt(
            id_vars=["agent_id", "role_level"],
            value_vars=["shift_1_count", "shift_2_count", "shift_3_count", "shift_4_count", "leave_count"],
            var_name="Assignment", value_name="Days",
        ),
        x="agent_id", y="Days", color="Assignment",
        title="Shift Distribution per Agent",
        labels={"agent_id": "Agent", "Days": "Days"},
        color_discrete_map={
            "shift_1_count": "#2ecc71",
            "shift_2_count": "#3498db",
            "shift_3_count": "#e67e22",
            "shift_4_count": "#9b59b6",
            "leave_count": "#ecf0f1",
        },
    )
    fig2.update_layout(height=500, xaxis_tickangle=45)
    st.plotly_chart(fig2, use_container_width=True)

    # Table
    with st.expander("View agent details"):
        st.dataframe(agent_sum, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
