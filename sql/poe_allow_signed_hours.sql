-- Additive migration: enable signed monthly POE adjustments.
-- Apply ONLY to a verified Planificacion LSE database branch.
-- No tables or rows are removed, and EAC / ERP are unaffected.
BEGIN;
ALTER TABLE public.poe_monthly_hours
    DROP CONSTRAINT IF EXISTS poe_monthly_hours_real_hours_check,
    DROP CONSTRAINT IF EXISTS poe_monthly_hours_planned_hours_check;
COMMIT;
