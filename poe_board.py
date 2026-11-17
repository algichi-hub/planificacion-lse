"""Independent POE manual monthly hours board. No ERP/EAC writes or reads."""
from datetime import date
from decimal import Decimal, InvalidOperation
import json

import pandas as pd
import psycopg
from psycopg.rows import dict_row
import streamlit as st


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
        raise ValueError(f"Horas POE no válidas (0 o más, máximo 2 decimales): {value}")
    if number >= Decimal("1000000000000"):
        raise ValueError("Horas POE fuera de rango.")
    return number


@st.cache_data(ttl=300, show_spinner=False)
def snapshots(url):
    with connect(url) as conn:
        return conn.execute(
            "SELECT id,year,month,status,revision FROM poe_snapshots "
            "ORDER BY year DESC,month DESC"
        ).fetchall()


@st.cache_data(ttl=300, show_spinner=False)
def load(url, snapshot_id):
    # A single round trip for the complete POE snapshot, independent of ERP/EAC.
    with connect(url) as conn:
        result = conn.execute("""
            SELECT s.revision, s.status,
                COALESCE((SELECT jsonb_agg(jsonb_build_object('period',m.period,'kind',m.kind)
                  ORDER BY m.period) FROM poe_months m WHERE m.snapshot_id=s.id),'[]'::jsonb) AS months,
                COALESCE((SELECT jsonb_agg(d.director ORDER BY d.director)
                  FROM poe_directors d WHERE d.snapshot_id=s.id),'[]'::jsonb) AS directors,
                COALESCE((SELECT jsonb_agg(jsonb_build_object('director',h.director,
                    'period',h.period,'hours',h.hours)) FROM poe_hours h
                    WHERE h.snapshot_id=s.id),'[]'::jsonb) AS hours
            FROM poe_snapshots s WHERE s.id=%s
        """, (snapshot_id,)).fetchone()
    if result is None:
        raise ValueError("Snapshot POE no encontrado.")
    return result


def create(url, year, month, copy_previous):
    with connect(url) as conn:
        with conn.transaction():
            row = conn.execute(
                "INSERT INTO poe_snapshots(year,month) VALUES (%s,%s) "
                "ON CONFLICT(year,month) DO NOTHING RETURNING id", (year, month)
            ).fetchone()
            if not row:
                raise ValueError("Ya existe POE para ese mes.")
            identifier = row["id"]
            if copy_previous:
                prev = conn.execute(
                    "SELECT id FROM poe_snapshots WHERE (year,month)<(%s,%s) "
                    "AND status='published' ORDER BY year DESC,month DESC LIMIT 1",
                    (year, month)
                ).fetchone()
                if prev:
                    old = prev["id"]
                    conn.execute(
                        "INSERT INTO poe_months(snapshot_id,period,kind) "
                        "SELECT %s,period,kind FROM poe_months WHERE snapshot_id=%s",
                        (identifier, old)
                    )
                    conn.execute(
                        "INSERT INTO poe_directors(snapshot_id,director) "
                        "SELECT %s,director FROM poe_directors WHERE snapshot_id=%s",
                        (identifier, old)
                    )
                    conn.execute(
                        "INSERT INTO poe_hours(snapshot_id,director,period,hours) "
                        "SELECT %s,director,period,hours FROM poe_hours WHERE snapshot_id=%s",
                        (identifier, old)
                    )
    snapshots.clear()
    return identifier


def to_work(record):
    # Month/Director identities persist without relying on the grid's current viewport.
    return {
        "revision": int(record["revision"]), "status": record["status"],
        "months": {str(x["period"])[:10]: x["kind"] for x in record["months"]},
        "directors": list(record["directors"]),
        "hours": {(x["director"], str(x["period"])[:10]): str(x["hours"])
                  for x in record["hours"]},
    }


def validate(work):
    directors = work["directors"]
    periods = work["months"]
    if len(directors) != len(set(directors)) or any(not d.strip() or len(d) > 100 for d in directors):
        raise ValueError("Director duplicado, vacío o demasiado largo.")
    if any(date.fromisoformat(p).day != 1 or t not in ("real", "previsto")
           for p, t in periods.items()):
        raise ValueError("Mes o clasificación POE inválidos.")
    entries = []
    for (director, period), value in work["hours"].items():
        if director not in directors or period not in periods:
            continue
        number = parse_hours(value)
        if number is not None:
            entries.append({"director": director, "period": period, "hours": str(number)})
    return entries


def save(url, snapshot_id, work):
    """Optimistic concurrency and three bulk inserts, POE tables only."""
    values = validate(work)
    months = [{"period": p, "kind": kind} for p, kind in sorted(work["months"].items())]
    directors = [{"director": d} for d in work["directors"]]
    with connect(url) as conn:
        with conn.transaction():
            updated = conn.execute(
                "UPDATE poe_snapshots SET revision=revision+1,updated_at=now() "
                "WHERE id=%s AND status='draft' AND revision=%s RETURNING revision",
                (snapshot_id, work["revision"])
            ).fetchone()
            if not updated:
                raise ValueError("Edición rechazada: snapshot publicado o modificado por otro usuario. Recarga.")
            # Foreign keys cascade only within POE.
            conn.execute("DELETE FROM poe_months WHERE snapshot_id=%s", (snapshot_id,))
            conn.execute("DELETE FROM poe_directors WHERE snapshot_id=%s", (snapshot_id,))
            conn.execute(
                "INSERT INTO poe_months(snapshot_id,period,kind) "
                "SELECT %s, x.period::date, x.kind FROM jsonb_to_recordset(%s::jsonb) "
                "AS x(period text,kind text)",
                (snapshot_id, json.dumps(months))
            )
            conn.execute(
                "INSERT INTO poe_directors(snapshot_id,director) "
                "SELECT %s,x.director FROM jsonb_to_recordset(%s::jsonb) "
                "AS x(director text)",
                (snapshot_id, json.dumps(directors))
            )
            conn.execute(
                "INSERT INTO poe_hours(snapshot_id,director,period,hours) "
                "SELECT %s,x.director,x.period::date,x.hours::numeric "
                "FROM jsonb_to_recordset(%s::jsonb) "
                "AS x(director text,period text,hours text)",
                (snapshot_id, json.dumps(values))
            )
    snapshots.clear()
    load.clear()


def publish(url, snapshot_id, revision):
    with connect(url) as conn:
        with conn.transaction():
            result = conn.execute(
                "UPDATE poe_snapshots SET status='published',published_at=now(),"
                "revision=revision+1 WHERE id=%s AND revision=%s AND status='draft' "
                "AND EXISTS(SELECT 1 FROM poe_hours WHERE snapshot_id=%s) "
                "RETURNING id", (snapshot_id, revision, snapshot_id)
            ).fetchone()
            if not result:
                raise ValueError("No se puede publicar: guarda horas o recarga el snapshot.")
    snapshots.clear()
    load.clear()


def grid_frame(work, periods):
    frame = pd.DataFrame({"Director": work["directors"]})
    for period in periods:
        frame[period] = pd.Series(
            [float(work["hours"][(d, period)]) if (d, period) in work["hours"] else float("nan")
             for d in work["directors"]], dtype=float
        )
    return frame


def apply_grid(work, edited, periods):
    # Called before any structural control to protect pasted Excel blocks.
    for row in edited.to_dict("records"):
        director = row["Director"]
        for period in periods:
            key = (director, period)
            parsed = parse_hours(row[period])
            if parsed is None:
                work["hours"].pop(key, None)
            else:
                work["hours"][key] = str(parsed)


def render(url):
    st.subheader("POE mensual")
    st.caption("Reales y ETC introducidos manualmente. Independiente de EAC, OF y bonos.")
    try:
        history = snapshots(url)
    except psycopg.errors.UndefinedTable:
        st.warning("Faltan las tablas POE. Aplicar sql/poe_additive.sql una sola vez.")
        return
    except psycopg.Error as exc:
        st.error(f"Error al cargar POE: {type(exc).__name__}")
        return

    with st.expander("Nuevo snapshot POE", expanded=not bool(history)):
        a, b = st.columns(2)
        year = a.number_input("Año", 2000, 2200, date.today().year, key="poe_new_year")
        month = b.selectbox("Mes", range(1, 13), index=date.today().month-1,
                            key="poe_new_month")
        copy_previous = st.checkbox("Copiar último POE publicado", value=True)
        if st.button("Crear borrador", key="poe_new"):
            try:
                identifier = create(url, int(year), month, copy_previous)
                st.session_state["poe_selected"] = identifier
                st.rerun()
            except (ValueError, psycopg.Error) as exc:
                st.error(str(exc))
    if not history:
        st.info("Crea el primer snapshot POE para empezar.")
        return

    labels = {x["id"]: f'{x["year"]}-{x["month"]:02d} · {x["status"]}' for x in history}
    if st.session_state.get("poe_selected") not in labels:
        st.session_state["poe_selected"] = history[0]["id"]
    editing = st.session_state.get("poe_editing", False)
    selected = st.selectbox("Snapshot POE", list(labels), format_func=labels.get,
                            key="poe_selected", disabled=editing)
    try:
        record = load(url, selected)
    except (ValueError, psycopg.Error) as exc:
        st.error(str(exc))
        return
    if st.session_state.get("poe_work_id") != selected:
        st.session_state["poe_work"] = to_work(record)
        st.session_state["poe_work_id"] = selected
        st.session_state["poe_grid_serial"] = 0
        st.session_state["poe_editing"] = False

    work = st.session_state["poe_work"]
    editing = st.session_state["poe_editing"]
    st.caption(f"Estado: {record['status']} · Revisión: {record['revision']}")
    a, b, c = st.columns(3)
    if not editing and record["status"] == "draft" and a.button("Abrir edición"):
        st.session_state["poe_editing"] = True
        st.rerun()
    if editing and a.button("Cerrar edición sin guardar"):
        st.session_state["poe_work"] = to_work(record)
        st.session_state["poe_editing"] = False
        st.session_state["poe_grid_serial"] += 1
        st.rerun()

    available_years = sorted({int(p[:4]) for p in work["months"]})
    if not available_years:
        available_years = [date.today().year]
    if st.session_state.get("poe_year") not in available_years:
        st.session_state["poe_year"] = available_years[0]
    selected_year = st.session_state["poe_year"]
    periods = sorted(p for p in work["months"] if p.startswith(str(selected_year)))
    st.write(f"**Año {selected_year}** · {len(work['directors'])} directores · "
             f"{len(work['months'])} meses planificados")
    if work["directors"] and periods:
        grid = grid_frame(work, periods)
        edited = st.data_editor(
            grid, hide_index=True, use_container_width=True, num_rows="fixed",
            disabled=True if not editing else ["Director"],
            column_config={
                "Director": st.column_config.TextColumn("Director", width="medium"),
                **{p: st.column_config.NumberColumn(
                    f"{p[5:7]} · {'Real' if work['months'][p]=='real' else 'ETC'}",
                    min_value=0, step=1, format="%.2f") for p in periods},
            },
            key=f"poe_grid_{selected}_{selected_year}_{st.session_state['poe_grid_serial']}"
        )
        if editing:
            try:
                apply_grid(work, edited, periods)
            except ValueError as exc:
                st.error(str(exc))
                return
    else:
        st.info("Añade directores y meses para comenzar.")

    # All controls BELOW the editor: changes pasted in bulk are captured first.
    if len(available_years) > 1:
        a, b = st.columns([1, 3])
        with a:
            next_year = st.selectbox("Mostrar año", available_years,
                                     index=available_years.index(selected_year))
        if next_year != selected_year:
            st.session_state["poe_year"] = next_year
            st.rerun()

    if editing:
        st.markdown("**Tipo de cada mes** · conmuta toda la columna sin alterar las horas")
        for offset in range(0, len(periods), 4):
            controls = st.columns(4)
            for col, period in zip(controls, periods[offset:offset + 4]):
                kind = work["months"][period]
                if col.button(f"{period[5:7]}/{period[:4]} · {kind} ⇄", key=f"kind_{period}"):
                    work["months"][period] = "previsto" if kind == "real" else "real"
                    st.session_state["poe_grid_serial"] += 1
                    st.rerun()
        st.divider()
        st.markdown("**Modificar estructura**")
        a, b = st.columns(2)
        director = a.text_input("Nuevo director", max_chars=100, key="poe_new_director").strip()
        if b.button("Añadir director", disabled=not director):
            if director in work["directors"]:
                st.warning("Ese director ya existe.")
            else:
                work["directors"].append(director)
                work["directors"].sort()
                st.session_state["poe_grid_serial"] += 1
                st.rerun()
        a, b = st.columns(2)
        if a.button("Añadir mes anterior"):
            base = min(map(date.fromisoformat, work["months"])) if work["months"] else date.today().replace(day=1)
            period = month_shift(base, -1).isoformat() if work["months"] else base.isoformat()
            work["months"][period] = "real"
            st.session_state["poe_year"] = int(period[:4])
            st.session_state["poe_grid_serial"] += 1
            st.rerun()
        if b.button("Añadir mes posterior"):
            base = max(map(date.fromisoformat, work["months"])) if work["months"] else date.today().replace(day=1)
            period = month_shift(base, 1).isoformat() if work["months"] else base.isoformat()
            work["months"][period] = "previsto"
            st.session_state["poe_year"] = int(period[:4])
            st.session_state["poe_grid_serial"] += 1
            st.rerun()

        a, b = st.columns(2)
        remove_director = a.selectbox("Eliminar director", [""] + work["directors"])
        remove_period = b.selectbox("Eliminar mes", [""] + sorted(work["months"]))
        confirm = st.checkbox("Confirmo la eliminación en el borrador POE")
        a, b = st.columns(2)
        if a.button("Eliminar director", disabled=not (confirm and remove_director)):
            work["directors"].remove(remove_director)
            work["hours"] = {k: v for k, v in work["hours"].items() if k[0] != remove_director}
            st.session_state["poe_grid_serial"] += 1
            st.rerun()
        if b.button("Eliminar mes", disabled=not (confirm and remove_period)):
            del work["months"][remove_period]
            work["hours"] = {k: v for k, v in work["hours"].items() if k[1] != remove_period}
            st.session_state["poe_grid_serial"] += 1
            st.rerun()

        if st.button("Guardar borrador POE", type="primary"):
            try:
                save(url, selected, work)
                st.session_state["poe_work"] = to_work(load(url, selected))
                st.session_state["poe_grid_serial"] += 1
                st.success("POE guardado.")
                st.rerun()
            except (ValueError, psycopg.Error) as exc:
                st.error(str(exc))
        st.caption("Los cambios de estructura y las celdas pegadas no llegan a Neon hasta guardar.")
    elif record["status"] == "draft":
        if st.button("Publicar snapshot POE"):
            try:
                publish(url, selected, record["revision"])
                st.rerun()
            except (ValueError, psycopg.Error) as exc:
                st.error(str(exc))
    else:
        st.info("Snapshot publicado y de solo lectura. Crea otro mes para conservar el histórico.")
