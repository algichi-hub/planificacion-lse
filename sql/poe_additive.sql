-- POE only. No ALTER/UPDATE/DELETE on ERP or EAC structures.
CREATE TABLE IF NOT EXISTS poe_snapshots (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    year integer NOT NULL CHECK(year BETWEEN 2000 AND 2200),
    month smallint NOT NULL CHECK(month BETWEEN 1 AND 12),
    status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published')),
    revision bigint NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    UNIQUE(year,month)
);
CREATE TABLE IF NOT EXISTS poe_months (
    snapshot_id bigint NOT NULL REFERENCES poe_snapshots(id) ON DELETE CASCADE,
    period date NOT NULL CHECK(EXTRACT(DAY FROM period)=1),
    kind text NOT NULL CHECK(kind IN ('real','previsto')),
    PRIMARY KEY(snapshot_id,period)
);
CREATE TABLE IF NOT EXISTS poe_directors (
    snapshot_id bigint NOT NULL REFERENCES poe_snapshots(id) ON DELETE CASCADE,
    director text NOT NULL CHECK(length(btrim(director)) BETWEEN 1 AND 100),
    PRIMARY KEY(snapshot_id,director)
);
CREATE TABLE IF NOT EXISTS poe_hours (
    snapshot_id bigint NOT NULL,
    director text NOT NULL,
    period date NOT NULL,
    hours numeric(14,2) NOT NULL CHECK(hours >= 0),
    PRIMARY KEY(snapshot_id,director,period),
    FOREIGN KEY(snapshot_id,director) REFERENCES poe_directors(snapshot_id,director) ON DELETE CASCADE,
    FOREIGN KEY(snapshot_id,period) REFERENCES poe_months(snapshot_id,period) ON DELETE CASCADE
);
