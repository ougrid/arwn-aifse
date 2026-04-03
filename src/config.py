"""Business constants and configuration for the CS scheduling system."""

from dataclasses import dataclass, field
from pathlib import Path

# --- Paths ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

HISTORICAL_PERFORMANCE_PATH = DATA_DIR / "historical_performance.csv"
AGENTS_PATH = DATA_DIR / "agents.jsonl"
LEAVE_REQUESTS_PATH = DATA_DIR / "leave_requests_apr_2026.csv"

# --- Shift definitions ---
SHIFTS = {
    1: {"name": "Morning", "hours": "06:00–14:00"},
    2: {"name": "Afternoon", "hours": "14:00–20:00"},
    3: {"name": "Evening", "hours": "20:00–00:00"},
    4: {"name": "Night", "hours": "00:00–06:00"},
}
SHIFT_IDS = [1, 2, 3, 4]
NIGHT_SHIFT = 4

# --- Quality targets ---
CSAT_TARGET = 4.0
MAX_WAIT_SECONDS = 60.0

# --- Scheduling constants ---
SCHEDULE_YEAR = 2026
SCHEDULE_MONTH = 4  # April
DAYS_IN_APRIL = 30

TOTAL_LEAVE_DAYS_PER_AGENT = 6
PRE_SELECTED_LEAVE_DAYS = 3
SYSTEM_ASSIGNED_LEAVE_DAYS = 3  # includes night_rest days

# --- Agent pool (derived from data, but useful as constants) ---
TOTAL_AGENTS = 50
TOTAL_SENIORS = 10
TOTAL_JUNIORS = 40
TOTAL_ENGLISH = 8
SENIOR_ENGLISH = 2
JUNIOR_ENGLISH = 6


@dataclass
class SchedulingConfig:
    """Tunable parameters for the scheduling optimizer."""

    # CP-SAT solver time limit in seconds
    solver_time_limit: int = 120

    # Soft constraint weights
    shift_continuity_weight: int = 3
    night_fairness_weight: int = 5
    overstaffing_weight: int = 1
    preference_weight: int = 1  # weight for agent shift preference soft constraint

    # Shift transition penalty matrix (from_shift → to_shift)
    # Penalize large jumps; 0 = same shift, higher = worse
    shift_transition_penalties: dict = field(
        default_factory=lambda: {
            (1, 1): 0,
            (1, 2): 1,
            (1, 3): 2,
            (1, 4): 4,
            (2, 1): 1,
            (2, 2): 0,
            (2, 3): 1,
            (2, 4): 3,
            (3, 1): 2,
            (3, 2): 1,
            (3, 3): 0,
            (3, 4): 2,
            (4, 1): 4,
            (4, 2): 3,
            (4, 3): 2,
            (4, 4): 0,
        }
    )
