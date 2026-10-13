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
view = str(st.query_params.get("view", "home")).lower()
if view not in {"home", "risks"}:
    view = "home"

st.title(
    "Planificación"
    if view == "home"
    else "Análisis de riesgos"
)

# Material Symbols font for the bottom navigation icons.
st.markdown(
    """
    <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,500,0,0" rel="stylesheet">
    <style>
    .block-container {
        padding-bottom: 6.2rem;
    }
    [data-testid="stSidebar"] [data-testid="stSidebarContent"] {
        padding-top: 0.55rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Components v2 receives Streamlit's native --st-* theme variables directly.
# This keeps the fixed navigation bar fully opaque while following Light/Dark live.
bottom_nav = st.components.v2.component(
    "planificacion_bottom_nav",
    html="""
    <nav class="bottom-nav" aria-label="Navegación principal">
        <a href="?view=home" data-view="home">
            <span class="icon">home</span>
            <span>Home</span>
        </a>
        <a href="?view=risks" data-view="risks">
            <span class="icon">manage_search</span>
            <span>Riesgos</span>
        </a>
    </nav>
    """,
    css="""
    .bottom-nav {
        position: fixed;
        left: 0;
        right: 0;
        bottom: 0;
        z-index: 9999;
        display: flex;
        justify-content: flex-start;
        gap: 2.75rem;
        padding: 0.75rem 1.25rem calc(0.75rem + env(safe-area-inset-bottom));
        background-color: var(--st-secondary-background-color);
        border-top: 1px solid var(--st-border-color);
        box-shadow: 0 -4px 16px color-mix(in srgb, var(--st-text-color) 12%, transparent);
        opacity: 1;
    }
    .bottom-nav a {
        min-width: 4.5rem;
        min-height: 2.8rem;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 0.12rem;
        color: var(--st-text-color);
        text-decoration: none;
        font-size: 0.72rem;
        opacity: 0.68;
    }
    .bottom-nav a .icon {
        font-family: "Material Symbols Rounded";
        font-weight: normal;
        font-style: normal;
        font-size: 1.55rem;
        line-height: 1;
        letter-spacing: normal;
        text-transform: none;
        display: inline-block;
        white-space: nowrap;
        word-wrap: normal;
        direction: ltr;
        -webkit-font-feature-settings: "liga";
        -webkit-font-smoothing: antialiased;
        font-feature-settings: "liga";
    }
    .bottom-nav a.active {
        color: #2563EB;
        opacity: 1;
        font-weight: 700;
    }
    @media (max-width: 768px) {
        .bottom-nav {
            justify-content: flex-start;
            gap: 2.25rem;
            padding-left: 1rem;
            padding-right: 5.5rem;
        }
    }
    """,
    js="""
    export default function(component) {
        const { data, parentElement } = component;
        const root = parentElement;
        const links = root.querySelectorAll(".bottom-nav a");
        links.forEach((link) => {
            link.classList.toggle("active", link.dataset.view === data.view);
        });
    }
    """,
)
bottom_nav(data={"view": view}, key="bottom_nav")


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

project_statuses = query(
    f"""
    SELECT DISTINCT p.status
    FROM fact_hours f
    LEFT JOIN projects p ON p.project_code = f.project_code
    WHERE f.snapshot_date = %s
      AND f.work_center IN ({center_placeholders})
      AND p.project_manager IN ({manager_placeholders})
      AND p.status IS NOT NULL
      AND TRIM(p.status) <> ''
    ORDER BY p.status
    """,
    (snapshot, *selected_centers, *selected_managers),
)
available_statuses = project_statuses["status"].astype(str).tolist()
selected_statuses = st.sidebar.multiselect(
    "Estado del proyecto",
    available_statuses,
    default=available_statuses,
    help="Filtra por uno o varios estados del proyecto. Por defecto se incluyen todos.",
)

if not selected_statuses:
    st.warning("Selecciona al menos un estado del proyecto para visualizar datos.")
    st.stop()

status_placeholders = ",".join(["%s"] * len(selected_statuses))

if view == "risks":
    risk_bonuses = query(
        f"""
        SELECT
            f.project_code,
            COALESCE(MAX(p.description), MAX(f.project_code)) AS project_description,
            MAX(p.project_manager) AS project_manager,
            f.order_number,
            COALESCE(MAX(od.of_detailed_description), 'Pendiente confirmar') AS order_description,
            f.bonus_id,
            COALESCE(MAX(bd.bo_detailed_description), 'Pendiente confirmar') AS operation_description,
            SUM(f.hours_granted) AS hours_granted,
            SUM(f.hours_incurred) AS hours_incurred,
            SUM(f.hours_incurred) - SUM(f.hours_granted) AS deviation_hours,
            CASE
                WHEN SUM(f.hours_granted) = 0 THEN NULL
                ELSE SUM(f.hours_incurred) / SUM(f.hours_granted)
            END AS consumption_ratio
        FROM fact_hours f
        LEFT JOIN projects p ON p.project_code = f.project_code
        LEFT JOIN of_descriptions od ON od.snapshot_date = f.snapshot_date AND od.order_number = f.order_number
        LEFT JOIN bonus_descriptions bd ON bd.snapshot_date = f.snapshot_date AND bd.bonus_id = f.bonus_id
        WHERE f.snapshot_date = %s
          AND f.work_center IN ({center_placeholders})
          AND p.project_manager IN ({manager_placeholders})
          AND p.status IN ({status_placeholders})
          AND f.bonus_id IS NOT NULL
        GROUP BY f.project_code, f.order_number, f.bonus_id
        """,
        (snapshot, *selected_centers, *selected_managers, *selected_statuses),
    )

    if risk_bonuses.empty:
        st.info("No hay bonos con horas concedidas o incurridas para los filtros actuales.")
        st.stop()

    risk_bonuses["consumption_pct"] = risk_bonuses["consumption_ratio"] * 100

    def classify_risk(row):
        granted = float(row["hours_granted"] or 0)
        incurred = float(row["hours_incurred"] or 0)
        pct = row["consumption_pct"]

        if granted <= 0 and incurred > 0:
            return "Crítico >110%"
        if pd.isna(pct):
            return "Normal <90%"
        if pct > 110:
            return "Crítico >110%"
        if pct >= 100:
            return "Alto 100–110%"
        if pct >= 90:
            return "Vigilancia 90–100%"
        return "Normal <90%"

    risk_bonuses["risk_level"] = risk_bonuses.apply(classify_risk, axis=1)
    risk_bonuses["risk_order"] = risk_bonuses["risk_level"].map({
        "Crítico >110%": 0,
        "Alto 100–110%": 1,
        "Vigilancia 90–100%": 2,
        "Normal <90%": 3,
    })

    # Prioridad por delta de horas, no por porcentaje.
    risk_bonuses = risk_bonuses.sort_values(
        ["deviation_hours", "risk_order", "project_code", "order_number", "bonus_id"],
        ascending=[False, True, True, True, True],
    ).reset_index(drop=True)

    st.caption(
        "Priorización por Δ horas = horas incurridas − horas concedidas. "
        "El porcentaje se usa únicamente para clasificar el nivel de riesgo."
    )

    risk_labels = [
        "Crítico >110%",
        "Alto 100–110%",
        "Vigilancia 90–100%",
        "Normal <90%",
    ]
    risk_cols = st.columns(4)
    for col, label in zip(risk_cols, risk_labels):
        bucket = risk_bonuses[risk_bonuses["risk_level"] == label]
        delta_sum = float(bucket["deviation_hours"].sum()) if not bucket.empty else 0.0
        col.metric(
            label,
            f"{len(bucket):,} bonos",
            delta=f"{delta_sum:+,.1f} h Δ",
            delta_color="inverse",
        )

    st.divider()
    st.subheader("EXCESOS Y HORAS DISPONIBLES POR PROYECTO")
    st.caption(
        "Cálculo individual por bono: exceso = máx(incurridas − concedidas, 0); "
        "disponible = máx(concedidas − incurridas, 0). "
        "Los excesos y disponibles no se compensan entre bonos."
    )

    project_risk = risk_bonuses.copy()
    project_risk["excess_hours"] = project_risk["deviation_hours"].clip(lower=0)
    project_risk["available_hours"] = (-project_risk["deviation_hours"]).clip(lower=0)
    project_risk = (
        project_risk.groupby("project_code", as_index=False)
        .agg(
            excess_hours=("excess_hours", "sum"),
            available_hours=("available_hours", "sum"),
            bonus_count=("bonus_id", "nunique"),
        )
        .sort_values(["excess_hours", "available_hours", "project_code"],
                     ascending=[False, False, True])
    )

    project_chart = project_risk.melt(
        id_vars=["project_code", "bonus_count"],
        value_vars=["excess_hours", "available_hours"],
        var_name="Serie",
        value_name="Horas",
    )
    project_chart["Serie"] = project_chart["Serie"].map({
        "excess_hours": "Excedidas",
        "available_hours": "Disponibles",
    })
    project_chart["project_code"] = project_chart["project_code"].astype(str)
    fig_project_risk = px.bar(
        project_chart,
        y="project_code",
        x="Horas",
        color="Serie",
        orientation="h",
        barmode="group",
        color_discrete_map={"Excedidas": "#E05252", "Disponibles": "#36A66A"},
        category_orders={
            "project_code": project_risk["project_code"].astype(str).tolist(),
            "Serie": ["Excedidas", "Disponibles"],
        },
        hover_data={"bonus_count": True, "Horas": ":,.1f"},
        labels={"project_code": "Proyecto", "bonus_count": "Bonos"},
    )
    # Two adjacent bars per project, with a compact gap between projects.
    # Each bar fills its 0.25-wide group slot; bargroupgap=0 makes them touch.
    fig_project_risk.update_traces(width=0.25)
    fig_project_risk.update_layout(
        height=max(270, 30 * len(project_risk) + 120),
        bargap=0.5,
        bargroupgap=0,
        xaxis=dict(title="Horas", fixedrange=True, rangemode="tozero"),
        yaxis=dict(title=None, fixedrange=True, autorange="reversed"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="center", x=0.5, title=None),
        dragmode=False,
        margin=dict(l=10, r=10, t=65, b=20),
    )
    st.plotly_chart(
        fig_project_risk,
        use_container_width=True,
        theme="streamlit",
        config={
            "displayModeBar": False,
            "scrollZoom": False,
            "doubleClick": False,
            "showTips": False,
        },
    )

    st.divider()
    st.subheader("BONOS PRIORIZADOS POR DELTA DE HORAS")

    filter_col1, filter_col2 = st.columns(2)
    selected_risk = filter_col1.selectbox(
        "Nivel de riesgo",
        ["Todos"] + risk_labels,
        key="risk_level_filter",
    )
    risk_orders = ["Todas"] + risk_bonuses["order_number"].dropna().astype(str).drop_duplicates().tolist()
    selected_risk_order = filter_col2.selectbox(
        "Orden de Fabricación",
        risk_orders,
        key="risk_order_filter",
    )

    displayed_risk = risk_bonuses.copy()
    if selected_risk != "Todos":
        displayed_risk = displayed_risk[displayed_risk["risk_level"] == selected_risk]
    if selected_risk_order != "Todas":
        displayed_risk = displayed_risk[
            displayed_risk["order_number"].astype(str) == selected_risk_order
        ]

    st.dataframe(
        displayed_risk[
            [
                "risk_level", "project_code", "project_manager", "bonus_id",
                "operation_description", "hours_granted", "hours_incurred",
                "deviation_hours", "consumption_pct"
            ]
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            "risk_level": st.column_config.TextColumn("Riesgo"),
            "project_code": st.column_config.TextColumn("Proyecto"),
            "project_manager": st.column_config.TextColumn("Director de proyecto"),
            "bonus_id": st.column_config.TextColumn("Bono"),
            "operation_description": st.column_config.TextColumn("Descripción"),
            "hours_granted": st.column_config.NumberColumn("Concedidas", format="%.1f h"),
            "hours_incurred": st.column_config.NumberColumn("Incurridas", format="%.1f h"),
            "deviation_hours": st.column_config.NumberColumn("Desviación", format="%+.1f h"),
            "consumption_pct": st.column_config.NumberColumn("Consumo %", format="%.1f %%"),
        },
    )

    st.stop()

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
      AND p.status IN ({status_placeholders})
    GROUP BY f.project_code
    ORDER BY deviation_hours DESC, f.project_code
    """,
    (snapshot, *selected_centers, *selected_managers, *selected_statuses),
)

all_projects = ["Todos"] + projects["project_code"].dropna().astype(str).tolist()
filtered_projects = projects

granted = float(filtered_projects["hours_granted"].sum())
incurred = float(filtered_projects["hours_incurred"].sum())
deviation = incurred - granted
consumption = (incurred / granted) if granted else None

st.divider()
st.subheader("RESUMEN DIRECTORES")

# Se agregan los proyectos ya filtrados, evitando duplicar horas de un proyecto.
director_summary = (
    filtered_projects.groupby("project_manager", as_index=False, dropna=False)
    .agg(
        hours_granted=("hours_granted", "sum"),
        hours_incurred=("hours_incurred", "sum"),
        project_count=("project_code", "nunique"),
    )
    .sort_values("hours_granted", ascending=False)
)
director_summary["project_manager"] = director_summary["project_manager"].fillna("Sin director")
director_summary["deviation_hours"] = (
    director_summary["hours_incurred"] - director_summary["hours_granted"]
)
director_summary["consumption_pct"] = (
    director_summary["hours_incurred"]
    / director_summary["hours_granted"].replace(0, float("nan"))
    * 100
)

d1, d2 = st.columns(2)
d1.metric("Horas concedidas", f"{granted:,.1f} h")
d2.metric("Consumo", "—" if consumption is None else f"{consumption:.1%}")

director_chart = director_summary.melt(
    id_vars=["project_manager", "project_count"],
    value_vars=["hours_granted", "hours_incurred"],
    var_name="Serie",
    value_name="Horas",
)
director_chart["Serie"] = director_chart["Serie"].map({
    "hours_granted": "Concedidas",
    "hours_incurred": "Incurridas",
})
fig_directors = px.bar(
    director_chart,
    x="project_manager",
    y="Horas",
    color="Serie",
    barmode="group",
    color_discrete_map={
        "Concedidas": "#B69CE8",  # Morado claro
        "Incurridas": "#6034A0",  # Morado oscuro
    },
    category_orders={
        "project_manager": director_summary["project_manager"].tolist(),
        "Serie": ["Concedidas", "Incurridas"],
    },
    hover_data={"project_count": True},
    labels={"project_manager": "Director de proyecto", "project_count": "Proyectos"},
)
fig_directors.update_layout(
    xaxis=dict(
        fixedrange=True,
        tickmode="array",
        tickvals=director_summary["project_manager"].tolist(),
        ticktext=director_summary["project_manager"].astype(str).str[:6].tolist(),
    ),
    yaxis=dict(fixedrange=True),
    dragmode=False,
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="center",
        x=0.5,
        title=None,
    ),
    margin=dict(l=10, r=10, t=70, b=20),
)
st.plotly_chart(
    fig_directors,
    use_container_width=True,
    theme="streamlit",
    config={
        "displayModeBar": False,
        "scrollZoom": False,
        "doubleClick": False,
        "showTips": False,
    },
)
st.dataframe(
    director_summary[
        ["project_manager", "project_count", "hours_granted",
         "hours_incurred", "deviation_hours", "consumption_pct"]
    ],
    use_container_width=True,
    hide_index=True,
    column_config={
        "project_manager": st.column_config.TextColumn("Director de proyecto"),
        "project_count": st.column_config.NumberColumn("Proyectos"),
        "hours_granted": st.column_config.NumberColumn("Concedidas", format="%.1f h"),
        "hours_incurred": st.column_config.NumberColumn("Incurridas", format="%.1f h"),
        "deviation_hours": st.column_config.NumberColumn("Desviación", format="%+.1f h"),
        "consumption_pct": st.column_config.NumberColumn("Consumo %", format="%.1f %%"),
    },
)

st.divider()
st.subheader("RESUMEN PROYECTOS")
c1, c2 = st.columns(2)
c1.metric("Horas concedidas", f"{granted:,.1f} h")
c2.metric("Consumo", "—" if consumption is None else f"{consumption:.1%}")

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
    color_discrete_map={
        "Concedidas": "#1F4E8C",  # Azul oscuro
        "Incurridas": "#70B7EA",  # Azul claro
    },
    labels={"project_code": "Proyecto", "Horas": ""},
)
fig.update_layout(
    xaxis=dict(fixedrange=True),
    yaxis=dict(fixedrange=True),
    dragmode=False,
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="center",
        x=0.5,
        title=None,
    ),
    margin=dict(l=10, r=10, t=70, b=20),
)
st.plotly_chart(
    fig,
    use_container_width=True,
    theme="streamlit",
    config={
        "displayModeBar": False,
        "scrollZoom": False,
        "doubleClick": False,
        "showTips": False,
    },
)

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
        "project_code": st.column_config.TextColumn("Proyecto"),
        "project_manager": st.column_config.TextColumn("Director de proyecto"),
        "hours_granted": st.column_config.NumberColumn("Concedidas", format="%.1f h"),
        "hours_incurred": st.column_config.NumberColumn("Incurridas", format="%.1f h"),
        "deviation_hours": st.column_config.NumberColumn("Desviación", format="%+.1f h"),
        "remaining_hours": st.column_config.NumberColumn("Restantes", format="%+.1f h"),
        "project_description": st.column_config.TextColumn("Descripción"),
        "consumption_pct": st.column_config.NumberColumn(
            "Consumo %",
            format="%.1f %%",
        )
    },
)

selected_project = st.selectbox(
    "Project · Proyecto",
    all_projects,
    key="project_filter",
    help="Selecciona un proyecto para desplegar sus Órdenes de Fabricación.",
)

order_params = (snapshot, *selected_centers, *selected_managers, *selected_statuses)
order_filter = ""
if selected_project != "Todos":
    order_filter = "AND f.project_code = %s"
    order_params = (*order_params, selected_project)

orders = query(
    f"""
    SELECT
        f.project_code,
        f.order_number,
        COALESCE(MAX(od.of_detailed_description), 'Pendiente confirmar') AS order_description,
        MAX(f.order_status) AS order_status,
        SUM(f.hours_granted) AS hours_granted,
        SUM(f.hours_incurred) AS hours_incurred,
        SUM(f.hours_incurred) - SUM(f.hours_granted) AS deviation_hours,
        SUM(f.hours_granted) - SUM(f.hours_incurred) AS remaining_hours,
        CASE WHEN SUM(f.hours_granted)=0 THEN NULL
             ELSE SUM(f.hours_incurred)/SUM(f.hours_granted) END AS consumption_ratio
    FROM fact_hours f
    LEFT JOIN projects p ON p.project_code = f.project_code
    LEFT JOIN of_descriptions od ON od.snapshot_date = f.snapshot_date AND od.order_number = f.order_number
    WHERE f.snapshot_date = %s
      AND f.work_center IN ({center_placeholders})
      AND p.project_manager IN ({manager_placeholders})
      AND p.status IN ({status_placeholders})
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

    st.subheader("RESUMEN ORDEN DE FABRICACIÓN")
    of1, of2 = st.columns(2)
    of1.metric("Horas concedidas", f"{of_granted:,.1f} h")
    of2.metric("Consumo", "—" if of_consumption is None else f"{of_consumption:.1%}")

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
        yaxis=dict(
            type="category",
            title=None,
            categoryorder="array",
            categoryarray=order_chart["order_number"].drop_duplicates().tolist(),
            fixedrange=True,
        ),

        xaxis_title="Horas",
        legend_title_text=None,
        height=max(320, min(900, 32 * max(len(orders), 1) + 120)),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    fig_orders.update_layout(
        xaxis_fixedrange=True,
        yaxis_fixedrange=True,
        dragmode=False,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
            title=None,
        ),
        margin=dict(l=10, r=10, t=70, b=20),
    )
    st.plotly_chart(
        fig_orders,
        use_container_width=True,
        theme="streamlit",
        config={
            "displayModeBar": False,
            "scrollZoom": False,
            "doubleClick": False,
            "showTips": False,
        },
    )

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
            "order_number": st.column_config.TextColumn("OF"),
            "order_status": st.column_config.TextColumn("Estado OF"),
            "hours_granted": st.column_config.NumberColumn("Concedidas", format="%.1f h"),
            "hours_incurred": st.column_config.NumberColumn("Incurridas", format="%.1f h"),
            "deviation_hours": st.column_config.NumberColumn("Desviación", format="%+.1f h"),
            "remaining_hours": st.column_config.NumberColumn("Restantes", format="%+.1f h"),
            "order_description": st.column_config.TextColumn("Descripción"),
            "consumption_pct": st.column_config.NumberColumn(
                "Consumo %",
                format="%.1f %%",
            )
        },
    )

    all_orders = ["Todas"] + orders["order_number"].dropna().astype(str).drop_duplicates().tolist()
    selected_order = st.selectbox(
        "OF · Orden de Fabricación",
        all_orders,
        key="order_filter",
        help="Selecciona una Orden de Fabricación para desplegar sus bonos de trabajo.",
    )
else:
    selected_order = "Todas"

if selected_project != "Todos" and selected_order != "Todas":
    st.divider()
    bonuses = query(
        f"""
        SELECT
            f.order_number,
            f.operation_number,
            f.bonus_id,
            COALESCE(MAX(bd.bo_detailed_description), 'Pendiente confirmar') AS operation_description,
            SUM(f.hours_granted) AS hours_granted,
            SUM(f.hours_incurred) AS hours_incurred,
            SUM(f.hours_incurred) - SUM(f.hours_granted) AS deviation_hours,
            SUM(f.hours_granted) - SUM(f.hours_incurred) AS remaining_hours,
            CASE WHEN SUM(f.hours_granted)=0 THEN NULL
                 ELSE SUM(f.hours_incurred)/SUM(f.hours_granted) END AS consumption_ratio
        FROM fact_hours f
        LEFT JOIN projects p ON p.project_code = f.project_code
        LEFT JOIN bonus_descriptions bd ON bd.snapshot_date = f.snapshot_date AND bd.bonus_id = f.bonus_id
        WHERE f.snapshot_date = %s
          AND f.work_center IN ({center_placeholders})
          AND p.project_manager IN ({manager_placeholders})
          AND p.status IN ({status_placeholders})
          AND f.project_code = %s
          AND f.order_number = %s
        GROUP BY f.order_number, f.operation_number, f.bonus_id
        ORDER BY f.operation_number, f.bonus_id
        """,
        (snapshot, *selected_centers, *selected_managers, *selected_statuses, selected_project, selected_order),
    )
    bonuses["consumption_pct"] = bonuses["consumption_ratio"] * 100

    all_bonuses = ["Todos"] + bonuses["bonus_id"].dropna().astype(str).drop_duplicates().tolist()
    selected_bonus = st.session_state.get("bonus_filter", "Todos")
    if selected_bonus not in all_bonuses:
        selected_bonus = "Todos"
        st.session_state["bonus_filter"] = "Todos"

    displayed_bonuses = bonuses
    if selected_bonus != "Todos":
        displayed_bonuses = bonuses[bonuses["bonus_id"].astype(str) == selected_bonus]

    bonus_granted = float(displayed_bonuses["hours_granted"].sum())
    bonus_incurred = float(displayed_bonuses["hours_incurred"].sum())
    bonus_deviation = bonus_incurred - bonus_granted
    bonus_consumption = (bonus_incurred / bonus_granted) if bonus_granted else None

    st.subheader(f"RESUMEN BONOS OF {selected_order}")
    b1, b2 = st.columns(2)
    b1.metric("Horas concedidas", f"{bonus_granted:,.1f} h")
    b2.metric("Consumo", "—" if bonus_consumption is None else f"{bonus_consumption:.1%}")

    bonus_chart = (
        displayed_bonuses[["bonus_id", "hours_granted", "hours_incurred"]]
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
        yaxis=dict(
            type="category",
            title=None,
            categoryorder="array",
            categoryarray=bonus_chart["bonus_id"].drop_duplicates().tolist(),
            fixedrange=True,
        ),

        xaxis_title="Horas",
        legend_title_text=None,
        height=max(260, min(700, 22 * max(len(displayed_bonuses), 1) + 100)),
        bargap=0.12,
        bargroupgap=0.03,
        margin=dict(l=10, r=10, t=20, b=10),
    )
    fig_bonuses.update_layout(
        xaxis_fixedrange=True,
        yaxis_fixedrange=True,
        dragmode=False,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
            title=None,
        ),
        margin=dict(l=10, r=10, t=70, b=20),
    )
    st.plotly_chart(
        fig_bonuses,
        use_container_width=True,
        theme="streamlit",
        config={
            "displayModeBar": False,
            "scrollZoom": False,
            "doubleClick": False,
            "showTips": False,
        },
    )

    st.dataframe(
        displayed_bonuses[
            [
                "bonus_id", "operation_description", "consumption_pct",
                "hours_granted", "hours_incurred", "deviation_hours",
                "remaining_hours"
            ]
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            "bonus_id": st.column_config.TextColumn("Bono"),
            "hours_granted": st.column_config.NumberColumn("Concedidas", format="%.1f h"),
            "hours_incurred": st.column_config.NumberColumn("Incurridas", format="%.1f h"),
            "deviation_hours": st.column_config.NumberColumn("Desviación", format="%+.1f h"),
            "remaining_hours": st.column_config.NumberColumn("Restantes", format="%+.1f h"),
            "operation_description": st.column_config.TextColumn("Descripción"),
            "consumption_pct": st.column_config.NumberColumn(
                "Consumo %",
                format="%.1f %%",
            )
        },
    )

    if len(all_bonuses) > 2:
        st.selectbox(
            "Bono de trabajo",
            all_bonuses,
            key="bonus_filter",
            help="Selecciona un bono concreto dentro de la OF.",
        )
