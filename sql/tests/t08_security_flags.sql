-- The ISIN security-type rule (D-031) applies to Indian ISINs only: a foreign ISIN can't be 'non-ordinary'.
SELECT 't08_foreign_marked_non_ordinary' AS test, fund_id || ' ' || month || ' ' || sec_key AS detail
FROM intermediate.fund_exposure
WHERE non_ordinary AND foreign_isin;
