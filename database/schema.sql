-- Phase 4 - relational schema for the curated agricultural dataset.
--
-- Concept: a normalized schema stores each fact once and links tables by
-- key instead of repeating "United States" and its rainfall on every one
-- of its ~270 crop-year rows in a single flat table. Region/crop are
-- dimensions (who/what); weather, agricultural practice, and yield are
-- observations (facts measured over time).
--
-- No "soil" table: the source dataset (see docs/data_dictionary.md) has
-- no soil observations, and the project rule is not to fabricate
-- measurements that don't exist in the data (spec section 17).

PRAGMA foreign_keys = ON;

CREATE TABLE region (
    region_id   INTEGER PRIMARY KEY,
    region_name TEXT NOT NULL UNIQUE
);

CREATE TABLE crop (
    crop_id   INTEGER PRIMARY KEY,
    crop_name TEXT NOT NULL UNIQUE
);

-- Weather is a property of (region, year) - it does not depend on which
-- crop was grown there, so it gets its own table rather than being
-- repeated per crop.
CREATE TABLE weather_observation (
    region_id    INTEGER NOT NULL REFERENCES region(region_id),
    year         INTEGER NOT NULL,
    rainfall_mm  REAL,              -- nullable: source doesn't cover every region/year (see D3.2/D3.3)
    avg_temp_c   REAL,
    PRIMARY KEY (region_id, year)
);

-- Agricultural practice (pesticide use) is likewise (region, year) grain,
-- not per-crop, in this dataset.
CREATE TABLE agricultural_practice_observation (
    region_id          INTEGER NOT NULL REFERENCES region(region_id),
    year               INTEGER NOT NULL,
    pesticides_tonnes  REAL,
    PRIMARY KEY (region_id, year)
);

-- The finest-grain fact table: one row per (region, crop, year) - this is
-- the target variable for the yield model (Phase 9).
CREATE TABLE yield_observation (
    yield_id     INTEGER PRIMARY KEY,
    region_id    INTEGER NOT NULL REFERENCES region(region_id),
    crop_id      INTEGER NOT NULL REFERENCES crop(crop_id),
    year         INTEGER NOT NULL,
    yield_hg_ha  INTEGER NOT NULL,
    UNIQUE (region_id, crop_id, year)
);

CREATE INDEX idx_yield_region_year ON yield_observation (region_id, year);
CREATE INDEX idx_yield_crop ON yield_observation (crop_id);
CREATE INDEX idx_weather_region ON weather_observation (region_id);
CREATE INDEX idx_practice_region ON agricultural_practice_observation (region_id);
