"""Tests for data loading and validation."""

import pandas as pd
import pytest

from src.data_loader import load_all_data
from src.config import TOTAL_AGENTS, TOTAL_SENIORS, TOTAL_JUNIORS, TOTAL_ENGLISH


@pytest.fixture(scope="module")
def data():
    return load_all_data()


class TestDataIntegrity:
    """Verify data files load correctly and contain expected contents."""

    def test_agents_count(self, data):
        assert len(data["agents"]) == TOTAL_AGENTS

    def test_agent_roles(self, data):
        agents = data["agents"]
        assert agents[agents["role_level"] == "Senior"].shape[0] == TOTAL_SENIORS
        assert agents[agents["role_level"] == "Junior"].shape[0] == TOTAL_JUNIORS

    def test_english_agents(self, data):
        agents = data["agents"]
        assert agents[agents["is_english"]].shape[0] == TOTAL_ENGLISH

    def test_historical_shifts(self, data):
        hist = data["historical"]
        assert set(hist["shift"].unique()) == {1, 2, 3, 4}

    def test_historical_has_quality_columns(self, data):
        hist = data["historical"]
        for col in [
            "avg_csat",
            "avg_wait_seconds",
            "ticket_volume",
            "senior_staffed",
            "junior_staffed",
            "english_staffed",
        ]:
            assert col in hist.columns

    def test_leave_requests_count(self, data):
        leave = data["leave_requests"]
        # 50 agents × 3 pre-selected = 150
        assert len(leave) == 150

    def test_leave_all_pre_selected(self, data):
        leave = data["leave_requests"]
        assert (leave["leave_type"] == "pre_selected").all()

    def test_leave_all_agents_have_three(self, data):
        leave = data["leave_requests"]
        counts = leave.groupby("agent_id").size()
        assert (counts == 3).all()
