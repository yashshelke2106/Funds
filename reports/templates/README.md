# Closet Indexing in Indian Large-Cap Mutual Funds

**Question.** Which SEBI large-cap active funds effectively track the index while charging active fees, and what does that cost investors?

**Audience.** The product and research team at an Indian wealth platform deciding which funds to flag or drop.

**Answer.** [`reports/memo.md`](reports/memo.md): flag {{n_low}} funds, drop none, pause one for new regular-plan money.

Everything here is built from public files (AMFI, AMC websites, niftyindices.com). No synthetic or simulated data is used anywhere.

## Result in five lines

- {{n_low}} of {{n_classified}} funds with portfolios in scope have an active share below {{threshold}} against the Nifty 100. They hold {{low_aaum_share}}% of the group's regular-plan assets.
- Their regular-plan investors pay {{low_fee_min}} to {{low_fee_max}} percentage points a year above a Nifty 100 index fund's regular plan: ₹{{low_cr}} cr a year at Q4 FY26 assets.
- Low active share did not mean worse returns in this window: {{n_closet}} of the {{n_low}} beat the Nifty 100 TRI after regular-plan fees over 24 months, and {{active_neg24}} of the {{n_active}} more active funds trailed it.
- One fund, {{flag_fund}}, is below the threshold and behind the index on all {{n_variants}} test variants ({{flag_xs_reg_24}}% a year, regular plan). The shortfall is not statistically significant (t = {{flag_t}}).
- The textbook 60% threshold would label {{n_as_under_060}} of {{n_classified}} funds as closet indexers, because SEBI requires large-cap funds to hold 80% in the top 100 stocks. The threshold used here comes from the data and the regulation ([D-057](DECISIONS.md)).

## Run

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run_pipeline.py            # full build, including downloads from AMFI and mfapi
python run_pipeline.py --offline  # rebuild from the cached raw files, no network
python run_pipeline.py analysis report --offline   # any subset of steps
```

Steps, in order: `universe` → `nav` → `benchmark` → `portfolios` → `ter` → `quality` → `warehouse` → `metrics` → `analysis` → `export` → `report` → `checklist` → `test`. A failing step stops the build.

`data/raw/` is not in the repository (AMC files are not redistributed). `docs/download_checklist.md` lists every file to download and where it goes. Monthly portfolio files are downloaded by hand from each AMC's site; NAVs and expense ratios are fetched by the pipeline.

## Layout

```
data/raw/           gitignored: AMFI files, mfapi JSON, per-AMC portfolio files, TER API pages, TRI files
data/reference/     universe, scheme map, ISIN master and changes, survivorship events, TER category IDs
src/ingest/         AMFI and mfapi readers, one portfolio parser per AMC, TER API fetch and parse
src/quality/        NAV checks, cross-source NAV check, holdings checks
src/warehouse/      builds data/warehouse.duckdb from sql/staging, sql/intermediate, sql/marts; runs sql/tests
src/metrics/        active share, turnover, tracking error, rolling returns, information ratio, fee drag
src/analysis/       threshold sensitivity, classification, passive floors, beta-adjusted alpha, survivorship
src/export/         star-schema CSVs for Power BI
src/report/         fills reports/templates/ with the pipeline's numbers
dashboard/          Power BI build spec, DAX measures, screenshots
reports/memo.md     the business memo
docs/               interview_defense.md, resume_bullets.md, download_checklist.md
DECISIONS.md        every judgement call, the alternatives considered, and why
```

The memo, this README, the interview notes and the resume bullets are generated: each number is a placeholder in `reports/templates/` filled by the `report` step, so the documents cannot quote a figure the pipeline did not produce.

## Data

| Source | What | Notes |
|---|---|---|
| AMFI `NAVAll.txt` and NAV history | Universe, scheme codes, survivorship snapshot | Universe is derived from AMFI's category headers, not hand-picked. Snapshot pinned for reproducibility. |
| mfapi.in | Daily NAVs by scheme code | Checked against AMFI's official NAV in every build. |
| AMC websites | Monthly portfolio disclosures, {{holdings_start}} to {{window_end}} | {{n_classified}} AMCs, one parser each; formats differ and change mid-window. |
| niftyindices.com | Nifty 100 TRI | Benchmark returns. Its trading calendar is the master calendar. |
| {{index_fund}} | Monthly disclosed portfolio | Proxy for Nifty 100 weights; chosen as the index fund with the lowest tracking error ({{index_te_dir}}% a year). |
| AMFI TER disclosures | Daily expense ratios, both plans | Fetched from AMFI's JSON endpoint; identical to AMFI's Excel exports wherever both were available. |

**Scope.** {{n_universe_active}} large-cap active funds in AMFI; {{n_eligible}} have NAV history covering the window. Portfolios were collected for the largest funds first, up to 95% of category assets, plus two more: {{n_classified}} funds, {{classified_aaum_share}}% of regular-plan assets. The other {{n_not_classified}} have return and fee metrics only and are not classified.

## Method

- **Active share** = 0.5 × Σ |w_fund − w_benchmark| over the union of holdings, on equity weights renormalised to 100% after removing cash, TREPS, debt and options. The main version adds net stock-futures exposure to the underlying stock and spreads index futures across index constituents; an equity-only version is kept for comparison. Reported as the 12-month mean.
- **Tracking error** = standard deviation of daily excess returns over the Nifty 100 TRI × √252.
- **Excess return** = annualised fund return minus annualised TRI return over full 12- and 24-month windows only. Information ratio = excess ÷ tracking error.
- **Turnover proxy** = 0.5 × Σ |w_t − w_t−1| between consecutive months. It includes price drift.
- **Fee drag** = daily TER of the active fund's regular plan minus the index fund's regular plan, accrued over the window; in ₹ per ₹1 lakh and in ₹ crore a year at Jan to Mar 2026 average assets.
- **Classification.** Truly active: active share ≥ {{threshold}}. Closet: below {{threshold}}. Closet and underperforming: below {{threshold}} and regular-plan 24-month excess below zero.
- **Why {{threshold}}.** A Nifty 50 ETF scores {{floor_n50}} against the Nifty 100 and an 80% index + 20% other portfolio scores {{floor_sleeve}}, so the regulation puts the passive floor near 0.20. The funds' active shares have their widest gap between {{band_low}} ({{band_low_fund}}) and {{band_high}} ({{band_high_fund}}); any threshold in that gap gives the same groups.

## Robustness

Three thresholds × two weight definitions × five underperformance tests = {{n_variants}} variants. Results for the main weight definition ({{equity_only_note}}):

{{sensitivity_table}}

{{n_agree_all}} of {{n_classified}} funds keep their label in all {{n_variants}} variants; {{n_agree_main_threshold}} keep it in all {{n_variants_main_threshold}} variants at the main threshold. The classification is sensitive to the performance window: on the latest 12 months it is {{sens_040_12m}}.

## Data quality

Enforced in the build. Failures stop the pipeline; flags are written to `data/quality/` with counts and weights. Nothing is silently dropped.

- Every holding maps to an ISIN, or is listed with its weight.
- Each fund-month's holdings reconcile to the file's own stated total; equity weights sum to 100% after renormalisation.
- No duplicate (fund, month, ISIN) rows.
- NAVs: no gap over 5 weekdays, no non-positive values, daily moves over ±10% flagged; mfapi NAVs must equal AMFI's.
- SQL tests in `sql/tests/` return violating rows; each has a test proving it can fail.
- Metric functions are tested against examples worked by hand. Fixtures are verbatim excerpts of real files.

## Limitations

1. **Benchmark proxy.** Index weights come from an index fund's disclosed portfolio, not NSE's constituent file. Every fund is measured against the Nifty 100 even where it states the BSE 100 as its benchmark.
2. **Disclosure lag and snapshots.** Portfolios are month-end snapshots published by the 10th of the next month. Month M's portfolio is treated as known only from the 11th of M+1. Trading inside a month, and any month-end window dressing, cannot be seen.
3. **Survivorship.** {{surv_present}} large-cap scheme codes existed at the start of the window and still exist; none closed or merged. {{surv_new}} codes are new launches or legacy plan codes. A scheme launched and closed inside the window would be invisible.
4. **Scope.** 12 months of portfolios and 24 months of returns. {{n_not_classified}} smaller funds are unclassified, and smaller funds may be more active, so a count of closet indexers is biased upward; asset-weighted figures are the ones to quote.
5. **Statistical power.** With {{n_obs}} daily returns, only {{n_significant}} of {{n_classified}} funds has a 24-month excess return distinguishable from zero. Nothing here tests whether low active share predicts future returns.
6. **Fees.** Rupee totals use one quarter of average assets and simple accrual, and compare with one index fund's regular plan. They are fees paid above an index fund, not losses.
7. **Derivatives.** Futures are looked through; options are excluded because their exposure cannot be derived from month-end files.
8. **Calendar.** NAV gap checks count weekdays, not exchange trading days.

## Documents

- [`reports/memo.md`](reports/memo.md): the recommendation.
- [`DECISIONS.md`](DECISIONS.md): every judgement call, including the mistakes found and corrected.
- [`dashboard/README.md`](dashboard/README.md): Power BI model, measures and page layout.
- [`docs/interview_defense.md`](docs/interview_defense.md): the hardest questions about this work, answered.
