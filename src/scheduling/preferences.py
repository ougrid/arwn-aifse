"""Agent shift preferences — generates and manages shift preference data.

Since the assessment data doesn't include shift preferences, this module
generates realistic synthetic preferences based on agent attributes,
and integrates them as soft constraints in the scheduler.
"""

import pandas as pd
import numpy as np

from src.config import SHIFT_IDS


# Preference scale: 1 (strongly prefer) to 5 (strongly avoid)
# Lower = more preferred
PREF_STRONGLY_PREFER = 1
PREF_PREFER = 2
PREF_NEUTRAL = 3
PREF_AVOID = 4
PREF_STRONGLY_AVOID = 5


def generate_shift_preferences(
    agents: pd.DataFrame,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate realistic shift preferences for all agents.

    Preference patterns:
        - Senior agents tend to prefer morning/afternoon (stability)
        - Junior agents have more varied preferences
        - English agents slightly prefer morning/afternoon (international traffic)
        - Night shift is generally less preferred
        - Each agent gets a randomly assigned primary preference

    Returns:
        DataFrame with columns: agent_id, shift_1_pref, shift_2_pref,
        shift_3_pref, shift_4_pref (values 1-5, lower = more preferred)
    """
    rng = np.random.default_rng(seed)
    rows = []

    for _, agent in agents.iterrows():
        is_senior = agent["role_level"] == "Senior"
        is_english = agent["is_english"]

        # Base preferences: slight bias by role
        if is_senior:
            # Seniors prefer day shifts
            base = {1: 2.0, 2: 2.0, 3: 3.5, 4: 4.0}
        else:
            # Juniors have flatter preferences
            base = {1: 2.5, 2: 2.5, 3: 3.0, 4: 3.5}

        # English agents: slight preference for morning/afternoon
        if is_english:
            base[1] -= 0.5
            base[2] -= 0.3

        # Random individual variation: pick a primary preferred shift
        primary = rng.choice(SHIFT_IDS, p=[0.35, 0.30, 0.20, 0.15])
        base[primary] -= 1.0

        # Add noise and clamp
        prefs = {}
        for s in SHIFT_IDS:
            val = base[s] + rng.normal(0, 0.3)
            prefs[f"shift_{s}_pref"] = int(
                np.clip(round(val), PREF_STRONGLY_PREFER, PREF_STRONGLY_AVOID)
            )

        rows.append(
            {
                "agent_id": agent["agent_id"],
                **prefs,
            }
        )

    return pd.DataFrame(rows)


def get_preference_cost(preferences: pd.DataFrame, agent_id: str, shift: int) -> int:
    """Get the preference cost for assigning an agent to a shift.

    Returns 0 for strongly preferred (1), up to 4 for strongly avoided (5).
    This maps directly to a penalty in the objective function.
    """
    row = preferences[preferences["agent_id"] == agent_id]
    if row.empty:
        return 2  # neutral default
    pref = row.iloc[0][f"shift_{shift}_pref"]
    return pref - 1  # 0 (strongly prefer) to 4 (strongly avoid)


def preference_satisfaction_score(
    schedule: dict[str, list[str]],
    preferences: pd.DataFrame,
) -> dict:
    """Compute how well the schedule respects agent preferences.

    Returns:
        dict with satisfaction metrics including overall score,
        per-agent scores, and breakdown by preference level.
    """
    agent_scores = []
    pref_match_counts = {
        PREF_STRONGLY_PREFER: 0,
        PREF_PREFER: 0,
        PREF_NEUTRAL: 0,
        PREF_AVOID: 0,
        PREF_STRONGLY_AVOID: 0,
    }
    total_working = 0

    for agent_id, assignments in schedule.items():
        pref_row = preferences[preferences["agent_id"] == agent_id]
        if pref_row.empty:
            continue
        pref_row = pref_row.iloc[0]

        agent_pref_scores = []
        for assignment in assignments:
            if assignment.startswith("shift_"):
                shift = int(assignment.split("_")[1])
                pref = pref_row[f"shift_{shift}_pref"]
                agent_pref_scores.append(pref)
                pref_match_counts[pref] += 1
                total_working += 1

        if agent_pref_scores:
            agent_scores.append(
                {
                    "agent_id": agent_id,
                    "avg_pref_score": round(np.mean(agent_pref_scores), 2),
                    "working_days": len(agent_pref_scores),
                    "preferred_days": sum(
                        1 for p in agent_pref_scores if p <= PREF_PREFER
                    ),
                    "avoided_days": sum(
                        1 for p in agent_pref_scores if p >= PREF_AVOID
                    ),
                }
            )

    agent_df = pd.DataFrame(agent_scores)
    overall_avg = agent_df["avg_pref_score"].mean() if not agent_df.empty else 3.0

    # Satisfaction: 5 - avg_pref maps to a 0-4 scale; normalize to 0-100%
    satisfaction_pct = round((5 - overall_avg) / 4 * 100, 1) if overall_avg else 50.0

    return {
        "overall_avg_preference": round(overall_avg, 2),
        "satisfaction_pct": satisfaction_pct,
        "total_working_shifts": total_working,
        "preferred_assignments": pref_match_counts.get(PREF_STRONGLY_PREFER, 0)
        + pref_match_counts.get(PREF_PREFER, 0),
        "avoided_assignments": pref_match_counts.get(PREF_AVOID, 0)
        + pref_match_counts.get(PREF_STRONGLY_AVOID, 0),
        "agent_details": agent_df,
    }
