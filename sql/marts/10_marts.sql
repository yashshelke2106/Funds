-- Marts: what P4 computes from.

-- Fund vs benchmark weights, aligned per fund-month on the union of securities (active share input).
-- Excludes the benchmark proxy itself and the reference ETFs.
CREATE OR REPLACE TABLE marts.fund_month_weights AS
WITH f AS (
    SELECT w.* FROM intermediate.fund_weights w
    WHERE w.fund_id NOT IN (SELECT fund_id FROM staging.benchmark_proxy WHERE selected)
      AND w.fund_id NOT IN (SELECT fund_id FROM staging.reference_portfolios)),
fm AS (SELECT DISTINCT fund_id, month FROM f),
b AS (SELECT fm.fund_id, fm.month, bw.sec_key, bw.w_bench FROM fm JOIN intermediate.benchmark_weights bw USING (month))
SELECT coalesce(f.fund_id, b.fund_id)  AS fund_id,
       coalesce(f.month, b.month)      AS month,
       coalesce(f.sec_key, b.sec_key)  AS sec_key,
       coalesce(f.w_main, 0)           AS w_fund_main,
       coalesce(f.w_equity_only, 0)    AS w_fund_equity_only,
       coalesce(b.w_bench, 0)          AS w_bench,
       coalesce(f.no_isin, false)      AS no_isin,
       coalesce(f.non_ordinary, false) AS non_ordinary,
       coalesce(f.foreign_isin, false) AS foreign_isin
FROM f FULL OUTER JOIN b ON f.fund_id = b.fund_id AND f.month = b.month AND f.sec_key = b.sec_key;

-- One row per fund-month: disclosure timing (D-009) and what sits outside plain equity.
CREATE OR REPLACE TABLE marts.fund_month AS
WITH e AS (
    SELECT fund_id, month,
           count(*) FILTER (WHERE equity_w <> 0)                 AS n_equity_keys,
           sum(stock_fut_w)                                      AS stock_fut_net,
           sum(index_fut_w)                                      AS index_fut_net,
           sum(option_w)                                         AS option_net,
           coalesce(sum(equity_w) FILTER (WHERE no_isin), 0)     AS no_isin_weight,
           coalesce(sum(equity_w) FILTER (WHERE non_ordinary), 0) AS non_ordinary_weight,
           coalesce(sum(equity_w) FILTER (WHERE foreign_isin), 0) AS foreign_weight
    FROM intermediate.fund_exposure GROUP BY ALL),
a AS (SELECT fund_id, month, max(available_from) AS available_from FROM staging.holdings GROUP BY ALL)
SELECT m.fund_id, m.month, m.as_of, a.available_from,
       coalesce(u.role, 'reference') AS role, u.report_group,
       m.nav_lakh, m.equity_weight_raw, 1 - m.equity_weight_raw AS excluded_non_equity_weight,
       e.n_equity_keys, e.stock_fut_net, e.index_fut_net, e.option_net,
       e.no_isin_weight, e.non_ordinary_weight, e.foreign_weight
FROM staging.portfolio_meta m
JOIN a USING (fund_id, month)
JOIN e USING (fund_id, month)
LEFT JOIN staging.universe u USING (fund_id);

-- One row per fund x plan x TRI day with a return: returns plus that day's TER.
CREATE OR REPLACE TABLE marts.fund_daily AS
SELECT r.fund_id, r.role, r.plan, r.date, r.prev_date, r.n_tri_days, r.fund_ret, r.bench_ret, r.excess_ret,
       t.total AS ter_total, t.total_ex_costs AS ter_ex_costs, t.format AS ter_format, t.filled AS ter_filled,
       r.date BETWEEN DATE '{{window_start}}' AND DATE '{{window_end}}' AS in_window
FROM intermediate.daily_returns r
LEFT JOIN intermediate.ter_daily t ON t.fund_id = r.fund_id AND t.plan = r.plan AND t.ter_date = r.date;

-- One row per fund in the universe.
CREATE OR REPLACE TABLE marts.fund AS
WITH h AS (SELECT fund_id, count(*) AS holdings_months FROM marts.fund_month GROUP BY ALL),
d AS (SELECT fund_id,
             count(*) FILTER (WHERE in_window AND plan = 'direct')                            AS direct_return_days,
             count(*) FILTER (WHERE in_window AND plan = 'regular')                           AS regular_return_days,
             count(*) FILTER (WHERE in_window AND plan = 'regular' AND ter_total IS NOT NULL) AS regular_ter_days
      FROM marts.fund_daily GROUP BY ALL)
SELECT u.fund_id, u.role, u.amc, u.scheme_name, u.eligible, u.report_group, u.exclusion_reason,
       coalesce(h.holdings_months, 0) AS holdings_months,
       d.direct_return_days, d.regular_return_days, d.regular_ter_days
FROM staging.universe u
LEFT JOIN h USING (fund_id)
LEFT JOIN d USING (fund_id);
