"""Constraint definitions for the shift scheduling problem."""

from dataclasses import dataclass, field

import pandas as pd

from src.config import (
    DAYS_IN_APRIL,
    NIGHT_SHIFT,
    SHIFT_IDS,
    TOTAL_LEAVE_DAYS_PER_AGENT,
)


@dataclass
class SchedulingInput:
    """All inputs needed by the scheduler."""

    agents: pd.DataFrame
    staffing_requirements: pd.DataFrame  # date, shift, senior, junior, english
    leave_requests: pd.DataFrame  # pre-selected leaves
    num_days: int = DAYS_IN_APRIL

    @property
    def agent_ids(self) -> list[str]:
        return self.agents["agent_id"].tolist()

    @property
    def senior_ids(self) -> list[str]:
        return self.agents[self.agents["role_level"] == "Senior"]["agent_id"].tolist()

    @property
    def junior_ids(self) -> list[str]:
        return self.agents[self.agents["role_level"] == "Junior"]["agent_id"].tolist()

    @property
    def english_ids(self) -> list[str]:
        return self.agents[self.agents["is_english"]]["agent_id"].tolist()

    def get_pre_selected_leaves(self) -> dict[str, list[int]]:
        """Return {agent_id: [day_indices]} for pre-selected leaves.

        Day indices are 0-based (day 0 = April 1).
        """
        pre = self.leave_requests[self.leave_requests["leave_type"] == "pre_selected"]
        result: dict[str, list[int]] = {}
        for _, row in pre.iterrows():
            aid = row["agent_id"]
            day = row["leave_date"].day - 1  # 0-based
            result.setdefault(aid, []).append(day)
        return result

    def get_staffing_req(self, day: int, shift: int) -> dict:
        """Get staffing requirement for a specific day (0-based) and shift."""
        # day is 0-based, dates in staffing_requirements are datetime
        target_day = day + 1  # 1-based day of month
        row = self.staffing_requirements[
            (self.staffing_requirements["date"].dt.day == target_day) &
            (self.staffing_requirements["shift"] == shift)
        ]
        if row.empty:
            return {"senior": 0, "junior": 0, "english": 0}
        r = row.iloc[0]
        return {
            "senior": int(r["senior"]),
            "junior": int(r["junior"]),
            "english": int(r["english"]),
        }


@dataclass
class ConstraintViolation:
    """A record of a constraint that was violated."""

    constraint_name: str
    day: int  # 0-based
    details: str
    severity: str = "error"  # error or warning


def validate_schedule(
    schedule: dict[str, list[str]],
    scheduling_input: SchedulingInput,
) -> list[ConstraintViolation]:
    """Validate a completed schedule against all constraints.

    Args:
        schedule: {agent_id: [assignment_for_day_0, ..., assignment_for_day_29]}
                  where assignment is 'shift_1'..'shift_4' or 'leave'
        scheduling_input: the problem inputs

    Returns:
        list of constraint violations (empty = all constraints satisfied)
    """
    violations = []
    num_days = scheduling_input.num_days
    pre_leaves = scheduling_input.get_pre_selected_leaves()

    for agent_id in scheduling_input.agent_ids:
        assignments = schedule.get(agent_id, [])
        if len(assignments) != num_days:
            violations.append(ConstraintViolation(
                "schedule_completeness", -1,
                f"{agent_id}: expected {num_days} days, got {len(assignments)}"
            ))
            continue

        # Check total leave days = 6
        leave_days = [d for d in range(num_days) if assignments[d] == "leave"]
        if len(leave_days) != TOTAL_LEAVE_DAYS_PER_AGENT:
            violations.append(ConstraintViolation(
                "total_leave", -1,
                f"{agent_id}: has {len(leave_days)} leave days, expected {TOTAL_LEAVE_DAYS_PER_AGENT}"
            ))

        # Check pre-selected leaves honored
        for day in pre_leaves.get(agent_id, []):
            if day < num_days and assignments[day] != "leave":
                violations.append(ConstraintViolation(
                    "pre_selected_leave", day,
                    f"{agent_id}: pre-selected leave on day {day+1} not honored"
                ))

        # Check night shift rest rule
        for d in range(num_days - 1):
            if assignments[d] == "shift_4" and assignments[d + 1] != "leave":
                violations.append(ConstraintViolation(
                    "night_rest", d,
                    f"{agent_id}: worked night shift day {d+1}, not on leave day {d+2}"
                ))

        # Check exactly one assignment per day
        for d in range(num_days):
            if assignments[d] not in ("shift_1", "shift_2", "shift_3", "shift_4", "leave"):
                violations.append(ConstraintViolation(
                    "valid_assignment", d,
                    f"{agent_id}: invalid assignment '{assignments[d]}' on day {d+1}"
                ))

    # Check minimum staffing per shift per day
    for d in range(num_days):
        for shift in SHIFT_IDS:
            shift_key = f"shift_{shift}"
            req = scheduling_input.get_staffing_req(d, shift)

            assigned_agents = [
                aid for aid in scheduling_input.agent_ids
                if schedule.get(aid, [""] * num_days)[d] == shift_key
            ]

            senior_count = sum(1 for a in assigned_agents if a in scheduling_input.senior_ids)
            junior_count = sum(1 for a in assigned_agents if a in scheduling_input.junior_ids)
            english_count = sum(1 for a in assigned_agents if a in scheduling_input.english_ids)

            if senior_count < req["senior"]:
                violations.append(ConstraintViolation(
                    "min_senior_staffing", d,
                    f"Day {d+1} Shift {shift}: {senior_count} seniors, need {req['senior']}",
                    severity="warning",
                ))
            if junior_count < req["junior"]:
                violations.append(ConstraintViolation(
                    "min_junior_staffing", d,
                    f"Day {d+1} Shift {shift}: {junior_count} juniors, need {req['junior']}",
                    severity="warning",
                ))
            if english_count < req["english"]:
                violations.append(ConstraintViolation(
                    "min_english_staffing", d,
                    f"Day {d+1} Shift {shift}: {english_count} english, need {req['english']}",
                    severity="warning",
                ))

    # Check shift continuity (soft — as warnings)
    for agent_id in scheduling_input.agent_ids:
        assignments = schedule.get(agent_id, [])
        for d in range(num_days - 1):
            if assignments[d].startswith("shift_") and assignments[d + 1].startswith("shift_"):
                s1 = int(assignments[d].split("_")[1])
                s2 = int(assignments[d + 1].split("_")[1])
                if abs(s1 - s2) >= 3:
                    violations.append(ConstraintViolation(
                        "shift_continuity", d,
                        f"{agent_id}: shift {s1} on day {d+1} → shift {s2} on day {d+2}",
                        severity="warning",
                    ))

    return violations
