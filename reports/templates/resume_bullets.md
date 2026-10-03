# Resume bullets

Built only from results the pipeline produced. Re-rendered on every build, so they stay true if the data changes.

- Built a reproducible, one-command analytics pipeline (Python, DuckDB SQL, Power BI; 200+ automated tests) that ingests 12 months of portfolio disclosures from {{n_classified}} AMCs in {{n_classified}} different Excel layouts, 24 months of daily NAVs and AMFI expense-ratio data for {{n_eligible}} Indian large-cap funds, with every fund-month reconciled to the source file's stated total.
- Measured active share against a Nifty 100 proxy and found {{n_low}} of {{n_classified}} funds, holding {{low_aaum_share}}% of the group's regular-plan assets, below {{threshold}}; their investors pay {{low_fee_mean}} percentage points a year (about ₹{{low_cr}} crore a year) above an index fund for portfolios that overlap the index by roughly two-thirds.
- Showed that the textbook 60% closet-indexing threshold flags {{n_as_under_060}} of {{n_classified}} funds under SEBI's 80%-in-top-100 rule, derived a {{threshold}} threshold from a {{n_variants}}-variant sensitivity analysis, and recommended a fee-disclosure flag instead of drops after finding that {{n_closet}} of the {{n_low}} low-active-share funds still beat the index after fees and only {{n_significant}} of {{n_classified}} excess returns was statistically significant.

## Do not claim

- That closet indexers underperform. In this window they mostly did not.
- That ₹{{low_cr}} crore was "lost" or "saved". It is a fee gap at one quarter's assets.
- That the result is predictive. It covers 12 months of holdings and 24 months of returns.
- Coverage of the whole category by count: {{n_classified}} of {{n_eligible}} eligible funds were classified ({{classified_aaum_share}}% of regular-plan assets).
