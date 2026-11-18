-- Additive POE-only preference. Existing directors remain visible by default.
ALTER TABLE poe_directors ADD COLUMN IF NOT EXISTS visible boolean NOT NULL DEFAULT true;
