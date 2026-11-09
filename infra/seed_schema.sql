-- Schema + seed data for dbo.raw_sales, dbo.store_promotions, dbo.fact_sales.
-- Run this once against EACH database (dev and uat) created by
-- infra/azure_sql_setup.sh. Destructive by design (drops and recreates the
-- three tables) -- only ever run it against these throwaway test databases,
-- never anything with real data.
--
-- The seed data is small and hand-computable on purpose, so the "golden"
-- figures in tests/golden_fact_sales.example.yaml can be checked by eye --
-- the same way you'd eyeball a pivot table. store_id 1 has TWO rows in
-- dbo.store_promotions; everything else has exactly one. That's what the
-- planted bug in procs/sp_refresh_fact_sales.example.sql (a plain INNER JOIN
-- against store_promotions, with no de-duplication) fans out on: any sale
-- from store 1 gets counted twice. Categories that never touch store 1
-- (Apparel here) are unaffected -- a useful illustration that this kind of
-- bug doesn't necessarily show up everywhere, which is exactly why a
-- row-count check alone wouldn't have caught it as reliably as checking the
-- actual category-level figures.

IF OBJECT_ID('dbo.raw_sales', 'U') IS NOT NULL DROP TABLE dbo.raw_sales;
IF OBJECT_ID('dbo.store_promotions', 'U') IS NOT NULL DROP TABLE dbo.store_promotions;
IF OBJECT_ID('dbo.fact_sales', 'U') IS NOT NULL DROP TABLE dbo.fact_sales;
GO

CREATE TABLE dbo.raw_sales (
    sale_id INT IDENTITY PRIMARY KEY,
    store_id INT NOT NULL,
    product_category VARCHAR(50) NOT NULL,
    revenue DECIMAL(12,2) NOT NULL
);

CREATE TABLE dbo.store_promotions (
    promotion_id INT IDENTITY PRIMARY KEY,
    store_id INT NOT NULL,
    promotion_name VARCHAR(100) NOT NULL
);

-- Starts empty; dbo.sp_refresh_fact_sales populates it via TRUNCATE + INSERT.
CREATE TABLE dbo.fact_sales (
    product_category VARCHAR(50) NOT NULL,
    revenue DECIMAL(12,2) NOT NULL,
    txn_count INT NOT NULL
);
GO

INSERT INTO dbo.raw_sales (store_id, product_category, revenue) VALUES
    (1, 'Electronics', 500.00),
    (2, 'Electronics', 1000.00),
    (3, 'Electronics', 1500.00),
    (1, 'Groceries', 200.00),
    (4, 'Groceries', 300.00),
    (2, 'Apparel', 100.00),
    (5, 'Apparel', 150.00);

INSERT INTO dbo.store_promotions (store_id, promotion_name) VALUES
    (1, 'Summer Sale'),
    (1, 'Clearance'),        -- store 1's SECOND promotion row -- this is what fans out
    (2, 'Loyalty Week'),
    (3, 'Back to School'),
    (4, 'Weekend Deal'),
    (5, 'Flash Sale');
GO

-- Correct (golden) figures for this seed data, computed by hand:
--   Electronics: 500 + 1000 + 1500 = 3000.00, 3 transactions
--   Groceries:   200 + 300         =  500.00, 2 transactions
--   Apparel:     100 + 150         =  250.00, 2 transactions
-- (matches tests/golden_fact_sales.example.yaml)
--
-- What the CURRENT buggy procedure will actually produce against this data
-- (store 1's rows double-counted because of the extra promotion row):
--   Electronics: (500*2) + 1000 + 1500 = 3500.00, 4 transactions  -- WRONG
--   Groceries:   (200*2) + 300         =  700.00, 3 transactions  -- WRONG
--   Apparel:     100 + 150             =  250.00, 2 transactions  -- happens to be correct
