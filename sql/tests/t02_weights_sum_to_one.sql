-- coalesce(..., true): a NULL/NaN sum (e.g. a fund-month whose weights total zero) must FAIL, not slip through.
SELECT 't02_w_main_sum' AS test, fund_id || ' ' || month || ' sum=' || coalesce(CAST(sum(w_main) AS VARCHAR), 'NULL') AS detail
FROM intermediate.fund_weights GROUP BY fund_id, month HAVING coalesce(abs(sum(w_main) - 1) > 1e-9, true)
UNION ALL
SELECT 't02_w_equity_only_sum', fund_id || ' ' || month || ' sum=' || coalesce(CAST(sum(w_equity_only) AS VARCHAR), 'NULL')
FROM intermediate.fund_weights GROUP BY fund_id, month HAVING coalesce(abs(sum(w_equity_only) - 1) > 1e-9, true)
UNION ALL
SELECT 't02_w_bench_sum', month || ' sum=' || coalesce(CAST(sum(w_bench) AS VARCHAR), 'NULL')
FROM intermediate.benchmark_weights GROUP BY month HAVING coalesce(abs(sum(w_bench) - 1) > 1e-9, true)
UNION ALL
SELECT 't02_mart_sums', fund_id || ' ' || month
FROM marts.fund_month_weights GROUP BY fund_id, month
HAVING coalesce(abs(sum(w_fund_main) - 1) > 1e-9 OR abs(sum(w_fund_equity_only) - 1) > 1e-9
                OR abs(sum(w_bench) - 1) > 1e-9, true);
