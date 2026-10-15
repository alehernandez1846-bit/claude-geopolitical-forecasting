# Claude Geopolitical Forecasting

An evaluation of how well Claude forecasts real-world geopolitical events.

**Question:** Can large language models give well-calibrated probability forecasts on conflicts, elections, and policy decisions?

**Method:**
- 100 yes/no questions across all world regions, written and committed on October 14, 2026, before any of them resolve
- Claude is asked each question multiple times, with and without a short news brief
- As questions resolve, forecasts are scored with Brier scores and calibration plots

**Files:**
- `questions_cleaned.csv`: the question set with resolution criteria
- `run_forecasts.py`: script that collects Claude's forecasts
- `forecasts.csv`: Claude's recorded forecasts (timestamped)

*Work in progress.*
