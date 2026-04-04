"""Tests for bonus features: preferences, fairness, and remediation."""

import numpy as np
import pandas as pd
import pytest

from src.config import SHIFT_IDS
from src.evaluation.fairness import compute_fairness_metrics, gini_coefficient
from src.evaluation.remediation import build_remediation_report, generate_remediation
from src.scheduling.constraints import ConstraintViolation
from src.scheduling.preferences import (
    PREF_AVOID,
    PREF_NEUTRAL,
    PREF_PREFER,
    PREF_STRONGLY_AVOID,
    PREF_STRONGLY_PREFER,
    generate_shift_preferences,
    get_preference_cost,
    preference_satisfaction_score,
)


# --- Fixtures ---


@pytest.fixture
def sample_agents():
    return pd.DataFrame(
        {
            "agent_id": ["A1", "A2", "A3", "A4"],
            "role_level": ["Senior", "Junior", "Junior", "Senior"],
            "is_english": [True, False, True, False],
        }
    )


@pytest.fixture
def sample_preferences(sample_agents):
    return generate_shift_preferences(sample_agents, seed=42)


@pytest.fixture
def sample_schedule():
    """A simple 4-agent, 5-day schedule."""
    return {
        "A1": ["shift_1", "shift_1", "shift_2", "leave", "shift_1"],
        "A2": ["shift_2", "shift_3", "shift_2", "shift_4", "leave"],
        "A3": ["shift_1", "shift_2", "leave", "shift_1", "shift_3"],
        "A4": ["shift_4", "leave", "shift_3", "shift_3", "shift_2"],
    }


@pytest.fixture
def sample_agent_summary():
    """Agent summary DataFrame for fairness testing."""
    return pd.DataFrame(
        {
            "agent_id": [f"A{i}" for i in range(10)],
            "role_level": ["Senior"] * 3 + ["Junior"] * 7,
            "working_days": [24, 24, 24, 24, 24, 24, 24, 24, 24, 24],
            "shift_1_count": [8, 6, 7, 5, 6, 7, 8, 5, 6, 7],
            "shift_2_count": [6, 8, 7, 7, 6, 5, 6, 8, 7, 6],
            "shift_3_count": [6, 6, 5, 7, 7, 8, 6, 6, 7, 5],
            "shift_4_count": [4, 4, 5, 5, 5, 4, 4, 5, 4, 6],
            "leave_count": [6, 6, 6, 6, 6, 6, 6, 6, 6, 6],
        }
    )


# --- Preference Tests ---


class TestPreferenceGeneration:
    def test_generates_for_all_agents(self, sample_agents, sample_preferences):
        assert len(sample_preferences) == len(sample_agents)
        assert set(sample_preferences["agent_id"]) == set(sample_agents["agent_id"])

    def test_preference_columns_exist(self, sample_preferences):
        for s in SHIFT_IDS:
            assert f"shift_{s}_pref" in sample_preferences.columns

    def test_preferences_in_valid_range(self, sample_preferences):
        for s in SHIFT_IDS:
            col = sample_preferences[f"shift_{s}_pref"]
            assert col.min() >= PREF_STRONGLY_PREFER
            assert col.max() <= PREF_STRONGLY_AVOID

    def test_deterministic_with_same_seed(self, sample_agents):
        p1 = generate_shift_preferences(sample_agents, seed=99)
        p2 = generate_shift_preferences(sample_agents, seed=99)
        pd.testing.assert_frame_equal(p1, p2)

    def test_different_seeds_differ(self, sample_agents):
        p1 = generate_shift_preferences(sample_agents, seed=1)
        p2 = generate_shift_preferences(sample_agents, seed=2)
        # At least some values should differ
        pref_cols = [f"shift_{s}_pref" for s in SHIFT_IDS]
        assert not p1[pref_cols].equals(p2[pref_cols])


class TestPreferenceCost:
    def test_cost_range(self, sample_preferences):
        for _, row in sample_preferences.iterrows():
            for s in SHIFT_IDS:
                cost = get_preference_cost(sample_preferences, row["agent_id"], s)
                assert 0 <= cost <= 4

    def test_missing_agent_returns_neutral(self, sample_preferences):
        cost = get_preference_cost(sample_preferences, "NONEXISTENT", 1)
        assert cost == 2  # neutral default


class TestPreferenceSatisfaction:
    def test_returns_required_keys(self, sample_schedule, sample_preferences):
        result = preference_satisfaction_score(sample_schedule, sample_preferences)
        assert "satisfaction_pct" in result
        assert "overall_avg_preference" in result
        assert "total_working_shifts" in result
        assert "preferred_assignments" in result
        assert "avoided_assignments" in result
        assert "agent_details" in result

    def test_satisfaction_in_range(self, sample_schedule, sample_preferences):
        result = preference_satisfaction_score(sample_schedule, sample_preferences)
        assert 0 <= result["satisfaction_pct"] <= 100

    def test_total_working_shifts_correct(self, sample_schedule, sample_preferences):
        result = preference_satisfaction_score(sample_schedule, sample_preferences)
        expected_working = sum(
            1
            for assignments in sample_schedule.values()
            for a in assignments
            if a.startswith("shift_")
        )
        assert result["total_working_shifts"] == expected_working


# --- Fairness Tests ---


class TestGiniCoefficient:
    def test_perfect_equality(self):
        assert gini_coefficient(np.array([5, 5, 5, 5])) == pytest.approx(0.0)

    def test_maximum_inequality(self):
        # One person has everything
        g = gini_coefficient(np.array([0, 0, 0, 100]))
        assert g > 0.7  # Should be close to 0.75 for 4 elements

    def test_empty_returns_zero(self):
        assert gini_coefficient(np.array([])) == 0.0

    def test_all_zeros(self):
        assert gini_coefficient(np.array([0, 0, 0])) == 0.0

    def test_moderate_inequality(self):
        g = gini_coefficient(np.array([1, 2, 3, 4]))
        assert 0.1 < g < 0.5


class TestFairnessMetrics:
    def test_returns_required_keys(self, sample_agent_summary):
        result = compute_fairness_metrics(sample_agent_summary)
        expected_keys = {
            "night_shift_gini",
            "night_shift_range",
            "night_shift_std",
            "night_shift_mean",
            "workload_gini",
            "workload_range",
            "shift_entropy_avg",
            "shift_entropy_max",
            "composite_score",
            "fairness_grade",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_grade_is_valid(self, sample_agent_summary):
        result = compute_fairness_metrics(sample_agent_summary)
        assert result["fairness_grade"] in ("A", "B", "C", "D", "F")

    def test_composite_in_range(self, sample_agent_summary):
        result = compute_fairness_metrics(sample_agent_summary)
        assert 0 <= result["composite_score"] <= 100

    def test_fair_distribution_gets_good_grade(self, sample_agent_summary):
        result = compute_fairness_metrics(sample_agent_summary)
        # The sample has fairly even distribution
        assert result["fairness_grade"] in ("A", "B", "C")

    def test_gini_values_valid(self, sample_agent_summary):
        result = compute_fairness_metrics(sample_agent_summary)
        assert 0 <= result["night_shift_gini"] <= 1
        assert 0 <= result["workload_gini"] <= 1


# --- Remediation Tests ---


class TestRemediation:
    def test_known_constraint_has_suggestion(self):
        v = ConstraintViolation(
            constraint_name="min_senior_staffing",
            day=5,
            severity="error",
            details="Shift 1 day 6: 3 seniors assigned, need 4",
        )
        suggestion = generate_remediation(v)
        assert len(suggestion) > 10  # Non-trivial suggestion
        assert "senior" in suggestion.lower()

    def test_unknown_constraint_has_fallback(self):
        v = ConstraintViolation(
            constraint_name="unknown_future_constraint",
            day=0,
            severity="warning",
            details="Something happened",
        )
        suggestion = generate_remediation(v)
        assert len(suggestion) > 5

    def test_build_report_empty_input(self):
        report = build_remediation_report([])
        assert report == []

    def test_build_report_groups_by_type(self):
        violations = [
            ConstraintViolation(
                "shift_continuity", day=d, severity="warning", details=f"Day {d}"
            )
            for d in range(5)
        ]
        report = build_remediation_report(violations)
        assert len(report) == 1  # All grouped
        assert report[0]["count"] == 5
        assert report[0]["constraint"] == "shift_continuity"

    def test_build_report_multiple_types(self):
        violations = [
            ConstraintViolation(
                "shift_continuity", day=0, severity="warning", details="..."
            ),
            ConstraintViolation(
                "min_senior_staffing", day=1, severity="error", details="..."
            ),
            ConstraintViolation(
                "shift_continuity", day=2, severity="warning", details="..."
            ),
        ]
        report = build_remediation_report(violations)
        assert len(report) == 2
        names = {r["constraint"] for r in report}
        assert names == {"shift_continuity", "min_senior_staffing"}

    def test_report_has_remediation_field(self):
        violations = [
            ConstraintViolation(
                "night_rest", day=3, severity="error", details="Not resting"
            ),
        ]
        report = build_remediation_report(violations)
        assert len(report) == 1
        assert "remediation" in report[0]
        assert len(report[0]["remediation"]) > 10


# --- Integration test using pipeline results ---


class TestBonusIntegration:
    """Test bonus features are present in pipeline results (uses module fixture)."""

    @pytest.fixture(scope="class")
    def pipeline_results(self):
        from main import run_pipeline

        return run_pipeline(solver_time_limit=60)

    def test_preferences_in_results(self, pipeline_results):
        assert "preferences" in pipeline_results
        assert "preference_summary" in pipeline_results
        prefs = pipeline_results["preferences"]
        assert len(prefs) == 50  # all agents

    def test_fairness_in_results(self, pipeline_results):
        assert "fairness" in pipeline_results
        fairness = pipeline_results["fairness"]
        assert "fairness_grade" in fairness
        assert "composite_score" in fairness

    def test_remediation_in_results(self, pipeline_results):
        assert "remediation" in pipeline_results
        remediation = pipeline_results["remediation"]
        assert isinstance(remediation, list)
