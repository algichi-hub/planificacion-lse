"""Transactional Neon ingestion of bonus-to-CT history and closed OF totals.

Consumes only the two auxiliary indexes previously validated against ERP hashes.
No hours are duplicated across bonuses; ambiguous CTs remain unallocated.
"""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path


def read_index(z: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    with z.open(name) as stream:
        return list(csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline=""), delimiter=";"))


def load_closed_pipeline(cur, prepared_zip: Path, snapshot: date, closed_hash: str) -> dict[str, int]:
    with zipfile.ZipFile(prepared_zip) as z:
        bonus_rows = read_index(z, "indice_bono_ct.csv")
        closed_rows = read_index(z, "indice_of_cerradas.csv")

    # Seed known historical relationships before adding the current export.
    # A contradictory legacy CT is an error, never an implicit overwrite.
    conflicts = cur.execute("""
        SELECT bonus_id FROM fact_hours
        WHERE bonus_id IS NOT NULL AND work_center IS NOT NULL
        GROUP BY bonus_id HAVING COUNT(DISTINCT work_center) > 1
        LIMIT 10
    """).fetchall()
    if conflicts:
        raise ValueError(f"Bonos históricos con varios CT: {conflicts}")

    conflicts = cur.execute("""
        SELECT f.bonus_id, r.work_center, MIN(f.work_center)
        FROM fact_hours f JOIN bonus_ct_registry r ON r.bonus_id=f.bonus_id
        WHERE f.bonus_id IS NOT NULL AND f.work_center IS NOT NULL
        GROUP BY f.bonus_id, r.work_center
        HAVING MIN(f.work_center) <> r.work_center LIMIT 10
    """).fetchall()
    if conflicts:
        raise ValueError(f"Registro bono-CT contradice historial: {conflicts}")

    cur.execute("""
        INSERT INTO bonus_ct_registry
            (bonus_id, order_number, work_center, first_seen_snapshot, last_seen_snapshot)
        SELECT bonus_id, MIN(order_number), MIN(work_center),
               MIN(snapshot_date), MAX(snapshot_date)
        FROM fact_hours
        WHERE bonus_id IS NOT NULL AND work_center IS NOT NULL
        GROUP BY bonus_id
        ON CONFLICT (bonus_id) DO UPDATE SET
            first_seen_snapshot = LEAST(bonus_ct_registry.first_seen_snapshot,
                                        EXCLUDED.first_seen_snapshot),
            last_seen_snapshot = GREATEST(bonus_ct_registry.last_seen_snapshot,
                                         EXCLUDED.last_seen_snapshot)
    """)

    cur.execute("CREATE TEMP TABLE incoming_bonus_ct (bonus_id TEXT PRIMARY KEY, work_center TEXT NOT NULL) ON COMMIT DROP")
    with cur.copy("COPY incoming_bonus_ct (bonus_id, work_center) FROM STDIN") as cp:
        for row in bonus_rows:
            cp.write_row((row["Bono numero"], row["Ct."]))

    conflicts = cur.execute("""
        SELECT incoming.bonus_id, registry.work_center, incoming.work_center
        FROM incoming_bonus_ct incoming
        JOIN bonus_ct_registry registry USING (bonus_id)
        WHERE incoming.work_center <> registry.work_center
        LIMIT 20
    """).fetchall()
    if conflicts:
        raise ValueError(f"Conflicto bono-CT, importación cancelada: {conflicts}")

    cur.execute("""
        INSERT INTO bonus_ct_registry
            (bonus_id, order_number, work_center, first_seen_snapshot, last_seen_snapshot)
        SELECT bonus_id, LEFT(bonus_id, 6), work_center, %s, %s
        FROM incoming_bonus_ct WHERE TRUE
        ON CONFLICT (bonus_id) DO UPDATE SET
            last_seen_snapshot = GREATEST(bonus_ct_registry.last_seen_snapshot,
                                         EXCLUDED.last_seen_snapshot)
    """, (snapshot, snapshot))

    cur.execute("CREATE TEMP TABLE incoming_closed (order_number TEXT PRIMARY KEY, hours_incurred NUMERIC(18,4)) ON COMMIT DROP")
    with cur.copy("COPY incoming_closed (order_number, hours_incurred) FROM STDIN") as cp:
        for row in closed_rows:
            cp.write_row((row["OF numero"], Decimal(row["H_INV_TOT_"])))

    # The closed file is a complete export, not a delta. Replace the selected
    # snapshot's closed-OF set atomically, leaving all older snapshots untouched.
    cur.execute("DELETE FROM closed_of_hours WHERE snapshot_date = %s", (snapshot,))
    cur.execute("""
        INSERT INTO closed_of_hours
            (snapshot_date, order_number, hours_incurred, project_code,
             work_center, attribution_status, source_file_hash)
        SELECT %s, c.order_number, c.hours_incurred,
               CASE WHEN p.project_count = 1 THEN p.project_code ELSE NULL END,
               CASE WHEN w.ct_count = 1 THEN w.work_center ELSE NULL END,
               CASE WHEN w.ct_count IS NULL THEN 'unknown_ct'
                    WHEN w.ct_count > 1 THEN 'multi_ct'
                    ELSE 'single_ct' END,
               %s
        FROM incoming_closed c
        LEFT JOIN (
            SELECT r.order_number, COUNT(DISTINCT r.work_center) AS ct_count,
                   MIN(r.work_center) AS work_center
            FROM bonus_ct_registry r JOIN incoming_closed c2 ON c2.order_number = r.order_number
            GROUP BY r.order_number
        ) w ON w.order_number = c.order_number
        LEFT JOIN (
            SELECT f.order_number, COUNT(DISTINCT f.project_code) AS project_count,
                   MIN(f.project_code) AS project_code
            FROM fact_hours f JOIN incoming_closed c3 ON c3.order_number = f.order_number
            WHERE f.project_code IS NOT NULL
            GROUP BY f.order_number
        ) p ON p.order_number = c.order_number
    """, (snapshot, closed_hash))
    rows = cur.execute("""
        SELECT attribution_status, COUNT(*) FROM closed_of_hours
        WHERE snapshot_date = %s GROUP BY attribution_status
    """, (snapshot,)).fetchall()
    return {"bonuses_in_source": len(bonus_rows),
            "closed_of": len(closed_rows),
            **{status: count for status, count in rows}}
