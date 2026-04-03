"""Tests for the scheduling engine and constraint validation."""

import pytest

from main import run_pipeline
from src.config import (
    DAYS_IN_APRIL,
    NIGHT_SHIFT,
    SHIFT_IDS,
    TOTAL_AGENTS,
    TOTAL_LEAVE_DAYS_PER_AGENT,
)


@pytest.fixture(scope="module")
def pipeline_results():
    """Run the full pipeline once for all scheduling tests."""
    return run_pipeline(csat_target=4.0, max_wait=60.0, solver_time_limit=120)


class TestScheduleValidity:
    """Verify the schedule satisfies all hard constraints."""

    def test_solver_finds_solution(self, pipeline_results):
        assert pipeline_results["status"] in ("OPTIMAL", "FEASIBLE")

    def test_no_hard_constraint_errors(self, pipeline_results):
        assert pipeline_results["num_errors"] == 0

    def test_all_agents_scheduled(self, pipeline_results):
        df = pipeline_results["schedule_df"]
        assert df["agent_id"].nunique() == TOTAL_AGENTS

    def test_every_agent_has_30_days(self, pipeline_results):
        df = pipeline_results["schedule_df"]
        for aid, grp in df.groupby("agent_id"):
            assert len(grp) == DAYS_IN_APRIL, f"{aid} has {len(grp)} days"


class TestLeaveConstraints:
    """Verify leave-related constraints."""

    def test_each_agent_has_6_leave_days(self, pipeline_results):
        df = pipeline_results["schedule_df"]
        for aid, grp in df.groupby("agent_id"):
            leave_count = (grp["assignment"] == "leave").sum()
            assert leave_count == TOTAL_LEAVE_DAYS_PER_AGENT, (
                f"{aid}: {leave_count} leave days, expected {TOTAL_LEAVE_DAYS_PER_AGENT}"
            )

    def test_pre_selected_leaves_honored(self, pipeline_results):
        df = pipeline_results["schedule_df"]
        agents = pipeline_results["agents"]
        from src.data_loader import load_all_data
        data = load_all_data()
        leave_req = data["leave_requests"]

        for _, row in leave_req.iterrows():
            agent_sched = df[
                (df["agent_id"] == row["agent_id"]) &
                (df["date"] == row["leave_date"])
            ]
            assert len(agent_sched) == 1
            assert agent_sched.iloc[0]["assignment"] == "leave", (
                f"{row['agent_id']} not on leave on {row['leave_date']}"
            )


class TestNightShiftRest:
    """Verify night shift rest rule."""

    def test_night_shift_followed_by_leave(self, pipeline_results):
        df = pipeline_results["schedule_df"]
        dates = sorted(df["date"].unique())

        for aid in df["agent_id"].unique():
            agent_sched = df[df["agent_id"] == aid].sort_values("date")
            assignments = agent_sched["assignment"].tolist()
            agent_dates = agent_sched["date"].tolist()

            for i in range(len(assignments) - 1):
                if assignments[i] == f"shift_{NIGHT_SHIFT}":
                    assert assignments[i + 1] == "leave", (
                        f"{aid}: night shift on {agent_dates[i]}, "
                        f"but '{assignments[i+1]}' on {agent_dates[i+1]}"
                    )


class TestAssignmentValidity:
    """Verify basic assignment validity."""

    def test_valid_assignments_only(self, pipeline_results):
        df = pipeline_results["schedule_df"]
        valid = {"shift_1", "shift_2", "shift_3", "shift_4", "leave"}
        assert set(df["assignment"].unique()).issubset(valid)

    def test_one_assignment_per_day(self, pipeline_results):
        df = pipeline_results["schedule_df"]
        dupes = df.groupby(["agent_id", "date"]).size()
        assert (dupes == 1).all(), "Some agent-day combos have multiple assignments"


class TestQualityMetrics:
    """Verify quality projection results."""

    def test_quality_summary_exists(self, pipeline_results):
        qs = pipeline_results["quality_summary"]
        assert "avg_projected_csat" in qs
        assert "avg_projected_wait" in qs

    def test_csat_in_valid_range(self, pipeline_results):
        qs = pipeline_results["quality_summary"]
        assert 1.0 <= qs["avg_projected_csat"] <= 5.0

    def test_wait_positive(self, pipeline_results):
        qs = pipeline_results["quality_summary"]
        assert qs["avg_projected_wait"] > 0

    def test_majority_targets_met(self, pipeline_results):
        qs = pipeline_results["quality_summary"]
        # At least 80% of shifts should meet both targets
        pct = qs["shifts_both_targets_met"] / qs["total_shifts"]
        assert pct >= 0.8, f"Only {pct:.0%} of shifts met both targets"
