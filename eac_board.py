"""ETC quarterly editor and informational EAC dashboard. ERP data are read-only."""
from datetime import date
from decimal import Decimal, InvalidOperation
import pandas as pd
import plotly.express as px
import psycopg
from psycopg.rows import dict_row
import streamlit as st

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
                raise ValueError("Ya existe una fotografía para ese año y trimestre.")
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
                    conn.execute(
                        "INSERT INTO eac_project_hours_audit(snapshot_id,project_code,old_hours,new_hours) "
                        "SELECT %s,project_code,NULL,etc_hours FROM eac_project_hours WHERE snapshot_id=%s",
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
                raise ValueError("Fotografía inexistente o publicada: edición bloqueada.")
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
                conn.execute(
                    "INSERT INTO eac_project_hours_audit(snapshot_id,project_code,old_hours,new_hours) "
                    "VALUES (%s,%s,%s,%s)", (snapshot_id,code,old,new)
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
                raise ValueError("No es posible publicar un ETC sin valores.")
            conn.execute(
                "UPDATE eac_snapshots SET status='published', published_at=now(),updated_at=now() "
                "WHERE id=%s", (snapshot_id,)
            )

def operational_hours(url, on_date):
    with connection(url) as conn:
        return pd.DataFrame(conn.execute(
            "SELECT f.project_code, SUM(f.hours_granted) AS hours_granted,"
            "SUM(f.hours_incurred) AS hours_incurred FROM fact_hours f "
            "WHERE f.snapshot_date=%s GROUP BY f.project_code", (on_date,)
        ).fetchall())

def latest_operational_date(url):
    with connection(url) as conn:
        row = conn.execute("SELECT max(snapshot_date) AS date FROM fact_hours").fetchone()
        return row["date"]

def hours_value(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Valor ETC no válido: {value}")
    if not decimal.is_finite() or decimal < 0 or decimal.as_tuple().exponent < -2:
        raise ValueError(f"ETC requiere un número >= 0 con un máximo de 2 decimales: {value}")
    return decimal

def render(url):
    st.subheader("EAC · Fotografías ETC trimestrales")
    st.caption("Datos manuales informativos: independientes de OF y bonos. "
               "Los directores son agrupaciones de gestión.")
    try:
        snapshots = list_snapshots(url)
    except psycopg.errors.UndefinedTable:
        st.warning("Faltan las tablas EAC. Ejecuta una sola vez sql/eac_additive.sql en Neon.")
        st.stop()
    except psycopg.Error as exc:
        st.error(f"No se puede leer EAC en Neon: {type(exc).__name__}")
        st.stop()

    with st.expander("Nueva fotografía ETC", expanded=snapshots.empty):
        c1,c2,c3 = st.columns(3)
        year = c1.number_input("Año", min_value=2000,max_value=2200,value=date.today().year,step=1)
        quarter = c2.selectbox("Trimestre", [1,2,3,4], index=(date.today().month-1)//3,
                               format_func=lambda q:f"Q{q}")
        copy_previous = c3.checkbox("Copiar valores del último trimestre",value=False)
        if st.button("Crear borrador ETC",type="primary"):
            try:
                create_snapshot(url,int(year),int(quarter),copy_previous)
                st.success("Fotografía creada.")
                st.rerun()
            except (ValueError,psycopg.Error) as exc:
                st.error(str(exc))
    if snapshots.empty:
        st.info("Crea una fotografía para comenzar.")
        return
    choices = {int(x.id):f"{int(x.year)} · Q{int(x.quarter)} · {x.status}"
               for x in snapshots.itertuples(index=False)}
    selected = st.selectbox("Fotografía ETC", list(choices), format_func=lambda v:choices[v])
    status = snapshots.loc[snapshots["id"]==selected,"status"].iloc[0]
    original = load_projects(url,selected)
    if original.empty:
        st.info("Todavía no hay proyectos en el catálogo.")
        return
    groups = sorted(original["management_group"].unique())
    group = st.selectbox("Agrupación de gestión", ["Todas"]+groups)
    filtered = original if group=="Todas" else original[original.management_group==group]
    st.metric("ETC registrado · trimestre seleccionado",
              f"{float(original.etc_hours.dropna().sum()):,.2f} h")
    st.caption(f"{original.etc_hours.notna().sum()} de {len(original)} proyectos tienen ETC registrado. "
               "El campo vacío representa 'sin dato', no cero.")
    st.subheader("Editar ETC por proyecto")
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
            "management_group":st.column_config.TextColumn("Agrupación"),
            "etc_hours":st.column_config.NumberColumn("ETC (h)",min_value=0,step=0.5,format="%.2f")
        }
    )
    if status=="draft":
        if st.button("Guardar modificaciones ETC",type="primary"):
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
        if st.button("Publicar fotografía ETC",help="La publicación bloquea nuevas ediciones."):
            try:
                publish(url,selected)
                st.success("Fotografía publicada.")
                st.rerun()
            except (ValueError,psycopg.Error) as exc:
                st.error(str(exc))
    else:
        st.info("Fotografía publicada y bloqueada contra ediciones.")

    st.divider()
    st.subheader("Comparación informativa ETC / concedidas / incurridas")
    on_date=latest_operational_date(url)
    if on_date is None:
        st.info("No hay snapshot ERP operativo para comparar.")
        return
    st.caption(f"ETC {choices[selected]} frente a snapshot ERP del {on_date}. "
               "ETC es una previsión trimestral, no una concesión formal.")
    facts=operational_hours(url,on_date)
    joined=original.merge(facts,on="project_code",how="left")
    for col in ["hours_granted","hours_incurred"]:
        joined[col]=pd.to_numeric(joined[col],errors="coerce").fillna(0)
    joined["etc_hours"]=pd.to_numeric(joined["etc_hours"],errors="coerce")
    modes=st.tabs(["Agrupaciones de gestión","Proyectos"])
    with modes[0]:
        agg=(joined.groupby("management_group",as_index=False)
             .agg(etc_hours=("etc_hours",lambda x:x.sum(min_count=1)),
                  hours_granted=("hours_granted","sum"),hours_incurred=("hours_incurred","sum")))
        chart(agg,"management_group")
    with modes[1]:
        chart(joined,"project_code")
    with st.expander("Auditoría de cambios ETC"):
        with connection(url) as conn:
            audit=pd.DataFrame(conn.execute(
                "SELECT project_code,old_hours,new_hours,changed_at "
                "FROM eac_project_hours_audit WHERE snapshot_id=%s "
                "ORDER BY changed_at DESC,id DESC",(selected,)
            ).fetchall())
        st.dataframe(audit,hide_index=True,use_container_width=True)

def chart(frame,category):
    data=frame.melt(id_vars=[category],value_vars=["etc_hours","hours_granted","hours_incurred"],
                    var_name="serie",value_name="horas")
    data["serie"]=data["serie"].map({"etc_hours":"ETC","hours_granted":"Concedidas",
                                     "hours_incurred":"Incurridas"})
    data=data.dropna(subset=["horas"])
    fig=px.bar(data,x=category,y="horas",color="serie",barmode="group",
               color_discrete_map={"ETC":"#D5A547","Concedidas":"#70B7EA","Incurridas":"#1F4E8C"},
               labels={category:"Agrupación" if category=="management_group" else "Proyecto",
                       "horas":"Horas","serie":""})
    fig.update_layout(legend=dict(orientation="h",yanchor="bottom",y=1.02),
                      xaxis_tickangle=-25)
    st.plotly_chart(fig,use_container_width=True)
