CREATE TABLE IF NOT EXISTS imports (
    id BIGSERIAL PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    source_name TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (snapshot_date, source_name)
);

CREATE TABLE IF NOT EXISTS projects (
    project_code TEXT PRIMARY KEY,
    description TEXT,
    customer TEXT,
    reference TEXT,
    access_key TEXT,
    project_type TEXT,
    status TEXT,
    eta TEXT,
    project_manager TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fact_hours (
    snapshot_date DATE NOT NULL,
    source_row_no INTEGER NOT NULL,
    project_code TEXT,
    order_number TEXT NOT NULL,
    operation_number INTEGER,
    bonus_id TEXT,
    article TEXT,
    order_description TEXT,
    operation_description TEXT,
    order_status TEXT,
    launch_date DATE,
    work_center TEXT,
    hours_granted NUMERIC(14,2) NOT NULL DEFAULT 0,
    hours_incurred NUMERIC(14,2) NOT NULL DEFAULT 0,
    hours_pending NUMERIC(14,2) NOT NULL DEFAULT 0,
    source_file_hash TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, source_row_no)
);

CREATE INDEX IF NOT EXISTS idx_fact_hours_project
    ON fact_hours (snapshot_date, project_code);

CREATE INDEX IF NOT EXISTS idx_fact_hours_order
    ON fact_hours (snapshot_date, order_number);

CREATE INDEX IF NOT EXISTS idx_fact_hours_bonus
    ON fact_hours (snapshot_date, bonus_id);

CREATE INDEX IF NOT EXISTS idx_fact_hours_work_center
    ON fact_hours (snapshot_date, work_center);

CREATE OR REPLACE VIEW v_latest_snapshot AS
SELECT MAX(snapshot_date) AS snapshot_date
FROM fact_hours;

CREATE OR REPLACE VIEW v_project_hours AS
SELECT
    f.snapshot_date,
    f.project_code,
    f.work_center,
    COALESCE(MAX(p.description), MAX(f.project_code)) AS project_description,
    MAX(p.customer) AS customer,
    MAX(p.status) AS project_status,
    MAX(p.project_manager) AS project_manager,
    SUM(f.hours_granted) AS hours_granted,
    SUM(f.hours_incurred) AS hours_incurred,
    SUM(f.hours_incurred) - SUM(f.hours_granted) AS deviation_hours,
    SUM(f.hours_granted) - SUM(f.hours_incurred) AS remaining_hours,
    CASE
        WHEN SUM(f.hours_granted) = 0 THEN NULL
        ELSE SUM(f.hours_incurred) / SUM(f.hours_granted)
    END AS consumption_ratio
FROM fact_hours f
LEFT JOIN projects p ON p.project_code = f.project_code
GROUP BY f.snapshot_date, f.project_code, f.work_center;

CREATE OR REPLACE VIEW v_order_hours AS
SELECT
    f.snapshot_date,
    f.project_code,
    f.work_center,
    f.order_number,
    MAX(f.order_description) AS order_description,
    MAX(f.order_status) AS order_status,
    SUM(f.hours_granted) AS hours_granted,
    SUM(f.hours_incurred) AS hours_incurred,
    SUM(f.hours_incurred) - SUM(f.hours_granted) AS deviation_hours,
    SUM(f.hours_granted) - SUM(f.hours_incurred) AS remaining_hours,
    CASE
        WHEN SUM(f.hours_granted) = 0 THEN NULL
        ELSE SUM(f.hours_incurred) / SUM(f.hours_granted)
    END AS consumption_ratio
FROM fact_hours f
GROUP BY f.snapshot_date, f.project_code, f.work_center, f.order_number;

CREATE OR REPLACE VIEW v_bonus_hours AS
SELECT
    f.snapshot_date,
    f.project_code,
    f.work_center,
    f.order_number,
    f.operation_number,
    f.bonus_id,
    MAX(f.operation_description) AS operation_description,
    SUM(f.hours_granted) AS hours_granted,
    SUM(f.hours_incurred) AS hours_incurred,
    SUM(f.hours_incurred) - SUM(f.hours_granted) AS deviation_hours,
    SUM(f.hours_granted) - SUM(f.hours_incurred) AS remaining_hours,
    CASE
        WHEN SUM(f.hours_granted) = 0 THEN NULL
        ELSE SUM(f.hours_incurred) / SUM(f.hours_granted)
    END AS consumption_ratio
FROM fact_hours f
GROUP BY
    f.snapshot_date,
    f.project_code,
    f.work_center,
    f.order_number,
    f.operation_number,
    f.bonus_id;
