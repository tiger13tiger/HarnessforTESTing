-- Fixed version: see procs/sp_refresh_fact_sales.buggy_example.sql for the
-- planted-bug original (kept to demonstrate harness/evolve_cli.py's auto-fix
-- loop against DEV). The bug was a plain JOIN against dbo.store_promotions,
-- which fans out one sale row per promotion row for any store running more
-- than one active promotion -- fixed here by de-duplicating store_id before
-- the join, so a store's sales are only ever counted once regardless of how
-- many active promotions it has.
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
    JOIN (SELECT DISTINCT store_id FROM dbo.store_promotions) p ON p.store_id = s.store_id
    GROUP BY s.product_category;

    TRUNCATE TABLE dbo.fact_sales;
    INSERT INTO dbo.fact_sales (product_category, revenue, txn_count)
    SELECT product_category, revenue, txn_count FROM #tmp_fact_sales;
END
