"""POE: independent manual monthly real/planned hours. ERP directors are read-only."""
from datetime import date
from decimal import Decimal, InvalidOperation
import json

import pandas as pd
import psycopg
from psycopg.rows import dict_row
import streamlit as st

MONTHS = ("ENE", "FEB", "MAR", "ABR", "MAY", "JUN",
          "JUL", "AGO", "SEP", "OCT", "NOV", "DIC")
LIME = "#C5F27A"


def connect(url):
    return psycopg.connect(url, connect_timeout=10, row_factory=dict_row)


def month_shift(period, distance):
    index = period.year * 12 + period.month - 1 + distance
    return date(index // 12, index % 12 + 1, 1)


def parse_hours(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, str):
        value = value.strip().replace(" ", "").replace(",", ".")
        if not value:
            return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Horas POE no válidas: {value}")
    if not number.is_finite() or number < 0 or number.as_tuple().exponent < -2:
        raise ValueError(f"Horas POE no válidas (máximo 2 decimales): {value}")
    if number >= Decimal("1000000000000"):
        raise ValueError("Horas POE fuera de rango.")
    return number


def sync_directors(url):
    """One additive ERP read / POE write. Existing directors are never deleted."""
    with connect(url) as conn:
        with conn.transaction():
            return conn.execute("""
                WITH labels AS (
                  SELECT DISTINCT btrim(project_manager) AS label
                  FROM projects
                  WHERE NULLIF(btrim(project_manager), '') IS NOT NULL
                ), parsed AS (
                  SELECT substring(label FROM '^[^[:space:]]+') AS code,
                         CASE WHEN label ~ '[[:space:]]'
                              THEN btrim(regexp_replace(label, '^[^[:space:]]+[[:space:]]+', ''))
                              ELSE label END AS name
                  FROM labels
                )
                INSERT INTO poe_directors(code, name)
                SELECT DISTINCT ON (code) code, name FROM parsed
                WHERE code <> '' AND name <> ''
                ORDER BY code, name
                ON CONFLICT(code) DO NOTHING
                RETURNING code
            """).fetchall()


def load_year(url, year):
    """Exactly one read; includes archived directors even when no hours exist."""
    with connect(url) as conn:
        return conn.execute("""
            SELECT d.code, d.name, h.period, h.real_hours, h.planned_hours
            FROM poe_directors d LEFT JOIN poe_monthly_hours h
              ON h.code=d.code AND h.period >= %s AND h.period < %s
            ORDER BY d.code, h.period
        """, (date(year, 1, 1), date(year + 1, 1, 1))).fetchall()


def unpack_year(rows):
    directors = {}
    hours = {}
    for row in rows:
        directors[row["code"]] = row["name"]
        if row["period"] is not None:
            hours[(row["code"], row["period"])] = (
                row["real_hours"], row["planned_hours"]
            )
    return {"directors": directors, "hours": hours}


def month_frame(data, period):
    return pd.DataFrame([
        {"Director": name, "Real (h)": float(data["hours"].get((code, period), (None, None))[0])
         if data["hours"].get((code, period), (None, None))[0] is not None else float("nan"),
         "Previsto (h)": float(data["hours"].get((code, period), (None, None))[1])
         if data["hours"].get((code, period), (None, None))[1] is not None else float("nan")}
        for code, name in data["directors"].items()
    ])


def month_changes(data, period, edited):
    """Compare complete edited rows in their immutable catalog order."""
    codes = list(data["directors"])
    if len(codes) != len(edited):
        raise ValueError("La tabla ha cambiado de tamaño: recarga POE.")
    result = []
    for code, row in zip(codes, edited.to_dict("records")):
        if row["Director"] != data["directors"][code]:
            raise ValueError("Ha cambiado el orden de directores: recarga POE.")
        before = data["hours"].get((code, period), (None, None))
        after = (parse_hours(row["Real (h)"]), parse_hours(row["Previsto (h)"]))
        if before != after:
            result.append((code, before, after))
    return result


def save_month(url, period, changes):
    """Per-month atomic optimistic save, no writes to any non-POE table."""
    if not changes:
        return 0
    codes = [code for code, _, _ in changes]
    with connect(url) as conn:
        with conn.transaction():
            # Lock even when an edited (director, month) row does not yet exist.
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                         (f"poe-month:{period.isoformat()}",))
            rows = conn.execute(
                "SELECT code,real_hours,planned_hours FROM poe_monthly_hours "
                "WHERE period=%s AND code=ANY(%s) FOR UPDATE", (period, codes)
            ).fetchall()
            actual = {r["code"]: (r["real_hours"], r["planned_hours"]) for r in rows}
            for code, original, _ in changes:
                if actual.get(code, (None, None)) != original:
                    raise ValueError(
                        f"Conflicto en {code}, {period:%m/%Y}: "
                        "otro usuario ha modificado las horas. Recarga los datos."
                    )
            insert = [
                {"code": code, "real": str(new[0]) if new[0] is not None else None,
                 "planned": str(new[1]) if new[1] is not None else None}
                for code, _, new in changes if new != (None, None)
            ]
            removed = [code for code, _, new in changes if new == (None, None)]
            if insert:
                conn.execute("""
                    INSERT INTO poe_monthly_hours(code,period,real_hours,planned_hours)
                    SELECT x.code,%s,x.real::numeric,x.planned::numeric
                    FROM jsonb_to_recordset(%s::jsonb)
                         AS x(code text,real text,planned text)
                    ON CONFLICT(code,period) DO UPDATE SET
                      real_hours=EXCLUDED.real_hours,
                      planned_hours=EXCLUDED.planned_hours,
                      updated_at=now()
                """, (period, json.dumps(insert)))
            if removed:
                conn.execute(
                    "DELETE FROM poe_monthly_hours WHERE period=%s AND code=ANY(%s)",
                    (period, removed)
                )
    return len(changes)


def update_local(data, period, changes):
    for code, _, after in changes:
        if after == (None, None):
            data["hours"].pop((code, period), None)
        else:
            data["hours"][(code, period)] = after


def annual_frame(data, year):
    """One displayed value per month. Real=0 overrides any planned hours."""
    values = []
    masks = []
    for code, name in data["directors"].items():
        row = {"Director": name}
        mask = {"Director": ""}
        for month, title in enumerate(MONTHS, 1):
            real, planned = data["hours"].get((code, date(year, month, 1)), (None, None))
            row[title] = float(real if real is not None else planned) \
                if real is not None or planned is not None else float("nan")
            mask[title] = f"background-color: {LIME}; color: #20310A" if real is not None else ""
        values.append(row)
        masks.append(mask)
    return pd.DataFrame(values, columns=["Director", *MONTHS]), \
           pd.DataFrame(masks, columns=["Director", *MONTHS])


def style_annual(data, year):
    frame, mask = annual_frame(data, year)
    return frame.style.apply(lambda _: mask, axis=None).format(
        {month: "{:.2f}" for month in MONTHS}, na_rep=""
    )


def render(url):
    st.subheader("POE mensual")
    st.caption("Horas reales y previstas manuales; lectura de directores EAC, sin modificar OF, bonos ni EAC.")
    state = st.session_state
    if not state.get("poe_v5_synced", False):
        try:
            sync_directors(url)
            state["poe_v5_synced"] = True
        except psycopg.errors.UndefinedTable:
            st.error("Faltan las tablas POE V5. Aplicar sql/poe_v5.sql.")
            return
        except psycopg.Error as exc:
            st.error(f"Error de sincronización POE: {type(exc).__name__}")
            return

    if "poe_v5_cache" not in state:
        state["poe_v5_cache"] = {}
    if "poe_v5_period" not in state:
        today = date.today()
        state["poe_v5_period"] = date(today.year, today.month, 1)
    if "poe_v5_editing" not in state:
        state["poe_v5_editing"] = False
    if "poe_v5_grid_serial" not in state:
        state["poe_v5_grid_serial"] = 0
    period = state["poe_v5_period"]
    year = period.year
    cache = state["poe_v5_cache"]
    if year not in cache:
        try:
            cache[year] = unpack_year(load_year(url, year))
        except psycopg.Error as exc:
            st.error(f"No se puede leer POE: {type(exc).__name__}")
            return
    data = cache[year]

    if state["poe_v5_editing"]:
        st.markdown(f"**Edición abierta · {MONTHS[period.month-1]} {year}**")
        st.caption("Director de solo lectura; pega bloques Excel en Real (h) y Previsto (h).")
        edited = st.data_editor(
            month_frame(data, period),
            hide_index=True, use_container_width=True, num_rows="fixed",
            disabled=["Director"],
            column_config={
                "Director": st.column_config.TextColumn("Director", width="large"),
                "Real (h)": st.column_config.NumberColumn(
                    "Real (h)", min_value=0, step=0.01, format="%.2f"),
                "Previsto (h)": st.column_config.NumberColumn(
                    "Previsto (h)", min_value=0, step=0.01, format="%.2f"),
            },
            key=f"poe_v5_grid_{period:%Y%m}_{state['poe_v5_grid_serial']}",
        )

        # Controls after editor ensure block pastes reach the returned DataFrame first.
        left, save, close, right = st.columns([1, 2, 2, 1])
        action = ("prev" if left.button("◀", help="Guardar y mes anterior") else
                  "save" if save.button("Guardar mes") else
                  "close" if close.button("Cerrar edición") else
                  "next" if right.button("▶", help="Guardar y mes siguiente") else None)
        if action:
            try:
                changes = month_changes(data, period, edited)
                if changes:
                    with st.spinner("Guardando POE..."):
                        save_month(url, period, changes)
                    update_local(data, period, changes)
                if action in ("prev", "next"):
                    state["poe_v5_period"] = month_shift(period, -1 if action == "prev" else 1)
                if action == "close":
                    state["poe_v5_editing"] = False
                state["poe_v5_grid_serial"] += 1
                if action == "save":
                    st.toast(f"Guardadas {len(changes)} filas del mes.")
                st.rerun()
            except (ValueError, psycopg.Error) as exc:
                st.error(str(exc))
                st.warning("La edición permanece abierta y las celdas no se han descartado.")
    else:
        a, b = st.columns([2, 2])
        # Reconcile only on external year transitions; never overwrite a user's year choice.
        if state.get("poe_v5_year_anchor") != year:
            state["poe_v5_read_year"] = year
            state["poe_v5_year_anchor"] = year
        selected_year = a.number_input("Año", min_value=2000, max_value=2199,
                                       step=1, key="poe_v5_read_year")
        if int(selected_year) != year:
            state["poe_v5_period"] = date(int(selected_year), 1, 1)
            st.rerun()
        if b.button("Abrir modo edición", type="primary"):
            state["poe_v5_editing"] = True
            st.rerun()
        st.caption("Verde lima = real registrado (incluye cero). Sin fondo = previsto o vacío.")
        st.dataframe(style_annual(data, year), hide_index=True,
                     use_container_width=True)
        if st.button("Actualizar directores y datos POE"):
            try:
                sync_directors(url)
                state["poe_v5_cache"] = {}
                st.rerun()
            except psycopg.Error as exc:
                st.error(str(exc))
