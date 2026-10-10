import os

import pandas as pd
import plotly.express as px
import psycopg
import streamlit as st
from dotenv import load_dotenv


load_dotenv()


def get_database_url() -> str | None:
    """
    Local: lee DATABASE_URL desde .env / variable de entorno.
    Streamlit Cloud: lee DATABASE_URL desde st.secrets.
    """
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url

    try:
        return st.secrets.get("DATABASE_URL")
    except (FileNotFoundError, KeyError):
        return None


DATABASE_URL = get_database_url()

st.set_page_config(
    page_title="Planificación LSE",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.title("Resumen ejecutivo · Planificación LSE")

if not DATABASE_URL:
    st.error(
        "No se ha configurado DATABASE_URL. "
        "En local añádela al fichero .env; en Streamlit Community Cloud "
        "añádela en App settings → Secrets."
    )
    st.stop()


@st.cache_data(ttl=300, show_spinner=False)
def query(sql: str, params=()) -> pd.DataFrame:
    with psycopg.connect(DATABASE_URL, connect_timeout=10) as conn:
        return pd.read_sql_query(sql, conn, params=params)


try:
    latest = query("SELECT snapshot_date FROM v_latest_snapshot")
except psycopg.Error:
    st.error(
        "No se ha podido conectar con PostgreSQL/Neon o el esquema todavía no existe. "
        "Comprueba DATABASE_URL y ejecuta primero scripts/import_erp.py."
    )
    st.stop()

if latest.empty or pd.isna(latest.iloc[0]["snapshot_date"]):
    st.info("La base de datos todavía no contiene ningún snapshot.")
    st.stop()

snapshot = latest.iloc[0]["snapshot_date"]
st.caption(f"Snapshot activo: {snapshot}")

work_centers = query(
    """
    SELECT DISTINCT work_center
    FROM fact_hours
    WHERE snapshot_date = %s
      AND work_center IS NOT NULL
    ORDER BY work_center
    """,
    (snapshot,),
)
available_centers = work_centers["work_center"].astype(str).tolist()
default_centers = ["422"] if "422" in available_centers else available_centers
st.sidebar.markdown("### Filtros jerárquicos")
selected_centers = st.sidebar.multiselect(
    "Centro (Ct.)",
    available_centers,
    default=default_centers,
    help="Selecciona uno o varios centros de trabajo. Por defecto se muestra el 422.",
)

if not selected_centers:
    st.warning("Selecciona al menos un centro de trabajo (Ct.) para visualizar datos.")
    st.stop()

center_placeholders = ",".join(["%s"] * len(selected_centers))

managers = query(
    f"""
    SELECT DISTINCT p.project_manager
    FROM fact_hours f
    LEFT JOIN projects p ON p.project_code = f.project_code
    WHERE f.snapshot_date = %s
      AND f.work_center IN ({center_placeholders})
      AND p.project_manager IS NOT NULL
      AND TRIM(p.project_manager) <> ''
    ORDER BY p.project_manager
    """,
    (snapshot, *selected_centers),
)
available_managers = managers["project_manager"].astype(str).tolist()
selected_managers = st.sidebar.multiselect(
    "Owner · Director de proyecto",
    available_managers,
    default=available_managers,
    help="Filtra por uno o varios directores. La lista se adapta al Ct. seleccionado.",
)

if not selected_managers:
    st.warning("Selecciona al menos un director de proyecto para visualizar datos.")
    st.stop()

manager_placeholders = ",".join(["%s"] * len(selected_managers))
projects = query(
    f"""
    SELECT
        f.project_code,
        COALESCE(MAX(p.description), MAX(f.project_code)) AS project_description,
        MAX(p.customer) AS customer,
        MAX(p.status) AS project_status,
        MAX(p.project_manager) AS project_manager,
        SUM(f.hours_granted) AS hours_granted,
        SUM(f.hours_incurred) AS hours_incurred,
        SUM(f.hours_incurred) - SUM(f.hours_granted) AS deviation_hours,
        SUM(f.hours_granted) - SUM(f.hours_incurred) AS remaining_hours,
        CASE WHEN SUM(f.hours_granted)=0 THEN NULL
             ELSE SUM(f.hours_incurred)/SUM(f.hours_granted) END AS consumption_ratio
    FROM fact_hours f
    LEFT JOIN projects p ON p.project_code = f.project_code
    WHERE f.snapshot_date = %s
      AND f.work_center IN ({center_placeholders})
      AND p.project_manager IN ({manager_placeholders})
    GROUP BY f.project_code
    ORDER BY deviation_hours DESC, f.project_code
    """,
    (snapshot, *selected_centers, *selected_managers),
)

all_projects = ["Todos"] + projects["project_code"].dropna().astype(str).tolist()
selected_project = st.sidebar.selectbox("Project · Proyecto", all_projects)

selected_order = "Todas"
if selected_project != "Todos":
    order_options_df = query(
        f"""
        SELECT DISTINCT f.order_number
        FROM fact_hours f
        LEFT JOIN projects p ON p.project_code = f.project_code
        WHERE f.snapshot_date = %s
          AND f.work_center IN ({center_placeholders})
          AND p.project_manager IN ({manager_placeholders})
          AND f.project_code = %s
        ORDER BY f.order_number
        """,
        (snapshot, *selected_centers, *selected_managers, selected_project),
    )
    all_orders = ["Todas"] + order_options_df["order_number"].dropna().astype(str).tolist()
    selected_order = st.sidebar.selectbox("OF · Orden de Fabricación", all_orders)

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
            "project_code", "project_description", "project_manager",
            "hours_granted", "hours_incurred", "deviation_hours",
            "remaining_hours", "consumption_pct"
        ]
    ],
    use_container_width=True,
    hide_index=True,
)

order_params = (snapshot, *selected_centers, *selected_managers)
order_filter = ""
if selected_project != "Todos":
    order_filter = "AND f.project_code = %s"
    order_params = (*order_params, selected_project)
    if selected_order != "Todas":
        order_filter += " AND f.order_number = %s"
        order_params = (*order_params, selected_order)

orders = query(
    f"""
    SELECT
        f.project_code,
        f.order_number,
        MAX(f.order_description) AS order_description,
        MAX(f.order_status) AS order_status,
        SUM(f.hours_granted) AS hours_granted,
        SUM(f.hours_incurred) AS hours_incurred,
        SUM(f.hours_incurred) - SUM(f.hours_granted) AS deviation_hours,
        SUM(f.hours_granted) - SUM(f.hours_incurred) AS remaining_hours,
        CASE WHEN SUM(f.hours_granted)=0 THEN NULL
             ELSE SUM(f.hours_incurred)/SUM(f.hours_granted) END AS consumption_ratio
    FROM fact_hours f
    LEFT JOIN projects p ON p.project_code = f.project_code
    WHERE f.snapshot_date = %s
      AND f.work_center IN ({center_placeholders})
      AND p.project_manager IN ({manager_placeholders})
      {order_filter}
    GROUP BY f.project_code, f.order_number
    ORDER BY deviation_hours DESC, f.order_number
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

if selected_project != "Todos" and selected_order != "Todas":
    bonuses = query(
        f"""
        SELECT
            f.order_number,
            f.operation_number,
            f.bonus_id,
            MAX(f.operation_description) AS operation_description,
            SUM(f.hours_granted) AS hours_granted,
            SUM(f.hours_incurred) AS hours_incurred,
            SUM(f.hours_incurred) - SUM(f.hours_granted) AS deviation_hours,
            SUM(f.hours_granted) - SUM(f.hours_incurred) AS remaining_hours,
            CASE WHEN SUM(f.hours_granted)=0 THEN NULL
                 ELSE SUM(f.hours_incurred)/SUM(f.hours_granted) END AS consumption_ratio
        FROM fact_hours f
        LEFT JOIN projects p ON p.project_code = f.project_code
        WHERE f.snapshot_date = %s
          AND f.work_center IN ({center_placeholders})
          AND p.project_manager IN ({manager_placeholders})
          AND f.project_code = %s
          AND f.order_number = %s
        GROUP BY f.order_number, f.operation_number, f.bonus_id
        ORDER BY f.operation_number, f.bonus_id
        """,
        (snapshot, *selected_centers, *selected_managers, selected_project, selected_order),
    )
    bonuses["consumption_pct"] = bonuses["consumption_ratio"] * 100

    st.subheader("Bonos / operaciones")
    st.dataframe(
        bonuses[
            [
                "bonus_id", "operation_description", "hours_granted", "hours_incurred",
                "deviation_hours", "remaining_hours", "consumption_pct"
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )
