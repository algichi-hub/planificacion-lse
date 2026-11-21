"""Read-only post-import regression gate for LSE closed orders.

Usage: python scripts/check_closed_of_regression.py --snapshot-date 2026-11-21 \
    --director-code 500084 --ct 422 --expected-incurred 2820.7526

No writes. Uses DATABASE_URL from the environment.
"""
from __future__ import annotations

import argparse
import os
from datetime import date
from decimal import Decimal

import psycopg


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-date", required=True, type=date.fromisoformat)
    parser.add_argument("--director-code", required=True)
    parser.add_argument("--ct", default="422")
    parser.add_argument("--expected-incurred", type=Decimal)
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Falta DATABASE_URL")
    with psycopg.connect(url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            branch = cur.execute("SELECT current_setting('neon.branch_id', true)").fetchone()[0]
            if branch != "br-blue-firefly-b1adfx47":
                raise SystemExit(f"Rama Neon distinta de development: {branch}")
            incurred, granted = cur.execute("""
                SELECT COALESCE(SUM(f.hours_incurred), 0),
                       COALESCE(SUM(f.hours_granted), 0)
                FROM v_reporting_of_hours f
                JOIN projects p USING(project_code)
                WHERE f.snapshot_date = %s
                  AND f.work_center = %s
                  AND split_part(p.project_manager, ' ', 1) = %s
            """, (args.snapshot_date, args.ct, args.director_code)).fetchone()
            duplicates = cur.execute("""
                SELECT COUNT(*) FROM (
                    SELECT order_number FROM v_reporting_of_hours
                    WHERE snapshot_date = %s
                    GROUP BY order_number HAVING COUNT(*) > 1
                ) duplicated
            """, (args.snapshot_date,)).fetchone()[0]
            conflicts = cur.execute("""
                SELECT COUNT(*) FROM closed_of_hours c
                JOIN closed_of_manual_assignments a USING(order_number)
                WHERE c.snapshot_date = %s AND c.work_center IS DISTINCT FROM a.work_center
            """, (args.snapshot_date,)).fetchone()[0]
            source_descriptions = cur.execute("""
                SELECT COUNT(*) FROM closed_of_source_descriptions
                WHERE snapshot_date = %s
            """, (args.snapshot_date,)).fetchone()[0]
    print(f"Neon: {branch}; fecha: {args.snapshot_date}; Ct: {args.ct}; director: {args.director_code}")
    print(f"Incurridas: {incurred}; concedidas: {granted}; títulos ERP cerradas: {source_descriptions}")
    print(f"OF duplicadas: {duplicates}; asignaciones manuales contradictorias: {conflicts}")
    if duplicates or conflicts:
        raise SystemExit("ERROR: fallo de integridad tras importación")
    if args.expected_incurred is not None and abs(incurred - args.expected_incurred) > Decimal("0.0001"):
        raise SystemExit(f"ERROR: esperado {args.expected_incurred}; real {incurred}")
    print("PASS: validación de atribuciones y horas")


if __name__ == "__main__":
    main()
