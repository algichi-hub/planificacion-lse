"""Elimina un Ct/fecha de Neon sin afectar otros Ct ni otros snapshots.

Modo predeterminado: simulación con conteos, sin escritura.
No elimina proyectos maestros ni descripciones/importaciones compartidas por otros Ct.
"""
from __future__ import annotations

import argparse
import os
import re
from datetime import date

import psycopg
from dotenv import load_dotenv


def run(conn, ct: str, day: date, execute: bool) -> None:
    with conn.transaction():
        with conn.cursor() as cur:
            # Serializa esta utilidad para un mismo Ct/fecha (no sustituye el control
            # de concurrencia con procesos de carga independientes).
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))", (ct, day.isoformat()))
            cur.execute(
                "SELECT count(*), count(DISTINCT order_number), count(DISTINCT bonus_id) "
                "FROM fact_hours WHERE snapshot_date=%s AND work_center=%s",
                (day, ct),
            )
            hours, orders, bonuses = cur.fetchone()
            cur.execute(
                """SELECT count(*) FROM of_descriptions d
                   WHERE d.snapshot_date=%s
                     AND EXISTS (
                       SELECT 1 FROM fact_hours f
                       WHERE f.snapshot_date=d.snapshot_date
                         AND f.work_center=%s AND f.order_number=d.order_number
                     )
                     AND NOT EXISTS (
                       SELECT 1 FROM fact_hours f
                       WHERE f.snapshot_date=d.snapshot_date
                         AND f.work_center<>%s AND f.order_number=d.order_number
                     )""",
                (day, ct, ct),
            )
            of_count = cur.fetchone()[0]
            cur.execute(
                """SELECT count(*) FROM bonus_descriptions d
                   WHERE d.snapshot_date=%s
                     AND EXISTS (
                       SELECT 1 FROM fact_hours f
                       WHERE f.snapshot_date=d.snapshot_date
                         AND f.work_center=%s AND f.bonus_id=d.bonus_id
                     )
                     AND NOT EXISTS (
                       SELECT 1 FROM fact_hours f
                       WHERE f.snapshot_date=d.snapshot_date
                         AND f.work_center<>%s AND f.bonus_id=d.bonus_id
                     )""",
                (day, ct, ct),
            )
            bonus_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM fact_hours WHERE snapshot_date=%s AND work_center<>%s", (day,ct))
            other_hours=cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM imports WHERE snapshot_date=%s", (day,))
            imports=cur.fetchone()[0]
            print(f"Fecha: {day} | Ct: {ct}")
            print(f"fact_hours: {hours} filas; {orders} OF; {bonuses} bonos")
            print(f"Descripciones exclusivamente asociadas al Ct: OF={of_count}, bonos={bonus_count}")
            print(f"Filas de otros Ct en esa fecha (PROTEGIDAS): {other_hours}")
            print(f"imports por fecha: {imports}; {'se conservarán (compartidos)' if other_hours else 'se eliminarán (sin otros Ct)'}")
            print("projects: se conservan (maestro global compartido)")
            if not hours:
                print("No se han encontrado horas para ese Ct/fecha: sin cambios.")
                return
            if not execute:
                print("SIMULACIÓN: no se ha modificado Neon.")
                return
            # Eliminar únicamente descripciones no utilizadas por otros Ct
            # de la misma fecha; se usa la relación exacta con los hechos.
            cur.execute(
                """DELETE FROM bonus_descriptions d
                   WHERE d.snapshot_date=%s
                     AND EXISTS (
                       SELECT 1 FROM fact_hours f
                       WHERE f.snapshot_date=d.snapshot_date
                         AND f.work_center=%s AND f.bonus_id=d.bonus_id
                     )
                     AND NOT EXISTS (
                       SELECT 1 FROM fact_hours f
                       WHERE f.snapshot_date=d.snapshot_date
                         AND f.work_center<>%s AND f.bonus_id=d.bonus_id
                     )""",
                (day, ct, ct),
            )
            deleted_bonus=cur.rowcount
            cur.execute(
                """DELETE FROM of_descriptions d
                   WHERE d.snapshot_date=%s
                     AND EXISTS (
                       SELECT 1 FROM fact_hours f
                       WHERE f.snapshot_date=d.snapshot_date
                         AND f.work_center=%s AND f.order_number=d.order_number
                     )
                     AND NOT EXISTS (
                       SELECT 1 FROM fact_hours f
                       WHERE f.snapshot_date=d.snapshot_date
                         AND f.work_center<>%s AND f.order_number=d.order_number
                     )""",
                (day, ct, ct),
            )
            deleted_of=cur.rowcount
            cur.execute("DELETE FROM fact_hours WHERE snapshot_date=%s AND work_center=%s", (day,ct))
            deleted_hours=cur.rowcount
            deleted_imports=0
            # imports no contiene Ct; solo se puede eliminar el registro
            # completo de fecha si no hay otros centros presentes.
            if other_hours == 0:
                cur.execute("DELETE FROM imports WHERE snapshot_date=%s", (day,))
                deleted_imports=cur.rowcount
            cur.execute("SELECT count(*) FROM fact_hours WHERE snapshot_date=%s AND work_center=%s", (day,ct))
            if cur.fetchone()[0] != 0 or deleted_hours != hours:
                raise RuntimeError("Verificación fallida; se revierte la transacción.")
            print(f"ELIMINACIÓN CONFIRMADA: horas={deleted_hours}, OF={deleted_of}, bonos={deleted_bonus}, imports={deleted_imports}")
    print("Transacción confirmada correctamente.")


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ct",required=True)
    parser.add_argument("--snapshot-date",required=True)
    parser.add_argument("--execute",action="store_true",help="Permite escritura; exige --confirm")
    parser.add_argument("--confirm",help="Escribir exactamente ELIMINAR:CT:AAAA-MM-DD")
    args=parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,20}",args.ct):
        parser.error("Ct inválido")
    day=date.fromisoformat(args.snapshot_date)
    expected=f"ELIMINAR:{args.ct}:{day.isoformat()}"
    if args.execute and args.confirm != expected:
        parser.error(f"Confirmación incorrecta; añade --confirm {expected}")
    load_dotenv()
    url=os.getenv("DATABASE_URL")
    if not url:
        parser.error("Falta DATABASE_URL en .env o entorno")
    with psycopg.connect(url) as conn:
        run(conn,args.ct,day,args.execute)


if __name__=="__main__":
    main()
