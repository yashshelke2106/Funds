-- Fund and benchmark returns over exactly the same two dates (the fund's consecutive NAV dates on the TRI
-- calendar). n_tri_days > 1 means the return spans TRI days on which this plan had no NAV (D-014).
CREATE OR REPLACE TABLE intermediate.daily_returns AS
WITH x AS (
    SELECT *, lag(nav_date) OVER w AS prev_date, lag(nav) OVER w AS prev_nav,
              lag(tri) OVER w AS prev_tri, lag(tri_idx) OVER w AS prev_idx
    FROM intermediate.nav_on_tri_calendar
    WINDOW w AS (PARTITION BY fund_id, plan ORDER BY nav_date))
SELECT fund_id, role, plan, nav_date AS date, prev_date,
       tri_idx - prev_idx                                  AS n_tri_days,
       nav / prev_nav - 1                                  AS fund_ret,
       tri / prev_tri - 1                                  AS bench_ret,
       (nav / prev_nav - 1) - (tri / prev_tri - 1)         AS excess_ret
FROM x
WHERE prev_date IS NOT NULL;
