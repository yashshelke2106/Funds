# Closet Indexing in Indian Large-Cap Mutual Funds

**Question:** Which SEBI large-cap active funds effectively track the index while charging active fees, and what does that cost investors?
**Audience:** the product/research team at an Indian wealth platform, deciding which funds to flag or drop.
**Status:** Phase 1 (setup and acquisition) is built. Results: *pending*.

## Run

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run_pipeline.py            # universe -> nav -> quality -> checklist -> tests
python run_pipeline.py --offline  # rebuild from cached raw files, no network
```

## Layout

```
data/raw/          gitignored; AMFI files, mfapi JSON, per-AMC portfolio files, TER, benchmark
data/reference/    scheme_map.csv, scheme_events.csv (survivorship), universe.csv, download_checklist.csv
data/interim/      nav.parquet (gitignored)
data/quality/      nav_issues.csv, fetch errors (gitignored)
src/ingest/        amfi.py (AMFI parsers), universe.py, nav.py (mfapi), checklist.py
src/quality/       nav_checks.py
src/metrics/       (P4)
sql/               staging / intermediate / marts (P3)
tests/             pytest; fixtures are verbatim excerpts of real source files
DECISIONS.md       every judgement call, with the alternatives considered
docs/              download_checklist.md, interview_defense.md (P7)
```

## Study design (details in DECISIONS.md)

- **Universe:** every AMFI "Large Cap Fund" scheme with Direct and Regular Growth plans (34 today),
  derived from AMFI, not hand-picked. Funds whose NAV history doesn't cover the window are excluded and listed.
- **Window:** NAV metrics Sep-2024 … Aug-2026 (NAVs from Sep-2023 for rolling 12-month tracking error); holdings Sep-2025 … Aug-2026 (D-011).
- **Separate report:** eligible funds without the 12-month lookback (Bajaj Finserv) are reported apart from the main ranking (D-012).
- **Survivorship:** scheme codes in AMFI's 02-Sep-2024 snapshot compared with today's.
- **Look-ahead:** month M's holdings count as known only from day 11 of month M+1.

## Limitations (added to as the project goes)

- Benchmark weights come from a Nifty 100 index fund's disclosed portfolio (a proxy, not NSE constituent weights).
- Portfolio disclosures are monthly snapshots: intra-month trading, and any month-end window dressing, can't be seen.
- NAV gap checks count weekdays, not NSE trading days.
- Every fund is measured against the Nifty 100 TRI, though some state the BSE 100 TRI as their benchmark (D-021).
- Active share uses one month-end snapshot per month; the portfolio of month M is treated as known only from the 11th of M+1 (D-009).
