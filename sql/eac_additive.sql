-- EAC/ETC: additive objects only. Existing ERP tables and views remain unchanged.
CREATE TABLE IF NOT EXISTS eac_snapshots (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    year integer NOT NULL CHECK (year BETWEEN 2000 AND 2200),
    quarter smallint NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    UNIQUE (year, quarter)
);
CREATE TABLE IF NOT EXISTS eac_project_hours (
    snapshot_id bigint NOT NULL REFERENCES eac_snapshots(id) ON DELETE RESTRICT,
    project_code text NOT NULL REFERENCES projects(project_code) ON DELETE RESTRICT,
    etc_hours numeric(16,2) NOT NULL CHECK (etc_hours >= 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_id, project_code)
);
CREATE TABLE IF NOT EXISTS eac_project_hours_audit (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_id bigint NOT NULL REFERENCES eac_snapshots(id) ON DELETE RESTRICT,
    project_code text NOT NULL,
    old_hours numeric(16,2),
    new_hours numeric(16,2),
    changed_at timestamptz NOT NULL DEFAULT now(),
    CHECK (old_hours IS DISTINCT FROM new_hours)
);
CREATE INDEX IF NOT EXISTS idx_eac_hours_project ON eac_project_hours(project_code);
CREATE INDEX IF NOT EXISTS idx_eac_audit_snapshot ON eac_project_hours_audit(snapshot_id, changed_at DESC);
