-- Two weight variants per fund-month, each renormalised to 1:
--   w_main         equity + stock futures + index-future look-through (D-020 main result, D-027, D-044)
--   w_equity_only  equity alone: the brief's original definition, kept as the robustness check (D-020)
-- Options are in neither until P4 decides (D-041). No-ISIN and non-ordinary rows are kept and flagged.
CREATE OR REPLACE TABLE intermediate.fund_weights AS
SELECT fund_id, month, sec_key, no_isin, non_ordinary, foreign_isin,
       (equity_w + stock_fut_w + index_fut_w)
           / sum(equity_w + stock_fut_w + index_fut_w) OVER (PARTITION BY fund_id, month) AS w_main,
       equity_w / sum(equity_w) OVER (PARTITION BY fund_id, month)                       AS w_equity_only
FROM intermediate.fund_exposure
WHERE NOT is_option;

-- Benchmark = the selected Nifty 100 index fund's equity weights (D-010 resolved; it holds no derivatives,
-- which tests/t06 checks).
CREATE OR REPLACE TABLE intermediate.benchmark_weights AS
SELECT w.month, w.sec_key, w.w_equity_only AS w_bench
FROM intermediate.fund_weights w
JOIN staging.benchmark_proxy b ON b.fund_id = w.fund_id AND b.selected
WHERE w.w_equity_only <> 0;

-- D-024 robustness: new-format Total TER minus brokerage and transaction cost (outside TER under the old rules).
CREATE OR REPLACE TABLE intermediate.ter_daily AS
SELECT fund_id, plan, ter_date, total,
       CASE WHEN format = 'new' THEN total - coalesce(brokerage, 0) - coalesce(txn, 0) ELSE total END AS total_ex_costs,
       format, filled
FROM staging.ter_daily;
