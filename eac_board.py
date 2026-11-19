"""Quarterly EAC editor and dashboard. ERP data are read-only."""
from datetime import date
from decimal import Decimal, InvalidOperation
import pandas as pd
import plotly.express as px
import psycopg
from psycopg.rows import dict_row
import streamlit as st
from excel_compat import excel_copy_frame, excel_csv_bytes

def connection(url):
    return psycopg.connect(url, connect_timeout=10, row_factory=dict_row)

def list_snapshots(url):
    with connection(url) as conn:
        return pd.DataFrame(conn.execute(
            "SELECT id, year, quarter, status, updated_at FROM eac_snapshots ORDER BY year DESC, quarter DESC"
        ).fetchall())

def create_snapshot(url, year, quarter, copy_previous=False):
    with connection(url) as conn:
        with conn.transaction():
            row = conn.execute(
                "INSERT INTO eac_snapshots(year,quarter) VALUES (%s,%s) "
                "ON CONFLICT (year,quarter) DO NOTHING RETURNING id", (year, quarter)
            ).fetchone()
            if row is None:
                raise ValueError("Ya existe un snapshot para ese año y trimestre.")
            new_id = row["id"]
            if copy_previous:
                prev = conn.execute(
                    "SELECT id FROM eac_snapshots WHERE (year,quarter)<(%s,%s) "
                    "ORDER BY year DESC,quarter DESC LIMIT 1", (year,quarter)
                ).fetchone()
                if prev:
                    conn.execute(
                        "INSERT INTO eac_project_hours(snapshot_id,project_code,etc_hours) "
                        "SELECT %s,project_code,etc_hours FROM eac_project_hours WHERE snapshot_id=%s",
                        (new_id,prev["id"])
                    )
    return new_id

def load_projects(url, snapshot_id):
    with connection(url) as conn:
        return pd.DataFrame(conn.execute(
            "SELECT p.project_code, COALESCE(p.description,'') AS description, "
            "COALESCE(NULLIF(TRIM(p.project_manager),''),'Sin agrupación') AS management_group, "
            "p.status, e.etc_hours "
            "FROM projects p LEFT JOIN eac_project_hours e "
            "ON e.project_code=p.project_code AND e.snapshot_id=%s "
            "ORDER BY management_group,p.project_code", (snapshot_id,)
        ).fetchall())

def save_edits(url, snapshot_id, changes):
    """Atomic, optimistic edit: protects against concurrent writers and accidental overwrites."""
    with connection(url) as conn:
        with conn.transaction():
            status = conn.execute(
                "SELECT status FROM eac_snapshots WHERE id=%s FOR UPDATE", (snapshot_id,)
            ).fetchone()
            if not status or status["status"] != "draft":
                raise ValueError("Snapshot inexistente o publicado: edición bloqueada.")
            for code, old, new in changes:
                prior = conn.execute(
                    "SELECT etc_hours FROM eac_project_hours WHERE snapshot_id=%s "
                    "AND project_code=%s FOR UPDATE", (snapshot_id,code)
                ).fetchone()
                current = prior["etc_hours"] if prior else None
                if current != old:
                    raise ValueError(f"Conflicto en {code}: otro usuario ha modificado sus horas. Recarga.")
                if new is None:
                    conn.execute(
                        "DELETE FROM eac_project_hours WHERE snapshot_id=%s AND project_code=%s",
                        (snapshot_id,code)
                    )
                elif prior:
                    conn.execute(
                        "UPDATE eac_project_hours SET etc_hours=%s,updated_at=now() "
                        "WHERE snapshot_id=%s AND project_code=%s",
                        (new,snapshot_id,code)
                    )
                else:
                    conn.execute(
                        "INSERT INTO eac_project_hours(snapshot_id,project_code,etc_hours) "
                        "VALUES (%s,%s,%s)", (snapshot_id,code,new)
                    )
            if changes:
                conn.execute("UPDATE eac_snapshots SET updated_at=now() WHERE id=%s", (snapshot_id,))

def publish(url, snapshot_id):
    with connection(url) as conn:
        with conn.transaction():
            row = conn.execute(
                "SELECT status FROM eac_snapshots WHERE id=%s FOR UPDATE", (snapshot_id,)
            ).fetchone()
            if not row or row["status"] != "draft":
                raise ValueError("Solo puede publicarse un borrador.")
            count = conn.execute(
                "SELECT count(*) AS n FROM eac_project_hours WHERE snapshot_id=%s", (snapshot_id,)
            ).fetchone()["n"]
            if count == 0:
                raise ValueError("No es posible publicar un EAC sin valores.")
            conn.execute(
                "UPDATE eac_snapshots SET status='published', published_at=now(),updated_at=now() "
                "WHERE id=%s", (snapshot_id,)
            )

def reopen(url, snapshot_id):
    """Reopen a published EAC for controlled corrections."""
    with connection(url) as conn:
        with conn.transaction():
            conn.execute(
                "UPDATE eac_snapshots SET status='draft',published_at=NULL,updated_at=now() "
                "WHERE id=%s AND status='published'", (snapshot_id,)
            )

def operational_hours(url, on_date):
    with connection(url) as conn:
        return pd.DataFrame(conn.execute(
            "SELECT f.project_code, SUM(f.hours_granted) AS hours_granted,"
            "SUM(f.hours_incurred) AS hours_incurred FROM fact_hours f "
            "WHERE f.snapshot_date=%s GROUP BY f.project_code", (on_date,)
        ).fetchall())

def list_real_snapshots(url):
    """Available ERP snapshots; no write to operational data."""
    with connection(url) as conn:
        rows = conn.execute(
            "SELECT DISTINCT snapshot_date FROM fact_hours ORDER BY snapshot_date DESC"
        ).fetchall()
    return [row["snapshot_date"] for row in rows]


def hours_value(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Valor EAC no válido: {value}")
    if not decimal.is_finite() or decimal < 0 or decimal.as_tuple().exponent < -2:
        raise ValueError(f"EAC requiere un número >= 0 con un máximo de 2 decimales: {value}")
    return decimal

def render(url):
    st.subheader("Snapshot trimestral")
    try:
        snapshots = list_snapshots(url)
    except psycopg.errors.UndefinedTable:
        st.warning("Faltan las tablas EAC. Ejecuta una sola vez sql/eac_additive.sql en Neon.")
        st.stop()
    except psycopg.Error as exc:
        st.error(f"No se puede leer EAC en Neon: {type(exc).__name__}")
        st.stop()

    with st.expander("Nuevo snapshot EAC", expanded=snapshots.empty):
        c1,c2,c3 = st.columns(3)
        year = c1.number_input("Año", min_value=2000,max_value=2200,value=date.today().year,step=1)
        quarter = c2.selectbox("Trimestre", [1,2,3,4], index=(date.today().month-1)//3,
                               format_func=lambda q:f"Q{q}")
        copy_previous = c3.checkbox("Copiar valores del último trimestre",value=False)
        if st.button("Crear borrador EAC",type="primary"):
            try:
                create_snapshot(url,int(year),int(quarter),copy_previous)
                st.success("Snapshot creado.")
                st.rerun()
            except (ValueError,psycopg.Error) as exc:
                st.error(str(exc))
    if snapshots.empty:
        st.info("Crea un snapshot para comenzar.")
        return
    choices = {int(x.id):f"{int(x.year)} · Q{int(x.quarter)} · {x.status}"
               for x in snapshots.itertuples(index=False)}
    selected = st.selectbox("Snapshot EAC seleccionado", list(choices), index=0, format_func=lambda v:choices[v])
    try:
        real_dates = list_real_snapshots(url)
    except psycopg.Error as exc:
        st.error(f"No se pueden consultar los snapshots reales: {type(exc).__name__}")
        st.stop()
    if not real_dates:
        st.warning("No hay snapshots reales disponibles en la BBDD.")
        st.stop()
    real_date = st.selectbox(
        "Snapshot real seleccionado",
        real_dates,
        index=0,
        format_func=lambda value: value.strftime("%d/%m/%Y"),
        help="Fecha del snapshot ERP que se utiliza para concedidas, incurridas y pendientes.",
    )
    status = snapshots.loc[snapshots["id"]==selected,"status"].iloc[0]
    original = load_projects(url,selected)
    if original.empty:
        st.info("Todavía no hay proyectos en el catálogo.")
        return
    selected_meta = snapshots.loc[snapshots["id"] == selected].iloc[0]
    eac_period = f"{int(selected_meta['year'])}Q{int(selected_meta['quarter'])}"
    try:
        facts = operational_hours(url, real_date)
    except psycopg.Error as exc:
        st.error(f"No se pueden consultar las horas reales: {type(exc).__name__}")
        st.stop()
    # Reutilizar el mismo snapshot ERP para indicador y gráficos: una consulta menos.
    pending_hours = (facts["hours_granted"] - facts["hours_incurred"]).sum()
    headline_eac, headline_pending = st.columns(2)
    headline_eac.metric(
        f"EAC registrado · {eac_period}",
        f"{float(original.etc_hours.dropna().sum()):,.2f} h",
    )
    headline_pending.metric(
        f"Horas concedidas pend. · Fecha {real_date:%d/%m/%Y}",
        f"{float(pending_hours):,.2f} h",
    )

    groups = sorted(original["management_group"].unique())
    group = st.selectbox("Agrupación por director", ["Todas"]+groups)
    filtered = original if group=="Todas" else original[original.management_group==group]
    st.caption(f"{original.etc_hours.notna().sum()} de {len(original)} proyectos tienen EAC registrado.")
    st.subheader("Editar EAC por proyecto")
    editor = filtered[["project_code","description","management_group","etc_hours"]].copy()
    # Float values are only used in the UI; writes are converted back to exact Decimal.
    editor["etc_hours"] = pd.to_numeric(editor["etc_hours"],errors="coerce")
    edited = st.data_editor(
        editor,hide_index=True,use_container_width=True,num_rows="fixed",
        disabled=["project_code","description","management_group"] if status=="draft" else True,
        key=f"eac_editor_{selected}_{group}",
        column_config={
            "project_code":st.column_config.TextColumn("Proyecto"),
            "description":st.column_config.TextColumn("Descripción"),
            "management_group":st.column_config.TextColumn("Director"),
            "etc_hours":st.column_config.NumberColumn("EAC (h)",min_value=0,step=0.5,format="%.2f")
        }
    )
    if status=="draft":
        if st.button("Guardar modificaciones EAC",type="primary"):
            changes=[]
            try:
                orig_map=dict(zip(filtered.project_code,filtered.etc_hours))
                for row in edited.itertuples(index=False):
                    old=hours_value(orig_map[row.project_code])
                    new=hours_value(row.etc_hours)
                    if old!=new:
                        changes.append((row.project_code,old,new))
                save_edits(url,selected,changes)
                st.success(f"Guardadas {len(changes)} modificaciones.")
                st.rerun()
            except (ValueError,psycopg.Error) as exc:
                st.error(str(exc))
        if st.button("Publicar snapshot EAC",help="La publicación bloquea nuevas ediciones."):
            try:
                publish(url,selected)
                st.success("Snapshot publicado.")
                st.rerun()
            except (ValueError,psycopg.Error) as exc:
                st.error(str(exc))
    else:
        st.info("Snapshot publicado. Puedes reabrirlo para corregir valores.")
        if st.button("Reabrir para editar", help="Permite modificar de nuevo un snapshot publicado."):
            reopen(url,selected)
            st.rerun()

    st.divider()
    st.subheader("EAC por director")
    st.caption(f"EAC {eac_period} · Reales {real_date:%d/%m/%Y}.")
    joined = original.merge(facts, on="project_code", how="left")
    for column in ("hours_granted", "hours_incurred"):
        joined[column] = pd.to_numeric(joined[column], errors="coerce").fillna(0)
    joined["etc_hours"] = pd.to_numeric(joined["etc_hours"], errors="coerce")

    # El resumen completo de directores es independiente del filtro de proyectos.
    summary = (
        joined.groupby("management_group", as_index=False)
        .agg(
            etc_hours=("etc_hours", lambda x: x.sum(min_count=1)),
            hours_granted=("hours_granted", "sum"),
            hours_incurred=("hours_incurred", "sum"),
        )
        .sort_values("management_group")
    )
    chart(summary, "management_group")
    # El gráfico usa el agregado original; la tabla calcula la diferencia sin tocarlo.
    director_table = director_comparison(joined, summary)
    st.caption("ETC = EAC − Total incurrido. Se calcula si ambos totales están disponibles.")
    comparison_table(
        director_table,
        {
            "management_group": "Director",
            "hours_incurred": "Total incurrido",
            "etc_hours": "EAC",
            "etc_remaining": "ETC",
        },
        "eac_directores.csv",
        "eac_directores",
    )

    st.divider()
    st.subheader("EAC por proyecto")
    director = st.selectbox(
        "Agrupación por director",
        groups,
        key=f"eac_project_director_{selected}",
        help="Selecciona la agrupación cuyos proyectos quieres visualizar.",
    )
    selected_projects = project_comparison(joined.loc[joined["management_group"] == director])
    chart(selected_projects, "project_code")
    st.caption("ETC = EAC − Total incurrido. Negativo indica exceso; sin EAC, ETC vacío.")
    # El mismo componente de consulta y exportación utilizado por directores.
    comparison_table(
        selected_projects,
        {
            "project_code": "Proyecto",
            "description": "Descripción",
            "management_group": "Director",
            "hours_incurred": "Total incurrido",
            "etc_hours": "EAC",
            "etc_remaining": "ETC",
        },
        "eac_proyectos.csv",
        "etc_proyectos",
    )


def project_comparison(frame):
    """Display-only remaining hours: EAC minus incurred hours."""
    result = frame.copy()
    result["etc_remaining"] = result["etc_hours"] - result["hours_incurred"]
    return result


def director_comparison(projects, director_totals):
    """Calculate remaining hours for each director aggregate."""
    return project_comparison(director_totals)


@st.fragment
def comparison_table(frame, labels, filename, key):
    """Reusable, database-free table + Spanish-Excel CSV for both EAC views."""
    columns = list(labels)
    st.dataframe(
        excel_copy_frame(frame[columns]),
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-cell",
        key=f"select_{key}",
        use_container_width=True,
        column_config={column: st.column_config.TextColumn(title) for column, title in labels.items()},
    )
    st.download_button(
        "Descargar CSV",
        data=excel_csv_bytes(frame[columns].rename(columns=labels)),
        file_name=filename,
        mime="text/csv; charset=utf-8",
        key=f"csv_{key}",
    )


def chart(frame, category, metrics=None, palette=None):
    """Reusable bars: original EAC view or POE's chosen three-series comparison."""
    metrics = metrics or {
        "etc_hours": "EAC",
        "hours_granted": "Concedidas",
        "hours_incurred": "Incurridas",
    }
    data = frame.melt(
        id_vars=[category],
        value_vars=list(metrics),
        var_name="serie", value_name="horas",
    )
    data["serie"] = data["serie"].map(metrics)
    data = data.dropna(subset=["horas"])
    if data.empty:
        st.info("No hay horas disponibles para este gráfico.")
        return
    data[category] = data[category].astype(str)
    ordered_codes = frame[category].astype(str).tolist()
    horizontal = category == "project_code"
    fig = px.bar(
        data,
        x="horas" if horizontal else category,
        y=category if horizontal else "horas",
        color="serie",
        orientation="h" if horizontal else "v",
        barmode="group",
        color_discrete_map=palette or {
            "EAC": "#D5A547",
            "Concedidas": "#70B7EA",
            "Incurridas": "#1F4E8C",
        },
        category_orders={
            category: ordered_codes,
            "serie": list(metrics.values()),
        },
        labels={
            category: "Director" if category == "management_group" else "Proyecto",
            "horas": "Horas", "serie": "",
        },
    )
    fig.update_layout(
        autosize=True,
        height=max(300, 46 * len(ordered_codes) + 115) if horizontal else 465,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="center", x=0.5, title=None),
        dragmode=False,
        margin=dict(l=0, r=0, t=65, b=95 if not horizontal else 20),
    )
    if horizontal:
        fig.update_layout(
            xaxis=dict(title="Horas", fixedrange=True, rangemode="tozero"),
            yaxis=dict(title=None, fixedrange=True, type="category",
                       categoryorder="array", categoryarray=ordered_codes,
                       autorange="reversed", automargin=True),
        )
    else:
        fig.update_layout(
            xaxis=dict(
                title=None, fixedrange=True, tickmode="array",
                tickvals=ordered_codes,
                ticktext=[code.split(" ", 1)[0] for code in ordered_codes],
                automargin=True,
            ),
            yaxis=dict(title=None, fixedrange=True, rangemode="tozero"),
        )
    st.plotly_chart(
        fig, use_container_width=True, theme="streamlit",
        config={"displayModeBar": False, "scrollZoom": False,
                "doubleClick": False, "showTips": False},
    )
