PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS cities (
    id INTEGER PRIMARY KEY CHECK (id BETWEEN 1 AND 7),
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS projects (
    data_id INTEGER PRIMARY KEY,
    compound_id INTEGER,
    city_id INTEGER NOT NULL REFERENCES cities(id),
    name TEXT,
    name_ar TEXT,
    developer_id INTEGER,
    developer_name TEXT,
    developer_name_ar TEXT,
    area_id INTEGER,
    area_name TEXT,
    area_name_ar TEXT,
    coordinates TEXT,
    project_area TEXT,
    bedrooms TEXT,
    min_unit_price REAL,
    min_built_up_area REAL,
    finishing TEXT,
    source_date TEXT,
    raw_json TEXT NOT NULL CHECK(json_valid(raw_json)),
    collected_at TEXT NOT NULL,
    imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_city_price ON projects(city_id, min_unit_price);
CREATE INDEX IF NOT EXISTS idx_projects_compound ON projects(compound_id);
CREATE VIEW IF NOT EXISTS projects_with_city AS
    SELECT projects.*, cities.name AS city_name
    FROM projects JOIN cities ON cities.id = projects.city_id;
CREATE TABLE IF NOT EXISTS project_details (
    data_id INTEGER PRIMARY KEY REFERENCES projects(data_id) ON DELETE CASCADE,
    raw_json TEXT NOT NULL CHECK(json_valid(raw_json)),
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS phases (
    data_id INTEGER NOT NULL REFERENCES project_details(data_id) ON DELETE CASCADE,
    phase_id INTEGER NOT NULL,
    name TEXT,
    status_code TEXT,
    delivery_from_code INTEGER,
    delivery_to_code INTEGER,
    club_fees TEXT,
    cash_discount REAL,
    maintenance TEXT,
    parking_fees TEXT,
    raw_json TEXT NOT NULL CHECK(json_valid(raw_json)),
    PRIMARY KEY(data_id, phase_id)
);
CREATE TABLE IF NOT EXISTS units (
    data_id INTEGER NOT NULL,
    phase_id INTEGER NOT NULL,
    detail_id INTEGER NOT NULL,
    unit_type TEXT NOT NULL,
    bedrooms TEXT,
    built_up_area REAL,
    price_from REAL,
    price_to REAL,
    cash_price_from REAL,
    cash_price_to REAL,
    finishing_code TEXT,
    raw_json TEXT NOT NULL CHECK(json_valid(raw_json)),
    PRIMARY KEY(data_id, phase_id, detail_id),
    FOREIGN KEY(data_id, phase_id) REFERENCES phases(data_id, phase_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS payment_plans (
    data_id INTEGER NOT NULL,
    phase_id INTEGER NOT NULL,
    plan_id INTEGER NOT NULL,
    down_payment REAL,
    instalment_value REAL,
    instalment_frequency REAL,
    instalment_start REAL,
    discount REAL,
    bulks TEXT,
    comment TEXT,
    raw_json TEXT NOT NULL CHECK(json_valid(raw_json)),
    PRIMARY KEY(data_id, phase_id, plan_id),
    FOREIGN KEY(data_id, phase_id) REFERENCES phases(data_id, phase_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_units_price ON units(price_from);
CREATE TABLE IF NOT EXISTS detail_fetch_state (
    data_id INTEGER PRIMARY KEY REFERENCES projects(data_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK(status IN ('success','failed')),
    attempted_at TEXT NOT NULL,
    error TEXT
);
