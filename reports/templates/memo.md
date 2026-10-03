# Closet indexing in Indian large-cap funds: flag ten, drop none

**To:** Product and research team · **Decision:** which large-cap active funds to flag or drop from recommendations

**Data:** {{n_classified}} funds holding {{classified_aaum_share}}% of the category's regular-plan assets; monthly portfolios {{holdings_start}} to {{window_end}}; daily NAVs and expense ratios {{window_start}} to {{window_end}}

## Recommendation

**Drop no fund for low active share. Flag the {{n_low}} funds below {{threshold}} active share by showing the index-fund alternative and the fee gap, and take one of them, {{flag_fund}}, off the default list for new regular-plan money until a review in six months.**

This is not a sell call. The evidence does not support telling existing investors to exit, and exits carry tax and exit-load costs this study did not measure.

## What the data shows

1. **Most large-cap money sits in portfolios that are about two-thirds index.** Active share against the Nifty 100 runs from {{as_min}} ({{as_min_fund}}) to {{as_max}} ({{as_max_fund}}). {{n_low}} of {{n_classified}} funds are below {{threshold}}; they hold {{low_aaum_share}}% of the group's regular-plan assets (₹{{low_aaum_cr}} cr). For scale, a Nifty 50 ETF scores {{floor_n50}} against the Nifty 100.
2. **The fee for that exposure is certain.** Regular-plan investors in the {{n_low}} funds pay {{low_fee_min}} to {{low_fee_max}} percentage points a year (mean {{low_fee_mean}}) above the regular plan of a Nifty 100 index fund: about ₹{{low_rs_lakh}} per ₹1 lakh over two years, and ₹{{low_cr}} cr a year at Q4 FY26 assets. Charged against only the part of the portfolio that differs from the index, that is {{low_fee_per_active}}% a year, against {{active_fee_per_active}}% for the {{n_active}} more active funds.
3. **Low active share did not mean worse returns in this window.** After regular-plan fees, {{n_closet}} of the {{n_low}} beat the Nifty 100 TRI over 24 months ({{closet_xs_min}}% to {{closet_xs_max}}% a year), while {{active_neg24}} of the {{n_active}} more active funds trailed it. Only {{n_below_index_fund}} of {{n_classified}} funds ({{below_index_fund_funds}}) did worse than the index fund's regular plan, which itself trailed the TRI by {{index_lag_reg}}% a year.
4. **Two years cannot separate skill from noise.** On {{n_obs}} daily returns, {{n_significant}} of {{n_classified}} funds has an excess return statistically different from zero ({{significant_funds}}, t = {{significant_t}}), about what chance alone produces. The picture also moves: over the latest 12 months, {{low_neg12}} of the {{n_low}} trailed the TRI.

## Why {{flag_fund}} is treated differently

It is the only fund below the threshold and behind the index on every test run ({{flag_agree}} of {{n_variants}} combinations of threshold, weight definition and performance measure). Its regular plan returned {{flag_xs_reg_24}}% a year against the TRI over 24 months, {{flag_rank_phrase}}, and {{flag_vs_index_fund}}% against the index fund's regular plan; it was behind in {{flag_neg12_windows}} of {{flag_n_windows}} rolling 12-month windows. The direct plan is also behind ({{flag_xs_dir_24}}%), so distributor commission is not the cause, and adjusting for its lower market sensitivity (beta {{flag_beta}}) widens the gap ({{flag_alpha_reg}}%). The portfolio overlaps the index by {{flag_overlap}}%, and investors pay {{flag_fee_gap}} points a year above the index fund (₹{{flag_cr}} cr a year on ₹{{flag_aaum_cr}} cr).

The shortfall is **not statistically significant** (t = {{flag_t}}). The case is an asymmetry: the fee is certain, evidence of value for it is absent, and pausing a recommendation for new money is cheap to reverse. A recommended list should require evidence that a fund earns its fee, not proof that it fails.

## What this does not tell you

- **It describes; it does not forecast.** Portfolios cover 12 months and returns 24. Nothing here shows that low active share predicts underperformance.
- **The threshold is a judgement.** {{threshold}} sits in the widest gap in the data (any value from {{band_low}} to {{band_high}} gives the same groups). At the textbook 0.60, {{n_as_under_060}} of {{n_classified}} funds would be "closet", which reflects SEBI's rule that large-cap funds hold 80% in the top 100 stocks, not fund behaviour.
- **Benchmark weights are a proxy:** the {{index_fund}}'s disclosed portfolio (tracking error {{index_te_dir}}% a year), not NSE's weights. Every fund is measured against the Nifty 100, though some state the BSE 100.
- **{{n_not_classified}} smaller funds are unclassified** because their portfolios were not collected. Do not apply the flag to them.
- **Rupee totals** use one quarter of assets (Jan to Mar 2026) and simple accrual. They are fees paid above an index fund, not money lost.
- **Timing and survivorship.** Portfolios are month-end snapshots, treated as known from the 11th of the next month; trading inside a month is invisible. No large-cap scheme closed or merged in the window ({{surv_present}} scheme codes present at both ends).

## Next steps

1. Add the fee-gap and index-alternative line to the {{n_low}} fund pages; pause {{flag_fund}} for new regular-plan money.
2. Re-run in March 2027, with 18 months of portfolios and 30 of returns. Reinstate {{flag_fund}} if its 24-month regular-plan return is ahead of the index fund's.

## Fund-level results

{{fund_table}}

Active share: 12-month mean against the Nifty 100 proxy, futures included. Fee gap: regular plan minus the {{index_fund}} regular plan (mean TER {{index_ter_reg}}%). Excess: annualised regular-plan return minus the Nifty 100 TRI ({{bench_ret_24}}% a year over the window). t-stat: approximate, information ratio × √years. Methods: `README.md`; every judgement call: `DECISIONS.md`.
