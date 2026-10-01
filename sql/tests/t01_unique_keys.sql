SELECT 't01_unique_fund_weights' AS test, fund_id || ' ' || month || ' ' || sec_key AS detail
FROM intermediate.fund_weights GROUP BY fund_id, month, sec_key HAVING count(*) > 1
UNION ALL
SELECT 't01_unique_fund_month_weights', fund_id || ' ' || month || ' ' || sec_key
FROM marts.fund_month_weights GROUP BY fund_id, month, sec_key HAVING count(*) > 1
UNION ALL
SELECT 't01_unique_fund_daily', fund_id || ' ' || plan || ' ' || date
FROM marts.fund_daily GROUP BY fund_id, plan, date HAVING count(*) > 1
UNION ALL
SELECT 't01_unique_ter_daily', fund_id || ' ' || plan || ' ' || ter_date
FROM intermediate.ter_daily GROUP BY fund_id, plan, ter_date HAVING count(*) > 1
UNION ALL
SELECT 't01_unique_fund_month', fund_id || ' ' || month
FROM marts.fund_month GROUP BY fund_id, month HAVING count(*) > 1;
