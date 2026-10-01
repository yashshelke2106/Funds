-- D-014: every return sits on the TRI calendar; no return spans more than 5 TRI days (P1 NAV gap rule);
-- excess = fund - benchmark; returns per plan = NAV-days-on-calendar - 1.
SELECT 't06_off_calendar' AS test, fund_id || ' ' || plan || ' ' || date AS detail
FROM intermediate.daily_returns
WHERE date NOT IN (SELECT tri_date FROM intermediate.tri_calendar)
   OR prev_date NOT IN (SELECT tri_date FROM intermediate.tri_calendar)
UNION ALL
SELECT 't06_span_too_long', fund_id || ' ' || plan || ' ' || date || ' spans ' || n_tri_days
FROM intermediate.daily_returns WHERE n_tri_days > 5 OR n_tri_days < 1
UNION ALL
SELECT 't06_excess', fund_id || ' ' || plan || ' ' || date
FROM marts.fund_daily WHERE abs(excess_ret - (fund_ret - bench_ret)) > 1e-12
UNION ALL
SELECT 't06_return_count', n.fund_id || ' ' || n.plan
FROM (SELECT fund_id, plan, count(*) AS c FROM intermediate.nav_on_tri_calendar GROUP BY ALL) n
JOIN (SELECT fund_id, plan, count(*) AS c FROM intermediate.daily_returns GROUP BY ALL) r USING (fund_id, plan)
WHERE r.c <> n.c - 1;
