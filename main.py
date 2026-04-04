"""Main entry point — runs the full forecasting + scheduling pipeline."""

import logging
import sys
import time

import pandas as pd

from src.config import SchedulingConfig
from src.data_loader import load_all_data
from src.evaluation.metrics import (
    build_agent_summary,
    build_constraint_report,
    build_shift_summary,
    overall_quality_summary,
)
from src.evaluation.fairness import compute_fairness_metrics
from src.evaluation.remediation import build_remediation_report
from src.forecasting.demand_model import train_volume_model, predict_april_volume
from src.forecasting.staffing_optimizer import (
    compute_staffing_requirements,
    train_quality_models,
)
from src.scheduling.constraints import SchedulingInput, validate_schedule
from src.scheduling.scheduler import build_and_solve, schedule_to_dataframe
from src.scheduling.preferences import (
    generate_shift_preferences,
    preference_satisfaction_score,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run_pipeline(
    csat_target: float = 4.0,
    max_wait: float = 60.0,
    solver_time_limit: int = 120,
) -> dict:
    """Run the complete forecasting and scheduling pipeline.

    Returns a dict with all results for use by the Streamlit UI.
    """
    t_start = time.time()

    # --- Load data ---
    logger.info("Loading data...")
    data = load_all_data()

    # --- Demand Forecasting ---
    logger.info("Training volume forecasting model...")
    forecast_result = train_volume_model(data["historical"])
    logger.info(
        f"Volume model — Val MAE: {forecast_result.model_metrics['val_mae']:.1f}, "
        f"Val R²: {forecast_result.model_metrics['val_r2']:.3f}"
    )

    logger.info("Predicting April 2026 ticket volumes...")
    volume_predictions = predict_april_volume(forecast_result)

    logger.info("Training quality models (CSAT + wait time)...")
    quality_models = train_quality_models(data["historical"])
    logger.info(
        f"Quality models — CSAT R²: {quality_models.csat_r2:.3f}, "
        f"Wait R²: {quality_models.wait_r2:.3f}"
    )

    logger.info("Computing staffing requirements...")
    staffing_req = compute_staffing_requirements(
        volume_predictions,
        quality_models,
        data["historical"],
        csat_target=csat_target,
        max_wait=max_wait,
    )

    # --- Shift Scheduling ---
    logger.info("Generating agent shift preferences...")
    preferences = generate_shift_preferences(data["agents"])

    logger.info("Building and solving shift schedule...")
    inputs = SchedulingInput(
        agents=data["agents"],
        staffing_requirements=staffing_req,
        leave_requests=data["leave_requests"],
    )

    config = SchedulingConfig(
        solver_time_limit=solver_time_limit,
        shift_continuity_weight=0,  # disabled for solver performance
        night_fairness_weight=5,
        overstaffing_weight=1,
    )

    schedule_result = build_and_solve(inputs, config, preferences=preferences)
    logger.info(
        f"Solver status: {schedule_result.status} ({schedule_result.solve_time:.1f}s)"
    )

    if not schedule_result.schedule:
        logger.error("Scheduling failed — no feasible solution found.")
        return {
            "status": schedule_result.status,
            "error": "No feasible schedule found. Try relaxing quality targets.",
        }

    # --- Convert to DataFrames ---
    schedule_df = schedule_to_dataframe(schedule_result)

    # --- Validation ---
    logger.info("Validating schedule constraints...")
    violations = validate_schedule(schedule_result.schedule, inputs)
    errors = [v for v in violations if v.severity == "error"]
    warnings = [v for v in violations if v.severity == "warning"]
    logger.info(f"Constraint check: {len(errors)} errors, {len(warnings)} warnings")

    # --- Evaluation ---
    logger.info("Building evaluation summaries...")
    shift_summary = build_shift_summary(
        schedule_df,
        data["agents"],
        staffing_req,
        quality_models,
    )
    agent_summary = build_agent_summary(schedule_df, data["agents"])
    constraint_report = build_constraint_report(violations)
    quality_summary = overall_quality_summary(shift_summary)

    # Preference satisfaction
    pref_summary = preference_satisfaction_score(schedule_result.schedule, preferences)
    logger.info(
        f"Preference satisfaction: {pref_summary['satisfaction_pct']}% "
        f"(avg pref score: {pref_summary['overall_avg_preference']})"
    )

    # Fairness metrics
    fairness = compute_fairness_metrics(agent_summary)
    logger.info(
        f"Fairness grade: {fairness['fairness_grade']} "
        f"(night Gini: {fairness['night_shift_gini']}, "
        f"composite: {fairness['composite_score']})"
    )

    # Remediation suggestions
    remediation = build_remediation_report(violations)

    elapsed = time.time() - t_start
    logger.info(f"Pipeline complete in {elapsed:.1f}s")

    return {
        "status": schedule_result.status,
        "solve_time": schedule_result.solve_time,
        "total_time": elapsed,
        # DataFrames
        "agents": data["agents"],
        "historical": data["historical"],
        "volume_predictions": volume_predictions,
        "staffing_requirements": staffing_req,
        "schedule_df": schedule_df,
        "shift_summary": shift_summary,
        "agent_summary": agent_summary,
        "constraint_report": constraint_report,
        # Summaries
        "quality_summary": quality_summary,
        "forecast_metrics": forecast_result.model_metrics,
        "quality_model_metrics": {
            "csat_r2": quality_models.csat_r2,
            "wait_r2": quality_models.wait_r2,
        },
        "violations": violations,
        "num_errors": len(errors),
        "num_warnings": len(warnings),
        "preferences": preferences,
        "preference_summary": pref_summary,
        "fairness": fairness,
        "remediation": remediation,
    }


def print_results(results: dict) -> None:
    """Print a summary of pipeline results to stdout."""
    import sys
    import io

    # Handle Windows console encoding for emoji
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )

    if "error" in results:
        print(f"\n❌ {results['error']}")
        return

    print("\n" + "=" * 70)
    print("CS SHIFT SCHEDULING — RESULTS SUMMARY")
    print("=" * 70)

    qs = results["quality_summary"]
    print(f"\n📊 Schedule Quality:")
    print(f"  Avg projected CSAT:  {qs['avg_projected_csat']} (target ≥ 4.0)")
    print(f"  Min projected CSAT:  {qs['min_projected_csat']}")
    print(f"  Shifts meeting CSAT: {qs['pct_csat_met']}%")
    print(f"  Avg projected wait:  {qs['avg_projected_wait']}s (target ≤ 60s)")
    print(f"  Max projected wait:  {qs['max_projected_wait']}s")
    print(f"  Shifts meeting wait: {qs['pct_wait_met']}%")
    print(
        f"  Both targets met:    {qs['shifts_both_targets_met']}/{qs['total_shifts']} shifts"
    )

    print(f"\n🔍 Constraint Validation:")
    print(f"  Hard constraint errors: {results['num_errors']}")
    print(f"  Soft constraint warnings: {results['num_warnings']}")

    fm = results["forecast_metrics"]
    print(f"\n📈 Model Performance:")
    print(f"  Volume model — MAE: {fm['val_mae']:.1f}, R²: {fm['val_r2']:.3f}")
    qm = results["quality_model_metrics"]
    print(f"  CSAT model R²: {qm['csat_r2']:.3f}")
    print(f"  Wait model R²: {qm['wait_r2']:.3f}")

    print(f"\n⏱️  Solver: {results['status']} in {results['solve_time']:.1f}s")
    print(f"  Total pipeline: {results['total_time']:.1f}s")

    # Staffing summary by shift
    ss = results["shift_summary"]
    print(f"\n📋 Average Daily Staffing by Shift:")
    for shift in [1, 2, 3, 4]:
        s = ss[ss["shift"] == shift]
        print(
            f"  Shift {shift} ({s['shift_name'].iloc[0]:>9}): "
            f"Sr={s['senior_assigned'].mean():.1f} "
            f"Jr={s['junior_assigned'].mean():.1f} "
            f"Eng={s['english_assigned'].mean():.1f} "
            f"Total={s['total_assigned'].mean():.1f} "
            f"| CSAT={s['projected_csat'].mean():.2f} "
            f"Wait={s['projected_wait'].mean():.1f}s"
        )

    # Agent night shift distribution
    agent_sum = results["agent_summary"]
    print(f"\n🌙 Night Shift Distribution:")
    night_counts = agent_sum["shift_4_count"]
    print(
        f"  Min: {night_counts.min()}, Max: {night_counts.max()}, "
        f"Mean: {night_counts.mean():.1f}, Std: {night_counts.std():.1f}"
    )

    # Fairness metrics
    fairness = results["fairness"]
    print(f"\n⚖️  Fairness Metrics:")
    print(
        f"  Grade: {fairness['fairness_grade']} (composite: {fairness['composite_score']})"
    )
    print(f"  Night shift Gini: {fairness['night_shift_gini']} (0=perfect equality)")
    print(f"  Workload Gini: {fairness['workload_gini']}")
    print(
        f"  Shift entropy: {fairness['shift_entropy_avg']:.3f}/{fairness['shift_entropy_max']:.3f}"
    )

    # Preference satisfaction
    pref = results["preference_summary"]
    print(f"\n💜 Shift Preference Satisfaction:")
    print(f"  Overall: {pref['satisfaction_pct']}%")
    print(
        f"  Preferred assignments: {pref['preferred_assignments']}/{pref['total_working_shifts']}"
    )
    print(
        f"  Avoided assignments: {pref['avoided_assignments']}/{pref['total_working_shifts']}"
    )

    # Remediation suggestions
    remediation = results.get("remediation", [])
    if remediation:
        print(f"\n🔧 Remediation Suggestions:")
        for r in remediation:
            print(f"  [{r['severity'].upper()}] {r['constraint']} ({r['count']}x):")
            print(f"    → {r['remediation']}")


def main():
    results = run_pipeline()
    print_results(results)

    # Export schedule
    if "schedule_df" in results:
        output_path = "output_schedule_apr2026.csv"
        results["schedule_df"].to_csv(output_path, index=False)
        logger.info(f"Schedule exported to {output_path}")

        summary_path = "output_shift_summary_apr2026.csv"
        results["shift_summary"].to_csv(summary_path, index=False)
        logger.info(f"Shift summary exported to {summary_path}")


if __name__ == "__main__":
    main()
