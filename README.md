# CS Demand Forecasting & Shift Scheduling

A production-ready tool for Customer Service shift scheduling that predicts staffing requirements and generates optimal monthly shift assignments for April 2026.

## Features

- **Demand Forecasting**: Gradient Boosting model predicts ticket volume per shift, then determines minimum staffing (Senior/Junior/English) to meet CSAT ≥ 4.0 and wait time ≤ 60s targets
- **Shift Scheduling**: Google OR-Tools CP-SAT solver assigns 50 agents to 4 shifts across 30 days, respecting all business constraints
- **Interactive Dashboard**: Streamlit UI with 5 tabs — Forecast, Schedule, Shift Summary, Constraints, Agents — with adjustable parameters and CSV export
- **Constraint Validation**: Full validation of hard constraints (leave, night rest, staffing) and soft constraints (shift continuity, night shift fairness)

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
├── app.py                          # Streamlit dashboard
├── src/
│   ├── config.py                   # Business constants, shift definitions, solver config
│   ├── data_loader.py              # Load agents, historical data, leave requests
│   ├── forecasting/
│   │   ├── feature_engineering.py  # Time features (day_of_week, cyclical, etc.)
│   │   ├── demand_model.py         # GradientBoosting volume forecaster
│   │   └── staffing_optimizer.py   # Quality models + minimum staffing solver
│   ├── scheduling/
│   │   ├── constraints.py          # Constraint definitions + validation
│   │   └── scheduler.py            # CP-SAT shift assignment engine
│   └── evaluation/
│       └── metrics.py              # Shift/agent summaries, quality projections
├── tests/
│   ├── test_data.py                # Data integrity tests
│   ├── test_forecasting.py         # Forecasting pipeline tests
│   └── test_scheduling.py         # Schedule constraint tests
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

**Results:** OPTIMAL solution, 0 hard constraint errors, ~37s total pipeline time

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
