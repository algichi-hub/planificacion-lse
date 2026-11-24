"""Capture only observed OF status transitions between dated ERP snapshots.

No derived bonus hours, no retroactive CT changes and no extra round-trips per OF.
Missing OFs are not inferred to be closed; first observations create no event.
"""


def refresh_lifecycle_events(cur, snapshot):
    """Rebuild the selected snapshot's events within the existing import transaction."""
    cur.execute("DELETE FROM of_lifecycle_events WHERE snapshot_date = %s", (snapshot,))
    cur.execute("""
        WITH states AS (
            SELECT f.snapshot_date, f.order_number,
                   CASE
                       WHEN UPPER(BTRIM(MAX(f.order_status))) LIKE 'CERRAD%%' THEN 'CERRADA'
                       WHEN UPPER(BTRIM(MAX(f.order_status))) LIKE 'ACTIV%%' THEN 'ACTIVA'
                       WHEN UPPER(BTRIM(MAX(f.order_status))) LIKE 'LANZAD%%' THEN 'LANZADA'
                       WHEN UPPER(BTRIM(MAX(f.order_status))) LIKE 'TERMINAD%%' THEN 'TERMINADA'
                       ELSE COALESCE(NULLIF(UPPER(BTRIM(MAX(f.order_status))), ''), 'DESCONOCIDO')
                   END AS status
            FROM fact_hours f
            WHERE f.snapshot_date <= %s
            GROUP BY f.snapshot_date, f.order_number

            UNION ALL

            SELECT c.snapshot_date, c.order_number, 'CERRADA' AS status
            FROM closed_of_hours c
            WHERE c.snapshot_date <= %s
              AND NOT EXISTS (
                  SELECT 1 FROM fact_hours f
                  WHERE f.snapshot_date = c.snapshot_date
                    AND f.order_number = c.order_number
              )
        ),
        changes AS (
            SELECT snapshot_date, order_number, status,
                   LAG(snapshot_date) OVER history AS previous_snapshot_date,
                   LAG(status) OVER history AS previous_status
            FROM states
            WINDOW history AS (PARTITION BY order_number ORDER BY snapshot_date)
        )
        INSERT INTO of_lifecycle_events
            (snapshot_date, order_number, previous_snapshot_date,
             previous_status, current_status)
        SELECT snapshot_date, order_number, previous_snapshot_date,
               previous_status, status
        FROM changes
        WHERE snapshot_date = %s
          AND previous_status IS NOT NULL
          AND status IS DISTINCT FROM previous_status
    """, (snapshot, snapshot, snapshot))
    return cur.execute("""
        SELECT previous_status, current_status, COUNT(*)
        FROM of_lifecycle_events WHERE snapshot_date = %s
        GROUP BY previous_status, current_status
        ORDER BY previous_status, current_status
    """, (snapshot,)).fetchall()
