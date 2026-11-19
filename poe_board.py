"""POE: independent manual monthly real/planned hours. ERP directors are read-only."""
from datetime import date
from decimal import Decimal, InvalidOperation
import json

import pandas as pd
import plotly.graph_objects as go
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
            SELECT d.code, d.name, d.visible, h.period, h.real_hours, h.planned_hours,
                   (SELECT SUM(prev.real_hours) FROM poe_monthly_hours prev
                    WHERE prev.code=d.code AND prev.period < %s) AS opening_real,
                   (SELECT COUNT(prev.real_hours) FROM poe_monthly_hours prev
                    WHERE prev.code=d.code AND prev.period < %s) AS opening_count
            FROM poe_directors d LEFT JOIN poe_monthly_hours h
              ON h.code=d.code AND h.period >= %s AND h.period < %s
            ORDER BY d.code, h.period
        """, (date(year, 1, 1), date(year, 1, 1),
                 date(year, 1, 1), date(year + 1, 1, 1))).fetchall()


def unpack_year(rows):
    directors = {}
    visible = {}
    opening = {}
    opening_count = {}
    hours = {}
    for row in rows:
        directors[row["code"]] = row["name"]
        visible[row["code"]] = row.get("visible", True)
        opening[row["code"]] = row.get("opening_real")
        opening_count[row["code"]] = int(row.get("opening_count") or 0)
        if row["period"] is not None:
            hours[(row["code"], row["period"])] = (
                row["real_hours"], row["planned_hours"]
            )
    return {"directors": directors, "visible": visible, "hours": hours,
            "opening": opening, "opening_count": opening_count}


def month_frame(data, period):
    return pd.DataFrame([
        {"Visible": bool(data.get("visible", {}).get(code, True)),
         "Director": name, "Real (h)": float(data["hours"].get((code, period), (None, None))[0])
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


def visibility_changes(data, edited):
    """Detect edited checkboxes independently from the monthly hour values."""
    return [(code, bool(data.get("visible", {}).get(code, True)), bool(value))
            for code, value in zip(data["directors"], edited["Visible"])
            if bool(data.get("visible", {}).get(code, True)) != bool(value)]


def save_month(url, period, changes, visibility=()):
    """Atomic optimistic save of hours and visibility; POE tables only."""
    if not changes and not visibility:
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
            # Repeated saves from the same tab are harmless when already applied.
            pending = []
            for code, original, desired in changes:
                current = actual.get(code, (None, None))
                if current == desired:
                    continue
                if current != original:
                    raise ValueError(
                        f"Conflicto en {code}, {period:%m/%Y}: "
                        "el dato en Neon ha cambiado desde la carga."
                    )
                pending.append((code, original, desired))
            changes = pending
            if visibility:
                current_visible = {r["code"]: r["visible"] for r in conn.execute(
                    "SELECT code,visible FROM poe_directors WHERE code=ANY(%s) FOR UPDATE",
                    ([code for code, _, _ in visibility],)
                ).fetchall()}
                for code, old, new in visibility:
                    if current_visible.get(code) not in (old, new):
                        raise ValueError(f"Conflicto de visibilidad en {code}: recarga POE.")
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
            pending_visible = [{"code": code, "visible": new} for code, old, new in visibility
                               if current_visible.get(code) == old]
            if pending_visible:
                conn.execute("""
                    UPDATE poe_directors AS d SET visible=x.visible
                    FROM jsonb_to_recordset(%s::jsonb) AS x(code text, visible boolean)
                    WHERE d.code=x.code
                """, (json.dumps(pending_visible),))
    return len(changes) + len(pending_visible) if visibility else len(changes)


def update_local(data, period, changes, visibility=()):
    for code, _, new in visibility:
        data.setdefault("visible", {})[code] = new
    for code, _, after in changes:
        if after == (None, None):
            data["hours"].pop((code, period), None)
        else:
            data["hours"][(code, period)] = after


def restore_pending_cells(data, period, pending):
    """Overlay only user-edited cells onto freshly fetched Neon values."""
    frame = month_frame(data, period)
    columns = ("Real (h)", "Previsto (h)", "Visible")
    for index, code in enumerate(data["directors"]):
        for column in columns:
            key = (code, column)
            if key in pending:
                value = pending[key]
                frame.at[index, column] = (bool(value) if column == "Visible" else
                                           float(value) if value is not None else float("nan"))
    return frame


def queue_action(action):
    """Only one navigation/save operation per Streamlit session at a time."""
    state = st.session_state
    if not state.get("poe_v5_action"):
        state["poe_v5_action"] = action


def annual_frame(data, year):
    """One displayed value per month. Real=0 overrides any planned hours."""
    values = []
    masks = []
    for code, name in data["directors"].items():
        if not data.get("visible", {}).get(code, True):
            continue
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
        {month: "{:.0f}" for month in MONTHS}, na_rep=""
    )


@st.cache_data(ttl=300, show_spinner=False)
def director_eac(url, code):
    """Latest published EAC total for this director; one read, no writes."""
    with connect(url) as conn:
        return conn.execute("""
            SELECT s.year,s.quarter, SUM(e.etc_hours) AS eac_hours,
                   COUNT(e.project_code) AS projects
            FROM eac_snapshots s
            LEFT JOIN eac_project_hours e ON e.snapshot_id=s.id
            LEFT JOIN projects p ON p.project_code=e.project_code
            WHERE s.status='published' AND s.id=(
                SELECT id FROM eac_snapshots WHERE status='published'
                ORDER BY year DESC,quarter DESC LIMIT 1
            ) AND substring(btrim(p.project_manager) FROM '^[^[:space:]]+')=%s
            GROUP BY s.id,s.year,s.quarter
        """, (code,)).fetchone()


def annual_evolution(data, code, year):
    """Plot real and planned cumulatives for every month with each source value."""
    opening = data.get("opening", {}).get(code)
    real_total = planned_total = Decimal(opening) if opening is not None else Decimal(0)
    actual, forecast, gaps = [], [], []
    last_actual = None
    for month in range(1, 13):
        real, planned = data["hours"].get((code, date(year, month, 1)), (None, None))
        if real is not None:
            real_total += real
            last_actual = month
        # For the projected total, monthly planned replaces actual when provided;
        # otherwise reuse actual to preserve continuity with historical months.
        if planned is not None:
            planned_total += planned
        elif real is not None:
            planned_total += real
        actual.append(float(real_total) if real is not None else None)
        forecast.append(float(planned_total) if planned is not None else None)
        if real is None and planned is None:
            gaps.append(month)
    return actual, forecast, last_actual, gaps


def render_annual_chart(url, data, year):
    """Draw one director: the first visible row in the annual POE view."""
    visible_codes = [c for c in data["directors"]
                     if data.get("visible", {}).get(c, True)]
    if not visible_codes:
        st.info("No hay directores visibles para representar.")
        return
    code = visible_codes[0]
    try:
        reference = director_eac(url, code)
    except psycopg.Error as exc:
        st.warning(f"No se pudo consultar el EAC de referencia: {type(exc).__name__}")
        reference = None

    actual, forecast, last_actual, gaps = annual_evolution(data, code, year)
    if (last_actual is not None and last_actual < 12
            and forecast[last_actual - 1] is None
            and forecast[last_actual] is not None):
        # Bridge a forecast beginning immediately after the final real month.
        forecast[last_actual - 1] = actual[last_actual - 1]
    fig = go.Figure()
    if reference and reference["eac_hours"] is not None:
        fig.add_trace(go.Scatter(x=MONTHS, y=[float(reference["eac_hours"])] * 12,
                                 name="Límite EAC", mode="lines",
                                 line=dict(color="#2E9D57", width=2, dash="dash")))
    fig.add_trace(go.Scatter(x=MONTHS, y=forecast, name="Previsto acumulado",
                             mode="lines+markers", connectgaps=False,
                             line=dict(color="#89939B", width=3)))
    fig.add_trace(go.Scatter(x=MONTHS, y=actual, name="Incurrido real acumulado",
                             mode="lines+markers", connectgaps=False,
                             line=dict(color="#198754", width=3)))
    values = ([float(reference["eac_hours"])]
              if reference and reference["eac_hours"] is not None else [])
    values += [float(value) for value in actual + forecast if value is not None]
    upper = max([1.0, *values]) * 1.05
    fig.update_layout(height=390, margin=dict(l=15,r=15,t=15,b=10),
                      xaxis_title=None,yaxis_title=None,
                      xaxis=dict(fixedrange=True),
                      yaxis=dict(range=[0, upper], fixedrange=True),
                      dragmode=False,
                      legend=dict(orientation="h",y=-0.2),hovermode="x unified")
    st.subheader(f"Evolución {year} · {data['directors'][code]}")
    st.plotly_chart(fig, use_container_width=True, key=f"poe_chart_{year}_{code}",
                    config={"displayModeBar": False, "scrollZoom": False,
                            "doubleClick": False})
    if reference:
        st.caption(f"EAC {reference['year']} Q{reference['quarter']} · "
                   f"{reference['eac_hours']:,.0f} h · {reference['projects']} proyectos.")
    else:
        st.warning("Sin EAC publicado para este director; no se muestra límite.")
    if not data.get("opening_count", {}).get(code):
        st.caption(f"Sin reales manuales anteriores a enero de {year}: "
                   "la curva comienza en cero. El acumulado histórico puede estar incompleto.")
    if gaps:
        st.caption("Hay meses sin horas registradas; no se consideran ceros automáticos.")


def render(url):
    st.subheader("POE mensual")
    st.caption("Horas reales y previstas manuales; lectura de directores EAC, sin modificar OF, bonos ni EAC.")
    state = st.session_state
    if "poe_v5_cache" not in state:
        state["poe_v5_cache"] = {}
    if "poe_v5_period" not in state:
        today = date.today()
        state["poe_v5_period"] = date(today.year, today.month, 1)
    if "poe_v5_editing" not in state:
        state["poe_v5_editing"] = False
    if "poe_v5_grid_serial" not in state:
        state["poe_v5_grid_serial"] = 0
    # Correct legacy sessions whose uninitialized year selector fell back to 2000.
    if not state.get("poe_v5_current_year_fix"):
        if state["poe_v5_period"].year == 2000 and not state["poe_v5_editing"]:
            today = date.today()
            state["poe_v5_period"] = date(today.year, today.month, 1)
        state["poe_v5_current_year_fix"] = True
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
    notice = state.pop("poe_v5_notice", None)
    if notice:
        st.warning(notice)

    if state["poe_v5_editing"]:
        st.markdown(f"**Edición abierta · {MONTHS[period.month-1]} {year}**")
        st.caption("Marca Visible para mostrar el director en lectura. Pega bloques Excel en las columnas de horas.")
        pending = state.get("poe_v5_retry_cells", {})
        edited = st.data_editor(
            restore_pending_cells(data, period, pending)
            if state.get("poe_v5_retry_period") == period else month_frame(data, period),
            hide_index=True, use_container_width=True, num_rows="fixed",
            disabled=["Director"],
            column_config={
                "Visible": st.column_config.CheckboxColumn("Visible", width="small"),
                "Director": st.column_config.TextColumn("Director", width="large"),
                "Real (h)": st.column_config.NumberColumn(
                    "Real (h)", min_value=0, step=1, format="%.0f"),
                "Previsto (h)": st.column_config.NumberColumn(
                    "Previsto (h)", min_value=0, step=1, format="%.0f"),
            },
            key=f"poe_v5_grid_{period:%Y%m}_{state['poe_v5_grid_serial']}",
        )

        # Queue one action and render controls disabled on the saving rerun.
        # The grid is evaluated first so multi-cell Excel pastes are captured.
        busy = bool(state.get("poe_v5_action"))
        left, save, close, right = st.columns([1, 2, 2, 1])
        left.button("◀", help="Guardar y mes anterior",
                    disabled=busy, on_click=queue_action, args=("prev",))
        save.button("Guardar mes", disabled=busy,
                    on_click=queue_action, args=("save",))
        close.button("Cerrar edición", disabled=busy,
                     on_click=queue_action, args=("close",))
        right.button("▶", help="Guardar y mes siguiente",
                     disabled=busy, on_click=queue_action, args=("next",))

        action = state.pop("poe_v5_action", None)
        if action:
            state["poe_v5_busy"] = True
            try:
                changes = month_changes(data, period, edited)
                v_changes = visibility_changes(data, edited)
                if changes or v_changes:
                    with st.spinner("Guardando POE..."):
                        save_month(url, period, changes, v_changes)
                    update_local(data, period, changes, v_changes)
                    # Visibility is global to each director, not specific to a year.
                    for other_year, other_data in cache.items():
                        if other_year != year:
                            update_local(other_data, period, [], v_changes)
                    # Real hours registered in a past year affect the current
                    # year's opening balance. Invalidate it only when necessary.
                    if changes and year < date.today().year:
                        cache.pop(date.today().year, None)
                state.pop("poe_v5_retry_cells", None)
                state.pop("poe_v5_retry_period", None)
                if action in ("prev", "next"):
                    state["poe_v5_period"] = month_shift(period, -1 if action == "prev" else 1)
                if action == "close":
                    state["poe_v5_editing"] = False
                state["poe_v5_grid_serial"] += 1
                if action == "save":
                    st.toast(f"Guardados {len(changes)} cambios de horas y {len(v_changes)} de visibilidad.")
                st.rerun()
            except ValueError as exc:
                if str(exc).startswith("Conflicto en ") or str(exc).startswith("Conflicto de visibilidad"):
                    # Do not overwrite a newer DB value automatically. Refresh
                    # baseline, preserve only changed cells, and require a new save.
                    state["poe_v5_retry_cells"] = {
                        (code, col): after[i]
                        for code, before, after in changes
                        for i, col in enumerate(("Real (h)", "Previsto (h)"))
                        if before[i] != after[i]
                    }
                    state["poe_v5_retry_cells"].update(
                        {(code, "Visible"): new for code, _, new in v_changes}
                    )
                    state["poe_v5_retry_period"] = period
                    try:
                        cache[year] = unpack_year(load_year(url, year))
                    except psycopg.Error as refresh_exc:
                        st.error(f"No se pudo actualizar el año POE: {type(refresh_exc).__name__}")
                    else:
                        state["poe_v5_grid_serial"] += 1
                        state["poe_v5_notice"] = (
                            f"{exc} Se ha actualizado la referencia de Neon, "
                            "conservando tus celdas editadas SIN guardarlas. "
                            "Revisa el mes y pulsa Guardar de nuevo."
                        )
                        st.rerun()
                else:
                    st.error(str(exc))
            except psycopg.Error as exc:
                st.error(f"No se pudo guardar POE: {type(exc).__name__}")
            finally:
                state["poe_v5_busy"] = False
            st.warning("La edición permanece abierta y los cambios no se han descartado.")
    else:
        a, b = st.columns([2, 2])
        # Reconcile only on external year transitions; never overwrite a user's year choice.
        if state.get("poe_v5_year_anchor") != year:
            state["poe_v5_read_year_v2"] = year
            state["poe_v5_year_anchor"] = year
        selected_year = a.number_input("Año", min_value=2000, max_value=2199,
                                       value=year, step=1, key="poe_v5_read_year_v2")
        if int(selected_year) != year:
            state["poe_v5_period"] = date(int(selected_year), 1, 1)
            st.rerun()
        if b.button("Abrir modo edición", type="primary"):
            state["poe_v5_editing"] = True
            st.rerun()
        st.caption("Verde lima = real registrado (incluye cero). Sin fondo = previsto o vacío.")
        st.dataframe(style_annual(data, year), hide_index=True,
                     use_container_width=True)
        # Reuse the selected year's data already loaded for the annual table.
        render_annual_chart(url, data, year)
        refresh, sync = st.columns(2)
        if refresh.button("Actualizar POE", help="Recargar las horas y visibilidad desde Neon."):
            state["poe_v5_cache"] = {}
            director_eac.clear()
            st.rerun()
        if sync.button("Sincronizar directores", help="Incorporar directores nuevos desde ERP sin modificar los existentes."):
            try:
                added = sync_directors(url)
                state["poe_v5_cache"] = {}
                st.toast(f"{len(added)} directores nuevos incorporados.")
                st.rerun()
            except psycopg.Error as exc:
                st.error(str(exc))
