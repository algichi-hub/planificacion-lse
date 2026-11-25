-- POE V5: irreversible deletion of POE V1 test records only.
-- No modifications to projects, fact_hours, EAC, OF or bonus objects.
BEGIN;
DROP TABLE IF EXISTS poe_hours;
DROP TABLE IF EXISTS poe_months;
DROP TABLE IF EXISTS poe_directors;
DROP TABLE IF EXISTS poe_snapshots;

CREATE TABLE poe_directors (
  code text PRIMARY KEY,
  name text NOT NULL CHECK (btrim(name) <> ''),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE poe_monthly_hours (
  code text NOT NULL REFERENCES poe_directors(code) ON DELETE RESTRICT,
  period date NOT NULL CHECK (EXTRACT(DAY FROM period) = 1),
  real_hours numeric(14,2),
  planned_hours numeric(14,2),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (code, period)
);
CREATE INDEX idx_poe_monthly_period ON poe_monthly_hours(period);

CREATE TABLE poe_hours_audit (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code text NOT NULL,
  period date NOT NULL,
  old_real numeric(14,2),
  new_real numeric(14,2),
  old_planned numeric(14,2),
  new_planned numeric(14,2),
  changed_at timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION poe_audit_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO poe_hours_audit(code, period, old_real, new_real, old_planned, new_planned)
  VALUES (
    COALESCE(NEW.code, OLD.code), COALESCE(NEW.period, OLD.period),
    OLD.real_hours, NEW.real_hours, OLD.planned_hours, NEW.planned_hours
  );
  RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE TRIGGER trg_poe_hours_audit
AFTER INSERT OR DELETE OR UPDATE ON poe_monthly_hours
FOR EACH ROW EXECUTE FUNCTION poe_audit_change();
COMMIT;
