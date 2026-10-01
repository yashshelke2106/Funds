-- D-014: the TRI's trading calendar is the master calendar. NAVs on non-TRI days are dropped; a TRI day
-- without a NAV is skipped in BOTH series (the next return spans the gap); no forward fill.
CREATE OR REPLACE TABLE intermediate.tri_calendar AS
SELECT tri_date, tri, row_number() OVER (ORDER BY tri_date) AS tri_idx
FROM staging.benchmark_tri;

CREATE OR REPLACE TABLE intermediate.plan_codes AS
SELECT fund_id, role, 'direct' AS plan, direct_code AS scheme_code FROM staging.scheme_map
UNION ALL
SELECT fund_id, role, 'regular' AS plan, regular_code AS scheme_code FROM staging.scheme_map;

CREATE OR REPLACE TABLE intermediate.nav_on_tri_calendar AS
SELECT p.fund_id, p.role, p.plan, n.nav_date, n.nav, c.tri, c.tri_idx
FROM intermediate.plan_codes p
JOIN staging.nav n ON n.scheme_code = p.scheme_code
JOIN intermediate.tri_calendar c ON c.tri_date = n.nav_date;
