# Manual download checklist

The pipeline downloads AMFI and mfapi data itself. Everything below has to be downloaded by hand,
because AMCs publish portfolios on their own websites in their own formats.

`python run_pipeline.py checklist` writes **`data/reference/download_checklist.csv`**: one row per
(AMC, month), with `status` recomputed from what is on disk. Rerun it after each download session.

## 1. Monthly portfolio disclosures — P2 blocker

- **Which AMCs:** every AMC with an eligible fund in `data/reference/universe.csv`, plus the benchmark-weight index fund,
  which is chosen in code (`data/reference/benchmark_proxy_selection.csv`; first run: **Bandhan Nifty 100 Index Fund**). Make sure
  every Bandhan monthly file includes that scheme.
- **Months:** Sep-2025 … Aug-2026 (12 files per AMC; see DECISIONS D-011).
- **Where:** the AMC's own "Statutory disclosures → Monthly portfolio" page. Download the
  **month-end** portfolio, not the fortnightly one.
- **Save as:** `data/raw/portfolios/<amc_slug>/<original filename>`. The month is read from inside the file
  (D-018). Adding a `YYYY-MM__` prefix is optional; if you add one, it must match the file's "as on" date.
  The `amc_slug` is in the checklist CSV (for example `hdfc`, `icici_prudential`, `aditya_birla_sun_life`).
  **Keep the original filename after `__` and don't edit the file.**
- If an AMC puts all schemes in one workbook, save that one workbook. If it publishes one file per
  scheme, save only the large-cap fund's file (and the Nifty 100 fund's file for the benchmark AMC).
- If a month is missing on the AMC site, **don't substitute another month**. Leave it missing and note it
  in `data/reference/portfolio_gaps.csv` (columns: `amc_slug,month,reason,checked_on`).

**Before P2 parsers are written:** upload **one** file per AMC (any month) so I can inspect its layout.
Start with 3 AMCs, then batch the rest.

## 2. TER (expense ratios)

- AMFI → "Total Expense Ratio of Mutual Fund Schemes". Export the **daily or month-end TER** for
  every eligible scheme (Direct and Regular) and the Nifty 100 index funds, Sep-2024 … Aug-2026.
- Save in `data/raw/ter/` with the original filenames. Upload one sample before P2 TER parsing.

## 3. Benchmark returns — Nifty 100 TRI

- niftyindices.com → Historical Data → Total Returns Index → NIFTY 100, from 01-Sep-2023 to 31-Aug-2026.
- Save the CSV(s) in `data/raw/benchmark/`.
- If you can't get it, tell me: the fallback is the index fund's NAV (DECISIONS D-010), recorded as a
  limitation.

## 4. Automatic (no action)

| Data | Source | Saved to |
|---|---|---|
| Current scheme list | AMFI NAVAll.txt | `data/raw/amfi/NAVAll_<date>.txt` |
| Window-start snapshot | AMFI NAV history report, 02-Sep-2024 | `data/raw/amfi/NAVHistory_2024-09-02.txt` |
| Daily NAVs | api.mfapi.in | `data/raw/nav/<scheme_code>.json` |
