-- Exactly one proxy; it holds no derivatives; every month any fund has holdings has benchmark weights.
SELECT 't05_one_proxy' AS test, 'selected proxies=' || count(*) AS detail
FROM staging.benchmark_proxy WHERE selected HAVING count(*) <> 1
UNION ALL
SELECT 't05_proxy_has_derivatives', e.fund_id || ' ' || e.month
FROM intermediate.fund_exposure e JOIN staging.benchmark_proxy b ON b.fund_id = e.fund_id AND b.selected
WHERE e.stock_fut_w <> 0 OR e.index_fut_w <> 0 OR e.option_w <> 0
UNION ALL
SELECT 't05_month_without_benchmark', fm.fund_id || ' ' || fm.month
FROM (SELECT DISTINCT fund_id, month FROM marts.fund_month_weights) fm
WHERE fm.month NOT IN (SELECT DISTINCT month FROM intermediate.benchmark_weights);
