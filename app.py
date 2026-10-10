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
st.title("Cuadro de mando Planificación")

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
    snapshots = query(
        """
        SELECT DISTINCT snapshot_date
        FROM fact_hours
        ORDER BY snapshot_date DESC
        """
    )
except psycopg.Error:
    st.error(
        "No se ha podido conectar con PostgreSQL/Neon o el esquema todavía no existe. "
        "Comprueba DATABASE_URL y ejecuta primero scripts/import_erp.py."
    )
    st.stop()

if snapshots.empty:
    st.info("La base de datos todavía no contiene ningún snapshot.")
    st.stop()

snapshot_options = [
    pd.Timestamp(value).date()
    for value in snapshots["snapshot_date"].dropna().tolist()
]

theme_mode = st.sidebar.radio(
    "Apariencia",
    ["Oscuro", "Claro"],
    index=0,
    horizontal=True,
    help="Cambia entre el esquema oscuro actual y un esquema claro.",
)

if theme_mode == "Claro":
    app_bg = "#F7F9FC"
    sidebar_bg = "#FFFFFF"
    text_color = "#111827"
    muted_color = "#4B5563"
    border_color = "#E5E7EB"
    control_bg = "#FFFFFF"
    panel_bg = "#FFFFFF"
    plot_bg = "#FFFFFF"
    grid_color = "#E5E7EB"
    plotly_template = "plotly_white"
else:
    app_bg = "#0E1117"
    sidebar_bg = "#161B22"
    text_color = "#FAFAFA"
    muted_color = "#B8C0CC"
    border_color = "#30363D"
    control_bg = "#0E1117"
    panel_bg = "#161B22"
    plot_bg = "#0E1117"
    grid_color = "#30363D"
    plotly_template = "plotly_dark"

px.defaults.template = plotly_template

st.markdown(
    f"""
    <style>
    [data-testid="stAppViewContainer"] {{
        background-color: {app_bg};
        color: {text_color};
    }}
    [data-testid="stSidebar"] {{
        background-color: {sidebar_bg};
        border-right: 1px solid {border_color};
    }}
    [data-testid="stHeader"] {{
        background-color: {app_bg};
    }}
    [data-testid="stAppViewContainer"] p,
    [data-testid="stAppViewContainer"] label,
    [data-testid="stAppViewContainer"] h1,
    [data-testid="stAppViewContainer"] h2,
    [data-testid="stAppViewContainer"] h3,
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {{
        color: {text_color};
    }}
    [data-testid="stCaptionContainer"] {{
        color: {muted_color};
    }}
    div[data-baseweb="select"] > div,
    div[data-baseweb="input"] > div,
    div[data-baseweb="base-input"],
    div[role="listbox"],
    ul[role="listbox"] {{
        background-color: {control_bg} !important;
        border-color: {border_color} !important;
        color: {text_color} !important;
    }}
    [data-testid="stMetric"],
    [data-testid="stDataFrame"],
    [data-testid="stTable"],
    [data-testid="stPlotlyChart"] {{
        background-color: {panel_bg} !important;
        border-color: {border_color} !important;
    }}
    [data-testid="stDataFrame"] > div,
    [data-testid="stTable"] > div,
    [data-testid="stPlotlyChart"] > div {{
        background-color: {panel_bg} !important;
    }}
    [data-testid="stDataFrame"] canvas {{
        background-color: {panel_bg} !important;
    }}
    hr {{
        border-color: {border_color};
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.sidebar.markdown("### Filtros jerárquicos")
snapshot = st.sidebar.selectbox(
    "Snapshot",
    snapshot_options,
    index=0,
    format_func=lambda value: value.strftime("%Y-%m-%d"),
    help="Selecciona la fecha del snapshot que quieres analizar.",
)
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

st.divider()
st.subheader(
    "RESUMEN PROYECTO"
    if selected_project == "Todos"
    else f"RESUMEN PROYECTO {selected_project}"
)
c1, c2 = st.columns(2)
c1.metric("Horas concedidas", f"{granted:,.1f} h")
c2.metric("Consumo", "—" if consumption is None else f"{consumption:.1%}")

st.subheader("Gráfica Concedidas vs. incurridas por Proyecto")
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
fig.update_layout(
    template=plotly_template,
    paper_bgcolor=plot_bg,
    plot_bgcolor=plot_bg,
    font_color=text_color,
    xaxis=dict(gridcolor=grid_color),
    yaxis=dict(gridcolor=grid_color),
    legend=dict(
        orientation="h",
        yanchor="top",
        y=-0.18,
        xanchor="center",
        x=0.5,
        title=None,
    ),
    margin=dict(l=10, r=10, t=20, b=80),
)
st.plotly_chart(fig, use_container_width=True)

st.subheader("Tabla Concedidas vs. incurridas por Proyecto")
project_table = filtered_projects.copy()
project_table["consumption_pct"] = project_table["consumption_ratio"] * 100
st.dataframe(
    project_table[
        [
            "project_code", "project_description", "consumption_pct", "project_manager",
            "hours_granted", "hours_incurred", "deviation_hours",
            "remaining_hours"
        ]
    ],
    use_container_width=True,
    hide_index=True,
    column_config={
        "project_description": st.column_config.TextColumn("Descripción"),
        "consumption_pct": st.column_config.NumberColumn(
            "Consumo %",
            format="%.1f %%",
        )
    },
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

if selected_project != "Todos":
    st.divider()
    of_granted = float(orders["hours_granted"].sum())
    of_incurred = float(orders["hours_incurred"].sum())
    of_deviation = of_incurred - of_granted
    of_consumption = (of_incurred / of_granted) if of_granted else None

    st.subheader(
        "RESUMEN ORDEN DE FABRICACIÓN"
        if selected_order == "Todas"
        else f"RESUMEN OF {selected_order}"
    )
    of1, of2 = st.columns(2)
    of1.metric("Horas concedidas", f"{of_granted:,.1f} h")
    of2.metric("Consumo", "—" if of_consumption is None else f"{of_consumption:.1%}")

    st.subheader("Gráfica Concedidas vs. incurridas por Orden de Fabricación")
    order_chart = (
        orders[["order_number", "hours_granted", "hours_incurred"]]
        .groupby("order_number", as_index=False)[["hours_granted", "hours_incurred"]]
        .sum()
    )
    order_chart["order_number"] = order_chart["order_number"].astype("string")
    order_chart = order_chart.melt(
        id_vars="order_number",
        value_vars=["hours_granted", "hours_incurred"],
        var_name="Serie",
        value_name="Horas",
    )
    order_chart["Serie"] = order_chart["Serie"].map({
        "hours_granted": "Concedidas",
        "hours_incurred": "Incurridas",
    })
    fig_orders = px.bar(
        order_chart,
        y="order_number",
        x="Horas",
        color="Serie",
        barmode="group",
        orientation="h",
        color_discrete_map={
            "Concedidas": "#F2C94C",
            "Incurridas": "#F2994A",
        },
        labels={"order_number": "OF"},
    )
    fig_orders.update_layout(
        yaxis=dict(type="category", title=None, categoryorder="array",
                   categoryarray=order_chart["order_number"].drop_duplicates().tolist()),

        xaxis_title="Horas",
        legend_title_text=None,
        height=max(320, min(900, 32 * max(len(orders), 1) + 120)),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    fig_orders.update_layout(
        template=plotly_template,
        paper_bgcolor=plot_bg,
        plot_bgcolor=plot_bg,
        font_color=text_color,
        xaxis=dict(gridcolor=grid_color),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.12,
            xanchor="center",
            x=0.5,
            title=None,
        ),
        margin=dict(l=10, r=10, t=20, b=70),
    )
    st.plotly_chart(fig_orders, use_container_width=True)

    st.subheader("Tabla Concedidas vs. incurridas por Orden de Fabricación")
    orders["consumption_pct"] = orders["consumption_ratio"] * 100
    st.dataframe(
        orders[
            [
                "order_number", "order_description", "consumption_pct",
                "order_status", "hours_granted", "hours_incurred",
                "deviation_hours", "remaining_hours"
            ]
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            "order_description": st.column_config.TextColumn("Descripción"),
            "consumption_pct": st.column_config.NumberColumn(
                "Consumo %",
                format="%.1f %%",
            )
        },
    )

if selected_project != "Todos" and selected_order != "Todas":
    st.divider()
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

    bonus_granted = float(bonuses["hours_granted"].sum())
    bonus_incurred = float(bonuses["hours_incurred"].sum())
    bonus_deviation = bonus_incurred - bonus_granted
    bonus_consumption = (bonus_incurred / bonus_granted) if bonus_granted else None

    st.subheader(f"RESUMEN BONOS OF {selected_order}")
    b1, b2 = st.columns(2)
    b1.metric("Horas concedidas", f"{bonus_granted:,.1f} h")
    b2.metric("Consumo", "—" if bonus_consumption is None else f"{bonus_consumption:.1%}")

    st.subheader("Gráfica Concedidas vs. incurridas por Bono de trabajo")
    bonus_chart = (
        bonuses[["bonus_id", "hours_granted", "hours_incurred"]]
        .groupby("bonus_id", as_index=False)[["hours_granted", "hours_incurred"]]
        .sum()
    )
    bonus_chart["bonus_id"] = bonus_chart["bonus_id"].astype("string")
    bonus_chart = bonus_chart.melt(
        id_vars="bonus_id",
        value_vars=["hours_granted", "hours_incurred"],
        var_name="Serie",
        value_name="Horas",
    )
    bonus_chart["Serie"] = bonus_chart["Serie"].map({
        "hours_granted": "Concedidas",
        "hours_incurred": "Incurridas",
    })
    fig_bonuses = px.bar(
        bonus_chart,
        y="bonus_id",
        x="Horas",
        color="Serie",
        barmode="group",
        orientation="h",
        color_discrete_map={
            "Concedidas": "#6FCF97",
            "Incurridas": "#219653",
        },
        labels={"bonus_id": "Bono"},
    )
    fig_bonuses.update_layout(
        yaxis=dict(type="category", title=None, categoryorder="array",
                   categoryarray=bonus_chart["bonus_id"].drop_duplicates().tolist()),

        xaxis_title="Horas",
        legend_title_text=None,
        height=max(260, min(700, 22 * max(len(bonuses), 1) + 100)),
        bargap=0.12,
        bargroupgap=0.03,
        margin=dict(l=10, r=10, t=20, b=10),
    )
    fig_bonuses.update_layout(
        template=plotly_template,
        paper_bgcolor=plot_bg,
        plot_bgcolor=plot_bg,
        font_color=text_color,
        xaxis=dict(gridcolor=grid_color),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.12,
            xanchor="center",
            x=0.5,
            title=None,
        ),
        margin=dict(l=10, r=10, t=20, b=70),
    )
    st.plotly_chart(fig_bonuses, use_container_width=True)

    st.subheader("Tabla Concedidas vs. incurridas por Bono de trabajo")
    st.dataframe(
        bonuses[
            [
                "bonus_id", "operation_description", "consumption_pct",
                "hours_granted", "hours_incurred", "deviation_hours",
                "remaining_hours"
            ]
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            "operation_description": st.column_config.TextColumn("Descripción"),
            "consumption_pct": st.column_config.NumberColumn(
                "Consumo %",
                format="%.1f %%",
            )
        },
    )
