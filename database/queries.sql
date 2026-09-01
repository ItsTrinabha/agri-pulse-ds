-- Phase 4 - analytical SQL queries against the normalized schema.
-- Each query answers a specific business question and demonstrates a
-- required SQL concept (see roadmap Phase 4 "Learn" list).

-- Q1. SELECT / WHERE / ORDER BY / LIMIT
-- "What are the 10 highest single Maize yield observations on record?"
SELECT r.region_name, y.year, y.yield_hg_ha
FROM yield_observation y
JOIN region r ON r.region_id = y.region_id
JOIN crop c ON c.crop_id = y.crop_id
WHERE c.crop_name = 'Maize'
ORDER BY y.yield_hg_ha DESC
LIMIT 10;

-- Q2. JOIN / GROUP BY / ORDER BY
-- "What is the average yield per crop, across all regions and years?"
SELECT c.crop_name, ROUND(AVG(y.yield_hg_ha), 1) AS avg_yield_hg_ha, COUNT(*) AS n_observations
FROM yield_observation y
JOIN crop c ON c.crop_id = y.crop_id
GROUP BY c.crop_name
ORDER BY avg_yield_hg_ha DESC;

-- Q3. JOIN / GROUP BY / HAVING
-- "Which regions have at least 40 years of Maize yield history?"
-- (a data-completeness question - which regions have enough history to
-- support a reliable per-region trend model later)
SELECT r.region_name, COUNT(*) AS n_years
FROM yield_observation y
JOIN region r ON r.region_id = y.region_id
JOIN crop c ON c.crop_id = y.crop_id
WHERE c.crop_name = 'Maize'
GROUP BY r.region_name
HAVING COUNT(*) >= 40
ORDER BY n_years DESC;

-- Q4. Subquery
-- "Which regions have above-(global-)average Maize yield?"
SELECT r.region_name, ROUND(AVG(y.yield_hg_ha), 1) AS avg_yield_hg_ha
FROM yield_observation y
JOIN region r ON r.region_id = y.region_id
JOIN crop c ON c.crop_id = y.crop_id
WHERE c.crop_name = 'Maize'
GROUP BY r.region_name
HAVING AVG(y.yield_hg_ha) > (
    SELECT AVG(y2.yield_hg_ha)
    FROM yield_observation y2
    JOIN crop c2 ON c2.crop_id = y2.crop_id
    WHERE c2.crop_name = 'Maize'
)
ORDER BY avg_yield_hg_ha DESC;

-- Q5. CASE
-- "Bucket every Maize yield observation into a low/medium/high tier
-- relative to that crop's own global average and standard deviation"
-- (a coarse precursor to the Phase 10 risk classification target - not
-- the real target, just illustrating CASE-based bucketing here)
WITH crop_stats AS (
    SELECT AVG(y.yield_hg_ha) AS avg_yield, AVG(y.yield_hg_ha * y.yield_hg_ha) - AVG(y.yield_hg_ha) * AVG(y.yield_hg_ha) AS variance
    FROM yield_observation y
    JOIN crop c ON c.crop_id = y.crop_id
    WHERE c.crop_name = 'Maize'
)
SELECT
    r.region_name,
    y.year,
    y.yield_hg_ha,
    CASE
        WHEN y.yield_hg_ha < (SELECT avg_yield - SQRT(variance) FROM crop_stats) THEN 'low'
        WHEN y.yield_hg_ha > (SELECT avg_yield + SQRT(variance) FROM crop_stats) THEN 'high'
        ELSE 'medium'
    END AS yield_tier
FROM yield_observation y
JOIN region r ON r.region_id = y.region_id
JOIN crop c ON c.crop_id = y.crop_id
WHERE c.crop_name = 'Maize'
ORDER BY r.region_name, y.year
LIMIT 20;

-- Q6. CTE + window function (RANK)
-- "For each region growing Maize, what was its single best year?"
WITH ranked AS (
    SELECT
        r.region_name,
        y.year,
        y.yield_hg_ha,
        RANK() OVER (PARTITION BY y.region_id ORDER BY y.yield_hg_ha DESC) AS yield_rank
    FROM yield_observation y
    JOIN region r ON r.region_id = y.region_id
    JOIN crop c ON c.crop_id = y.crop_id
    WHERE c.crop_name = 'Maize'
)
SELECT region_name, year, yield_hg_ha
FROM ranked
WHERE yield_rank = 1
ORDER BY yield_hg_ha DESC
LIMIT 15;

-- Q7. Window function (LAG) - year-over-year change
-- "How did Maize yield change year over year for the United States?"
SELECT
    y.year,
    y.yield_hg_ha,
    LAG(y.yield_hg_ha) OVER (ORDER BY y.year) AS prev_year_yield,
    y.yield_hg_ha - LAG(y.yield_hg_ha) OVER (ORDER BY y.year) AS yoy_change_hg_ha
FROM yield_observation y
JOIN region r ON r.region_id = y.region_id
JOIN crop c ON c.crop_id = y.crop_id
WHERE r.region_name = 'United States of America' AND c.crop_name = 'Maize'
ORDER BY y.year;

-- Q8. Multi-table JOIN - the feature table shape models will consume later
-- "Yield alongside its rainfall/temperature/pesticide context, for Maize"
SELECT
    r.region_name,
    y.year,
    y.yield_hg_ha,
    w.rainfall_mm,
    w.avg_temp_c,
    p.pesticides_tonnes
FROM yield_observation y
JOIN region r ON r.region_id = y.region_id
JOIN crop c ON c.crop_id = y.crop_id
LEFT JOIN weather_observation w ON w.region_id = y.region_id AND w.year = y.year
LEFT JOIN agricultural_practice_observation p ON p.region_id = y.region_id AND p.year = y.year
WHERE c.crop_name = 'Maize' AND r.region_name = 'India'
ORDER BY y.year
LIMIT 20;
