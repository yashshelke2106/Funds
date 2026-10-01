-- D-009: month M's portfolio is known only from the 11th of M+1.
SELECT 't07_available_from' AS test, fund_id || ' ' || month || ' available ' || available_from AS detail
FROM marts.fund_month
WHERE available_from <> month + INTERVAL 1 MONTH + INTERVAL 10 DAY
   OR available_from <= as_of;
