# CS Demand Forecasting & Shift Scheduling

A production-ready tool for Customer Service shift scheduling that predicts staffing requirements and generates optimal monthly shift assignments for April 2026.

## Features

- **Demand Forecasting**: Gradient Boosting model predicts ticket volume per shift, then determines minimum staffing (Senior/Junior/English) to meet CSAT ≥ 4.0 and wait time ≤ 60s targets
- **Shift Scheduling**: Google OR-Tools CP-SAT solver assigns 50 agents to 4 shifts across 30 days, respecting all business constraints
- **Interactive Dashboard**: Streamlit UI with 7 tabs — Forecast, Schedule, Shift Summary, Constraints, Agents, Fairness, Preferences — with adjustable parameters and CSV export
- **Constraint Validation**: Full validation of hard constraints (leave, night rest, staffing) and soft constraints (shift continuity, night shift fairness), with actionable remediation suggestions
- **Agent Shift Preferences**: Synthetic preference generation based on agent attributes (role, language), integrated as soft objective in the scheduler with satisfaction tracking
- **Fairness Metrics**: Gini coefficient for night shift and workload equity, shift entropy for variety, composite fairness grade (A–F)
- **Remediation Suggestions**: Actionable remediation for each constraint violation type, grouped by category in the dashboard

## Quick Start

### Prerequisites

- Python 3.11+

### Installation

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e .
```

### Run the Pipeline (CLI)

```bash
python main.py
```

Outputs:
- `output_schedule_apr2026.csv` — Full agent schedule
- `output_shift_summary_apr2026.csv` — Shift-level summary with projected quality

### Run the Dashboard

```bash
streamlit run app.py
```

Opens at http://localhost:8501 with interactive controls for CSAT target, max wait time, and solver time limit.

### Run Tests

```bash
pytest tests/ -v
```

## Architecture

```
├── main.py                         # CLI entry point — runs full pipeline
├── app.py                          # Streamlit dashboard (7 tabs)
├── src/
│   ├── config.py                   # Business constants, shift definitions, solver config
│   ├── data_loader.py              # Load agents, historical data, leave requests
│   ├── forecasting/
│   │   ├── feature_engineering.py  # Time features (day_of_week, cyclical, etc.)
│   │   ├── demand_model.py         # GradientBoosting volume forecaster
│   │   └── staffing_optimizer.py   # Quality models + minimum staffing solver
│   ├── scheduling/
│   │   ├── constraints.py          # Constraint definitions + validation
│   │   ├── scheduler.py            # CP-SAT shift assignment engine
│   │   └── preferences.py          # Agent shift preference generation & scoring
│   └── evaluation/
│       ├── metrics.py              # Shift/agent summaries, quality projections
│       ├── fairness.py             # Gini coefficient, fairness grading
│       └── remediation.py          # Actionable remediation suggestions
├── tests/
│   ├── test_data.py                # Data integrity tests
│   ├── test_forecasting.py         # Forecasting pipeline tests
│   ├── test_scheduling.py          # Schedule constraint tests
│   └── test_bonus.py               # Preferences, fairness, remediation tests
└── data/                           # Input data files
```

## Approach

### Task A: Demand Forecasting (Two-Stage)

**Stage 1 — Volume Prediction:**
- GradientBoostingRegressor trained on 6 months of historical shift data (Oct 2025 – Mar 2026)
- Features: day of week, day of month, weekend flag, cyclical month encoding, shift ID
- Time-based validation split (last month held out)
- Results: R² = 0.927, MAE = 19.7 tickets

**Stage 2 — Staffing Optimization:**
- Separate CSAT and wait-time regression models trained on historical (volume, senior, junior, english) → quality
- For each predicted shift volume, vectorized grid search finds minimum staffing that satisfies CSAT ≥ 4.0 AND wait ≤ 60s
- Historical staffing floors (10th percentile from shifts meeting targets) prevent under-staffing from model extrapolation
- Feasibility caps account for agent pool sizes and leave rates (critical for English agents: 8 total, ~6.4 available/day)

### Task B: Shift Scheduling (Constraint Programming)

**Engine:** Google OR-Tools CP-SAT solver

**Hard Constraints:**
1. Exactly one assignment per agent per day (shift or leave)
2. Each agent gets exactly 6 leave days
3. All 3 pre-selected leave dates honored
4. Night shift (00:00–06:00) followed by mandatory rest day (counts as leave)
5. Minimum staffing per shift by category (Senior, Junior, English)
6. Daily leave cap (max 19 agents on leave)

**Soft Constraints (Objective):**
- Night shift fairness: minimize variance in night shifts across agents (weight=5)
- Overstaffing penalty: minimize excess beyond minimum requirements (weight=1)
- Agent shift preferences: minimize assignments to disliked shifts (weight=1)

**Results:** FEASIBLE solution, 0 hard constraint errors, ~71s total pipeline time

### Bonus Features

**Agent Shift Preferences:** Generates realistic synthetic preferences (1=strongly prefer, 5=strongly avoid) based on agent role, language capability, and individual variation. Integrated as a soft constraint in the CP-SAT objective. Typical satisfaction: ~82%.

**Fairness Metrics:** Gini coefficient measures equality in night shift distribution and overall workload. Shift entropy measures variety of shift types per agent. Composite score (0-100) with letter grade (A-F). Night shift Gini is weighted by sparsity — with ~80 night slots across 50 agents, some inequality is mathematically inevitable.

**Constraint Remediation:** Each constraint violation is mapped to an actionable suggestion (e.g., "move a senior agent from a lower-demand shift" for staffing shortfalls). Violations are grouped by type in the dashboard with expandable remediation details.

## Key Assumptions

1. All 50 agents are available for the full month (no long-term leave)
2. Each agent works exactly one 8-hour shift per working day
3. Night rest days count toward the 6-day monthly leave allowance
4. English CS agents count toward both their role-level and English requirements simultaneously
5. Quality models (CSAT, wait time) from historical data generalize to April 2026
6. April 2026 has 30 days

## Technology Stack

| Component | Technology |
|---|---|
| Forecasting | scikit-learn GradientBoostingRegressor |
| Scheduling | Google OR-Tools CP-SAT |
| Dashboard | Streamlit + Plotly |
| Data | pandas, numpy |
| Testing | pytest |
