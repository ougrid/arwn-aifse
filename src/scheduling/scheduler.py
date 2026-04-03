"""CP-SAT based shift scheduler using Google OR-Tools."""

import logging
from dataclasses import dataclass

import pandas as pd
from ortools.sat.python import cp_model

from src.config import (
    DAYS_IN_APRIL,
    NIGHT_SHIFT,
    SHIFT_IDS,
    TOTAL_LEAVE_DAYS_PER_AGENT,
    SchedulingConfig,
)
from src.scheduling.constraints import SchedulingInput

logger = logging.getLogger(__name__)


@dataclass
class ScheduleResult:
    """Output of the scheduling solver."""

    schedule: dict[str, list[str]]  # {agent_id: [assignment per day]}
    status: str  # OPTIMAL, FEASIBLE, INFEASIBLE
    solve_time: float
    objective_value: float | None


def build_and_solve(
    inputs: SchedulingInput,
    config: SchedulingConfig | None = None,
) -> ScheduleResult:
    """Build and solve the shift scheduling problem using CP-SAT.

    Decision variables:
        work[a, d, s] ∈ {0, 1} — agent a works shift s on day d
        leave[a, d] ∈ {0, 1} — agent a is on leave on day d
    """
    if config is None:
        config = SchedulingConfig()

    model = cp_model.CpModel()
    num_days = inputs.num_days
    agents = inputs.agent_ids
    seniors = set(inputs.senior_ids)
    juniors = set(inputs.junior_ids)
    english = set(inputs.english_ids)
    pre_leaves = inputs.get_pre_selected_leaves()

    num_agents = len(agents)
    agent_idx = {a: i for i, a in enumerate(agents)}

    # --- Decision Variables ---
    work = {}
    for a in agents:
        for d in range(num_days):
            for s in SHIFT_IDS:
                work[a, d, s] = model.new_bool_var(f"work_{a}_{d}_{s}")

    leave = {}
    for a in agents:
        for d in range(num_days):
            leave[a, d] = model.new_bool_var(f"leave_{a}_{d}")

    # --- Hard Constraints ---

    # C1: Each agent has exactly one assignment per day (one shift or leave)
    for a in agents:
        for d in range(num_days):
            model.add_exactly_one(
                [work[a, d, s] for s in SHIFT_IDS] + [leave[a, d]]
            )

    # C2: Total leave days = 6 per agent
    for a in agents:
        model.add(
            sum(leave[a, d] for d in range(num_days)) == TOTAL_LEAVE_DAYS_PER_AGENT
        )

    # C3: Pre-selected leaves must be honored
    for a in agents:
        for d in pre_leaves.get(a, []):
            if d < num_days:
                model.add(leave[a, d] == 1)

    # C4: Night shift rest rule — night shift on day d → leave on day d+1
    for a in agents:
        for d in range(num_days - 1):
            model.add_implication(work[a, d, NIGHT_SHIFT], leave[a, d + 1])

    # C5: Minimum staffing per shift per day
    for d in range(num_days):
        for s in SHIFT_IDS:
            req = inputs.get_staffing_req(d, s)

            # Senior staffing
            if req["senior"] > 0:
                model.add(
                    sum(work[a, d, s] for a in agents if a in seniors) >= req["senior"]
                )

            # Junior staffing
            if req["junior"] > 0:
                model.add(
                    sum(work[a, d, s] for a in agents if a in juniors) >= req["junior"]
                )

            # English staffing
            if req["english"] > 0:
                model.add(
                    sum(work[a, d, s] for a in agents if a in english) >= req["english"]
                )

    # C6: Daily leave cap — ensure enough agents are available
    # Calculate max agents that can be on leave any day
    # (total agents minus sum of max per-shift requirements across all shifts)
    max_daily_req = 0
    for s in SHIFT_IDS:
        max_req = 0
        for d in range(num_days):
            req = inputs.get_staffing_req(d, s)
            total = req["senior"] + req["junior"]
            max_req = max(max_req, total)
        max_daily_req += max_req

    daily_leave_cap = max(6, num_agents - max_daily_req)
    logger.info(f"Daily leave cap: {daily_leave_cap} (max daily requirement: {max_daily_req})")

    for d in range(num_days):
        model.add(
            sum(leave[a, d] for a in agents) <= daily_leave_cap
        )

    # --- Soft Constraints (Objective) ---
    objective_terms = []

    # Soft 1: Shift continuity — penalize large shift transitions
    if config.shift_continuity_weight > 0:
        for a in agents:
            for d in range(num_days - 1):
                for s1 in SHIFT_IDS:
                    for s2 in SHIFT_IDS:
                        penalty = config.shift_transition_penalties.get((s1, s2), 0)
                        if penalty > 0:
                            # Both[a,d,s1] and work[a,d+1,s2] are true
                            both = model.new_bool_var(f"trans_{a}_{d}_{s1}_{s2}")
                            model.add_bool_and([work[a, d, s1], work[a, d + 1, s2]]).only_enforce_if(both)
                            model.add_bool_or([work[a, d, s1].negated(), work[a, d + 1, s2].negated()]).only_enforce_if(both.negated())
                            objective_terms.append(both * penalty * config.shift_continuity_weight)

    # Soft 2: Night shift fairness — minimize max night shifts across agents
    if config.night_fairness_weight > 0:
        night_counts = {}
        for a in agents:
            night_counts[a] = sum(work[a, d, NIGHT_SHIFT] for d in range(num_days))

        max_nights = model.new_int_var(0, num_days, "max_nights")
        min_nights = model.new_int_var(0, num_days, "min_nights")
        for a in agents:
            model.add(max_nights >= night_counts[a])
            model.add(min_nights <= night_counts[a])

        night_spread = model.new_int_var(0, num_days, "night_spread")
        model.add(night_spread == max_nights - min_nights)
        objective_terms.append(night_spread * config.night_fairness_weight)

    # Soft 3: Minimize overstaffing (sum of staff above requirement)
    if config.overstaffing_weight > 0:
        for d in range(num_days):
            for s in SHIFT_IDS:
                req = inputs.get_staffing_req(d, s)
                total_req = req["senior"] + req["junior"]
                total_assigned = sum(work[a, d, s] for a in agents)
                overstaffing = model.new_int_var(0, num_agents, f"over_{d}_{s}")
                model.add(overstaffing >= total_assigned - total_req)
                objective_terms.append(overstaffing * config.overstaffing_weight)

    # Set objective: minimize total penalty
    if objective_terms:
        model.minimize(sum(objective_terms))

    # --- Solve ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.solver_time_limit
    solver.parameters.num_workers = 4
    solver.parameters.log_search_progress = False

    logger.info(f"Solving scheduling problem: {num_agents} agents × {num_days} days × {len(SHIFT_IDS)} shifts")

    status = solver.solve(model)

    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }.get(status, "UNKNOWN")

    logger.info(f"Solver status: {status_name}, time: {solver.wall_time:.1f}s")

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        schedule = {}
        for a in agents:
            assignments = []
            for d in range(num_days):
                if solver.value(leave[a, d]):
                    assignments.append("leave")
                else:
                    for s in SHIFT_IDS:
                        if solver.value(work[a, d, s]):
                            assignments.append(f"shift_{s}")
                            break
                    else:
                        assignments.append("unassigned")
            schedule[a] = assignments

        return ScheduleResult(
            schedule=schedule,
            status=status_name,
            solve_time=solver.wall_time,
            objective_value=solver.objective_value if objective_terms else None,
        )

    return ScheduleResult(
        schedule={},
        status=status_name,
        solve_time=solver.wall_time,
        objective_value=None,
    )


def schedule_to_dataframe(result: ScheduleResult, year: int = 2026, month: int = 4) -> pd.DataFrame:
    """Convert schedule dict to a DataFrame in the required output format."""
    rows = []
    for agent_id, assignments in result.schedule.items():
        for d, assignment in enumerate(assignments):
            date = pd.Timestamp(year=year, month=month, day=d + 1)
            rows.append({
                "date": date,
                "agent_id": agent_id,
                "assignment": assignment,
            })

    df = pd.DataFrame(rows)
    df = df.sort_values(["date", "agent_id"]).reset_index(drop=True)
    return df
