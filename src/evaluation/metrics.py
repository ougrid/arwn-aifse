"""Evaluation metrics — CSAT/wait projections, schedule summaries, constraint reports."""

import pandas as pd
import numpy as np

from src.config import SHIFT_IDS, SHIFTS, CSAT_TARGET, MAX_WAIT_SECONDS
from src.forecasting.staffing_optimizer import QualityModels, predict_quality


def build_shift_summary(
    schedule_df: pd.DataFrame,
    agents_df: pd.DataFrame,
    staffing_requirements: pd.DataFrame,
    quality_models: QualityModels,
) -> pd.DataFrame:
    """Build a per-day, per-shift summary with headcounts and projected quality.

    Returns a DataFrame with columns:
        date, shift, shift_name, senior_assigned, junior_assigned, english_assigned,
        total_assigned, senior_required, junior_required, english_required,
        predicted_volume, projected_csat, projected_wait,
        csat_meets_target, wait_meets_target
    """
    senior_ids = set(agents_df[agents_df["role_level"] == "Senior"]["agent_id"])
    english_ids = set(agents_df[agents_df["is_english"]]["agent_id"])

    rows = []
    for date in sorted(schedule_df["date"].unique()):
        day_schedule = schedule_df[schedule_df["date"] == date]

        for shift in SHIFT_IDS:
            shift_key = f"shift_{shift}"
            assigned = day_schedule[day_schedule["assignment"] == shift_key]["agent_id"]
            assigned_set = set(assigned)

            senior_count = len(assigned_set & senior_ids)
            junior_count = len(assigned_set) - senior_count
            english_count = len(assigned_set & english_ids)

            # Get requirements
            req_row = staffing_requirements[
                (staffing_requirements["date"] == date)
                & (staffing_requirements["shift"] == shift)
            ]
            if not req_row.empty:
                req = req_row.iloc[0]
                volume = int(req["predicted_volume"])
                sr_req = int(req["senior"])
                jr_req = int(req["junior"])
                eng_req = int(req["english"])
            else:
                volume, sr_req, jr_req, eng_req = 0, 0, 0, 0

            # Project quality
            csat, wait = predict_quality(
                quality_models, volume, senior_count, junior_count, english_count
            )

            rows.append(
                {
                    "date": date,
                    "shift": shift,
                    "shift_name": SHIFTS[shift]["name"],
                    "senior_assigned": senior_count,
                    "junior_assigned": junior_count,
                    "english_assigned": english_count,
                    "total_assigned": len(assigned_set),
                    "senior_required": sr_req,
                    "junior_required": jr_req,
                    "english_required": eng_req,
                    "predicted_volume": volume,
                    "projected_csat": round(csat, 2),
                    "projected_wait": round(wait, 1),
                    "csat_meets_target": csat >= CSAT_TARGET,
                    "wait_meets_target": wait <= MAX_WAIT_SECONDS,
                }
            )

    return pd.DataFrame(rows)


def build_agent_summary(
    schedule_df: pd.DataFrame,
    agents_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build per-agent summary: shift counts, leave counts, night shift counts."""
    rows = []
    for _, agent in agents_df.iterrows():
        aid = agent["agent_id"]
        agent_sched = schedule_df[schedule_df["agent_id"] == aid]

        shift_counts = {}
        for shift in SHIFT_IDS:
            shift_counts[f"shift_{shift}_count"] = len(
                agent_sched[agent_sched["assignment"] == f"shift_{shift}"]
            )

        leave_count = len(agent_sched[agent_sched["assignment"] == "leave"])

        rows.append(
            {
                "agent_id": aid,
                "name": agent["name"],
                "role_level": agent["role_level"],
                "is_english": agent["is_english"],
                **shift_counts,
                "leave_count": leave_count,
                "working_days": 30 - leave_count,
            }
        )

    return pd.DataFrame(rows)


def build_constraint_report(violations: list) -> pd.DataFrame:
    """Convert violation list to a summary DataFrame."""
    if not violations:
        return pd.DataFrame(
            columns=["constraint", "severity", "count", "sample_details"]
        )

    records = []
    from collections import Counter

    by_type = {}
    for v in violations:
        key = (v.constraint_name, v.severity)
        by_type.setdefault(key, []).append(v.details)

    for (name, severity), details in sorted(by_type.items()):
        records.append(
            {
                "constraint": name,
                "severity": severity,
                "count": len(details),
                "sample_details": details[0] if details else "",
            }
        )

    return pd.DataFrame(records)


def overall_quality_summary(shift_summary: pd.DataFrame) -> dict:
    """Compute overall quality statistics from shift summary."""
    return {
        "avg_projected_csat": round(shift_summary["projected_csat"].mean(), 2),
        "min_projected_csat": round(shift_summary["projected_csat"].min(), 2),
        "pct_csat_met": round(shift_summary["csat_meets_target"].mean() * 100, 1),
        "avg_projected_wait": round(shift_summary["projected_wait"].mean(), 1),
        "max_projected_wait": round(shift_summary["projected_wait"].max(), 1),
        "pct_wait_met": round(shift_summary["wait_meets_target"].mean() * 100, 1),
        "total_shifts": len(shift_summary),
        "shifts_both_targets_met": int(
            (
                shift_summary["csat_meets_target"] & shift_summary["wait_meets_target"]
            ).sum()
        ),
    }
