-- ============================================================
-- GSP Event Upload Application - Database Initialization Script
-- ============================================================

-- Create hosts table
CREATE TABLE IF NOT EXISTS hosts (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT,
    email TEXT
);

-- Create venues table
CREATE TABLE IF NOT EXISTS venues (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    default_day TEXT,
    default_time TEXT
);

-- Create events table
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    host_id INT REFERENCES hosts(id),
    venue_id INT REFERENCES venues(id),
    event_date DATE,
    highlights TEXT,
    pdf_url TEXT,
    ai_recap TEXT,
    status TEXT DEFAULT 'unposted'
);

-- Create event_photos table
CREATE TABLE IF NOT EXISTS event_photos (
    id SERIAL PRIMARY KEY,
    event_id INT REFERENCES events(id),
    photo_url TEXT
);

-- ============================================================
-- Seed Data from CSVs
-- NOTE: This assumes hosts.csv and venues.csv are available
-- in the same directory where you run psql.
-- ============================================================

-- Import hosts
\copy hosts(name,phone,email) FROM 'hosts.csv' DELIMITER ',' CSV HEADER;

-- Import venues
\copy venues(name,default_day,default_time) FROM 'venues.csv' DELIMITER ',' CSV HEADER;

-- ============================================================
-- Verification Queries
-- ============================================================

-- Count rows
SELECT COUNT(*) AS host_count FROM hosts;
SELECT COUNT(*) AS venue_count FROM venues;

-- Preview data
SELECT * FROM hosts LIMIT 5;
SELECT * FROM venues LIMIT 5;