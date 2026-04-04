"""Fairness metrics for shift schedule evaluation.

Measures equity in shift distribution, particularly night shifts,
using Gini coefficient and other fairness indicators.
"""

import numpy as np
import pandas as pd

from src.config import SHIFT_IDS


def gini_coefficient(values: np.ndarray) -> float:
    """Compute the Gini coefficient of an array of values.

    Returns a value between 0 (perfect equality) and 1 (maximum inequality).
    """
    values = np.sort(values).astype(float)
    n = len(values)
    if n == 0 or values.sum() == 0:
        return 0.0
    index = np.arange(1, n + 1)
    return float(
        (2 * np.sum(index * values) - (n + 1) * np.sum(values)) / (n * np.sum(values))
    )


def compute_fairness_metrics(
    agent_summary: pd.DataFrame,
) -> dict:
    """Compute comprehensive fairness metrics from agent schedule summary.

    Returns dict with:
        - night_shift_gini: Gini coefficient for night shift distribution (0 = perfectly fair)
        - night_shift_range: (min, max) night shifts among agents
        - night_shift_std: standard deviation of night shift counts
        - workload_gini: Gini for total working days
        - workload_range: (min, max) working days
        - shift_entropy_avg: average entropy of shift distribution per agent (higher = more varied)
        - fairness_grade: A-F letter grade based on combined fairness score
    """
    night_counts = agent_summary["shift_4_count"].values
    working_days = agent_summary["working_days"].values

    # Night shift fairness
    night_gini = gini_coefficient(night_counts)
    night_range = (int(night_counts.min()), int(night_counts.max()))
    night_std = float(np.std(night_counts))
    night_mean = float(np.mean(night_counts))

    # Overall workload fairness
    workload_gini = gini_coefficient(working_days)
    workload_range = (int(working_days.min()), int(working_days.max()))

    # Shift distribution entropy per agent (higher = more varied assignments)
    entropies = []
    for _, row in agent_summary.iterrows():
        counts = np.array([row[f"shift_{s}_count"] for s in SHIFT_IDS], dtype=float)
        total = counts.sum()
        if total > 0:
            probs = counts / total
            probs = probs[probs > 0]
            entropy = -np.sum(probs * np.log2(probs))
            entropies.append(entropy)
    avg_entropy = float(np.mean(entropies)) if entropies else 0.0
    max_entropy = np.log2(len(SHIFT_IDS))  # ~2.0 for 4 shifts

    # Composite fairness score (0-100, higher = fairer)
    # Weight: night fairness 40%, workload 30%, shift variety 30%
    # Night Gini scaled by expected Gini for sparse distribution:
    # With ~80 night slots / 50 agents, perfect distribution is 1-2 per agent → natural Gini
    expected_night_per_agent = night_mean
    max_possible_nights = 30  # theoretical max
    sparsity_factor = min(
        1.0, expected_night_per_agent / 4
    )  # normalize: 4+ nights/agent → full weight
    night_score = max(0, 100 * (1 - night_gini * sparsity_factor * 2))
    workload_score = max(0, 100 * (1 - workload_gini * 5))  # Gini 0.2 → score 0
    entropy_score = 100 * (avg_entropy / max_entropy) if max_entropy > 0 else 50

    composite = 0.4 * night_score + 0.3 * workload_score + 0.3 * entropy_score

    # Letter grade
    if composite >= 90:
        grade = "A"
    elif composite >= 80:
        grade = "B"
    elif composite >= 70:
        grade = "C"
    elif composite >= 60:
        grade = "D"
    else:
        grade = "F"

    return {
        "night_shift_gini": round(night_gini, 3),
        "night_shift_range": night_range,
        "night_shift_std": round(night_std, 2),
        "night_shift_mean": round(night_mean, 1),
        "workload_gini": round(workload_gini, 3),
        "workload_range": workload_range,
        "shift_entropy_avg": round(avg_entropy, 3),
        "shift_entropy_max": round(max_entropy, 3),
        "composite_score": round(composite, 1),
        "fairness_grade": grade,
    }
