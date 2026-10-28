CREATE CATALOG IF NOT EXISTS mma COMMENT 'MMA intelligence app';
CREATE SCHEMA IF NOT EXISTS mma.raw COMMENT 'Landing zone for external ingestion';
CREATE VOLUME IF NOT EXISTS mma.raw.landing COMMENT 'Raw files pushed by external scrapers';
