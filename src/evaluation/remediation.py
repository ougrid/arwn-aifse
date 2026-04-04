"""Constraint remediation — generates actionable suggestions for violations."""

from src.config import SHIFTS
from src.scheduling.constraints import ConstraintViolation


def generate_remediation(violation: ConstraintViolation) -> str:
    """Generate an actionable remediation suggestion for a constraint violation."""
    name = violation.constraint_name
    day_str = f"day {violation.day + 1}" if violation.day >= 0 else ""

    remediations = {
        "total_leave": (
            "Adjust system-assigned leave days for this agent. "
            "Check if night rest days are consuming too many leave slots."
        ),
        "pre_selected_leave": (
            f"Override conflict on {day_str}: either honor the pre-selected leave "
            "or negotiate an alternative date with the agent."
        ),
        "night_rest": (
            f"On {day_str}: reassign the agent from night shift to an earlier shift, "
            "or ensure the following day is marked as leave."
        ),
        "valid_assignment": (
            "Data integrity issue. Re-run the scheduler or check for corrupted schedule data."
        ),
        "schedule_completeness": (
            "Agent is missing assignments for some days. Re-run the scheduler."
        ),
        "min_senior_staffing": (
            f"On {day_str}: move a senior agent from a lower-demand shift to this one, "
            "or reduce the senior requirement by 1 if quality projections allow."
        ),
        "min_junior_staffing": (
            f"On {day_str}: redistribute junior agents from overstaffed shifts, "
            "move a system-assigned leave day away from this date, "
            "or consider reducing the junior requirement."
        ),
        "min_english_staffing": (
            f"On {day_str}: reassign an English-capable agent from another shift. "
            "English agents are scarce (8 total), so consider reducing English "
            "requirements for low-volume shifts."
        ),
        "shift_continuity": (
            f"On {day_str}: swap shift assignments with another agent who has a "
            "complementary pattern, or insert a transition shift between the jumps."
        ),
    }

    return remediations.get(
        name, "Review the constraint and adjust staffing or leave assignments."
    )


def build_remediation_report(
    violations: list[ConstraintViolation],
) -> list[dict]:
    """Build a remediation report with suggestions for each violation type.

    Groups violations by type and generates remediation suggestions.
    Returns a list of dicts suitable for display in the dashboard.
    """
    if not violations:
        return []

    # Group by constraint name
    by_type: dict[str, list[ConstraintViolation]] = {}
    for v in violations:
        by_type.setdefault(v.constraint_name, []).append(v)

    report = []
    for name, group in sorted(by_type.items()):
        errors = [v for v in group if v.severity == "error"]
        warnings = [v for v in group if v.severity == "warning"]
        sample = group[0]

        # Get affected days
        days = sorted(set(v.day + 1 for v in group if v.day >= 0))
        days_str = ", ".join(str(d) for d in days[:10])
        if len(days) > 10:
            days_str += f" ... ({len(days)} total)"

        report.append(
            {
                "constraint": name,
                "severity": "error" if errors else "warning",
                "count": len(group),
                "affected_days": days_str if days else "N/A",
                "sample": sample.details,
                "remediation": generate_remediation(sample),
            }
        )

    return report
