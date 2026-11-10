-- Known-buggy candidate, kept for demonstrating harness/evolve_cli.py's auto-fix
-- loop against DEV: the planted fan-out join (dbo.store_promotions has 8 stores
-- with a duplicate promotion row) double-counts any sale from those stores.
-- The fixed version lives at procs/sp_refresh_fact_sales.example.sql; this file
-- is a frozen copy of the bug for the LLM to find on its own.
-- Re-triggering end-to-end test now that GH_PAT, the transient-error fix,
-- and the rotated Azure SQL credentials are all confirmed in place.
CREATE OR ALTER PROCEDURE dbo.sp_refresh_fact_sales
AS
BEGIN
    SET NOCOUNT ON;

    SELECT
        s.product_category,
        SUM(s.revenue) AS revenue,
        COUNT(*) AS txn_count
    INTO #tmp_fact_sales
    FROM dbo.raw_sales s
    JOIN dbo.store_promotions p ON p.store_id = s.store_id
    GROUP BY s.product_category;

    TRUNCATE TABLE dbo.fact_sales;
    INSERT INTO dbo.fact_sales (product_category, revenue, txn_count)
    SELECT product_category, revenue, txn_count FROM #tmp_fact_sales;
END
