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

-- Persistent, incremental mapping: operation/bonus -> work center.
CREATE TABLE IF NOT EXISTS bonus_ct_registry (
    bonus_id TEXT PRIMARY KEY CHECK (bonus_id ~ '^[0-9]{10}$'),
    order_number TEXT NOT NULL,
    work_center TEXT NOT NULL,
    first_seen_snapshot DATE NOT NULL,
    last_seen_snapshot DATE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bonus_ct_registry_order ON bonus_ct_registry (order_number);

-- One final incurred-hours amount per closed OF, never per bonus.
-- Unknown and multicenter OF remain unallocated (NULL work_center).
CREATE TABLE IF NOT EXISTS closed_of_hours (
    snapshot_date DATE NOT NULL,
    order_number TEXT NOT NULL,
    hours_incurred NUMERIC(18,4) NOT NULL,
    project_code TEXT,
    work_center TEXT,
    attribution_status TEXT NOT NULL
        CHECK (attribution_status IN ('single_ct', 'unknown_ct', 'multi_ct')),
    source_file_hash TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, order_number)
);
CREATE INDEX IF NOT EXISTS idx_closed_of_hours_ct
    ON closed_of_hours (snapshot_date, work_center);
CREATE OR REPLACE VIEW v_closed_of_hours AS
SELECT snapshot_date, order_number, project_code, work_center,
       hours_incurred, attribution_status
FROM closed_of_hours;

-- Explicit user-approved attribution of historical OFs; never inferred from bonuses.
-- The importer reapplies these mappings on every future snapshot.
CREATE TABLE IF NOT EXISTS closed_of_manual_assignments (
    order_number TEXT PRIMARY KEY CHECK (order_number ~ '^[0-9]{6}$'),
    project_code TEXT NOT NULL REFERENCES projects(project_code),
    work_center TEXT NOT NULL,
    justification TEXT NOT NULL CHECK (btrim(justification) <> ''),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- User-validated description is global to the closed OF and survives snapshot reloads.
ALTER TABLE closed_of_manual_assignments
    ADD COLUMN IF NOT EXISTS manual_description TEXT;

-- ERP source label, preserved by snapshot independently of manual overrides.
CREATE TABLE IF NOT EXISTS closed_of_source_descriptions (
    snapshot_date DATE NOT NULL,
    order_number TEXT NOT NULL,
    source_description TEXT NOT NULL CHECK (btrim(source_description) <> ''),
    source_file_hash TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, order_number)
);

-- A closed OF is 100% consumed: reporting grants equal definitive incurred hours.
-- Raw ERP source hours remain unchanged and are never distributed to bonuses.
-- Previous snapshots are not backfilled; closed totals apply only on their dated rows.
-- Nothing is reported for closed OFs without both an explicit/verified project and CT.
CREATE OR REPLACE VIEW v_reporting_of_hours AS
SELECT f.snapshot_date, f.project_code, f.work_center, f.order_number,
       MAX(f.order_description) AS order_description,
       MAX(f.order_status) AS order_status,
       SUM(f.hours_granted) AS hours_granted,
       SUM(f.hours_incurred) AS hours_incurred,
       SUM(f.hours_pending) AS hours_pending,
       'OPERATIVE'::TEXT AS hours_source
FROM fact_hours f
GROUP BY f.snapshot_date, f.project_code, f.work_center, f.order_number
UNION ALL
SELECT c.snapshot_date, c.project_code, c.work_center, c.order_number,
       COALESCE(NULLIF(BTRIM(od.of_detailed_description), ''),
                NULLIF(BTRIM(a.manual_description), ''),
                NULLIF(BTRIM(sd.source_description), ''),
                'OF cerrada')::TEXT AS order_description,
       'Cerrad'::TEXT AS order_status,
       c.hours_incurred AS hours_granted,
       c.hours_incurred,
       0::NUMERIC AS hours_pending,
       'CLOSED_OF'::TEXT AS hours_source
FROM closed_of_hours c
LEFT JOIN closed_of_manual_assignments a ON a.order_number = c.order_number
LEFT JOIN of_descriptions od ON od.snapshot_date = c.snapshot_date AND od.order_number = c.order_number
LEFT JOIN closed_of_source_descriptions sd ON sd.snapshot_date = c.snapshot_date AND sd.order_number = c.order_number
WHERE c.project_code IS NOT NULL AND c.work_center IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM fact_hours f
      WHERE f.snapshot_date = c.snapshot_date AND f.order_number = c.order_number
  );

CREATE OR REPLACE VIEW v_latest_snapshot AS
SELECT MAX(snapshot_date) AS snapshot_date
FROM v_reporting_of_hours;

CREATE OR REPLACE VIEW v_project_hours AS
SELECT
    f.snapshot_date,
    f.project_code,
    f.work_center,
    COALESCE(MAX(p.description), MAX(f.project_code)) AS project_description,
    MAX(p.customer) AS customer,
    MAX(p.status) AS project_status,
    MAX(p.project_manager) AS project_manager,
    CASE WHEN COUNT(*) FILTER (WHERE f.hours_granted IS NULL)>0 THEN NULL ELSE SUM(f.hours_granted) END AS hours_granted,
    SUM(f.hours_incurred) AS hours_incurred,
    CASE WHEN COUNT(*) FILTER (WHERE f.hours_granted IS NULL)>0 THEN NULL ELSE SUM(f.hours_incurred) - SUM(f.hours_granted) END AS deviation_hours,
    CASE WHEN COUNT(*) FILTER (WHERE f.hours_granted IS NULL)>0 THEN NULL ELSE SUM(f.hours_granted) - SUM(f.hours_incurred) END AS remaining_hours,
    CASE
        WHEN COUNT(*) FILTER (WHERE f.hours_granted IS NULL)>0 OR SUM(f.hours_granted) = 0 THEN NULL
        ELSE SUM(f.hours_incurred) / SUM(f.hours_granted)
    END AS consumption_ratio
FROM v_reporting_of_hours f
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
    CASE WHEN COUNT(*) FILTER (WHERE f.hours_granted IS NULL)>0 THEN NULL ELSE SUM(f.hours_granted) END AS hours_granted,
    SUM(f.hours_incurred) AS hours_incurred,
    CASE WHEN COUNT(*) FILTER (WHERE f.hours_granted IS NULL)>0 THEN NULL ELSE SUM(f.hours_incurred) - SUM(f.hours_granted) END AS deviation_hours,
    CASE WHEN COUNT(*) FILTER (WHERE f.hours_granted IS NULL)>0 THEN NULL ELSE SUM(f.hours_granted) - SUM(f.hours_incurred) END AS remaining_hours,
    CASE
        WHEN COUNT(*) FILTER (WHERE f.hours_granted IS NULL)>0 OR SUM(f.hours_granted) = 0 THEN NULL
        ELSE SUM(f.hours_incurred) / SUM(f.hours_granted)
    END AS consumption_ratio
FROM v_reporting_of_hours f
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

-- Snapshot-scoped, validated LLM descriptions. The generic ERP descriptions
-- remain stored separately and are not used as fallback in the dashboard.
CREATE TABLE IF NOT EXISTS of_descriptions (
    snapshot_date DATE NOT NULL,
    order_number TEXT NOT NULL,
    of_detailed_description TEXT NOT NULL CHECK (btrim(of_detailed_description) <> ''),
    source_file_hash TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, order_number)
);

CREATE TABLE IF NOT EXISTS bonus_descriptions (
    snapshot_date DATE NOT NULL,
    bonus_id TEXT NOT NULL,
    bo_detailed_description TEXT NOT NULL CHECK (btrim(bo_detailed_description) <> ''),
    source_file_hash TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, bonus_id)
);
