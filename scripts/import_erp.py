from __future__ import annotations

import argparse
import csv
import hashlib
import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import psycopg
from dotenv import load_dotenv


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"No se pudo decodificar {path}")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decimal_es(value: str | None) -> Decimal:
    if value is None:
        return Decimal("0")
    s = value.strip().replace("\xa0", "")
    if not s:
        return Decimal("0")
    s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation as exc:
        raise ValueError(f"Valor numérico no válido: {value!r}") from exc


def int_or_none(value: str | None) -> int | None:
    s = (value or "").strip()
    if not s:
        return None
    return int(s)


def date_es(value: str | None) -> date | None:
    s = (value or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def rows_pipe(path: Path) -> tuple[list[str], list[list[str]]]:
    text = read_text(path)
    reader = csv.reader(text.splitlines(), delimiter="|")
    rows = list(reader)
    if not rows:
        raise ValueError(f"Fichero vacío: {path}")
    headers = [h.strip() for h in rows[0]]
    return headers, rows[1:]


def row_dict(headers: list[str], row: list[str]) -> dict[str, str]:
    values = [v.strip() for v in row]
    if len(values) < len(headers):
        values += [""] * (len(headers) - len(values))
    return dict(zip(headers, values, strict=False))


def require_headers(headers: list[str], required: set[str], path: Path) -> None:
    missing = sorted(required - set(headers))
    if missing:
        raise ValueError(f"{path.name}: faltan columnas obligatorias: {', '.join(missing)}")


def load_projects(cur, path: Path) -> int:
    headers, rows = rows_pipe(path)
    required = {"Proyecto", "Descripción", "Cliente", "Referencia", "Clave Acceso", "Tip", "Estatus", "Eta", "Director Proyecto"}
    require_headers(headers, required, path)

    count = 0
    for raw in rows:
        r = row_dict(headers, raw)
        code = r["Proyecto"].strip()
        if not code:
            continue
        cur.execute(
            """
            INSERT INTO projects (
                project_code, description, customer, reference, access_key,
                project_type, status, eta, project_manager, updated_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (project_code) DO UPDATE SET
                description = EXCLUDED.description,
                customer = EXCLUDED.customer,
                reference = EXCLUDED.reference,
                access_key = EXCLUDED.access_key,
                project_type = EXCLUDED.project_type,
                status = EXCLUDED.status,
                eta = EXCLUDED.eta,
                project_manager = EXCLUDED.project_manager,
                updated_at = NOW()
            """,
            (
                code, r["Descripción"], r["Cliente"], r["Referencia"], r["Clave Acceso"],
                r["Tip"], r["Estatus"], r["Eta"], r["Director Proyecto"],
            ),
        )
        count += 1
    return count


def load_hours(cur, path: Path, snapshot: date) -> tuple[int, str]:
    headers, rows = rows_pipe(path)
    required = {
        "Orden", "Artículo", "Descripcion", "Estat.", "F.Lanz.", "Opr.",
        "Descripción", "Ct.", "T.Conce.", "T.Inver.", "T.Pendi.", "Proyec"
    }
    require_headers(headers, required, path)

    digest = file_hash(path)
    cur.execute("DELETE FROM fact_hours WHERE snapshot_date = %s", (snapshot,))

    count = 0
    for source_row_no, raw in enumerate(rows, start=2):
        r = row_dict(headers, raw)
        order_number = r["Orden"].strip()
        if not order_number:
            continue

        operation_number = int_or_none(r["Opr."])
        bonus_id = (
            f"{order_number}{operation_number:04d}"
            if operation_number is not None else None
        )

        hours_granted = decimal_es(r["T.Conce."])
        hours_incurred = decimal_es(r["T.Inver."])
        try:
            hours_pending = decimal_es(r["T.Pendi."])
        except ValueError:
            # Algunos exports ERP muestran ####### por desbordamiento de formato.
            # El pendiente es derivable de los dos campos base y no debe bloquear la carga.
            hours_pending = hours_granted - hours_incurred

        cur.execute(
            """
            INSERT INTO fact_hours (
                snapshot_date, source_row_no, project_code, order_number,
                operation_number, bonus_id, article, order_description,
                operation_description, order_status, launch_date, work_center,
                hours_granted, hours_incurred, hours_pending, source_file_hash
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                snapshot,
                source_row_no,
                r["Proyec"].strip() or None,
                order_number,
                operation_number,
                bonus_id,
                r["Artículo"],
                r["Descripcion"],
                r["Descripción"],
                r["Estat."],
                date_es(r["F.Lanz."]),
                r["Ct."].strip() or None,
                hours_granted,
                hours_incurred,
                hours_pending,
                digest,
            ),
        )
        count += 1

    return count, digest


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa exports ERP a PostgreSQL/Neon.")
    parser.add_argument("--hours", required=True, type=Path, help="OOFF_OP_Planif_Terminada.txt")
    parser.add_argument("--projects", required=True, type=Path, help="Proyectos_Sevilla.csv")
    parser.add_argument("--snapshot-date", default=date.today().isoformat(), help="YYYY-MM-DD")
    args = parser.parse_args()

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("Falta DATABASE_URL en el entorno o en .env")

    snapshot = date.fromisoformat(args.snapshot_date)
    schema = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(schema.read_text(encoding="utf-8"))
            project_count = load_projects(cur, args.projects)
            hours_count, digest = load_hours(cur, args.hours, snapshot)

            cur.execute(
                """
                INSERT INTO imports (snapshot_date, source_name, file_hash, row_count)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (snapshot_date, source_name) DO UPDATE SET
                    file_hash = EXCLUDED.file_hash,
                    row_count = EXCLUDED.row_count,
                    loaded_at = NOW()
                """,
                (snapshot, args.hours.name, digest, hours_count),
            )

            unmatched = cur.execute(
                """
                SELECT COUNT(DISTINCT f.project_code)
                FROM fact_hours f
                LEFT JOIN projects p ON p.project_code = f.project_code
                WHERE f.snapshot_date = %s
                  AND f.project_code IS NOT NULL
                  AND p.project_code IS NULL
                """,
                (snapshot,),
            ).fetchone()[0]

            totals = cur.execute(
                """
                SELECT
                    COALESCE(SUM(hours_granted),0),
                    COALESCE(SUM(hours_incurred),0),
                    COALESCE(SUM(hours_pending),0)
                FROM fact_hours
                WHERE snapshot_date = %s
                """,
                (snapshot,),
            ).fetchone()

        conn.commit()

    print(f"Snapshot: {snapshot}")
    print(f"Proyectos maestro procesados: {project_count}")
    print(f"Filas de horas importadas: {hours_count}")
    print(f"Proyectos sin correspondencia: {unmatched}")
    print(f"Horas concedidas: {totals[0]}")
    print(f"Horas incurridas: {totals[1]}")
    print(f"Horas pendientes fuente: {totals[2]}")


if __name__ == "__main__":
    main()
