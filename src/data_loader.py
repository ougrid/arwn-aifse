"""Data loading and validation utilities."""

import json
from pathlib import Path

import pandas as pd

from src.config import (
    AGENTS_PATH,
    HISTORICAL_PERFORMANCE_PATH,
    LEAVE_REQUESTS_PATH,
    TOTAL_AGENTS,
    PRE_SELECTED_LEAVE_DAYS,
)


def load_agents(path: Path = AGENTS_PATH) -> pd.DataFrame:
    """Load agents from JSONL file."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    df = pd.DataFrame(records)
    df["is_english"] = df["is_english"].astype(bool)
    df = df.sort_values("agent_id").reset_index(drop=True)

    assert len(df) == TOTAL_AGENTS, f"Expected {TOTAL_AGENTS} agents, got {len(df)}"
    assert set(df["role_level"].unique()) == {"Senior", "Junior"}
    return df


def load_historical_performance(path: Path = HISTORICAL_PERFORMANCE_PATH) -> pd.DataFrame:
    """Load historical shift performance data."""
    df = pd.read_csv(path, parse_dates=["date"])

    # Validate columns
    required = [
        "date", "shift", "shift_name", "ticket_volume",
        "senior_staffed", "junior_staffed", "english_staffed",
        "avg_csat", "avg_wait_seconds",
    ]
    missing = set(required) - set(df.columns)
    assert not missing, f"Missing columns: {missing}"

    # Validate shifts
    assert set(df["shift"].unique()) == {1, 2, 3, 4}

    df = df.sort_values(["date", "shift"]).reset_index(drop=True)
    return df


def load_leave_requests(path: Path = LEAVE_REQUESTS_PATH) -> pd.DataFrame:
    """Load pre-selected leave requests for April 2026."""
    df = pd.read_csv(path, parse_dates=["leave_date"])

    assert "agent_id" in df.columns
    assert "leave_date" in df.columns
    assert "leave_type" in df.columns

    # Validate each agent has exactly 3 pre-selected days
    pre_selected = df[df["leave_type"] == "pre_selected"]
    counts = pre_selected.groupby("agent_id").size()
    bad = counts[counts != PRE_SELECTED_LEAVE_DAYS]
    assert bad.empty, f"Agents without exactly {PRE_SELECTED_LEAVE_DAYS} pre-selected leaves: {bad.to_dict()}"

    return df


def load_all_data() -> dict:
    """Load all data files and return as a dictionary."""
    agents = load_agents()
    historical = load_historical_performance()
    leave_requests = load_leave_requests()

    return {
        "agents": agents,
        "historical": historical,
        "leave_requests": leave_requests,
    }
