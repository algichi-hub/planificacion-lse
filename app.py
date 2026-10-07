import os

import pandas as pd
import plotly.express as px
import psycopg
import streamlit as st
from dotenv import load_dotenv


load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

st.set_page_config(page_title="Planificación LSE", layout="wide")
st.title("Resumen ejecutivo · Planificación LSE")

if not DATABASE_URL:
    st.error("Falta DATABASE_URL. Configúrala en .env o en los secretos del despliegue.")
    st.stop()


@st.cache_data(ttl=300)
def query(sql: str, params=()) -> pd.DataFrame:
    with psycopg.connect(DATABASE_URL) as conn:
        return pd.read_sql_query(sql, conn, params=params)


latest = query("SELECT snapshot_date FROM v_latest_snapshot")
if latest.empty or pd.isna(latest.iloc[0]["snapshot_date"]):
    st.info("La base de datos todavía no contiene ningún snapshot.")
    st.stop()

snapshot = latest.iloc[0]["snapshot_date"]
st.caption(f"Snapshot activo: {snapshot}")

projects = query(
    """
    SELECT *
    FROM v_project_hours
    WHERE snapshot_date = %s
    ORDER BY deviation_hours DESC, project_code
    """,
    (snapshot,),
)

all_projects = ["Todos"] + projects["project_code"].dropna().astype(str).tolist()
selected_project = st.sidebar.selectbox("Proyecto", all_projects)

filtered_projects = projects
if selected_project != "Todos":
    filtered_projects = projects[projects["project_code"].astype(str) == selected_project]

granted = float(filtered_projects["hours_granted"].sum())
incurred = float(filtered_projects["hours_incurred"].sum())
deviation = incurred - granted
consumption = (incurred / granted) if granted else None

c1, c2, c3, c4 = st.columns(4)
c1.metric("Horas concedidas", f"{granted:,.1f} h")
c2.metric("Horas incurridas", f"{incurred:,.1f} h")
c3.metric("Desviación", f"{deviation:+,.1f} h")
c4.metric("Consumo", "—" if consumption is None else f"{consumption:.1%}")

st.subheader("Concedidas vs. incurridas por proyecto")
chart_df = filtered_projects[["project_code", "hours_granted", "hours_incurred"]].copy()
chart_df = chart_df.melt(
    id_vars="project_code",
    value_vars=["hours_granted", "hours_incurred"],
    var_name="Serie",
    value_name="Horas",
)
chart_df["Serie"] = chart_df["Serie"].map({
    "hours_granted": "Concedidas",
    "hours_incurred": "Incurridas",
})
fig = px.bar(
    chart_df,
    x="project_code",
    y="Horas",
    color="Serie",
    barmode="group",
    labels={"project_code": "Proyecto"},
)
st.plotly_chart(fig, use_container_width=True)

st.subheader("Proyectos")
project_table = filtered_projects.copy()
project_table["consumption_pct"] = project_table["consumption_ratio"] * 100
st.dataframe(
    project_table[
        [
            "project_code", "project_description", "hours_granted",
            "hours_incurred", "deviation_hours", "remaining_hours",
            "consumption_pct"
        ]
    ],
    use_container_width=True,
    hide_index=True,
)

order_params = (snapshot,) if selected_project == "Todos" else (snapshot, selected_project)
order_filter = "" if selected_project == "Todos" else "AND project_code = %s"
orders = query(
    f"""
    SELECT *
    FROM v_order_hours
    WHERE snapshot_date = %s
      {order_filter}
    ORDER BY deviation_hours DESC, order_number
    """,
    order_params,
)

st.subheader("Órdenes de fabricación")
orders["consumption_pct"] = orders["consumption_ratio"] * 100
st.dataframe(
    orders[
        [
            "project_code", "order_number", "order_description", "order_status",
            "hours_granted", "hours_incurred", "deviation_hours",
            "remaining_hours", "consumption_pct"
        ]
    ],
    use_container_width=True,
    hide_index=True,
)

if selected_project != "Todos":
    bonuses = query(
        """
        SELECT *
        FROM v_bonus_hours
        WHERE snapshot_date = %s
          AND project_code = %s
        ORDER BY deviation_hours DESC, order_number, operation_number
        """,
        (snapshot, selected_project),
    )
    bonuses["consumption_pct"] = bonuses["consumption_ratio"] * 100

    st.subheader("Bonos / operaciones")
    st.dataframe(
        bonuses[
            [
                "order_number", "operation_number", "bonus_id",
                "operation_description", "hours_granted", "hours_incurred",
                "deviation_hours", "remaining_hours", "consumption_pct"
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )
